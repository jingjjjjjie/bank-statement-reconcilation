"""Resolve previews through existing evidence checks before returning source bytes."""

import json
import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from dashboard.previews import extraction as extraction_preview, office as office_preview
from dashboard.routes import active_context
from dashboard.services.extraction import extraction_runs
from dashboard.services.matching import final_review
from reconciliation.intake.duplicates import fingerprint

router = APIRouter(prefix="/api")


def file_response(path, mime=None):
    """Read a validated source while the review lock protects its location."""
    return Response(
        path.read_bytes(), media_type=mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    )


def matching_source(kind: str, id: str, request: Request):
    """Capture one review and validate read-only evidence without the decision lock."""
    review = request.state.context.review
    if review is None:
        raise HTTPException(409, "Select a workspace before viewing evidence")
    return final_review.evidence(review, kind, id)


@router.get("/matching-preview")
def matching_preview(path=Depends(matching_source)):
    """Describe a validated bank or supporting source."""
    return {**extraction_preview.describe(path), "source_path": str(path)}


@router.get("/matching-image")
def matching_image(page: int = Query(0, ge=0), path=Depends(matching_source)):
    """Render one validated evidence page."""
    return Response(extraction_preview.image(path, page), media_type="image/png")


@router.get("/matching-office")
def matching_office(page: int = Query(0, ge=0), path=Depends(matching_source)):
    """Return structured Office evidence without executing embedded content."""
    return office_preview.page(path, page)


@router.get("/matching-file")
def matching_file(kind: str, id: str, download: bool = False, state=Depends(active_context)):
    """Return original matching evidence with a conservative content type."""
    path = final_review.evidence(state.review, kind, id)
    safe = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".txt", ".csv", ".xlsx", ".docx"}
    response = file_response(path, None if path.suffix.lower() in safe else "application/octet-stream")
    disposition = "attachment" if download else "inline"
    response.headers['Content-Disposition'] = disposition + "; filename*=UTF-8''" + quote(path.name, safe='')
    return response


def extraction_source(id: str, request: Request):
    """Validate one Step 2 original independently of slow workflow status checks."""
    review = request.state.context.review
    if review is None:
        raise HTTPException(409, "Select a workspace before viewing evidence")
    return extraction_runs.source(review, id)


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
    return file_response(extraction_runs.source(state.review, id))


@router.get("/bank-workbook")
def bank_workbook(state=Depends(active_context)):
    """Return the known bank-only export path."""
    return file_response(state.review.manifest_path.parent / "bank-output/answer_statement_bank_only.xlsx")


@router.get("/document")
def document(id: str | None = None, content_id: str | None = None, state=Depends(active_context)):
    """Describe either an exact-copy source or prepared content source."""
    if content_id is not None:
        return office_preview.describe(extraction_runs.source(state.review, content_id))
    if id is None:
        raise HTTPException(422, "A document ID is required")
    return state.review.document(id)


@router.get("/office-view")
def office(
    id: str | None = None, content_id: str | None = None, page: int = Query(0, ge=0), state=Depends(active_context)
):
    """Render structured Office data from an authorized source."""
    if content_id is None and id is None:
        raise HTTPException(422, "A document ID is required")
    path = extraction_runs.source(state.review, content_id) if content_id else state.review.file_path(id)
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
        units = json.loads(
            (state.review.data / "previews" / fingerprint(path) / "units.json").read_text(encoding="utf-8")
        )
        path = Path(units[page]["image"])
    return file_response(path)


@router.get('/unmatched-documents-export')
def unmatched_documents_export(state=Depends(active_context)):
    """Download unmatched originals in their folder structure and clean up the temporary ZIP."""
    from dashboard.services.matching.unmatched_export import export_zip

    path = export_zip(state.review)
    return FileResponse(
        path,
        media_type='application/zip',
        filename='unmatched-documents.zip',
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.get('/source-export')
def source_export(kind: str, state=Depends(active_context)):
    """Download original or confirmed-match inputs with temporary-file cleanup."""
    from dashboard.services.source_export import export_zip

    names = {'original': 'original-documents.zip', 'project': 'original-project.zip', 'matched': 'matched-documents.zip'}
    if kind not in names:
        raise HTTPException(400, 'Unknown document export option')
    path = export_zip(state.review, kind)
    return FileResponse(
        path, media_type='application/zip', filename=names[kind],
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.get('/matching-evidence-download')
def matching_evidence_download(bank_id: str, state=Depends(active_context)):
    """Download one verified original or a ZIP of this transaction's approved documents."""
    import hashlib

    from dashboard.services.matching.evidence_download import approved_files
    from dashboard.services.matching.unmatched_export import write_zip

    files = approved_files(state.review, bank_id)
    if len(files) == 1:
        source, _, expected = files[0]
        body = source.read_bytes()
        if hashlib.sha256(body).hexdigest().upper() != expected:
            raise ValueError('A document changed during export; retry the download')
        return Response(
            body,
            media_type=mimetypes.guess_type(source.name)[0] or 'application/octet-stream',
            headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(source.name, safe='')},
        )
    path = write_zip(files, [])
    return FileResponse(
        path, media_type='application/zip', filename=f'evidence-{bank_id}.zip',
        background=BackgroundTask(path.unlink, missing_ok=True),
    )
