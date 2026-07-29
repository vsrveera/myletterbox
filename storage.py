import asyncio
import logging
import os
from datetime import datetime, timezone

from google.cloud import firestore, storage

logger = logging.getLogger("myletterbox")

_GCS_BUCKET = os.environ.get("GCS_BUCKET", "myletterbox-757041740498")

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
) -> None:
    pdf_gcs_uri: str | None = None

    if pdf_bytes:
        blob_path = f"{sender_email}/{event_id}/{pdf_filename}"
        bucket = _gcs().bucket(_GCS_BUCKET)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(pdf_bytes, content_type="application/pdf")
        pdf_gcs_uri = f"gs://{_GCS_BUCKET}/{blob_path}"
        logger.info("PDF saved to %s", pdf_gcs_uri)

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
        "pdf_filename": pdf_filename,
        "attachment_count": attachment_count,
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
    )
