import base64
import io
import json
import mimetypes
from pathlib import Path

import anthropic
import pillow_heif
from PIL import Image
from pypdf import PdfReader, PdfWriter

pillow_heif.register_heif_opener()  # adds HEIC/HEIF support to Pillow

client = anthropic.Anthropic()

CATEGORIES = [
    "Identity & Legal",
    "Finance",
    "Property",
    "Vehicles",
    "Insurance",
    "Health",
    "Family",
    "Career & Business",
    "Education",
    "Travel",
    "Purchases & Warranties",
    "Reference",
    "Archive",
]

SYSTEM_PROMPT = (
    "You are an expert assistant that helps understand nonEniglish documents, letters, and emails. "
    "When a user forwards emails with attachments (images or PDFs of German documents), provide a clear "
    "and comprehensive summary in English covering: the email's context, key information from "
    "any attached the documents, action items or deadlines, and how it relates to the prior "
    "email thread. When given standalone document images with no email context, summarize the "
    "document content including key topics, and overall purpose. I don't have to mention reciever's name as this summary will be provided to reciever as a summary"
)

# Formats Claude accepts natively
_CLAUDE_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# All image formats we accept from users/emails (converted to JPEG before sending to Claude)
ACCEPTED_IMAGE_TYPES = {
    "image/jpeg", "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic", "image/heif",       # iPhone default (iOS 11+)
    "image/x-heic", "image/x-heif",   # non-standard HEIC variants
    "image/avif",                       # AV1 Image (modern Android/Chrome)
    "image/tiff", "image/x-tiff",      # TIFF from some cameras
    "image/bmp", "image/x-ms-bmp",    # BMP
}


def _to_claude_image(data: bytes, media_type: str) -> tuple[bytes, str]:
    """Convert any supported image format to one Claude accepts (JPEG fallback)."""
    if media_type in _CLAUDE_IMAGE_TYPES:
        return data, media_type
    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue(), "image/jpeg"


def _encode_image(image_path: str | Path) -> tuple[str, str]:
    """Return (base64_data, mime_type) for an image file, converting to JPEG if needed."""
    path = Path(image_path)
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type is None:
        mime_type = "image/jpeg"
    with open(path, "rb") as f:
        raw = f.read()
    data, mime_type = _to_claude_image(raw, mime_type)
    return base64.standard_b64encode(data).decode("utf-8"), mime_type


def combine_attachments_to_pdf(attachments: list[dict]) -> bytes | None:
    """
    Merge all image and PDF attachments into a single multi-page PDF.

    Each image becomes one page; each PDF contributes all its pages.
    Returns None if there are no processable attachments.
    """
    writer = PdfWriter()

    for att in attachments:
        media_type = att.get("media_type", "")
        data = att["data"]

        if media_type in ACCEPTED_IMAGE_TYPES:
            img_data, _ = _to_claude_image(data, media_type)
            img = Image.open(io.BytesIO(img_data)).convert("RGB")
            img_pdf_buf = io.BytesIO()
            img.save(img_pdf_buf, format="PDF")
            img_pdf_buf.seek(0)
            for page in PdfReader(img_pdf_buf).pages:
                writer.add_page(page)

        elif media_type == "application/pdf":
            for page in PdfReader(io.BytesIO(data)).pages:
                writer.add_page(page)

    if len(writer.pages) == 0:
        return None

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def summarize_german_document(
    image_paths: str | Path | list[str | Path],
    model: str = "claude-opus-4-8",
) -> str:
    """Summarize one or more images of a German letter/document in English."""
    if isinstance(image_paths, (str, Path)):
        image_paths = [image_paths]

    content: list[dict] = []
    for path in image_paths:
        data, mime_type = _encode_image(path)
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mime_type, "data": data},
        })

    page_word = "page" if len(image_paths) == 1 else f"{len(image_paths)} pages"
    content.append({
        "type": "text",
        "text": (
            f"These are {page_word} from a German letter or document. "
            "Please summarize the content in English."
        ),
    })

    response = client.messages.create(
        model=model,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        max_tokens=1024,
    )
    return response.content[0].text


def analyze_email(
    *,
    subject: str = "",
    sender: str = "",
    body: str = "",
    attachments: list[dict] | None = None,
    thread_history: list[dict] | None = None,
    existing_assets: list[str] | None = None,
    model: str = "claude-opus-4-8",
) -> dict:
    """
    Analyze an email with attachments and thread history.

    Returns a dict with:
        subject, summary — descriptive subject line and English summary
        category — one of CATEGORIES
        document_type, tags, document_date, expiry_date, asset_name, owner
            — best-effort metadata, null/empty when not determinable
    """
    attachments = attachments or []
    thread_history = thread_history or []
    existing_assets = existing_assets or []

    content: list[dict] = []

    # Build the text context block (thread history + current email)
    parts: list[str] = []
    if thread_history:
        parts.append("=== PREVIOUS EMAILS IN THREAD ===")
        for prev in thread_history:
            parts.append(f"From: {prev.get('from', 'Unknown')}")
            parts.append(f"Date: {prev.get('date', '')}")
            parts.append(f"Subject: {prev.get('subject', '')}")
            parts.append(prev.get("text") or "(no plain-text body)")
            parts.append("---")

    parts.append("=== CURRENT EMAIL ===")
    parts.append(f"From: {sender}")
    parts.append(f"Subject: {subject}")
    parts.append(f"Body:\n{body or '(no plain-text body)'}")

    content.append({"type": "text", "text": "\n".join(parts)})

    # Attach images and PDFs
    for att in attachments:
        media_type = att.get("media_type", "")
        raw = att["data"]

        if media_type in ACCEPTED_IMAGE_TYPES:
            img_data, img_type = _to_claude_image(raw, media_type)
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": img_type, "data": base64.standard_b64encode(img_data).decode()},
            })
        elif media_type == "application/pdf":
            content.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": base64.standard_b64encode(raw).decode()},
            })

    assets_hint = (
        f"The user already has these assets on file: {', '.join(existing_assets)}. "
        "Reuse one of these names verbatim if this document clearly belongs to it."
        if existing_assets
        else "The user has no assets on file yet."
    )

    content.append({
        "type": "text",
        "text": (
            "Respond with ONLY a single JSON object (no markdown fences, no prose "
            "outside the JSON), with exactly these keys:\n\n"
            '  "subject": concise descriptive subject line (max 60 chars) based on the '
            "actual content — ignore the original subject if it is vague, missing, or "
            "generic like 'test' or 'hello'\n"
            '  "summary": comprehensive English summary covering the sender\'s intent, '
            "key information from any attached German documents, action items or "
            "deadlines, and how this relates to the prior thread if any\n"
            f'  "category": exactly one of {json.dumps(CATEGORIES)}\n'
            '  "document_type": short free-text type, e.g. "Invoice", "Insurance Policy", '
            '"Utility Bill", "Contract"\n'
            '  "tags": array of 1-5 short lowercase tags\n'
            '  "document_date": ISO date (YYYY-MM-DD) the document itself is dated, or '
            "null if not determinable\n"
            '  "expiry_date": ISO date (YYYY-MM-DD) this document expires or is due/renews, '
            "or null if not applicable\n"
            f'  "asset_name": the real-world entity this document belongs to (e.g. "BMW '
            'iX3", "Frankfurt Apartment"), or null if it doesn\'t clearly belong to one. '
            f"{assets_hint}\n"
            '  "owner": the person\'s name this document concerns, or null if not '
            "identifiable"
        ),
    })

    response = client.messages.create(
        model=model,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        max_tokens=2048,
    )

    text = response.content[0].text.strip()
    result = {
        "subject": subject,
        "summary": text,
        "category": None,
        "document_type": None,
        "tags": [],
        "document_date": None,
        "expiry_date": None,
        "asset_name": None,
        "owner": None,
    }

    try:
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        parsed = json.loads(text)
        result["subject"] = (parsed.get("subject") or subject) or subject
        result["summary"] = parsed.get("summary") or result["summary"]
        if parsed.get("category") in CATEGORIES:
            result["category"] = parsed["category"]
        result["document_type"] = parsed.get("document_type") or None
        tags = parsed.get("tags")
        result["tags"] = [str(t) for t in tags] if isinstance(tags, list) else []
        result["document_date"] = parsed.get("document_date") or None
        result["expiry_date"] = parsed.get("expiry_date") or None
        result["asset_name"] = parsed.get("asset_name") or None
        result["owner"] = parsed.get("owner") or None
    except (json.JSONDecodeError, AttributeError, IndexError):
        pass  # keep the plain-text fallback populated above

    return result
