"""Observed hong leong statement layout and source controls."""

import re
from datetime import datetime

from reconciliation.bank.statement import amount

from .common import MONEY, one


def counterparty(narration, money_in):
    """Read the printed party name for recognised transfer and bill rows."""
    lines = narration.splitlines()
    if len(lines) < 3:
        return ''
    first, last = lines[0], lines[-1]
    if first.startswith(('Instant Transfer', 'CIB Instant Transfer')) and re.fullmatch(r'\d{8}[A-Z]{8}\w+', last):
        party = lines[-2]
    elif first.startswith('JomPAY Bill Payment') and len(lines) == 5:
        party = lines[-2]
    elif first.startswith(('Fund Transfer', 'Fund Trf fr', 'Cr Adv-Interbank GIRO')):
        party = last
    elif first.startswith('ATM Interbank Funds Trf'):
        # The name is the one line that is not the repeated INSTANT TRANSFER label.
        others = [line for line in lines[1:] if line != 'INSTANT TRANSFER']
        party = others[0] if len(others) == 1 else ''
    else:
        return ''
    # A party name has letters and no digits; references stay unidentified.
    return party if re.search('[A-Za-z]', party) and not re.search(r'\d', party) else ''


def specification(cover, whole, texts):
    """Require the issuer-specific account, dates, totals, and column layout."""
    account_pattern = r'A/C No /No Akaun\s*:\s*(\d+) MYR'
    period = datetime.strptime(one(r'Date / Tarikh\s*:\s*(\d{2}-\d{2}-\d{4})', cover, 'statement date'), '%d-%m-%Y')
    start_text, end_text = one(
        r'Statement Period /\s*:\s*(\d{2}/\d{2}/\d{2}) - (\d{2}/\d{2}/\d{2})', cover, 'statement period'
    )
    start_date, end_date = (datetime.strptime(value, '%d/%m/%y').date() for value in (start_text, end_text))
    if end_date != period.date() or start_date > end_date:
        raise ValueError('Conflicting Hong Leong statement dates.')
    opening = amount(one(r'Balance from previous statement\s+' + MONEY, whole, 'opening balance'))
    closing = amount(one(r'Closing Balance / Baki Akhir:\s*' + MONEY, whole, 'closing balance'))
    out_count, debit_text = one(r'Total Withdrawals / Jumlah Pengeluaran\s*:\s*(\d+)\s+' + MONEY, whole, 'withdrawals')
    in_count, credit_text = one(r'Total Deposits / Jumlah Simpanan\s*:\s*(\d+)\s+' + MONEY, whole, 'deposits')
    debit, credit, counts = amount(debit_text), amount(credit_text), (int(out_count), int(in_count))
    header, width, columns = 'Date Transaction Description Deposit Withdrawal Balance', 595.44, (100, 325, 403, 483)
    date_format, page_pattern = '%d-%m-%Y', r'Page No / No Mukasurat\s*:\s*(\d+) of (\d+)'
    return dict(
        start_date=start_date,
        deposits_first=True,
        sparse_balances=True,
        ignore_rotated=True,
        opening_prefix='Balance from previous statement',
        end_prefix='Total Withdrawals /',
        page_end=('Hong Leong Bank Berhad',),
        skip_prefixes=('Tarikh Deskripsi',),
        account_pattern=account_pattern,
        period=period,
        opening=opening,
        closing=closing,
        debit=debit,
        credit=credit,
        counts=counts,
        header=header,
        width=width,
        columns=columns,
        date_format=date_format,
        page_pattern=page_pattern,
    )
