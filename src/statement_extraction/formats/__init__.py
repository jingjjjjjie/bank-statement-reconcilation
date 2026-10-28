"""Strict readers for the observed Malaysian digital statement layouts."""

import re

BANKS = {
    'ambank': 'AmBank',
    'public_bank': 'Public Bank',
    'maybank': 'Maybank',
    'hong_leong': 'Hong Leong Bank',
    'cimb': 'CIMB',
    'uob': 'UOB',
}


SIGNATURES = {
    'ambank': r'\bAMBANK\b',
    'public_bank': r'\bPUBLIC BANK\b',
    'maybank': r'\bMALAYAN BANKING BERHAD\b',
    'hong_leong': r'\bHONG LEONG BANK BERHAD\b',
    'cimb': r'\bCIMB BANK BERHAD\b',
    'uob': r'\bUOBM\b|\bUOBM? JLN\b',
}


def issuers(cover):
    """List banks whose issuer wording appears on page 1; never use filenames."""
    text = cover.upper()
    return [bank for bank, pattern in SIGNATURES.items() if re.search(pattern, text)]


def names(banks):
    """Join bank display names for messages."""
    return ' and '.join(BANKS[bank] for bank in banks)


def check_selection(cover, selected):
    """Return the candidate readers to try; layout validation picks the real issuer."""
    if selected != 'auto' and selected not in BANKS:
        raise ValueError('Choose a supported bank: ' + ', '.join(BANKS.values()))
    if not cover.strip():
        raise ValueError('Page 1 has no readable text. Scanned statements are not supported; use the digital PDF from online banking.')
    found = issuers(cover)
    if not found:
        raise ValueError('No supported bank name found on page 1. Use a complete supported digital bank statement.')
    if selected == 'auto':
        return found
    if selected not in found:
        if len(found) == 1:
            named = names(found)
            raise ValueError(f'Selected {BANKS[selected]}, but this PDF is a {named} statement. Select {named}.')
        raise ValueError(f'Selected {BANKS[selected]}, but this PDF names {names(found)}. Select one of those banks.')
    return [selected]


def layout(bank):
    """Load one bank module without coupling its rules to other readers."""
    from importlib import import_module

    if bank not in BANKS:
        raise ValueError('Unsupported bank')
    return import_module(f'{__name__}.{bank}')
