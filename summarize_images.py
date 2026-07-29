import base64
import mimetypes
from pathlib import Path

import anthropic

client = anthropic.Anthropic()

SYSTEM_PROMPT = (
    "You are an expert assistant that helps understand German documents, letters, and emails. "
    "When given emails with attachments (images or PDFs of German documents), provide a clear "
    "and comprehensive summary in English covering: the sender's intent, key information from "
    "any attached German documents, action items or deadlines, and how it relates to the prior "
    "email thread. When given standalone document images with no email context, summarize the "
    "document content including sender, recipient, key topics, and overall purpose."
)

_SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _encode_image(image_path: str | Path) -> tuple[str, str]:
    """Return (base64_data, mime_type) for an image file."""
    path = Path(image_path)
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type is None:
        mime_type = "image/jpeg"
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return data, mime_type


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
    model: str = "claude-opus-4-8",
) -> str:
    """
    Analyze an email with attachments and thread history, returning an English summary.

    Args:
        subject: Email subject line.
        sender: Sender address/name.
        body: Plain-text email body.
        attachments: List of {"data": bytes, "media_type": str, "filename": str}.
                     Supports images (jpeg/png/gif/webp) and PDFs.
        thread_history: Previous emails in the chain, each a dict with keys
                        "from", "date", "subject", "text".
        model: Claude model to use.

    Returns:
        Comprehensive English summary of the email, attachments, and thread context.
    """
    attachments = attachments or []
    thread_history = thread_history or []

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
        b64 = base64.standard_b64encode(att["data"]).decode()

        if media_type in _SUPPORTED_IMAGE_TYPES:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            })
        elif media_type == "application/pdf":
            content.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            })

    content.append({
        "type": "text",
        "text": (
            "Please provide a comprehensive English summary of this email and its attachments. "
            "Cover: the sender's intent, key information from any attached German documents, "
            "action items or deadlines, and how this relates to the prior thread (if any)."
        ),
    })

    response = client.messages.create(
        model=model,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        max_tokens=2048,
    )
    return response.content[0].text
