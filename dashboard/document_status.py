"""Summarize saved content-review progress for every source document."""
from pathlib import Path

from reconciliation.vision_workflow import load
from dashboard.content_review import work_path


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
    eligible = {digest for digest, document in documents.items() if document.get("accepted", True)}
    screens = {digest: 0 for digest in eligible}
    candidates = {digest: 0 for digest in eligible}
    comparisons = {digest: 0 for digest in eligible}
    decisions = {digest: 0 for digest in eligible}
    for pair, screen in state["screens"].items():
        left, right = pair.split(":")
        for digest in (left, right):
            screens[digest] += 1
            if screen["candidate"]:
                candidates[digest] += 1
                comparisons[digest] += pair in state["pairs"]
                decisions[digest] += pair in state["decisions"]
    rows = []
    for digest, document in documents.items():
        if digest not in eligible:
            continue
        units = document["units"]
        read = sum(f"{digest}:{number}" in state["units"] for number in range(len(units)))
        if document["error"] or any(unit.get("blocked") for unit in units):
            status = "Needs attention"
        elif read < len(units):
            status = "Extracting" if read else "Waiting for extraction"
        elif any(not state["units"][f"{digest}:{number}"].get("readable") for number in range(len(units))):
            status = "Needs attention"
        elif screens[digest] < len(eligible) - 1:
            status = "Screening" if screens[digest] else "Waiting for screening"
        elif comparisons[digest] < candidates[digest]:
            status = "Comparing matches"
        elif decisions[digest] < candidates[digest]:
            status = "Admin review"
        else:
            status = "Complete"
        path = document["paths"][0]
        rows.append({"id": digest, "name": Path(path).name, "path": path, "status": status,
                     "units_read": read, "units_total": len(units), "pairs_screened": screens[digest],
                     "pairs_total": max(len(eligible) - 1, 0), "candidates": candidates[digest],
                     "comparisons": comparisons[digest], "decisions": decisions[digest]})
    rows.sort(key=lambda row: (row["name"].casefold(), row["path"].casefold()))
    return {"prepared": True, "documents": rows}
