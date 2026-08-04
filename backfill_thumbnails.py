"""
Backfill PDF thumbnails for documents saved before thumbnail generation existed.

Usage:
    python3 backfill_thumbnails.py --dry-run   # preview what would change
    python3 backfill_thumbnails.py             # actually write thumbnails
"""
import sys

from google.cloud import firestore
from storage import _GCS_BUCKET, _gcs, _render_pdf_thumbnail


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    db = firestore.Client()
    bucket = _gcs().bucket(_GCS_BUCKET)

    total = updated = no_pdf = failed = 0

    for doc in db.collection_group("documents").stream():
        total += 1
        data = doc.to_dict()
        if data.get("thumbnail_url"):
            continue

        pdf_gcs_uri = data.get("pdf_gcs_uri")
        if not pdf_gcs_uri:
            no_pdf += 1
            continue

        blob_path = pdf_gcs_uri.split(f"gs://{_GCS_BUCKET}/", 1)[-1]
        try:
            pdf_bytes = bucket.blob(blob_path).download_as_bytes()
        except Exception as exc:
            print(f"FAILED download {doc.reference.path}: {exc}")
            failed += 1
            continue

        thumb_bytes = _render_pdf_thumbnail(pdf_bytes)
        if not thumb_bytes:
            print(f"FAILED render {doc.reference.path}")
            failed += 1
            continue

        thumb_path = f"{blob_path.rsplit('/', 1)[0]}/thumb.jpg"
        thumbnail_url = f"https://storage.googleapis.com/{_GCS_BUCKET}/{thumb_path}"

        if dry_run:
            print(f"[dry-run] {doc.reference.path} -> {thumbnail_url}")
        else:
            bucket.blob(thumb_path).upload_from_string(thumb_bytes, content_type="image/jpeg")
            doc.reference.update({"thumbnail_url": thumbnail_url})
            print(f"Updated {doc.reference.path}")
        updated += 1

    print(f"\nTotal: {total}  Updated: {updated}  No PDF: {no_pdf}  Failed: {failed}")


if __name__ == "__main__":
    main()
