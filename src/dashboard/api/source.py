"""Workspace selection and bank statement endpoints."""

import secrets
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, StrictInt

from dashboard.routes import active_context, context
from dashboard.services.extraction import extraction_runs
from dashboard.services.projects import list_projects
from dashboard.services.review import Review
from reconciliation.intake.workspace import STATEMENT_YEARS

router = APIRouter(prefix="/api")


class PathChoice(BaseModel):
    """A user-selected local input path."""

    path: str = Field(min_length=1)


class ProjectChoice(BaseModel):
    """Identify a saved project without accepting a manifest path from the browser."""

    id: str = Field(min_length=1, max_length=24)


@router.get("/projects")
def projects(request: Request, state=Depends(context)):
    """List saved workspaces without changing selection or workflow state."""
    items = list_projects(state.sources, state.review)
    for item in items:
        if item['workspace']:
            item['in_use'] = request.app.state.sessions.in_use(state, Path(item['workspace']) / 'documents')
    return {"projects": items}


@router.post("/projects/select")
def select_project(body: ProjectChoice, state=Depends(context)):
    """Select saved inputs; the existing Proceed action still activates the review."""
    project = next((item for item in list_projects(state.sources, state.review) if item["id"] == body.id), None)
    if not project or not project["workspace"]:
        raise ValueError("Project is unavailable. Select its workspace folder again.")
    return state.sources.save_workspace(project["workspace"])


class StartChoice(BaseModel):
    """The exact preview the user explicitly chose to proceed with."""

    preview: str = Field(min_length=1)


class BankYear(BaseModel):
    """Require an explicit four-digit statement year."""

    year: StrictInt = Field(ge=STATEMENT_YEARS[0], le=STATEMENT_YEARS[1])


class ExportChoice(BaseModel):
    """Company heading used by the existing workbook exporter."""

    company: str


@router.get("/source")
def selected(state=Depends(context)):
    """Describe selected inputs and the active supporting review."""
    source, bank = state.sources.selected(), state.sources.selected_bank()
    return {
        "active": str(state.review.root) if state.review else None,
        "workspace": state.sources.selected_workspace(),
        "selected": state.sources.inspect(source) if source else None,
        "bank": state.sources.inspect_bank(bank) if bank else None,
    }


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


@router.post("/source/start")
def start(body: StartChoice, request: Request, state=Depends(context)):
    """Resume the same review; invalidate cached views only for a different project."""
    same_source = state.review and state.sources.selected() == state.review.root
    if state.review and not same_source:
        from dashboard.services.matching.piece_match_jobs import status as matching_status

        if extraction_runs.execution_status(state.review)["running"] or matching_status(state.review)["running"]:
            raise ValueError("Stop document processing and matching before changing workspaces")
    source = state.sources.selected()
    if source is None:
        raise ValueError('Choose a workspace first')
    sessions = request.app.state.sessions
    old = state.review.root if state.review else None
    sessions.claim(state, source)
    try:
        manifest, data = state.sources.start(body.preview)
        if state.review and state.review.manifest_path.resolve() == manifest.resolve():
            return {"active": str(state.review.root), "groups": len(state.review.groups), "resumed": True}
        review = Review(manifest, data)
        state.sources.activate(manifest)
        state.review = review
        state.review_id = secrets.token_hex(16)
    except Exception:
        if old is None or old.resolve() != source.resolve():
            sessions.release(state, source)
        raise
    if old is not None and old.resolve() != source.resolve():
        sessions.release(state, old)
    return {"active": str(review.root), "groups": len(review.groups), "resumed": False}


@router.post('/source/close')
def close_project(request: Request, state=Depends(active_context)):
    """Release a project explicitly after its background jobs have finished."""
    from dashboard.services.sessions import jobs_running

    if jobs_running(state.review):
        raise ValueError('Stop document processing and matching before closing the project')
    request.app.state.sessions.release(state, state.review.root)
    state.review = None
    state.review_id = secrets.token_hex(16)
    return {'closed': True}


@router.post("/source/bank-prepare")
def prepare_bank(body: BankYear, state=Depends(active_context)):
    """Extract deterministically in FastAPI's worker thread pool."""
    if state.sources.selected_workspace() and state.sources.selected() != state.review.root:
        raise ValueError("Create or open the selected workspace review before extracting its statement")
    return state.sources.prepare_bank(state.review.manifest_path, body.year)


@router.get("/bank-statement")
def bank_statement(state=Depends(context)):
    """Read saved transactions without invoking extraction."""
    return (
        state.review.bank_statement()
        if state.review
        else {"available": False, "transactions": [], "workbook_available": False}
    )


@router.get("/bank-export-defaults")
def export_defaults(state=Depends(active_context)):
    """Return saved workbook heading defaults."""
    return state.review.export_defaults()


@router.post("/bank-export")
def export_bank(body: ExportChoice, state=Depends(active_context)):
    """Generate the bank-only workbook without changing the master."""
    from reconciliation.bank.excel import export

    with tempfile.TemporaryDirectory() as temporary:
        output = export(
            state.review.manifest_path.parent / "bank-output/master_statement.csv",
            body.company,
            Path(temporary) / "answer_statement_bank_only.xlsx",
        )
        return Response(
            output.read_bytes(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
