"""Export complete supporting-document review inventory as CSV."""

import csv
import json


FIELDS = ("document_id", "source_path", "original_paths", "unit", "raw_text",
          "document_type", "invoice_numbers", "company", "brief_description",
          "references", "parties", "dates", "amounts_and_currencies",
          "details", "annotations_and_signatures", "limitations", "status",
          "duplicate_with", "comparison", "error")


def pair_key(left, right):
    """Use the same stable pair identifier as the review workflow."""
    return ":".join(sorted((left, right)))


def disposition(digest, index, state):
    """Summarize all comparisons involving one document without hiding pending work."""
    documents = index["documents"]
    if documents[digest]["error"]:
        return "unresolved", [], [], documents[digest]["error"]
    units = documents[digest]["units"]
    if any(unit.get("blocked") or state["units"].get(f"{digest}:{n}", {}).get("readable") is False
           for n, unit in enumerate(units)):
        return "unresolved", [], [], "Unit blocked or unreadable"
    if any(f"{digest}:{n}" not in state["units"] for n in range(len(units))):
        return "extraction_pending", [], [], ""
    matches, labels, pending = [], [], False
    for other in documents:
        if other == digest:
            continue
        pair = pair_key(digest, other)
        screen = state["screens"].get(pair)
        if screen is None:
            pending = True
            continue
        if not screen["candidate"]:
            continue
        result = state["pairs"].get(pair)
        decision = state["decisions"].get(pair)
        if result:
            labels.append(result["classification"])
        if not result or not decision:
            pending = True
        if result and result["classification"] == "same_document" and decision and decision["verdict"] != "keep_both":
            matches.append(other)
    if matches:
        status = "confirmed_duplicate"
    elif pending:
        status = "review_pending"
    elif labels:
        status = "reviewed_keep_both"
    else:
        status = "no_duplicate_found"
    candidates = [other for other in documents if other != digest and
                  state["screens"].get(pair_key(digest, other), {}).get("candidate")] if pending else []
    return status, matches or candidates, sorted(set(labels)), ""


def export(path, index, state):
    """Write one row per current source file and extracted review unit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for digest, document in sorted(index["documents"].items()):
            status, related, labels, error = disposition(digest, index, state)
            related_paths = [index["documents"][other]["paths"][0] for other in related]
            for source in document["paths"]:
                for number, unit in enumerate(document["units"] or [{}]):
                    data = state["units"].get(f"{digest}:{number}", {})
                    row = {"document_id": digest, "source_path": source,
                           "original_paths": json.dumps(document["original_paths"], ensure_ascii=False),
                           "unit": unit.get("label", ""), "raw_text": unit.get("text", ""),
                           "status": status, "duplicate_with": json.dumps(related_paths, ensure_ascii=False),
                           "comparison": json.dumps(labels, ensure_ascii=False),
                           "error": error or unit.get("blocked", "")}
                    for field in ("document_type", "brief_description", "details", "annotations_and_signatures"):
                        row[field] = data.get(field, "")
                    for field in ("invoice_numbers", "company", "references", "parties", "dates",
                                  "amounts_and_currencies", "limitations"):
                        row[field] = json.dumps(data.get(field, []), ensure_ascii=False)
                    writer.writerow(row)
    temporary.replace(path)
