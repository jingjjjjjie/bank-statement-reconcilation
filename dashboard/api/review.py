"""Review state and explicit human actions; business validation stays in Python workflows."""

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, StrictBool

from dashboard.routes import active_context, context, interrupt_context
from dashboard.services import development
from dashboard.services.extraction import document_status, extraction_runs, receipt_review
from dashboard.services.matching import final_review
from dashboard.services.review import workflow_guide
from reconciliation.core import development_cache
from reconciliation.core.settings import save_config
from reconciliation.intake.duplicates import check

router = APIRouter(prefix="/api")


class GroupChoice(BaseModel):
    """An explicit group selection or undo."""

    group: str
    id: str = ""


class SettingsChoice(BaseModel):
    """Settings validated by the existing revision-aware configuration module."""

    config: dict
    revision: str


class ModeChoice(BaseModel):
    """Require a real boolean for development-mode changes."""

    enabled: StrictBool


class Reviewer(BaseModel):
    """The person explicitly replaying saved decisions."""

    reviewer: str


@router.get("/workspace")
def workspace(state=Depends(context)):
    """Describe the current project for shared navigation."""
    return (
        state.review.workspace() if state.review else {"name": "No active review", "period": "Choose a source folder"}
    )


@router.get("/workflow-checks")
def workflow(request: Request):
    """Read header indicators without blocking evidence saves on the decision lock."""
    return workflow_guide(request.app.state.context.review)


@router.get("/state")
def snapshot(state=Depends(active_context)):
    """Read the exact-duplicate review and session token."""
    return {**state.review.snapshot(), "token": state.token}


@router.post("/keep")
def keep(body: GroupChoice, state=Depends(active_context)):
    """Retain the explicitly chosen legacy duplicate copy."""
    state.review.keep(body.group, body.id)
    return state.review.snapshot()


@router.post("/undo")
def undo(body: GroupChoice, state=Depends(active_context)):
    """Reverse an explicit legacy duplicate decision."""
    state.review.undo(body.group)
    return state.review.snapshot()


@router.post("/validate")
def validate(state=Depends(active_context)):
    """Rehash exact copies rather than trusting cached display state."""
    problems = check(state.review.root, state.review.manifest, state.review.manifest_path)
    return {"passed": not problems, "problems": problems}


@router.get("/config")
def config(state=Depends(active_context)):
    """Read settings and their current revision."""
    return state.review.settings()


@router.post("/config")
def configure(body: SettingsChoice, state=Depends(active_context)):
    """Save settings only if their source revision is current."""
    save_config(state.review.config_path, body.config, body.revision)
    return state.review.settings()


@router.get("/development-mode")
def mode():
    """Read the inexpensive shared development flag."""
    return development_cache.mode()


@router.post("/development-mode")
def set_mode(body: ModeChoice, state=Depends(context)):
    """Change development mode only when processing is idle."""
    if state.review and extraction_runs.execution_status(state.review)["running"]:
        raise ValueError("Stop the current review before changing development mode")
    result = development_cache.set_mode(body.enabled)
    if result["enabled"] and state.review:
        development.seed(state.review)
    return result


@router.get("/development-decisions")
def presets(state=Depends(active_context)):
    """Read remembered human decisions."""
    return development.snapshot(state.review)


def require_development():
    """Keep remembered-decision mutations behind the existing mode toggle."""
    if not development_cache.mode()["enabled"]:
        raise ValueError("Enable Development / testing mode in Settings first")


@router.post("/development/remember", dependencies=[Depends(require_development)])
def remember(state=Depends(active_context)):
    """Remember human decisions after an explicit click."""
    return development.remember(state.review)


@router.post("/development/apply", dependencies=[Depends(require_development)])
def apply(body: Reviewer, state=Depends(active_context)):
    """Replay only matching previously approved human decisions."""
    return development.apply(state.review, body.reviewer)


@router.get("/completion")
def completion(state=Depends(active_context)):
    """Read completion gates and qualified token totals."""
    return state.review.completion()


@router.get("/document-status")
def documents(state=Depends(context)):
    """Read saved processing progress without starting workers."""
    return document_status.snapshot(state.review)


@router.post("/content/prepare")
def prepare(state=Depends(active_context)):
    """Prepare local evidence in the request worker, outside the event loop."""
    return extraction_runs.prepare(state.review)


@router.post("/content/run")
def run(state=Depends(active_context)):
    """Start the existing cancellable background processing worker."""
    return extraction_runs.start(state.review)


@router.post("/content/stop")
def stop(review=Depends(interrupt_context)):
    """Cancel active model processes and retain completed checkpoints."""
    return extraction_runs.stop(review)


@router.get("/content/execution")
def execution(review=Depends(interrupt_context)):
    """Report process shutdown without reading document evidence."""
    return extraction_runs.execution_status(review)


@router.get("/receipts")
def receipts(state=Depends(context)):
    """Read receipt pieces and their revision."""
    return receipt_review.snapshot(state.review)


@router.get("/receipts/ground-truth")
def ground_truth(state=Depends(active_context)):
    """Download saved extraction reviews as a benchmark answer key."""
    body = json.dumps(receipt_review.ground_truth(state.review), ensure_ascii=False, indent=2)
    return Response(
        body, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="ground-truth.json"'}
    )


@router.post("/receipts/reset-original")
def reset_original_receipts(body: dict, state=Depends(active_context)):
    """Restore original model fields to the draft without changing saved approvals."""
    return receipt_review.original_extraction(state.review, body)


@router.post("/receipts/merge-all")
def merge_receipts(body: dict, state=Depends(active_context)):
    """Preview a merged draft; persistence still requires explicit acceptance."""
    from reconciliation.extraction.results.pieces import merge_all

    receipt_review.require_current(state.review, body['revision'])
    return {'receipt': merge_all(body['receipts'])}


@router.post("/receipts/accept")
def accept_receipts(body: dict, state=Depends(active_context)):
    """Validate receipt fields and stale revisions in the existing workflow."""
    return receipt_review.accept_extraction(state.review, body)


@router.post("/receipts/undo-accept")
def undo_accept_receipts(body: dict, state=Depends(active_context)):
    """Reopen an extraction while preserving its corrected receipt pieces."""
    return receipt_review.undo_accept_extraction(state.review, body)


@router.post("/receipts/accept-all")
def accept_all_receipts(body: dict, state=Depends(active_context)):
    """Accept current eligible extraction results without creating matching approvals."""
    return receipt_review.accept_all_extractions(state.review, body)


@router.post("/receipts/regenerate")
def regenerate_receipts(body: dict, state=Depends(active_context)):
    """Queue a document on the shared background extraction worker."""
    from dashboard.services.extraction import regeneration

    return {"jobs": regeneration.enqueue(state.review, body["document_id"])}


@router.post("/receipts/classify")
def classify_receipts(body: dict, state=Depends(active_context)):
    """Record an explicit trash or restore decision for a supporting document."""
    return receipt_review.classify_extraction(state.review, body)


@router.get("/receipts/regeneration")
def regeneration_status(state=Depends(active_context)):
    """Poll regeneration progress without rebuilding document previews."""
    from dashboard.services.extraction import regeneration

    return {"jobs": regeneration.snapshot(state.review)}


@router.get("/matching")
def matching(review=Depends(interrupt_context)):
    """Read a captured review without queuing behind unrelated workflow checks."""
    return final_review.snapshot(review)


@router.post("/matching-decide")
def matching_decide(body: dict, state=Depends(active_context)):
    """Keep evidence checks, revision checks, and human approval in the existing ledger."""
    return final_review.decide(state.review, body)


@router.post('/matching-pieces')
def matching_pieces(body: dict, state=Depends(active_context)):
    """Switch to reviewed pieces while preserving previous decisions as history."""
    from dashboard.services.matching.piece_matching import activate

    return activate(state.review)


@router.post('/matching-run')
def matching_run(body: dict, state=Depends(active_context)):
    """Generate proposals from complete documents without approving allocations."""
    from dashboard.services.matching.piece_match_jobs import start

    return start(state.review)


@router.get('/matching-run')
def matching_run_status(review=Depends(interrupt_context)):
    """Keep matching progress available while the background pool is working."""
    from dashboard.services.matching.piece_match_jobs import status

    return status(review)


@router.post('/matching-stop')
def matching_stop(body: dict, review=Depends(interrupt_context)):
    """Allow cancellation without waiting behind other review requests."""
    from dashboard.services.matching.piece_match_jobs import stop

    return stop(review)


@router.get("/matching-export")
def matching_export(include_evidence_paths: bool = True, state=Depends(active_context)):
    """Export every reviewed statement row under the existing export policy."""
    return Response(final_review.export_csv(state.review, include_evidence_paths), media_type="text/csv")


@router.get('/matching-workbook')
def matching_workbook(include_evidence_paths: bool = True, state=Depends(active_context)):
    """Download the styled final statement with optional supporting evidence paths."""
    from dashboard.services.matching.final_export import export_workbook

    filename = 'reviewed-statement-with-paths.xlsx' if include_evidence_paths else 'reviewed-statement.xlsx'
    return Response(
        export_workbook(state.review, include_evidence_paths),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
