"""Summarize saved content-review progress for every source document."""
from pathlib import Path
from reconciliation.receipt_assembly import current_assembly

from reconciliation.vision_workflow import load, removal_plan
from dashboard.content_review import work_path, execution_status


def snapshot(review):
    """Return document-level stages without starting model work."""
    if review is None:
        return {"prepared": False, "documents": []}
    work = work_path(review)
    if not (work / "index.json").is_file():
        return {"prepared": False, "documents": []}
    index, state = load(work)
    if Path(index["manifest"]).resolve() != review.manifest_path.resolve():
        raise ValueError("Prepared review belongs to a different manifest")
    documents = index["documents"]
    from dashboard.receipt_review import context
    review_units = context(review, include_banks=False, prepared=(index, state))[2]
    reviewed = {}
    discarded = {unit["document_id"] for unit in review_units.values() if unit.get("trash")}
    for unit in review_units.values():
        reviewed.setdefault(unit["document_id"], []).append(unit["accepted"])
    duplicates = removal_plan(state)
    eligible = {digest for digest, document in documents.items() if document.get("accepted", True)}
    rows = []
    for digest, document in documents.items():
        if digest not in eligible:
            continue
        units = document["units"]
        read = sum(f"{digest}:{number}" in state["units"] for number in range(len(units)))
        if digest in discarded:
            status = "Trash"
        elif document["error"] or any(unit.get("blocked") for unit in units):
            status = "Needs attention"
        elif read < len(units):
            status = "Processing" if read else "Queued"
        elif any(not state["units"][f"{digest}:{number}"].get("readable") for number in range(len(units))):
            status = "Needs attention"
        elif len(units) > 1 and not current_assembly(document, state):
            status = "Processing"
        elif not reviewed.get(digest) or not all(reviewed[digest]):
            status = "Needs review"
        else:
            status = "Complete"
        path = document["paths"][0]
        rows.append({"id": digest, "name": Path(path).name, "path": path, "status": status,
                     "approved_duplicate": digest in duplicates,
                     "extracted": bool(units) and status in {"Needs review", "Complete", "Trash"},
                     "assembly_total": int(len(units) > 1), "assembly_done": int(len(units) > 1 and bool(current_assembly(document, state))),
                     "units_read": read, "units_total": len(units)})
    rows.sort(key=lambda row: (row["name"].casefold(), row["path"].casefold()))
    return {"prepared": True, "documents": rows, **execution_status(review)}
