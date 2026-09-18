"""Resolve previews through existing evidence checks before returning source bytes."""
import json
import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from dashboard.routes import active_context
from dashboard import content_review, extraction_preview, matching_review, office_preview
from reconciliation.duplicate_workflow import fingerprint

router = APIRouter(prefix="/api")


def file_response(path, mime=None):
    """Read a validated source while the review lock protects its location."""
    return Response(path.read_bytes(), media_type=mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream")


def matching_source(kind: str, id: str, request: Request):
    """Capture one review and validate read-only evidence without the decision lock."""
    review = request.app.state.context.review
    if review is None:
        raise HTTPException(409, "Select a workspace before viewing evidence")
    return matching_review.evidence(review, kind, id)


@router.get("/matching-preview")
def matching_preview(path=Depends(matching_source)):
    """Describe a validated bank or supporting source."""
    return extraction_preview.describe(path)


@router.get("/matching-image")
def matching_image(page: int = Query(0, ge=0), path=Depends(matching_source)):
    """Render one validated evidence page."""
    return Response(extraction_preview.image(path, page), media_type="image/png")


@router.get("/matching-office")
def matching_office(page: int = Query(0, ge=0), path=Depends(matching_source)):
    """Return structured Office evidence without executing embedded content."""
    return office_preview.page(path, page)


@router.get("/matching-file")
def matching_file(kind: str, id: str, state=Depends(active_context)):
    """Return original matching evidence with a conservative content type."""
    path = matching_review.evidence(state.review, kind, id)
    safe = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".txt", ".csv", ".xlsx", ".docx"}
    response = file_response(path, None if path.suffix.lower() in safe else "application/octet-stream")
    response.headers['Content-Disposition'] = "inline; filename*=UTF-8''" + quote(path.name, safe='')
    return response


def extraction_source(id: str, request: Request):
    """Validate one Step 2 original independently of slow workflow status checks."""
    review = request.app.state.context.review
    if review is None:
        raise HTTPException(409, "Select a workspace before viewing evidence")
    return content_review.source(review, id)


@router.get("/extraction-preview")
def extraction(path=Depends(extraction_source)):
    """Describe a source referenced by the prepared review."""
    return extraction_preview.describe(path)


@router.get("/extraction-preview-image")
def extraction_image(page: int = Query(0, ge=0), path=Depends(extraction_source)):
    """Render the requested original source page."""
    if page == 0 and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        from PIL import Image
        with Image.open(path) as picture:
            if getattr(picture, "n_frames", 1) == 1 and picture.format in {"JPEG", "PNG", "WEBP"}:
                return file_response(path, Image.MIME[picture.format])
    return Response(extraction_preview.image(path, page), media_type="image/png")


@router.get("/extraction-office")
def extraction_office(page: int = Query(0, ge=0), path=Depends(extraction_source)):
    """Read one validated Step 2 Office page without the workflow decision lock."""
    return office_preview.page(path, page)


@router.get("/content-file")
def content_file(id: str, state=Depends(active_context)):
    """Return only an unchanged file named in the prepared review."""
    return file_response(content_review.source(state.review, id))


@router.get("/content-image")
def content_image(id: str, unit: int = Query(ge=0), state=Depends(active_context)):
    """Return a validated prepared page image."""
    return file_response(content_review.image(state.review, id, unit), "image/png")


@router.get("/bank-workbook")
def bank_workbook(state=Depends(active_context)):
    """Return the known bank-only export path."""
    return file_response(state.review.manifest_path.parent / "bank-output/answer_statement_bank_only.xlsx")


@router.get("/document")
def document(id: str | None = None, content_id: str | None = None, state=Depends(active_context)):
    """Describe either an exact-copy source or prepared content source."""
    if content_id is not None:
        return office_preview.describe(content_review.source(state.review, content_id))
    if id is None:
        raise HTTPException(422, "A document ID is required")
    return state.review.document(id)


@router.get("/office-view")
def office(id: str | None = None, content_id: str | None = None,
           page: int = Query(0, ge=0), state=Depends(active_context)):
    """Render structured Office data from an authorized source."""
    if content_id is None and id is None:
        raise HTTPException(422, "A document ID is required")
    path = content_review.source(state.review, content_id) if content_id else state.review.file_path(id)
    return office_preview.page(path, page)


@router.get("/file")
def original(id: str, state=Depends(active_context)):
    """Open an exact-review source through its manifest ID."""
    return file_response(state.review.file_path(id))


@router.get("/preview")
def preview(id: str, page: int = Query(0, ge=0), state=Depends(active_context)):
    """Preserve PDF, image, and Office previews for legacy exact reviews."""
    path = state.review.file_path(id)
    if path.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(path) as pdf:
            return Response(pdf[page].get_pixmap(dpi=110, alpha=False).tobytes("png"), media_type="image/png")
    metadata = state.review.document(id)
    if metadata["kind"] == "office":
        units = json.loads((state.review.data / "previews" / fingerprint(path) / "units.json").read_text(encoding="utf-8"))
        path = Path(units[page]["image"])
    return file_response(path)
