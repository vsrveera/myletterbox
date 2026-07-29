import base64
import mimetypes
from pathlib import Path

import anthropic

client = anthropic.Anthropic()

SYSTEM_PROMPT = (
    "You are an expert at reading German documents and letters. "
    "When given one or more images of German text, provide a clear and concise "
    "summary in English of the document's content, including the sender, recipient, "
    "key topics, any action items or deadlines, and the overall purpose of the document."
)


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
    """
    Summarize one or more images of a German letter/document in English.

    Args:
        image_paths: A single image path or a list of image paths (e.g. scanned pages).
        model: Claude model to use.

    Returns:
        English summary of the document content.
    """
    if isinstance(image_paths, (str, Path)):
        image_paths = [image_paths]

    content: list[dict] = []
    for path in image_paths:
        data, mime_type = _encode_image(path)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": data,
            },
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
