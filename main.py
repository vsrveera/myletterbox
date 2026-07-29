import base64
import logging
import os
import tempfile
from pathlib import Path

import httpx
import markdown as md
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

load_dotenv()

from summarize_images import ACCEPTED_IMAGE_TYPES, analyze_email, combine_attachments_to_pdf, summarize_german_document  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("myletterbox")

app = FastAPI(title="myletterbox")
AGENTMAIL_BASE = "https://api.agentmail.to/v0"


# ---------------------------------------------------------------------------
# AgentMail API helpers
# ---------------------------------------------------------------------------

def _agentmail_headers() -> dict:
    key = os.environ.get("AGENTMAIL_API_KEY", "")
    if not key:
        raise RuntimeError("AGENTMAIL_API_KEY is not set")
    return {"Authorization": f"Bearer {key}"}


async def _fetch_thread_history(inbox_id: str, thread_id: str, current_message_id: str) -> list[dict]:
    """Return all messages in the thread except the current one, oldest first."""
    url = f"{AGENTMAIL_BASE}/inboxes/{inbox_id}/threads/{thread_id}"
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(url, headers=_agentmail_headers())
        resp.raise_for_status()

    thread = resp.json()
    messages = thread.get("messages", [])
    return [
        {
            "from": m.get("from", ""),
            "date": m.get("timestamp", ""),
            "subject": m.get("subject", ""),
            "text": m.get("text") or m.get("preview", ""),
        }
        for m in messages
        if m.get("message_id") != current_message_id
    ]


async def _send_reply(
    inbox_id: str,
    message_id: str,
    subject: str,
    text: str,
    combined_pdf: bytes | None = None,
) -> None:
    url = f"{AGENTMAIL_BASE}/inboxes/{inbox_id}/messages/{message_id}/reply"
    html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; font-size: 14px; color: #222; max-width: 700px; line-height: 1.6;">
<p style="margin:0 0 16px 0; padding:8px 12px; background:#f5f5f5; border-left:4px solid #666; font-size:13px; color:#444;">
  <strong>Topic:</strong> {subject}
</p>
{md.markdown(text, extensions=["extra", "nl2br"])}
</body>
</html>"""

    payload: dict = {"text": f"Topic: {subject}\n\n{text}", "html": html_body}

    if combined_pdf:
        payload["attachments"] = [{
            "filename": "combined_documents.pdf",
            "content_type": "application/pdf",
            "content": base64.b64encode(combined_pdf).decode(),
        }]
        logger.info("Attaching combined PDF (%d bytes) to reply", len(combined_pdf))

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(url, headers=_agentmail_headers(), json=payload)
        resp.raise_for_status()
    logger.info("Reply sent — subject: %r  message: %s", subject, message_id)


async def _fetch_body(body_url: str) -> str:
    """Fetch the email body from AgentMail's pre-signed S3 URL."""
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(body_url)
        resp.raise_for_status()
    data = resp.json()
    return data.get("text") or data.get("html") or ""


async def _download_attachment(inbox_id: str, message_id: str, attachment_id: str) -> bytes:
    """
    Download attachment bytes from AgentMail.

    AgentMail may return either raw binary or a JSON envelope with a base64
    `content` field — handle both.
    """
    url = f"{AGENTMAIL_BASE}/inboxes/{inbox_id}/messages/{message_id}/attachments/{attachment_id}"
    async with httpx.AsyncClient(timeout=60) as http:
        resp = await http.get(url, headers=_agentmail_headers())
        resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    logger.info("Attachment response content-type: %s  size: %d bytes", content_type, len(resp.content))

    if "application/json" in content_type:
        envelope = resp.json()
        logger.info("Attachment JSON envelope keys: %s", list(envelope.keys()))

        # AgentMail returns a pre-signed download_url for the actual binary
        download_url = envelope.get("download_url")
        if download_url:
            async with httpx.AsyncClient(timeout=60) as http2:
                dl = await http2.get(download_url)
                dl.raise_for_status()
            return dl.content

        # Fallback: base64-encoded content field
        raw_b64 = envelope.get("content") or envelope.get("data") or envelope.get("body")
        if raw_b64:
            return base64.b64decode(raw_b64)

        raise ValueError(f"JSON attachment envelope has no download_url or content field: {list(envelope.keys())}")

    return resp.content


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/summarize")
async def summarize(files: list[UploadFile] = File(...)):
    """Direct image upload endpoint — accepts one or more German document images."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one image file is required.")

    for f in files:
        if f.content_type not in ACCEPTED_IMAGE_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type '{f.content_type}'. Allowed: {sorted(ACCEPTED_IMAGE_TYPES)}",
            )

    saved_paths: list[Path] = []
    try:
        for f in files:
            suffix = Path(f.filename or "upload").suffix or ".jpg"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(await f.read())
            tmp.close()
            saved_paths.append(Path(tmp.name))

        summary = summarize_german_document(saved_paths)
        return JSONResponse({"summary": summary})
    finally:
        for p in saved_paths:
            p.unlink(missing_ok=True)


@app.post("/webhook")
async def agentmail_webhook(request: Request):
    """
    AgentMail webhook receiver.

    AgentMail POSTs a `message.received` event here whenever the inbox gets
    an email. We download attachments, fetch thread history, and summarize
    everything with Claude.
    """
    payload = await request.json()
    logger.info("Webhook payload: %s", payload)

    event_type = payload.get("event_type")
    if event_type != "message.received":
        return {"status": "ignored", "event_type": event_type}

    message = payload.get("message", {})
    thread_meta = payload.get("thread", {})

    inbox_id = message.get("inbox_id", "")
    message_id = message.get("message_id", "")
    thread_id = message.get("thread_id", "")
    subject = message.get("subject", "")
    sender = message.get("from", "")

    # Body is delivered via a pre-signed URL, not inline in the webhook payload
    body = message.get("text") or ""
    body_url = message.get("body_url")
    if not body and body_url:
        try:
            body = await _fetch_body(body_url)
            logger.info("Fetched body from body_url (%d chars)", len(body))
        except Exception:
            logger.exception("Failed to fetch body from body_url")

    logger.info(
        "Processing email — inbox: %s  thread: %s  message: %s  subject: %r  attachments: %d",
        inbox_id, thread_id, message_id, subject,
        len(message.get("attachments", [])),
    )

    # Fetch previous messages if this is part of an ongoing thread
    thread_history: list[dict] = []
    if thread_meta.get("message_count", 1) > 1 and thread_id:
        try:
            thread_history = await _fetch_thread_history(inbox_id, thread_id, message_id)
            logger.info("Fetched %d prior messages from thread", len(thread_history))
        except Exception:
            logger.exception("Failed to fetch thread history for thread %s", thread_id)

    # Download attachments (images + PDFs only; skip everything else)
    supported_types = ACCEPTED_IMAGE_TYPES | {"application/pdf"}
    attachments: list[dict] = []

    raw_attachments = message.get("attachments", [])
    logger.info("Raw attachment list: %s", raw_attachments)

    for att in raw_attachments:
        media_type = att.get("content_type", "")
        if media_type not in supported_types:
            logger.info("Skipping unsupported attachment type: %s  filename: %s", media_type, att.get("filename"))
            continue

        # AgentMail uses "id" or "attachment_id" depending on context
        att_id = att.get("id") or att.get("attachment_id")
        if not att_id:
            logger.warning("Attachment has no id field: %s", att)
            continue

        try:
            data = await _download_attachment(inbox_id, message_id, att_id)
            logger.info("Downloaded attachment %s (%s) — %d bytes", att.get("filename"), media_type, len(data))
            attachments.append({
                "data": data,
                "media_type": media_type,
                "filename": att.get("filename", ""),
            })
        except Exception:
            logger.exception("Failed to download attachment %s (id=%s)", att.get("filename"), att_id)

    result = analyze_email(
        subject=subject,
        sender=sender,
        body=body,
        attachments=attachments,
        thread_history=thread_history,
    )
    generated_subject = result["subject"]
    summary = result["summary"]
    logger.info("Generated subject: %r", generated_subject)

    # Combine attachments into a single PDF when there are multiple
    combined_pdf: bytes | None = None
    if len(attachments) > 1:
        try:
            combined_pdf = combine_attachments_to_pdf(attachments)
            logger.info("Combined %d attachments into PDF", len(attachments))
        except Exception:
            logger.exception("Failed to combine attachments into PDF")

    try:
        await _send_reply(inbox_id, message_id, generated_subject, summary, combined_pdf)
    except Exception:
        logger.exception("Failed to send reply for message %s", message_id)

    return {"status": "ok", "subject": generated_subject, "summary": summary}
