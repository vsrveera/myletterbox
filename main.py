import base64
import html
import logging
import os
import re
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import firebase_admin
import httpx
import markdown as md
import stripe
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from firebase_admin import auth as firebase_auth

load_dotenv()

from storage import (  # noqa: E402
    claim_webhook_event,
    find_user_email_by_customer,
    get_asset_names,
    get_or_create_user,
    list_documents,
    list_users_with_reminders_enabled,
    save_document,
    update_document_fields,
    update_user_billing,
    update_user_settings,
)
from summarize_images import ACCEPTED_IMAGE_TYPES, analyze_email, combine_attachments_to_pdf, summarize_german_document  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("myletterbox")

firebase_admin.initialize_app()

app = FastAPI(title="myletterbox")
AGENTMAIL_BASE = "https://api.agentmail.to/v0"

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_DISPLAY = os.environ.get("STRIPE_PRICE_DISPLAY", "")

REMINDERS_JOB_SECRET = os.environ.get("REMINDERS_JOB_SECRET", "")
APP_URL = os.environ.get("APP_URL", "https://cabinet.orgme.guru")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://project-f33cb18b-d366-43b3-9ee.web.app",
        "https://project-f33cb18b-d366-43b3-9ee.firebaseapp.com",
        "https://orgme.guru",
        "https://cabinet.orgme.guru",
        "http://localhost:5000",
        "http://localhost:5050",
    ],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)


async def _verify_user(request: Request) -> str:
    """Verify the Firebase ID token in the Authorization header, return the sender's bare lowercased email."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = header[7:]
    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    email = decoded.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token has no email claim")
    return email.strip().lower()


# ---------------------------------------------------------------------------
# Billing / entitlement
# ---------------------------------------------------------------------------

def _entitlement_payload(user: dict) -> dict:
    """Derive {plan, entitled, trial_days_left} from a users/{email} billing doc."""
    plan = user.get("plan", "trial")
    trial_ends_at = user.get("trial_ends_at")

    if plan in ("active", "free"):
        return {"plan": plan, "entitled": True, "trial_days_left": None}

    if plan == "trial" and trial_ends_at:
        remaining = trial_ends_at - datetime.now(timezone.utc)
        if remaining.total_seconds() > 0:
            return {"plan": plan, "entitled": True, "trial_days_left": max(remaining.days, 0) + 1}

    return {"plan": plan, "entitled": False, "trial_days_left": 0}


async def _require_entitlement(email: str) -> None:
    """Raise 402 if this user's trial has lapsed and they have no active subscription."""
    user = await get_or_create_user(email)
    if not _entitlement_payload(user)["entitled"]:
        raise HTTPException(status_code=402, detail="Your free trial has ended. Please subscribe to continue.")


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
        safe_name = re.sub(r'[^\w\s-]', '', subject).strip().replace(' ', '_') or "combined_documents"
        payload["attachments"] = [{
            "filename": f"{safe_name}.pdf",
            "content_type": "application/pdf",
            "content": base64.b64encode(combined_pdf).decode(),
        }]
        logger.info("Attaching combined PDF (%d bytes) to reply", len(combined_pdf))

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(url, headers=_agentmail_headers(), json=payload)
        resp.raise_for_status()
    logger.info("Reply sent — subject: %r  message: %s", subject, message_id)


async def _send_digest_email(inbox_id: str, to_email: str, subject: str, text: str, html_body: str) -> None:
    """Send a brand-new email (not a reply) — used for the weekly reminders digest."""
    url = f"{AGENTMAIL_BASE}/inboxes/{inbox_id}/messages/send"
    payload = {"to": [to_email], "subject": subject, "text": text, "html": html_body}
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(url, headers=_agentmail_headers(), json=payload)
        resp.raise_for_status()
    logger.info("Reminders digest sent to %s via inbox %s", to_email, inbox_id)


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

    event_id = payload.get("event_id", "")
    if event_id and not await claim_webhook_event(event_id):
        logger.info("Duplicate webhook delivery for event_id=%s — skipping", event_id)
        return {"status": "duplicate"}

    message = payload.get("message", {})
    thread_meta = payload.get("thread", {})

    inbox_id = message.get("inbox_id", "")
    message_id = message.get("message_id", "")
    thread_id = message.get("thread_id", "")
    subject = message.get("subject", "")
    sender_raw = message.get("from", "")
    # Extract bare email from "Name <email>" or "email" formats
    m = re.search(r"<([^>]+)>", sender_raw)
    sender = m.group(1).strip().lower() if m else sender_raw.strip().lower()

    user = await get_or_create_user(sender)
    if not _entitlement_payload(user)["entitled"]:
        logger.info("Skipping email from %s — trial expired / no active subscription", sender)
        return {"status": "entitlement_denied"}

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

    existing_assets = await get_asset_names(sender)

    result = analyze_email(
        subject=subject,
        sender=sender,
        body=body,
        attachments=attachments,
        thread_history=thread_history,
        existing_assets=existing_assets,
    )
    generated_subject = result["subject"]
    summary = result["summary"]
    logger.info("Generated subject: %r", generated_subject)

    # Convert all attachments (images + PDFs) into a single combined PDF
    combined_pdf: bytes | None = None
    if attachments:
        try:
            combined_pdf = combine_attachments_to_pdf(attachments)
            logger.info("Combined %d attachments into PDF", len(attachments))
        except Exception:
            logger.exception("Failed to combine attachments into PDF")

    try:
        await _send_reply(inbox_id, message_id, generated_subject, summary, combined_pdf)
    except Exception:
        logger.exception("Failed to send reply for message %s", message_id)

    try:
        await save_document(
            sender_email=sender,
            event_id=event_id,
            thread_id=thread_id,
            inbox_id=inbox_id,
            subject=generated_subject,
            summary=summary,
            pdf_bytes=combined_pdf,
            pdf_filename=f"{re.sub(r'[^\w\s-]', '', generated_subject).strip().replace(' ', '_') or 'document'}.pdf",
            attachment_count=len(attachments),
            category=result.get("category"),
            document_type=result.get("document_type"),
            tags=result.get("tags"),
            document_date=result.get("document_date"),
            expiry_date=result.get("expiry_date"),
            asset_name=result.get("asset_name"),
            owner=result.get("owner"),
            source="email",
        )
    except Exception:
        logger.exception("Failed to save document to Firestore/GCS")

    return {"status": "ok", "subject": generated_subject, "summary": summary}


# ---------------------------------------------------------------------------
# Manual upload + metadata editing (web UI)
# ---------------------------------------------------------------------------

async def _classify_and_save_upload(
    *, sender: str, title: str, attachments: list[dict], existing_assets: list[str]
) -> dict:
    """Classify one group of attachments as a single document and save it. Returns the created document summary."""
    result = analyze_email(
        subject=title,
        sender=sender,
        body="",
        attachments=attachments,
        thread_history=[],
        existing_assets=existing_assets,
    )
    generated_subject = result["subject"]
    summary = result["summary"]

    combined_pdf: bytes | None = None
    try:
        combined_pdf = combine_attachments_to_pdf(attachments)
    except Exception:
        logger.exception("Failed to combine uploaded attachments into PDF")

    event_id = str(uuid.uuid4())
    pdf_filename = f"{re.sub(r'[^\w\s-]', '', generated_subject).strip().replace(' ', '_') or 'document'}.pdf"

    await save_document(
        sender_email=sender,
        event_id=event_id,
        thread_id="",
        inbox_id="",
        subject=generated_subject,
        summary=summary,
        pdf_bytes=combined_pdf,
        pdf_filename=pdf_filename,
        attachment_count=len(attachments),
        category=result.get("category"),
        document_type=result.get("document_type"),
        tags=result.get("tags"),
        document_date=result.get("document_date"),
        expiry_date=result.get("expiry_date"),
        asset_name=result.get("asset_name"),
        owner=result.get("owner"),
        source="upload",
        original_filename=", ".join(a.get("filename", "") for a in attachments),
    )

    return {"id": event_id, "subject": generated_subject, "summary": summary}


@app.post("/documents")
async def upload_document(
    request: Request,
    files: list[UploadFile] = File(...),
    title: str = Form(""),
    mode: str = Form("merge"),
):
    """
    Manual upload path — classifies and saves attachments the same way the webhook does.

    mode="merge" (default) treats all files as one document (one combined PDF, one
    classification). mode="separate" classifies and saves each file as its own document.
    """
    sender = await _verify_user(request)
    await _require_entitlement(sender)

    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")
    if mode not in ("merge", "separate"):
        raise HTTPException(status_code=400, detail="mode must be 'merge' or 'separate'.")

    supported_types = ACCEPTED_IMAGE_TYPES | {"application/pdf"}
    attachments: list[dict] = []
    for f in files:
        if f.content_type not in supported_types:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type '{f.content_type}'. Allowed: {sorted(supported_types)}",
            )
        data = await f.read()
        attachments.append({"data": data, "media_type": f.content_type, "filename": f.filename or ""})

    existing_assets = await get_asset_names(sender)

    if mode == "separate":
        documents = []
        for att in attachments:
            doc = await _classify_and_save_upload(
                sender=sender, title=title, attachments=[att], existing_assets=existing_assets,
            )
            documents.append(doc)
            # Refresh so later files in this batch can reuse assets just created.
            existing_assets = await get_asset_names(sender)
        return {"status": "ok", "documents": documents}

    doc = await _classify_and_save_upload(
        sender=sender, title=title, attachments=attachments, existing_assets=existing_assets,
    )
    return {"status": "ok", "documents": [doc]}


@app.patch("/documents/{doc_id}")
async def patch_document(doc_id: str, request: Request):
    """Edit a document's editable metadata (workflow_status, category, asset_name, tags, subject, summary)."""
    sender = await _verify_user(request)
    await _require_entitlement(sender)
    updates = await request.json()
    if not isinstance(updates, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object.")

    await update_document_fields(sender, doc_id, updates)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# User settings (reminders opt-in)
# ---------------------------------------------------------------------------

@app.get("/users/me/settings")
async def get_user_settings(request: Request):
    email = await _verify_user(request)
    user = await get_or_create_user(email)
    return {"reminders_enabled": bool(user.get("reminders_enabled", False))}


@app.patch("/users/me/settings")
async def patch_user_settings(request: Request):
    email = await _verify_user(request)
    body = await request.json()
    await update_user_settings(email, body)
    user = await get_or_create_user(email)
    return {"reminders_enabled": bool(user.get("reminders_enabled", False))}


# ---------------------------------------------------------------------------
# Reminders digest (weekly email for documents needing attention / expiring soon)
# ---------------------------------------------------------------------------

def _parse_expiry_date(doc: dict) -> date | None:
    raw = doc.get("expiry_date")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _digest_sections(docs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Mirror the frontend dashboard's 'Needs Attention' / 'Upcoming' filters (public/index.html)."""
    today = datetime.now(timezone.utc).date()
    in_30 = today + timedelta(days=30)

    attention, upcoming = [], []
    for d in docs:
        status = d.get("workflow_status") or "Inbox"
        if status == "Completed":
            continue
        exp = _parse_expiry_date(d)
        if status == "Needs Action" or (exp and exp <= in_30):
            attention.append(d)
        if exp and exp > today:
            upcoming.append(d)

    attention = attention[:10]
    attention_ids = {d["id"] for d in attention}
    upcoming = [d for d in upcoming if d["id"] not in attention_ids]
    upcoming.sort(key=_parse_expiry_date)
    return attention, upcoming[:10]


def _digest_item_meta(doc: dict, today: date) -> dict:
    exp = _parse_expiry_date(doc)
    return {
        "subject": doc.get("subject") or "Untitled document",
        "expiry_label": exp.strftime("%b %-d, %Y") if exp else None,
        "overdue": bool(exp and exp < today),
    }


def _build_digest_email(attention: list[dict], upcoming: list[dict]) -> tuple[str, str, str]:
    today = datetime.now(timezone.utc).date()
    attention_meta = [_digest_item_meta(d, today) for d in attention]
    upcoming_meta = [_digest_item_meta(d, today) for d in upcoming]

    total = len(attention_meta) + len(upcoming_meta)
    subject = f"Life Cabinet: {total} item{'' if total == 1 else 's'} to look at this week"

    # Plain-text fallback
    def text_line(m: dict) -> str:
        if not m["expiry_label"]:
            return f"- {m['subject']}"
        prefix = "overdue since" if m["overdue"] else "expires"
        return f"- {m['subject']} — {prefix} {m['expiry_label']}"

    text_lines = ["Here's what's coming up in your Life Cabinet this week.", ""]
    if attention_meta:
        text_lines += ["NEEDS ATTENTION", *[text_line(m) for m in attention_meta], ""]
    if upcoming_meta:
        text_lines += ["UPCOMING", *[text_line(m) for m in upcoming_meta], ""]
    text_lines.append(f"Open Life Cabinet: {APP_URL}")
    text = "\n".join(text_lines)

    # Styled HTML version, matching the app's own light-theme colour tokens
    def html_item(m: dict) -> str:
        badge = (
            '<span style="display:inline-block;margin-left:8px;padding:1px 8px;'
            'border-radius:999px;background:#fdecea;color:#d64545;font-size:11px;'
            'font-weight:600;vertical-align:middle;">OVERDUE</span>'
        ) if m["overdue"] else ""
        date_row = ""
        if m["expiry_label"]:
            label = "Overdue since" if m["overdue"] else "Expires"
            date_row = (
                f'<div style="color:#737d87;font-size:12.5px;margin-top:2px;">'
                f'{label} {m["expiry_label"]}</div>'
            )
        return (
            '<div style="padding:10px 0;border-bottom:1px solid #f1f3f5;">'
            f'<div style="font-size:14px;font-weight:600;color:#16191d;">'
            f'{html.escape(m["subject"])}{badge}</div>{date_row}</div>'
        )

    def html_section(title: str, items: list[dict]) -> str:
        if not items:
            return ""
        return (
            '<div style="font-size:11.5px;font-weight:700;letter-spacing:.06em;'
            f'text-transform:uppercase;color:#737d87;margin:20px 0 4px;">{title}</div>'
            + "".join(html_item(m) for m in items)
        )

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background:#f6f7f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e3e6ea;border-radius:12px;overflow:hidden;">
    <div style="padding:20px 24px;border-bottom:1px solid #e3e6ea;">
      <span style="font-size:17px;font-weight:700;color:#16191d;letter-spacing:-0.3px;">Life Cabinet</span>
    </div>
    <div style="padding:20px 24px;">
      <p style="margin:0;color:#495057;font-size:14px;line-height:1.6;">Here's what's coming up this week.</p>
      {html_section("Needs Attention", attention_meta)}
      {html_section("Upcoming", upcoming_meta)}
      <a href="{APP_URL}" style="display:inline-block;margin-top:20px;background:#1a73e8;color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;padding:10px 18px;border-radius:8px;">Open Life Cabinet</a>
    </div>
    <div style="padding:14px 24px;border-top:1px solid #e3e6ea;color:#8a939f;font-size:12px;line-height:1.5;">
      You're receiving this because weekly reminders are turned on. Toggle the bell icon in Life Cabinet's header to turn them off.
    </div>
  </div>
</body>
</html>"""

    return subject, text, html_body


@app.post("/jobs/reminders-digest")
async def reminders_digest_job(request: Request):
    """Triggered by Cloud Scheduler — emails the weekly digest to every opted-in user."""
    if not REMINDERS_JOB_SECRET or request.headers.get("x-job-secret") != REMINDERS_JOB_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    emails = await list_users_with_reminders_enabled()
    sent, skipped = 0, 0
    for email in emails:
        try:
            docs = await list_documents(email)
            if not docs:
                skipped += 1
                continue

            attention, upcoming = _digest_sections(docs)
            if not attention and not upcoming:
                skipped += 1
                continue

            inbox_id = docs[0].get("inbox_id")
            if not inbox_id:
                skipped += 1
                continue

            subject, text, html_body = _build_digest_email(attention, upcoming)
            await _send_digest_email(inbox_id, email, subject, text, html_body)
            sent += 1
        except Exception:
            logger.exception("Failed to send reminders digest to %s", email)
            skipped += 1

    logger.info("Reminders digest job complete — sent=%d skipped=%d", sent, skipped)
    return {"sent": sent, "skipped": skipped}


# ---------------------------------------------------------------------------
# Billing (Stripe)
# ---------------------------------------------------------------------------

@app.get("/billing/status")
async def billing_status(request: Request):
    email = await _verify_user(request)
    user = await get_or_create_user(email)
    payload = _entitlement_payload(user)
    payload["price_display"] = STRIPE_PRICE_DISPLAY
    return payload


@app.post("/billing/checkout-session")
async def create_checkout_session(request: Request):
    """Create a Stripe Checkout session for the single EUR subscription plan."""
    email = await _verify_user(request)
    body = await request.json()
    success_url = body.get("success_url")
    cancel_url = body.get("cancel_url")
    if not success_url or not cancel_url:
        raise HTTPException(status_code=400, detail="success_url and cancel_url are required.")

    user = await get_or_create_user(email)
    customer_id = user.get("stripe_customer_id")

    session_kwargs = {
        "mode": "subscription",
        "line_items": [{"price": STRIPE_PRICE_ID, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": email,
    }
    if customer_id:
        session_kwargs["customer"] = customer_id
    else:
        session_kwargs["customer_email"] = email

    try:
        session = stripe.checkout.Session.create(**session_kwargs)
    except stripe.error.StripeError as exc:
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc.user_message or str(exc)}") from exc

    return {"url": session.url}


@app.post("/billing/portal-session")
async def create_portal_session(request: Request):
    """Create a Stripe Customer Portal session so a subscribed user can manage/cancel billing."""
    email = await _verify_user(request)
    body = await request.json()
    return_url = body.get("return_url")
    if not return_url:
        raise HTTPException(status_code=400, detail="return_url is required.")

    user = await get_or_create_user(email)
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="No billing account found for this user yet.")

    try:
        session = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
    except stripe.error.StripeError as exc:
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc.user_message or str(exc)}") from exc

    return {"url": session.url}


_SUBSCRIPTION_STATUS_TO_PLAN = {
    "active": "active",
    "trialing": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "canceled": "canceled",
    "incomplete_expired": "canceled",
}


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Stripe webhook receiver — keeps each user's plan/subscription state in sync."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature.") from exc

    event_type = event["type"]
    data = event["data"]["object"].to_dict()  # StripeObject isn't dict-like in this SDK version
    logger.info("Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        email = data.get("client_reference_id") or (data.get("customer_details") or {}).get("email")
        if email:
            await update_user_billing(email.strip().lower(), {
                "plan": "active",
                "stripe_customer_id": data.get("customer"),
                "stripe_subscription_id": data.get("subscription"),
            })
        else:
            logger.warning("checkout.session.completed with no resolvable email: %s", data.get("id"))

    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        customer_id = data.get("customer")
        plan = _SUBSCRIPTION_STATUS_TO_PLAN.get(data.get("status"), "past_due")
        if event_type == "customer.subscription.deleted":
            plan = "canceled"
        email = await find_user_email_by_customer(customer_id)
        if email:
            await update_user_billing(email, {"plan": plan, "stripe_subscription_id": data.get("id")})
        else:
            logger.warning("Subscription event for unknown Stripe customer: %s", customer_id)

    return {"status": "ok"}
