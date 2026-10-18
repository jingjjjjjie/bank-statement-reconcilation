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


def detect_bank(cover):
    """Use issuer wording, never filenames or transaction bank abbreviations."""
    text = cover.upper()
    signatures = {
        'ambank': r'\bAMBANK\b',
        'public_bank': r'\bPUBLIC BANK\b',
        'maybank': r'\bMALAYAN BANKING BERHAD\b',
        'hong_leong': r'\bHONG LEONG BANK BERHAD\b',
        'cimb': r'\bCIMB BANK BERHAD\b',
        'uob': r'\bUOBM\b|\bUOBM? JLN\b',
    }
    found = [bank for bank, pattern in signatures.items() if re.search(pattern, text)]
    if len(found) != 1:
        raise ValueError('Cannot identify one statement issuer. Use a complete supported digital bank statement.')
    return found[0]


def check_selection(cover, selected):
    """Reject wrong-bank selection and unsupported issuers before extraction."""
    if selected != 'auto' and selected not in BANKS:
        raise ValueError('Choose a supported bank: ' + ', '.join(BANKS.values()))
    detected = detect_bank(cover)
    if selected != 'auto' and detected != selected:
        raise ValueError(
            f'Selected {BANKS[selected]}, but this PDF is a {BANKS[detected]} statement. Select {BANKS[detected]}.'
        )

    return detected


def layout(bank):
    """Load one bank module without coupling its rules to other readers."""
    from importlib import import_module

    if bank not in BANKS:
        raise ValueError('Unsupported bank')
    return import_module(f'{__name__}.{bank}')
