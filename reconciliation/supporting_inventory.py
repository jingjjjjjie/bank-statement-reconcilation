"""Export one CSV row per original file and extracted unit, for audit."""

import csv
import json
from pathlib import Path

from reconciliation.currencies import normalize_currencies


FIELDS = ("document_id", "source_path", "original_path", "exact_duplicate_with", "file_format", "format_status", "unit", "raw_text",
          "receipts", "receipt_status", "supporting_evidence_status", "supporting_evidence_reason", "invoice_numbers", "company", "brief_description",
          "references", "parties", "dates", "amounts_and_currencies",
          "details", "annotations_and_signatures", "status", "duplicate_with", "error")


def status(digest, index, state, removed):
    """Return (status, kept duplicate hash or None, error) for one document."""
    document = index["documents"][digest]
    if not document.get("accepted", True):
        return "not_accepted", None, "Format is outside PDF, picture, .xlsx, and .docx review"
    if document["error"]:
        return "unresolved", None, document["error"]
    if digest in removed:
        return "confirmed_duplicate", removed[digest], ""
    units = [state["units"].get(f"{digest}:{n}") for n in range(len(document["units"]))]
    if any(unit.get("blocked") for unit in document["units"]) or any(u and u.get("readable") is False for u in units):
        return "unresolved", None, "Unit blocked or unreadable"
    if any(unit is None for unit in units):
        return "extraction_pending", None, ""
    return "extracted", None, ""


def export(path, index, state, removed):
    """Write the inventory atomically; `removed` maps admin-removed duplicates to the kept hash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for digest, document in sorted(index["documents"].items()):
            label, kept, error = status(digest, index, state, removed)
            kept_paths = [index["documents"][kept]["paths"][0]] if kept in index["documents"] else []
            originals = document["original_paths"] or document["paths"]
            for original in originals:
                for number, unit in enumerate(document["units"] or [{}]):
                    writer.writerow(_row(digest, document, originals, original, number, unit, state,
                                         label, kept_paths, error))
    temporary.replace(path)


def _row(digest, document, originals, original, number, unit, state, label, kept_paths, error):
    """Build one CSV row from a unit's saved extraction."""
    data = normalize_currencies(state["units"].get(f"{digest}:{number}", {}))
    row = {"document_id": digest, "original_path": original, "file_format": Path(original).suffix.lower(),
           "source_path": original if original in document["paths"] else document["paths"][0],
           "exact_duplicate_with": json.dumps([other for other in originals if other != original], ensure_ascii=False),
           "receipts": json.dumps([{("piece_type" if k == "document_type" else k): v for k, v in piece.items() if k != "limitations"}
                                   for piece in data.get("receipts", [])], ensure_ascii=False),
           "format_status": "accepted" if document.get("accepted", True) else "not_accepted",
           "unit": unit.get("label", ""), "raw_text": unit.get("text", ""), "status": label,
           "duplicate_with": json.dumps(kept_paths, ensure_ascii=False), "error": error or unit.get("blocked", "")}
    for field in ("receipt_status", "supporting_evidence_status", "supporting_evidence_reason", "brief_description",
                  "details", "annotations_and_signatures"):
        row[field] = data.get(field, "")
    for field in ("invoice_numbers", "company", "references", "parties", "dates", "amounts_and_currencies"):
        row[field] = json.dumps(data.get(field, []), ensure_ascii=False)
    return row
