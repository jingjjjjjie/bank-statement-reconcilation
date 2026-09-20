"""Deterministic receipt allocations; matching totals never imply approval."""
import hashlib
import json
import re
from decimal import Decimal
from reconciliation.currencies import normalize_currency


def revision(value):
    """Bind saved decisions to the exact evidence and ledger version."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def amount(value):
    """Parse an explicit nonnegative decimal amount without rounding or guessing."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
        raise ValueError("Enter an amount with at most two decimal places")
    return Decimal(value)


def currency(value):
    """Require an explicit three-letter currency for monetary allocation."""
    value = normalize_currency(value)
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("Enter an explicit three-letter currency, such as MYR")
    return value


def allocated(matches):
    """Reserve accepted allocations, including stale matches until explicitly undone."""
    totals = {}
    for match in matches.values():
        if match["review_status"] == "accepted":
            for item in match["supporting_items"]:
                key = item["receipt_id"]
                totals[key] = totals.get(key, Decimal(0)) + amount(item["allocated_amount"])
    return totals


def proposal(bank, selected, receipts, matches):
    """Calculate a pending grouped or split allocation and reject double counting."""
    if not isinstance(selected, list) or not selected:
        raise ValueError("Select at least one receipt")
    bank_currency = currency(bank["currency"])
    bank_amount = amount(bank["amount"])
    used, seen, items = allocated(matches), set(), []
    for item in selected:
        receipt_id = item["receipt_id"]
        if receipt_id in seen:
            raise ValueError("A receipt can occur only once in a match")
        seen.add(receipt_id)
        receipt = receipts[receipt_id]
        if not receipt["accepted"]:
            raise ValueError("Review and accept the receipt extraction first")
        if currency(receipt["currency"]) != bank_currency:
            raise ValueError("Receipt and bank currencies differ; conversion is not inferred")
        value = amount(item["allocated_amount"])
        if value <= 0:
            raise ValueError("Allocations must be greater than zero")
        remaining = amount(receipt["total"]) - used.get(receipt_id, Decimal(0))
        if value > remaining:
            raise ValueError(f"Allocation exceeds the remaining amount for {receipt_id}")
        items.append({"receipt_id": receipt_id, "allocated_amount": str(value),
                      "evidence_revision": receipt["evidence_revision"],
                      "document_id": receipt["document_id"], "unit": receipt["unit"],
                      "location": receipt["location"], "source_path": receipt["source_path"],
                      "brief_description": receipt["brief_description"]})
    total = sum((amount(item["allocated_amount"]) for item in items), Decimal(0))
    return {"bank_transaction_id": bank["transaction_id"], "bank_revision": bank["evidence_revision"],
            "bank_amount": str(bank_amount), "currency": bank_currency, "supporting_items": items,
            "supporting_total": str(total), "difference": str(bank_amount - total), "review_status": "pending"}


def stale(match, banks, receipts):
    """Invalidate proposed or accepted links when their supporting evidence changes."""
    bank = banks.get(match["bank_transaction_id"])
    return (not bank or bank["evidence_revision"] != match["bank_revision"] or
            any(item["receipt_id"] not in receipts or
                receipts[item["receipt_id"]]["evidence_revision"] != item["evidence_revision"]
                for item in match["supporting_items"]))
