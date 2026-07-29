import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

load_dotenv()

from summarize_images import summarize_german_document  # noqa: E402 — must come after load_dotenv

app = FastAPI(title="myletterbox")

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/summarize")
async def summarize(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="At least one image file is required.")

    for f in files:
        if f.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type '{f.content_type}'. Allowed: {sorted(ALLOWED_MIME_TYPES)}",
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
