"""Normalize currency spelling without converting amounts or changing evidence in place."""


def normalize_currency(value):
    """Use MYR for RM; preserve other codes while normalizing case and whitespace."""
    if not isinstance(value, str):
        return value
    code = value.strip().upper()
    return 'MYR' if code == 'RM' else code


def normalize_currencies(value):
    """Copy structured output with currency fields normalized and all other facts unchanged."""
    if isinstance(value, dict):
        return {key: normalize_currency(item) if key == 'currency' else normalize_currencies(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_currencies(item) for item in value]
    return value
