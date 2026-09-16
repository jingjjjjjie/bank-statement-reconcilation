"""Conservative local triggers for document comparison."""

import re
import unicodedata


WEIGHTS = {"invoice": 4, "company": 2, "date": 1, "amount": 2, "description": 1}


def normalize(value):
    """Ignore common punctuation and case differences in extracted fields."""
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    return "".join(char for char in value if char.isalnum())


def values(units, primary, fallback=None):
    """Collect unique nonempty values from every page or sheet."""
    entries = [item for unit in units for item in unit.get(primary, [])]
    if not entries and fallback:
        entries = [item for unit in units for item in unit.get(fallback, [])]
    return {normalize(item) for item in entries if normalize(item)}


def description(units):
    """Collect meaningful words from short descriptions."""
    return {normalize(word) for unit in units for word in
            re.findall(r"\w+", unit.get("brief_description", "")) if len(normalize(word)) > 2}


def score(left, right):
    """Return a candidate score only when two independent fields match."""
    fields = {
        "invoice": (values(left, "invoice_numbers", "references"),
                    values(right, "invoice_numbers", "references")),
        "company": (values(left, "company", "parties"), values(right, "company", "parties")),
        "date": (values(left, "dates"), values(right, "dates")),
        "amount": (values(left, "amounts_and_currencies"), values(right, "amounts_and_currencies")),
        "description": (description(left), description(right)),
    }
    available = {name: pair for name, pair in fields.items() if all(pair)}
    matched = [name for name, (a, b) in available.items() if a & b]
    if len(matched) < 2:
        return 0, matched
    total = sum(WEIGHTS[name] for name in available)
    return round(100 * sum(WEIGHTS[name] for name in matched) / total), matched
