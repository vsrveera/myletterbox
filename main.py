import logging
import os
import tempfile
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

load_dotenv()

from summarize_images import analyze_email, summarize_german_document  # noqa: E402

logger = logging.getLogger("myletterbox")

app = FastAPI(title="myletterbox")

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
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
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_agentmail_headers())
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


async def _download_attachment(inbox_id: str, message_id: str, attachment_id: str) -> bytes:
    url = f"{AGENTMAIL_BASE}/inboxes/{inbox_id}/messages/{message_id}/attachments/{attachment_id}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url, headers=_agentmail_headers())
        resp.raise_for_status()
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
        if f.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type '{f.content_type}'. Allowed: {sorted(ALLOWED_IMAGE_TYPES)}",
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
    body = message.get("text") or ""

    # Fetch previous messages if this is part of an ongoing thread
    thread_history: list[dict] = []
    if thread_meta.get("message_count", 1) > 1 and thread_id:
        try:
            thread_history = await _fetch_thread_history(inbox_id, thread_id, message_id)
        except Exception:
            logger.exception("Failed to fetch thread history for thread %s", thread_id)

    # Download attachments (images + PDFs only; skip everything else)
    supported_types = ALLOWED_IMAGE_TYPES | {"application/pdf"}
    attachments: list[dict] = []
    for att in message.get("attachments", []):
        media_type = att.get("content_type", "")
        if media_type not in supported_types:
            logger.info("Skipping unsupported attachment type: %s", media_type)
            continue
        try:
            data = await _download_attachment(inbox_id, message_id, att["attachment_id"])
            attachments.append({
                "data": data,
                "media_type": media_type,
                "filename": att.get("filename", ""),
            })
        except Exception:
            logger.exception("Failed to download attachment %s", att.get("attachment_id"))

    summary = analyze_email(
        subject=subject,
        sender=sender,
        body=body,
        attachments=attachments,
        thread_history=thread_history,
    )

    return {"status": "ok", "summary": summary}
