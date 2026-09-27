"""Small deterministic helpers: evidence revisions and strict amount / currency parsing."""
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
