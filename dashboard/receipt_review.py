"""Persist receipt-level extraction approvals and human bank allocations."""
from concurrent.futures import ThreadPoolExecutor
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import validate, ValidationError
from reconciliation.codex_reviewer import RECEIPT
from reconciliation.currencies import normalize_currencies
from reconciliation.pdf_routing import review_warnings
from reconciliation.pieces import identify, assign_submitted
from reconciliation.receipt_assembly import ASSEMBLED_RECEIPT, current_assembly, validate_assembly
from reconciliation.duplicate_workflow import fingerprint
from reconciliation.receipt_matching import allocated, amount, currency, proposal, revision, stale
from reconciliation.vision_workflow import load_index, removal_plan
from dashboard.content_review import execution_status, work_path
from dashboard.review import write_json


def current_hash(path):
    """Keep missing or modified evidence visible as stale rather than hiding decisions."""
    try:
        return fingerprint(Path(path))
    except OSError:
        return ""


def context(review, *, include_banks=True, prepared=None):
    """Load current evidence and mark old approvals stale after an extraction refresh."""
    work = work_path(review)
    path = work / "receipt-matches.json"
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"extractions": {}, "matches": {}, "history": []}
    units, receipts, banks = {}, {}, {}
    if (work / "index.json").exists():
        from dashboard import regeneration
        jobs = regeneration.snapshot(review)
        index, state = prepared if prepared is not None else load_index(work)
        if Path(index["manifest"]).resolve() != review.manifest_path.resolve():
            raise ValueError("Prepared review belongs to another manifest")
        removed = removal_plan(state)
        originals = {document["paths"][0] for digest, document in index["documents"].items()
                     if digest not in removed and document.get("accepted", True) and not document["error"]}
        previews = {unit["image"]: unit["image_sha256"]
                    for document in index["documents"].values() for unit in document["units"]
                    if unit["image"]} if prepared is None else {}
        paths = sorted(originals | previews.keys())
        # Hash fresh bytes in parallel; never infer integrity from timestamps or cached hashes.
        with ThreadPoolExecutor(max_workers=8) as pool:
            hashes = dict(zip(paths, pool.map(current_hash, paths)))
        if any(hashes[path] != digest for path, digest in previews.items()):
            raise ValueError("Prepared image changed; create a new review")
        for digest, document in index["documents"].items():
            if digest in removed or not document.get("accepted", True) or document["error"]:
                continue
            source_hash = hashes[document["paths"][0]]
            trash = digest in saved.get("trash", {}) and source_hash == digest
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
                job = jobs.get(digest)
                binding_parts = [state["index_sha256"], raw, source_hash]
                if job:
                    binding_parts.append(job["id"])
                binding = revision(binding_parts)
                accepted = saved["extractions"].get(key)
                accepted = accepted if accepted and accepted["source_revision"] == binding and source_hash == digest else None
                pieces = identify(accepted["receipts"] if accepted else raw.get("receipts", []), digest, number, binding)
                evidence = revision([binding, pieces])
                units[key] = {"key": key, "document_id": digest, "unit": number, "label": unit["label"],
                              "source_path": document["paths"][0], "source_revision": binding,
                              "accepted": bool(accepted) and not trash, "trash": trash,
                              "needs_refresh": "receipts" not in raw,
                              "receipts": pieces, "readable": raw.get("readable", assembled),
                              "assembled": assembled, "assembly_pending": assembled and assembly is None,
                              "review_warnings": list(dict.fromkeys(warning
                                  for n in range(len(document["units"]))
                                  for warning in review_warnings(state["units"].get(f"{digest}:{n}", {})))),
                              "regeneration": job,
                              "supporting_evidence": [{"label": source["label"],
                                  "status": state["units"].get(f"{digest}:{n}", {}).get("supporting_evidence_status", "uncertain"),
                                  "reason": state["units"].get(f"{digest}:{n}", {}).get("supporting_evidence_reason", "")}
                                  for n, source in enumerate(document["units"])],
                              "source_units": [{"number": n + 1, "label": source["label"]}
                                               for n, source in enumerate(document["units"])]}
                for position, piece in enumerate([] if trash else pieces):
                    receipt_id = f"{digest}:u{number}:r{position}"
                    receipts[receipt_id] = {**piece, "receipt_id": receipt_id,
                        "document_id": digest, "unit": number, "source_path": document["paths"][0],
                        "accepted": bool(accepted), "evidence_revision": evidence}
    if not include_banks:
        return path, saved, units, receipts, banks
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
    return snapshot_context(context(review))


def snapshot_context(evidence):
    """Serialize one verified evidence set without rereading every source file."""
    path, saved, units, receipts, banks = evidence
    used = allocated(saved["matches"])
    for key, receipt in receipts.items():
        receipt["allocated_amount"] = str(used.get(key, 0))
        try:
            receipt["remaining_amount"] = str(amount(receipt["total"]) - used.get(key, 0))
        except ValueError:
            receipt["remaining_amount"] = ""
    matches = [{**match, "stale": bool(stale(match, banks, receipts))} for match in saved["matches"].values()]
    return normalize_currencies({"revision": revision([saved, units, banks]), "units": list(units.values()),
            "receipts": list(receipts.values()), "transactions": list(banks.values()), "matches": matches})


def require_current(review, expected):
    """Reject stale browser submissions and concurrent content-review mutations."""
    if execution_status(review)["running"]:
        raise ValueError("Wait for the document batch to finish before approving or matching")
    evidence = context(review)
    if snapshot_context(evidence)["revision"] != expected:
        raise ValueError("Evidence or decisions changed; reload before saving")
    return evidence


def verify_source(item):
    """Check original bytes before accepting any extraction or bank allocation."""
    if fingerprint(Path(item["source_path"])) != item["document_id"]:
        raise ValueError("Supporting source changed; refresh the extraction")


def record(path, saved, action, reviewer, before, after):
    """Audit explicit decisions; extraction approval does not require a name."""
    if not (action in {"accept_extraction", "trash_extraction", "restore_extraction"} and reviewer is None) and (not isinstance(reviewer, str) or not reviewer.strip()):
        raise ValueError("Enter your name")
    saved["history"].append({"at": datetime.now(timezone.utc).isoformat(), "reviewer": reviewer.strip() if reviewer else None,
                             "action": action, "before": before, "after": after})
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, saved)


def accept_extraction(review, body):
    """Accept corrected pieces without merging totals or changing the source document."""
    evidence = require_current(review, body["revision"])
    path, saved, units, receipts, banks = evidence
    unit = units[body["key"]]
    pieces = validate_acceptance(unit, body["receipts"], saved)
    previous = saved["extractions"].get(body["key"])
    value = {"source_revision": unit["source_revision"], "receipts": pieces, "reviewer": body.get("reviewer")}
    saved["extractions"][body["key"]] = value
    record(path, saved, "accept_extraction", body.get("reviewer"), previous, value)
    unit.update(accepted=True, receipts=pieces)
    return snapshot_units(evidence)


def validate_acceptance(unit, pieces, saved):
    """Apply the same source, boundary and field checks to individual and bulk acceptance."""
    verify_source(unit)
    if unit.get("trash"):
        raise ValueError("Restore this document from trash before accepting its extraction")
    if unit.get("regeneration") and unit["regeneration"]["status"] != "completed":
        raise ValueError("Finish regeneration before accepting this extraction")
    if unit.get("assembly_pending"):
        raise ValueError("Run documents to finish receipt assembly before accepting")
    if any(match["review_status"] == "accepted" and any(
            item["document_id"] == unit["document_id"] and (unit.get("assembled") or item["unit"] == unit["unit"])
            for item in match["supporting_items"]) for match in saved["matches"].values()):
        raise ValueError("Undo accepted matches for this unit before changing its receipts")
    validate(pieces, {"type": "array", "items": ASSEMBLED_RECEIPT if unit.get("assembled") else RECEIPT, "maxItems": 100})
    if unit.get("assembled"):
        validate_assembly({"receipts": pieces, "reviewed_units": [s["number"] for s in unit["source_units"]],
                           "limitations": []}, len(unit["source_units"]))
        if any(piece["needs_review"] for piece in pieces):
            raise ValueError("Resolve flagged receipt boundaries before accepting")
    for piece in pieces:
        if piece["total"]:
            amount(piece["total"])
    pieces = [{**piece, "currency": currency(piece["currency"]) if piece["currency"].strip() else ""} for piece in pieces]
    return assign_submitted(pieces, unit['receipts'])


def accept_all_extractions(review, body):
    """Accept eligible results in one write, retaining current edits and reporting skipped units."""
    evidence = require_current(review, body['revision'])
    path, saved, units, _, _ = evidence
    draft = body.get('draft')
    prepared, skipped = {}, []
    if draft:
        unit = units[draft['key']]
        prepared[unit['key']] = validate_acceptance(unit, draft['receipts'], saved)
    for key, unit in units.items():
        if key in prepared or unit['accepted'] or unit.get('trash'):
            continue
        try:
            if unit.get('review_warnings'):
                raise ValueError('Review the extraction warning individually before accepting')
            if not unit['readable'] or unit['needs_refresh']:
                raise ValueError('Extraction requires review or regeneration')
            if any(piece.get('needs_review') for piece in unit['receipts']):
                raise ValueError('Resolve flagged receipt boundaries before accepting')
            prepared[key] = validate_acceptance(unit, unit['receipts'], saved)
        except (ValueError, ValidationError, OSError) as error:
            skipped.append({'key': key, 'reason': str(error)})
    for key, pieces in prepared.items():
        unit = units[key]
        value = {'source_revision': unit['source_revision'], 'receipts': pieces, 'reviewer': None}
        saved['history'].append({'at': datetime.now(timezone.utc).isoformat(), 'reviewer': None,
            'action': 'accept_extraction', 'bulk': True, 'key': key,
            'before': saved['extractions'].get(key), 'after': value})
        saved['extractions'][key] = value
        unit.update(accepted=True, receipts=pieces)
    if prepared:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, saved)
    return {**snapshot_units(evidence), 'bulk': {'accepted': len(prepared), 'skipped': skipped}}


def snapshot_units(evidence):
    """Rebuild receipt records after a decision without rereading source files."""
    path, saved, units, receipts, banks = evidence
    updated = {}
    for item in units.values():
        if item.get("trash"):
            continue
        evidence_revision = revision([item["source_revision"], item["receipts"]])
        for position, piece in enumerate(item["receipts"]):
            key = f'{item["document_id"]}:u{item["unit"]}:r{position}'
            updated[key] = {**piece, "receipt_id": key, "document_id": item["document_id"],
                            "unit": item["unit"], "source_path": item["source_path"],
                            "accepted": item["accepted"],
                            "evidence_revision": evidence_revision}
    return snapshot_context((path, saved, units, updated, banks))


def classify_extraction(review, body):
    """Audit reversible trash classifications without moving or deleting originals."""
    action = body.get("action")
    if action not in {"trash", "restore"}:
        raise ValueError("Choose trash or restore")
    evidence = require_current(review, body["revision"])
    path, saved, units, receipts, banks = evidence
    unit = units[body["key"]]
    verify_source(unit)
    digest = unit["document_id"]
    if (unit.get("regeneration") or {}).get("status") in {"queued", "running"}:
        raise ValueError("Wait for regeneration to finish before classifying this document")
    if action == "trash":
        if any(match["review_status"] == "accepted" and any(
                item["document_id"] == digest for item in match["supporting_items"])
                for match in saved["matches"].values()):
            raise ValueError("Undo accepted matches for this document before discarding it")
        if (review.manifest_path.parent / "final-review/decisions.json").exists():
            from dashboard import matching_review
            _, ledger, _, items, _, _ = matching_review.context(review)
            if any(decision["status"] == "approved" and any(
                    items[allocation["item_id"]]["document"] == digest
                    for allocation in decision["allocations"])
                    for decision in ledger["decisions"].values()):
                raise ValueError("Undo approved Final review matches before discarding this document")
    discarded = saved.setdefault("trash", {})
    previous = discarded.get(digest)
    value = {"document_id": digest, "source_path": unit["source_path"], "classification": "trash"}
    if action == "trash":
        discarded[digest] = value
    else:
        discarded.pop(digest, None)
        value = None
    record(path, saved, f"{action}_extraction", None, previous, value)
    for item in units.values():
        if item["document_id"] != digest:
            continue
        item["trash"] = action == "trash"
        accepted = saved["extractions"].get(item["key"])
        item["accepted"] = bool(accepted and accepted["source_revision"] == item["source_revision"]) and not item["trash"]
    return snapshot_units(evidence)


def change_match(review, body):
    """Propose, accept, reject, or undo an allocation with immutable decision history."""
    final_state = review.manifest_path.parent / "final-review/decisions.json"
    if final_state.exists() and body.get("action") in {"propose", "accept"}:
        raise ValueError("Use Final review for matching; its saved decisions reserve the available evidence")
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
