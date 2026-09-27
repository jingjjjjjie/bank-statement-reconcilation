"""Money parsing: currency spelling and strict amounts; never converts or guesses values."""

import re
from decimal import Decimal


def normalize_currency(value):
    """Use MYR for RM; preserve other codes while normalizing case and whitespace."""
    if not isinstance(value, str):
        return value
    code = value.strip().upper()
    return 'MYR' if code == 'RM' else code


def normalize_currencies(value):
    """Copy structured output with currency fields normalized and all other facts unchanged."""
    if isinstance(value, dict):
        return {
            key: normalize_currency(item) if key == 'currency' else normalize_currencies(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_currencies(item) for item in value]
    return value


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
