"""Prepare local files and display previews without making model calls."""
from datetime import datetime, timezone
from pathlib import Path

from dashboard.excel_pdf import convert_excel_to_pdf
from dashboard.content_review import work_path
from reconciliation.vision_workflow import inventory, load_index, prepare, save
from reconciliation.review_settings import load_config


def prepare_workspace(review, progress):
    """Cache display PDFs separately, then prepare original extraction inputs."""
    warnings, previews = [], []
    work = work_path(review)
    inputs = inventory(review.root, review.manifest_path)
    excel = [(digest, Path(paths[0])) for digest, paths in inputs.items()
             if Path(paths[0]).suffix.lower() == ".xlsx"]
    for number, (digest, source) in enumerate(excel):
        progress("excel", number, len(excel), source.name)
        record = {"source": str(source), "sha256": digest}
        try:
            record.update(status="ready", preview=str(convert_excel_to_pdf(source)))
        except (OSError, RuntimeError, ValueError) as error:
            record.update(status="unresolved", error=str(error))
            warnings.append(f"{source.name}: {error}")
        previews.append(record)
    progress("excel", len(excel), len(excel), "Excel previews prepared")
    save(review.manifest_path.parent / "preview-status.json", {
        "at": datetime.now(timezone.utc).isoformat(), "display_only": True, "files": previews})
    progress("files", 0, 0, "Preparing PDF pages, images and document data")
    if not (work / "index.json").exists():
        if not review.config_path.exists():
            save(review.config_path, load_config(review.config_path))
        prepare(review.manifest_path, work, review.config_path,
                progress=lambda done, total, name: progress("files", done, total, name))
    index, _ = load_index(work)
    for document in index["documents"].values():
        if document.get("error"):
            warnings.append(f'{Path(document["paths"][0]).name}: {document["error"]}')
    progress("files", len(index["documents"]), len(index["documents"]), "Files prepared")
    return warnings
