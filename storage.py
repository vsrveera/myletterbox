import asyncio
import io
import logging
import os
from datetime import datetime, timedelta, timezone

import pypdfium2 as pdfium
from google.api_core import exceptions as gcloud_exceptions
from google.cloud import firestore, storage

logger = logging.getLogger("myletterbox")

_GCS_BUCKET = os.environ.get("GCS_BUCKET", "myletterbox-757041740498")

TRIAL_DAYS = 30
THUMBNAIL_WIDTH = 480

# Fields a client is allowed to change via the PATCH /documents/{id} endpoint.
EDITABLE_DOCUMENT_FIELDS = {
    "workflow_status", "category", "asset_name", "tags", "subject", "summary",
}

# Clients are created lazily so the module can be imported without credentials
_fs_client: firestore.Client | None = None
_gcs_client: storage.Client | None = None


def _fs() -> firestore.Client:
    global _fs_client
    if _fs_client is None:
        _fs_client = firestore.Client()
    return _fs_client


def _gcs() -> storage.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client()
    return _gcs_client


def _claim_webhook_event_sync(event_id: str) -> bool:
    """Atomically claim an AgentMail event_id. Returns False if already claimed (duplicate delivery)."""
    ref = _fs().collection("webhook_events").document(event_id)
    try:
        ref.create({"received_at": datetime.now(timezone.utc)})
        return True
    except gcloud_exceptions.AlreadyExists:
        return False


async def claim_webhook_event(event_id: str) -> bool:
    """AgentMail retries webhooks it doesn't hear back from quickly; dedupe on event_id."""
    return await asyncio.to_thread(_claim_webhook_event_sync, event_id)


def _get_asset_names_sync(sender_email: str) -> list[str]:
    docs = _fs().collection("users").document(sender_email).collection("assets").stream()
    return [d.get("name") for d in docs if d.get("name")]


async def get_asset_names(sender_email: str) -> list[str]:
    """Return the names of this user's existing assets, for AI classification hints."""
    return await asyncio.to_thread(_get_asset_names_sync, sender_email)


def _get_or_create_asset(sender_email: str, asset_name: str, category: str | None) -> str | None:
    """Case-insensitive get-or-create of an asset by name. Returns the asset_id, or None if asset_name is empty."""
    asset_name = (asset_name or "").strip()
    if not asset_name:
        return None

    assets_ref = _fs().collection("users").document(sender_email).collection("assets")
    for doc in assets_ref.stream():
        if (doc.get("name") or "").strip().lower() == asset_name.lower():
            return doc.id

    new_ref = assets_ref.document()
    new_ref.set({
        "name": asset_name,
        "category": category,
        "created_at": datetime.now(timezone.utc),
    })
    logger.info("Created asset %r (%s) for %s", asset_name, new_ref.id, sender_email)
    return new_ref.id


def _render_pdf_thumbnail(pdf_bytes: bytes) -> bytes | None:
    """Render the first page of a PDF to a JPEG thumbnail. Returns None on any failure."""
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        if len(pdf) == 0:
            return None
        page = pdf[0]
        width, _height = page.get_size()
        bitmap = page.render(scale=THUMBNAIL_WIDTH / width)
        buf = io.BytesIO()
        bitmap.to_pil().convert("RGB").save(buf, format="JPEG", quality=82)
        return buf.getvalue()
    except Exception:
        logger.exception("Failed to render PDF thumbnail")
        return None


def _save_sync(
    *,
    sender_email: str,
    event_id: str,
    thread_id: str,
    inbox_id: str,
    subject: str,
    summary: str,
    pdf_bytes: bytes | None,
    pdf_filename: str,
    attachment_count: int,
    category: str | None = None,
    document_type: str | None = None,
    tags: list[str] | None = None,
    document_date: str | None = None,
    expiry_date: str | None = None,
    asset_name: str | None = None,
    owner: str | None = None,
    source: str = "email",
    original_filename: str | None = None,
) -> None:
    pdf_gcs_uri: str | None = None

    pdf_public_url: str | None = None
    thumbnail_url: str | None = None

    if pdf_bytes:
        bucket = _gcs().bucket(_GCS_BUCKET)
        blob_path = f"{sender_email}/{event_id}/{pdf_filename}"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(pdf_bytes, content_type="application/pdf")
        pdf_gcs_uri = f"gs://{_GCS_BUCKET}/{blob_path}"
        pdf_public_url = f"https://storage.googleapis.com/{_GCS_BUCKET}/{blob_path}"
        logger.info("PDF saved to %s", pdf_gcs_uri)

        thumb_bytes = _render_pdf_thumbnail(pdf_bytes)
        if thumb_bytes:
            thumb_path = f"{sender_email}/{event_id}/thumb.jpg"
            bucket.blob(thumb_path).upload_from_string(thumb_bytes, content_type="image/jpeg")
            thumbnail_url = f"https://storage.googleapis.com/{_GCS_BUCKET}/{thumb_path}"

    asset_id = _get_or_create_asset(sender_email, asset_name or "", category)

    doc_ref = (
        _fs()
        .collection("users")
        .document(sender_email)
        .collection("documents")
        .document(event_id)
    )
    doc_ref.set({
        "subject": subject,
        "summary": summary,
        "timestamp": datetime.now(timezone.utc),
        "thread_id": thread_id,
        "inbox_id": inbox_id,
        "pdf_gcs_uri": pdf_gcs_uri,
        "pdf_public_url": pdf_public_url,
        "thumbnail_url": thumbnail_url,
        "pdf_filename": pdf_filename,
        "attachment_count": attachment_count,
        "category": category,
        "document_type": document_type,
        "workflow_status": "Inbox",
        "tags": tags or [],
        "document_date": document_date,
        "expiry_date": expiry_date,
        "asset_id": asset_id,
        "asset_name": asset_name if asset_id else None,
        "owner": owner,
        "source": source,
        "original_filename": original_filename,
    })
    logger.info("Saved to Firestore: users/%s/documents/%s", sender_email, event_id)


async def save_document(
    *,
    sender_email: str,
    event_id: str,
    thread_id: str,
    inbox_id: str,
    subject: str,
    summary: str,
    pdf_bytes: bytes | None,
    pdf_filename: str,
    attachment_count: int,
    category: str | None = None,
    document_type: str | None = None,
    tags: list[str] | None = None,
    document_date: str | None = None,
    expiry_date: str | None = None,
    asset_name: str | None = None,
    owner: str | None = None,
    source: str = "email",
    original_filename: str | None = None,
) -> None:
    """Async wrapper — runs sync GCS + Firestore writes in a thread pool."""
    await asyncio.to_thread(
        _save_sync,
        sender_email=sender_email,
        event_id=event_id,
        thread_id=thread_id,
        inbox_id=inbox_id,
        subject=subject,
        summary=summary,
        pdf_bytes=pdf_bytes,
        pdf_filename=pdf_filename,
        attachment_count=attachment_count,
        category=category,
        document_type=document_type,
        tags=tags,
        document_date=document_date,
        expiry_date=expiry_date,
        asset_name=asset_name,
        owner=owner,
        source=source,
        original_filename=original_filename,
    )


def _update_document_fields_sync(sender_email: str, doc_id: str, updates: dict) -> None:
    safe_updates = {k: v for k, v in updates.items() if k in EDITABLE_DOCUMENT_FIELDS}
    if not safe_updates:
        return

    doc_ref = (
        _fs()
        .collection("users")
        .document(sender_email)
        .collection("documents")
        .document(doc_id)
    )

    if "asset_name" in safe_updates:
        category = safe_updates.get("category") or doc_ref.get().get("category")
        safe_updates["asset_id"] = _get_or_create_asset(sender_email, safe_updates["asset_name"], category)

    doc_ref.update(safe_updates)
    logger.info("Updated users/%s/documents/%s: %s", sender_email, doc_id, list(safe_updates.keys()))


async def update_document_fields(sender_email: str, doc_id: str, updates: dict) -> None:
    """Apply a whitelisted set of metadata edits to a document the user owns."""
    await asyncio.to_thread(_update_document_fields_sync, sender_email, doc_id, updates)


# ---------------------------------------------------------------------------
# Billing (trial / subscription state, stored on the users/{email} root doc)
# ---------------------------------------------------------------------------

def _get_or_create_user_sync(email: str) -> dict:
    ref = _fs().collection("users").document(email)
    snap = ref.get()
    if snap.exists:
        return snap.to_dict()

    data = {
        "plan": "trial",
        "trial_ends_at": datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS),
        "created_at": datetime.now(timezone.utc),
    }
    ref.set(data)
    logger.info("Created user doc for %s — %d-day trial", email, TRIAL_DAYS)
    return data


async def get_or_create_user(email: str) -> dict:
    """Return this user's billing doc, creating it with a fresh trial on first sign-in."""
    return await asyncio.to_thread(_get_or_create_user_sync, email)


def _update_user_billing_sync(email: str, updates: dict) -> None:
    _fs().collection("users").document(email).set(updates, merge=True)
    logger.info("Updated billing for %s: %s", email, updates)


async def update_user_billing(email: str, updates: dict) -> None:
    """Merge Stripe/plan fields (plan, stripe_customer_id, stripe_subscription_id) into the user doc."""
    await asyncio.to_thread(_update_user_billing_sync, email, updates)


def _find_user_email_by_customer_sync(customer_id: str) -> str | None:
    docs = (
        _fs().collection("users")
        .where("stripe_customer_id", "==", customer_id)
        .limit(1)
        .stream()
    )
    for d in docs:
        return d.id
    return None


async def find_user_email_by_customer(customer_id: str) -> str | None:
    """Look up which user owns a given Stripe customer id — used by the webhook handler."""
    return await asyncio.to_thread(_find_user_email_by_customer_sync, customer_id)
