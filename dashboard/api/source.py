"""Workspace selection and bank statement endpoints."""
import secrets
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field, StrictInt

from dashboard.routes import context, active_context
from dashboard.review import Review
from dashboard import content_review
from reconciliation import development_cache

router = APIRouter(prefix="/api")


class PathChoice(BaseModel):
    """A user-selected local input path."""
    path: str = Field(min_length=1)


class StartChoice(BaseModel):
    """The exact preview the user explicitly chose to proceed with."""
    preview: str = Field(min_length=1)


class BankYear(BaseModel):
    """Require an explicit four-digit statement year."""
    year: StrictInt = Field(ge=1900, le=2100)


class ExportChoice(BaseModel):
    """Company heading used by the existing workbook exporter."""
    company: str


@router.get("/source")
def selected(state=Depends(context)):
    """Describe selected inputs and the active supporting review."""
    source, bank = state.sources.selected(), state.sources.selected_bank()
    return {"active": str(state.review.root) if state.review else None,
            "workspace": state.sources.selected_workspace(),
            "selected": state.sources.inspect(source) if source else None,
            "bank": state.sources.inspect_bank(bank) if bank else None}


@router.get("/source/browse")
def browse(path: str | None = None, kind: str = "folder", state=Depends(context)):
    """List local folders or PDFs for the picker."""
    return state.sources.browse(path, kind == "bank")


@router.get("/source/preview")
def preview(state=Depends(context)):
    """Hash current inputs before permitting activation."""
    return state.sources.preview()


@router.post("/source/workspace-select")
def select_workspace(body: PathChoice, state=Depends(context)):
    """Validate and save both inputs without starting processing."""
    return state.sources.save_workspace(body.path)


@router.post("/source/select")
def select_documents(body: PathChoice, state=Depends(context)):
    """Retain supporting-folder selection for existing clients."""
    return {"selected": state.sources.save(body.path)}


@router.post("/source/bank-select")
def select_bank(body: PathChoice, state=Depends(context)):
    """Retain explicit selection of a statement PDF."""
    return {"bank": state.sources.save_bank(body.path)}


@router.post("/source/start")
def start(body: StartChoice, state=Depends(context)):
    """Activate verified inputs and invalidate cached browser views."""
    if state.review and content_review.execution_status(state.review)["running"]:
        raise ValueError("Stop document processing before changing workspaces")
    manifest, data = state.sources.start(body.preview)
    review = Review(manifest, data)
    state.sources.activate(manifest)
    state.review = review
    state.review_id = secrets.token_hex(16)
    return {"active": str(review.root), "groups": len(review.groups)}


@router.post("/source/bank-prepare")
def prepare_bank(body: BankYear, state=Depends(active_context)):
    """Extract deterministically in FastAPI's worker thread pool."""
    if state.sources.selected_workspace() and state.sources.selected() != state.review.root:
        raise ValueError("Create or open the selected workspace review before extracting its statement")
    return state.sources.prepare_bank(state.review.manifest_path, body.year)


@router.get("/bank-statement")
def bank_statement(state=Depends(context)):
    """Read saved transactions without invoking extraction."""
    return state.review.bank_statement() if state.review else {
        "available": False, "transactions": [], "workbook_available": False}


@router.get("/bank-export-defaults")
def export_defaults(state=Depends(active_context)):
    """Return saved workbook heading defaults."""
    return state.review.export_defaults()


@router.post("/bank-export")
def export_bank(body: ExportChoice, state=Depends(active_context)):
    """Generate the bank-only workbook without changing the master."""
    from reconciliation.bank_excel import export
    with tempfile.TemporaryDirectory() as temporary:
        output = export(state.review.manifest_path.parent / "bank-output/master_statement.csv",
                        body.company, Path(temporary) / "answer_statement_bank_only.xlsx")
        development_cache.capture(state.review.manifest_path, "bank-export", [output])
        return Response(output.read_bytes(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
