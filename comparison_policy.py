"""Choose direct comparison or model screening from extracted evidence."""

import re
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation


def normalize(value):
    """Ignore case and punctuation in identifiers and names."""
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    return "".join(char for char in value if char.isalnum())


def values(units, field):
    """Collect nonempty values across all document units."""
    entries = [item for unit in units for item in unit.get(field, [])]
    return {normalize(item) for item in entries if normalize(item)}


def descriptions(units):
    """Collect useful short-description words."""
    return {normalize(word) for unit in units for word in
            re.findall(r"\w+", unit.get("brief_description", "")) if len(normalize(word)) > 2}


def money_value(item):
    """Parse an explicit amount and currency without guessing missing values."""
    currency = item.get("currency", "").strip().upper()
    currency = "MYR" if currency == "RM" else currency
    raw = item.get("amount", "").strip()
    if not re.fullmatch(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", raw):
        return None
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    try:
        return currency, Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def combined_total(units):
    """Use grand total, invoice totals, or line items once per currency."""
    groups = defaultdict(lambda: defaultdict(list))
    for unit in units:
        for item in unit.get("money", []):
            parsed = money_value(item)
            if parsed is None:
                return None
            currency, amount = parsed
            groups[currency][item["role"]].append(amount)
    if not groups:
        return None
    totals = {}
    for currency, roles in groups.items():
        grand = roles["grand_total"]
        invoices = roles["invoice_total"]
        lines = roles["line_item"]
        if len(grand) > 1 or not (grand or invoices or lines):
            return None
        if grand and invoices and grand[0] != sum(invoices):
            return None
        totals[currency] = grand[0] if grand else sum(invoices or lines)
    return totals


def route(left, right):
    """Fast-track clear combined-total matches; screen everything else."""
    left_total, right_total = combined_total(left), combined_total(right)
    if left_total is None or left_total != right_total:
        return "model_screen", "Combined total missing, unclear, or different"
    invoices = values(left, "invoice_numbers") & values(right, "invoice_numbers")
    if invoices:
        return "direct_compare", "Combined total and invoice number match"
    companies = values(left, "company") & values(right, "company")
    a, b = descriptions(left), descriptions(right)
    particulars_match = a and b and len(a & b) >= 2 and len(a & b) / len(a | b) >= 0.5
    if companies and particulars_match:
        date_match = bool(values(left, "dates") & values(right, "dates"))
        reason = "Combined total, company, and particulars match"
        return "direct_compare", reason + ("; date also matches" if date_match else "")
    return "model_screen", "Combined total matches without invoice or matching company and particulars"
