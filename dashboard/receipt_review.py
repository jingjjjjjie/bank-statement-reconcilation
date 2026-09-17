"""Persist receipt-level extraction approvals and human bank allocations."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import validate
from reconciliation.codex_reviewer import RECEIPT
from reconciliation.receipt_assembly import ASSEMBLED_RECEIPT, current_assembly, validate_assembly
from reconciliation.duplicate_workflow import fingerprint
from reconciliation.receipt_matching import allocated, amount, currency, proposal, revision, stale
from reconciliation.vision_workflow import load, removal_plan
from dashboard.content_review import execution_status, work_path
from dashboard.review import write_json


def current_hash(path):
    """Keep missing or modified evidence visible as stale rather than hiding decisions."""
    try:
        return fingerprint(Path(path))
    except OSError:
        return ""


def context(review):
    """Load current evidence and mark old approvals stale after an extraction refresh."""
    work = work_path(review)
    path = work / "receipt-matches.json"
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"extractions": {}, "matches": {}, "history": []}
    units, receipts, banks = {}, {}, {}
    if (work / "index.json").exists():
        index, state = load(work)
        if Path(index["manifest"]).resolve() != review.manifest_path.resolve():
            raise ValueError("Prepared review belongs to another manifest")
        removed = removal_plan(state)
        for digest, document in index["documents"].items():
            if digest in removed or not document.get("accepted", True) or document["error"]:
                continue
            source_hash = current_hash(document["paths"][0])
            assembled = len(document["units"]) > 1
            assembly = current_assembly(document, state) if assembled else None
            review_units = [(-1, {"label": "Whole document", "blocked": False})] if assembled else enumerate(document["units"])
            for number, unit in review_units:
                key = f"{digest}:{number}"
                raw = assembly if assembled else state["units"].get(key)
                if assembled and not raw:
                    raw = {"receipts": [], "limitations": ["Waiting for document receipt assembly"]}
                if not raw or unit.get("blocked"):
                    continue
                binding = revision([state["index_sha256"], raw, source_hash])
                accepted = saved["extractions"].get(key)
                accepted = accepted if accepted and accepted["source_revision"] == binding and source_hash == digest else None
                pieces = accepted["receipts"] if accepted else raw.get("receipts", [])
                evidence = revision([binding, pieces])
                units[key] = {"key": key, "document_id": digest, "unit": number, "label": unit["label"],
                              "source_path": document["paths"][0], "source_revision": binding,
                              "accepted": bool(accepted), "needs_refresh": "receipts" not in raw,
                              "receipts": pieces, "readable": raw.get("readable", assembled),
                              "assembled": assembled, "assembly_pending": assembled and assembly is None,
                              "limitations": raw.get("limitations", []),
                              "source_units": [{"number": n + 1, "label": source["label"]}
                                               for n, source in enumerate(document["units"])]}
                for position, piece in enumerate(pieces):
                    receipt_id = f"{digest}:u{number}:r{position}"
                    receipts[receipt_id] = {**piece, "receipt_id": receipt_id,
                        "document_id": digest, "unit": number, "source_path": document["paths"][0],
                        "accepted": bool(accepted), "evidence_revision": evidence}
    master = review.manifest_path.parent / "bank-output/master_statement.csv"
    if master.exists():
        master_revision = fingerprint(master)
        source_hashes = {}
        with master.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                incoming, outgoing = row.get("money_in", ""), row.get("money_out", "")
                value = outgoing if outgoing and amount(outgoing) > 0 else incoming
                source = row.get("source", "")
                if source not in source_hashes:
                    source_hashes[source] = current_hash(source)
                bank = {**row, "amount": value, "evidence_revision": revision([master_revision, row, source_hashes[source]])}
                if bank["transaction_id"] in banks:
                    raise ValueError("Bank transaction IDs must be unique")
                banks[bank["transaction_id"]] = bank
    return path, saved, units, receipts, banks


def snapshot(review):
    """Expose separate receipts, remaining amounts, and proposed or accepted matches."""
    if review is None:
        return {"revision": "", "units": [], "receipts": [], "transactions": [], "matches": []}
    path, saved, units, receipts, banks = context(review)
    used = allocated(saved["matches"])
    for key, receipt in receipts.items():
        receipt["allocated_amount"] = str(used.get(key, 0))
        try:
            receipt["remaining_amount"] = str(amount(receipt["total"]) - used.get(key, 0))
        except ValueError:
            receipt["remaining_amount"] = ""
    matches = [{**match, "stale": bool(stale(match, banks, receipts))} for match in saved["matches"].values()]
    return {"revision": revision([saved, units, banks]), "units": list(units.values()),
            "receipts": list(receipts.values()), "transactions": list(banks.values()), "matches": matches}


def require_current(review, expected):
    """Reject stale browser submissions and concurrent content-review mutations."""
    if execution_status(review)["running"]:
        raise ValueError("Wait for the document batch to finish before approving or matching")
    if snapshot(review)["revision"] != expected:
        raise ValueError("Evidence or decisions changed; reload before saving")


def verify_source(item):
    """Check original bytes before accepting any extraction or bank allocation."""
    if fingerprint(Path(item["source_path"])) != item["document_id"]:
        raise ValueError("Supporting source changed; refresh the extraction")


def record(path, saved, action, reviewer, before, after):
    """Audit explicit decisions; extraction approval does not require a name."""
    if not (action == "accept_extraction" and reviewer is None) and (not isinstance(reviewer, str) or not reviewer.strip()):
        raise ValueError("Enter your name")
    saved["history"].append({"at": datetime.now(timezone.utc).isoformat(), "reviewer": reviewer.strip() if reviewer else None,
                             "action": action, "before": before, "after": after})
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, saved)


def accept_extraction(review, body):
    """Accept corrected pieces without merging totals or changing the source document."""
    require_current(review, body["revision"])
    path, saved, units, receipts, banks = context(review)
    unit = units[body["key"]]
    verify_source(unit)
    if unit.get("assembly_pending"):
        raise ValueError("Run documents to finish receipt assembly before accepting")
    if any(match["review_status"] == "accepted" and any(
            item["document_id"] == unit["document_id"] and (unit.get("assembled") or item["unit"] == unit["unit"])
            for item in match["supporting_items"]) for match in saved["matches"].values()):
        raise ValueError("Undo accepted matches for this unit before changing its receipts")
    pieces = body["receipts"]
    validate(pieces, {"type": "array", "items": ASSEMBLED_RECEIPT if unit.get("assembled") else RECEIPT, "maxItems": 100})
    if unit.get("assembled"):
        validate_assembly({"receipts": pieces, "reviewed_units": [s["number"] for s in unit["source_units"]],
                           "limitations": []}, len(unit["source_units"]))
        if any(piece["needs_review"] for piece in pieces):
            raise ValueError("Resolve flagged receipt boundaries before accepting")
    for piece in pieces:
        if piece["total"]:
            amount(piece["total"])
        if piece["currency"]:
            currency(piece["currency"])
    previous = saved["extractions"].get(body["key"])
    value = {"source_revision": unit["source_revision"], "receipts": pieces, "reviewer": body.get("reviewer")}
    saved["extractions"][body["key"]] = value
    record(path, saved, "accept_extraction", body.get("reviewer"), previous, value)
    return snapshot(review)


def change_match(review, body):
    """Propose, accept, reject, or undo an allocation with immutable decision history."""
    require_current(review, body["revision"])
    path, saved, units, receipts, banks = context(review)
    bank_id, action = body["bank_transaction_id"], body["action"]
    previous = saved["matches"].get(bank_id)
    if action == "propose":
        if previous and previous["review_status"] == "accepted":
            raise ValueError("Undo the accepted match before changing it")
        value = proposal(banks[bank_id], body["supporting_items"], receipts, saved["matches"])
    elif action == "accept":
        if not previous or previous["review_status"] != "pending" or stale(previous, banks, receipts):
            raise ValueError("Create a current pending proposal before accepting")
        value = proposal(banks[bank_id], previous["supporting_items"], receipts, saved["matches"])
        for item in value["supporting_items"]:
            verify_source(receipts[item["receipt_id"]])
        bank = banks[bank_id]
        if bank.get("balance_checks") != "passed":
            raise ValueError("Bank balance validation must pass before accepting matches")
        if fingerprint(Path(bank["source"])) != bank["source_sha256"].upper():
            raise ValueError("Bank source changed; refresh the bank extraction")
        if amount(value["bank_amount"]) != amount(value["supporting_total"]) and not body.get("reason", "").strip():
            raise ValueError("Explain the amount difference before accepting")
        value["review_status"] = "accepted"
    elif action in {"reject", "undo"}:
        required = "pending" if action == "reject" else "accepted"
        if not previous or previous["review_status"] != required:
            raise ValueError(f"This action requires a {required} match")
        value = {**previous, "review_status": "rejected" if action == "reject" else "undone"}
    else:
        raise ValueError("Unknown match action")
    value = {**value, "reviewer": body["reviewer"], "reason": body.get("reason", "")}
    saved["matches"][bank_id] = value
    record(path, saved, action, body["reviewer"], previous, value)
    return snapshot(review)
