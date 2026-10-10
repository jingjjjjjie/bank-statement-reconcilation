"""Receipt review: load extracted pieces per document and save human accept / edit / discard decisions."""

import csv
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import ValidationError, validate

from dashboard.services.extraction.extraction_runs import execution_status, work_path
from dashboard.services.review import write_json
from reconciliation.core.money import amount, currency, normalize_currencies
from reconciliation.core.revision import revision
from reconciliation.extraction.pipeline.assembly import ASSEMBLED_RECEIPT, current_assembly, validate_assembly
from reconciliation.extraction.results.pieces import assign_submitted, canonical, identify
from reconciliation.extraction.results.schemas import RECEIPT
from reconciliation.extraction.sources.pdf_routing import review_warnings
from reconciliation.extraction.workflow import load_index, removal_plan
from reconciliation.intake.duplicates import fingerprint

#: Threads hashing source files in parallel when loading the review (I/O bound).
HASH_WORKERS = 8


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
    saved = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"extractions": {}, "matches": {}, "history": []}
    )
    units, receipts, banks = {}, {}, {}
    if (work / "index.json").exists():
        from dashboard.services.extraction import regeneration

        jobs = regeneration.snapshot(review)
        index, state = prepared if prepared is not None else load_index(work)
        if Path(index["manifest"]).resolve() != review.manifest_path.resolve():
            raise ValueError("Prepared review belongs to another manifest")
        removed = removal_plan(state)
        originals = {
            document["paths"][0]
            for digest, document in index["documents"].items()
            if digest not in removed and document.get("accepted", True) and not document["error"]
        }
        previews = (
            {
                unit["image"]: unit["image_sha256"]
                for document in index["documents"].values()
                for unit in document["units"]
                if unit["image"]
            }
            if prepared is None
            else {}
        )
        paths = sorted(originals | previews.keys())
        # Hash fresh bytes in parallel; never infer integrity from timestamps or cached hashes.
        with ThreadPoolExecutor(max_workers=HASH_WORKERS) as pool:
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
            review_units = (
                [(-1, {"label": "Whole document", "blocked": False})] if assembled else enumerate(document["units"])
            )
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
                accepted = (
                    accepted if accepted and accepted["source_revision"] == binding and source_hash == digest else None
                )
                if accepted and not accepted["receipts"] and accepted.get("supporting_only") is not True:
                    accepted = None
                pieces = identify(
                    accepted["receipts"] if accepted else raw.get("receipts", []), digest, number, binding
                )
                evidence = revision([binding, pieces])
                units[key] = {
                    "key": key,
                    "document_id": digest,
                    "unit": number,
                    "label": unit["label"],
                    "source_path": document["paths"][0],
                    "source_revision": binding,
                    "accepted": bool(accepted) and accepted.get("accepted", True) and not trash,
                    "supporting_only": bool(accepted and accepted.get("supporting_only")),
                    "trash": trash,
                    "needs_refresh": "receipts" not in raw,
                    "receipts": pieces,
                    "readable": raw.get("readable", assembled),
                    "description": raw.get("description", raw.get("summary", raw.get("brief_description", ""))),
                    "assembled": assembled,
                    "assembly_pending": assembled and assembly is None,
                    "review_warnings": (
                        ["No entries extracted. Add an entry or accept as supporting evidence."]
                        if not pieces and not accepted and not trash
                        else []
                    )
                    + list(
                        dict.fromkeys(
                            warning
                            for n in range(len(document["units"]))
                            for warning in review_warnings(state["units"].get(f"{digest}:{n}", {}))
                        )
                    ),
                    "regeneration": job,
                    "supporting_evidence": [
                        {
                            "label": source["label"],
                            "status": state["units"]
                            .get(f"{digest}:{n}", {})
                            .get("supporting_evidence_status", "uncertain"),
                            "reason": state["units"].get(f"{digest}:{n}", {}).get("supporting_evidence_reason", ""),
                        }
                        for n, source in enumerate(document["units"])
                    ],
                    "source_units": [
                        {"number": n + 1, "label": source["label"]} for n, source in enumerate(document["units"])
                    ],
                }
                for position, piece in enumerate([] if trash else pieces):
                    receipt_id = f"{digest}:u{number}:r{position}"
                    receipts[receipt_id] = {
                        **piece,
                        "receipt_id": receipt_id,
                        "document_id": digest,
                        "unit": number,
                        "source_path": document["paths"][0],
                        "accepted": bool(accepted) and accepted.get("accepted", True),
                        "evidence_revision": evidence,
                    }
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
                bank = {
                    **row,
                    "amount": value,
                    "evidence_revision": revision([master_revision, row, source_hashes[source]]),
                }
                if bank["transaction_id"] in banks:
                    raise ValueError("Bank transaction IDs must be unique")
                banks[bank["transaction_id"]] = bank
    return path, saved, units, receipts, banks


def snapshot(review):
    """Return every reviewable document unit and its pieces, plus the revision the browser must echo back."""
    if review is None:
        return {"revision": "", "units": [], "receipts": [], "transactions": []}
    return snapshot_context(context(review))


def snapshot_context(evidence):
    """Serialize one verified evidence set without rereading every source file."""
    path, saved, units, receipts, banks = evidence
    return normalize_currencies(
        {
            "revision": revision([saved, units, banks]),
            "units": list(units.values()),
            "receipts": list(receipts.values()),
            "transactions": list(banks.values()),
        }
    )


def ground_truth(review):
    """Export saved human review decisions per document as a benchmark answer key."""
    _, _, units, _, _ = context(review, include_banks=False)
    index, _ = load_index(work_path(review))
    root = index.get("root", "")
    documents = []
    for unit in units.values():
        status = "discarded" if unit["trash"] else "accepted" if unit["accepted"] else "pending"
        paths = [
            p[len(root) :].lstrip("/\\") if root and p.startswith(root) else p
            for p in index["documents"][unit["document_id"]]["paths"]
        ]
        pieces = (
            [
                {
                    "piece_id": piece["piece_id"],
                    **{k: v for k, v in canonical(piece).items() if k != "limitations"},
                    **({"source_units": piece["source_units"]} if "source_units" in piece else {}),
                }
                for piece in unit["receipts"]
            ]
            if status == "accepted"
            else []
        )
        documents.append({"document_id": unit["document_id"], "paths": paths, "status": status, "pieces": pieces})
    documents.sort(key=lambda document: document["paths"][0])
    counts = {status: sum(d["status"] == status for d in documents) for status in ("accepted", "discarded", "pending")}
    return normalize_currencies(
        {"exported_at": datetime.now(timezone.utc).isoformat(), "root": root, "counts": counts, "documents": documents}
    )


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
    if not (
        action in {"accept_extraction", "undo_accept_extraction", "trash_extraction", "restore_extraction"}
        and reviewer is None
    ) and (not isinstance(reviewer, str) or not reviewer.strip()):
        raise ValueError("Enter your name")
    saved["history"].append(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "reviewer": reviewer.strip() if reviewer else None,
            "action": action,
            "before": before,
            "after": after,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, saved)


def original_extraction(review, body):
    """Return an unsaved reset draft from model output, never from accepted edits."""
    _, _, units, _, _ = require_current(review, body['revision'])
    unit = units[body['key']]
    verify_source(unit)
    if (
        unit['trash']
        or unit['assembly_pending']
        or (unit.get('regeneration') or {}).get('status') in {'queued', 'running'}
    ):
        raise ValueError('Restore the document and finish extraction before resetting')
    index, state = load_index(work_path(review))
    document = index['documents'][unit['document_id']]
    raw = current_assembly(document, state) if unit['assembled'] else state['units'].get(unit['key'])
    if not raw or 'receipts' not in raw:
        raise ValueError('No original extraction is available')
    binding = [state['index_sha256'], raw, unit['document_id']]
    if unit.get('regeneration'):
        binding.append(unit['regeneration']['id'])
    if revision(binding) != unit['source_revision']:
        raise ValueError('Extraction changed; reload before resetting')
    parents = [piece['piece_id'] for piece in unit['receipts']]
    originals = deepcopy(raw['receipts'])
    for piece in originals:
        piece.pop('piece_id', None)
        piece['parent_piece_ids'] = parents
    return {'receipts': normalize_currencies(originals)}


def accept_extraction(review, body):
    """Accept corrected pieces without merging totals or changing the source document."""
    evidence = require_current(review, body["revision"])
    path, saved, units, receipts, banks = evidence
    unit = units[body["key"]]
    # Individual Accept may replace Discard; validate everything before changing state.
    pieces = validate_acceptance(
        {**unit, "trash": False}, body["receipts"], saved, supporting_only=body.get("supporting_only", False)
    )
    if unit.get("trash"):
        discarded = saved["trash"].pop(unit["document_id"])
        saved["history"].append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "reviewer": body.get("reviewer"),
                "action": "restore_extraction",
                "before": discarded,
                "after": None,
            }
        )
    previous = saved["extractions"].get(body["key"])
    value = {"source_revision": unit["source_revision"], "receipts": pieces, "reviewer": body.get("reviewer")}
    value["supporting_only"] = not pieces and body.get("supporting_only") is True
    saved["extractions"][body["key"]] = value
    record(path, saved, "accept_extraction", body.get("reviewer"), previous, value)
    unit.update(accepted=True, trash=False, receipts=pieces, supporting_only=value["supporting_only"])
    return snapshot_units(evidence)


def undo_accept_extraction(review, body):
    """Reopen reviewed pieces without losing corrections, identities or audit history."""
    evidence = require_current(review, body["revision"])
    path, saved, units, _, _ = evidence
    unit = units[body["key"]]
    verify_source(unit)
    if not unit["accepted"]:
        raise ValueError("This extraction is not accepted")
    if (unit.get("regeneration") or {}).get("status") in {"queued", "running"}:
        raise ValueError("Wait for regeneration to finish before undoing acceptance")
    require_unallocated_document(review, saved, unit["document_id"])
    previous = saved["extractions"][unit["key"]]
    value = {**previous, "accepted": False}
    saved["extractions"][unit["key"]] = value
    record(path, saved, "undo_accept_extraction", None, previous, value)
    unit["accepted"] = False
    return snapshot_units(evidence)


def require_unallocated_document(review, saved, digest):
    """Keep approved matching evidence intact until its allocations are undone."""
    if any(
        match["review_status"] == "accepted"
        and any(item["document_id"] == digest for item in match["supporting_items"])
        for match in saved["matches"].values()
    ):
        raise ValueError("Undo accepted matches for this document first")
    if (review.manifest_path.parent / "final-review/decisions.json").exists():
        from dashboard.services.matching import final_review

        _, ledger, _, items, _, _ = final_review.context(review)
        if any(
            decision["status"] == "approved"
            and any(items[allocation["item_id"]]["document"] == digest for allocation in decision["allocations"])
            for decision in ledger["decisions"].values()
        ):
            raise ValueError("Undo approved Final review matches for this document first")


def validate_acceptance(unit, pieces, saved, *, supporting_only=False):
    """Apply the same source, boundary and field checks to individual and bulk acceptance."""
    verify_source(unit)
    if not pieces and supporting_only is not True:
        raise ValueError("No entries extracted. Add an entry or accept as supporting evidence.")
    if pieces and supporting_only is True:
        raise ValueError("Supporting evidence only cannot contain monetary entries")
    if unit.get("trash"):
        raise ValueError("Restore this document from trash before accepting its extraction")
    if unit.get("regeneration") and unit["regeneration"]["status"] != "completed":
        raise ValueError("Finish regeneration before accepting this extraction")
    if unit.get("assembly_pending"):
        raise ValueError("Run documents to finish receipt assembly before accepting")
    if any(
        match["review_status"] == "accepted"
        and any(
            item["document_id"] == unit["document_id"] and (unit.get("assembled") or item["unit"] == unit["unit"])
            for item in match["supporting_items"]
        )
        for match in saved["matches"].values()
    ):
        raise ValueError("Undo accepted matches for this unit before changing its receipts")
    validate(
        pieces, {"type": "array", "items": ASSEMBLED_RECEIPT if unit.get("assembled") else RECEIPT, "maxItems": 100}
    )
    if unit.get("assembled"):
        validate_assembly(
            {"receipts": pieces, "reviewed_units": [s["number"] for s in unit["source_units"]], "limitations": []},
            len(unit["source_units"]),
        )
    for piece in pieces:
        if piece["total"]:
            amount(piece["total"])
    pieces = [
        {**piece, "currency": currency(piece["currency"]) if piece["currency"].strip() else ""} for piece in pieces
    ]
    return assign_submitted(pieces, unit['receipts'])


def accept_all_extractions(review, body):
    """Accept eligible results in one write, retaining current edits and reporting skipped units."""
    evidence = require_current(review, body['revision'])
    path, saved, units, _, _ = evidence
    draft = body.get('draft')
    prepared, skipped = {}, []
    if draft:
        unit = units[draft['key']]
        prepared[unit['key']] = validate_acceptance(
            unit, draft['receipts'], saved, supporting_only=not draft['receipts']
        )
    for key, unit in units.items():
        if key in prepared or unit['accepted'] or unit.get('trash'):
            continue
        try:
            if not unit['readable'] or unit['needs_refresh']:
                raise ValueError('Extraction requires review or regeneration')
            prepared[key] = validate_acceptance(
                unit, unit['receipts'], saved, supporting_only=not unit['receipts']
            )
        except (ValueError, ValidationError, OSError) as error:
            skipped.append({'key': key, 'reason': str(error)})
    for key, pieces in prepared.items():
        unit = units[key]
        value = {
            'source_revision': unit['source_revision'], 'receipts': pieces,
            'reviewer': None, 'supporting_only': not pieces,
        }
        saved['history'].append(
            {
                'at': datetime.now(timezone.utc).isoformat(),
                'reviewer': None,
                'action': 'accept_extraction',
                'bulk': True,
                'key': key,
                'before': saved['extractions'].get(key),
                'after': value,
            }
        )
        saved['extractions'][key] = value
        unit.update(accepted=True, receipts=pieces, supporting_only=not pieces)
        unit['review_warnings'] = [
            warning for warning in unit['review_warnings']
            if warning != 'No entries extracted. Add an entry or accept as supporting evidence.'
        ]
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
            updated[key] = {
                **piece,
                "receipt_id": key,
                "document_id": item["document_id"],
                "unit": item["unit"],
                "source_path": item["source_path"],
                "accepted": item["accepted"],
                "evidence_revision": evidence_revision,
            }
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
        require_unallocated_document(review, saved, digest)
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
        item["accepted"] = (
            bool(accepted and accepted.get("accepted", True) and accepted["source_revision"] == item["source_revision"])
            and not item["trash"]
        )
    return snapshot_units(evidence)
