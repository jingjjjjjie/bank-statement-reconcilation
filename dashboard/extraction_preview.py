"""Read-only original-document previews for extraction review."""
import io
from zipfile import ZipFile

import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError

from dashboard import office_preview


def embedded_images(path):
    """List Office picture parts without extracting archive paths onto disk."""
    with ZipFile(path) as archive:
        return sorted(name for name in archive.namelist()
                      if name.startswith(("word/media/", "xl/media/"))
                      and name.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif")))


def describe(path):
    """Expose pages or sheets for every renderable source, with an explicit fallback."""
    suffix = path.suffix.lower()
    if suffix in {".docx", ".xlsx"}:
        info = office_preview.describe(path)
        pictures = embedded_images(path)
        return {**info, "office_pages": info["pages"], "pages": info["pages"] + len(pictures),
                "labels": info["labels"] + [f"Embedded image: {name}" for name in pictures]}
    if suffix == ".pdf":
        with pymupdf.open(path) as document:
            if document.needs_pass:
                raise ValueError("This PDF requires a password. Open the original document.")
            count = len(document)
        return {"kind": "pdf", "pages": count, "labels": [f"Page {n + 1}" for n in range(count)]}
    try:
        with Image.open(path) as picture:
            count = getattr(picture, "n_frames", 1)
        return {"kind": "image", "pages": count, "labels": [f"Image {n + 1}" for n in range(count)]}
    except UnidentifiedImageError:
        if suffix in {".txt", ".csv", ".json", ".xml", ".md", ".log"}:
            return {"kind": "text", "pages": 1, "labels": ["Document"],
                    "text": path.read_text(encoding="utf-8-sig", errors="replace")}
        return {"kind": "unsupported", "pages": 0, "labels": [],
                "message": "Inline preview is unavailable for this format. Open the original document to review it."}


def image(path, page):
    """Render a PDF page or image frame without requiring a browser format plugin."""
    if page < 0:
        raise ValueError("Invalid preview page")
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as document:
            if page >= len(document):
                raise ValueError("Invalid preview page")
            return document[page].get_pixmap(dpi=150, alpha=False).tobytes("png")
    source = path
    if path.suffix.lower() in {".docx", ".xlsx"}:
        number = page - office_preview.describe(path)["pages"]
        pictures = embedded_images(path)
        if not 0 <= number < len(pictures):
            raise ValueError("Invalid embedded image")
        with ZipFile(path) as archive:
            source = io.BytesIO(archive.read(pictures[number]))
        page = 0
    with Image.open(source) as picture:
        if page >= getattr(picture, "n_frames", 1):
            raise ValueError("Invalid preview page")
        picture.seek(page)
        rendered = ImageOps.exif_transpose(picture).convert("RGB")
        output = io.BytesIO()
        rendered.save(output, format="PNG")
        return output.getvalue()
