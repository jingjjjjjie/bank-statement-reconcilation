"""Observed public bank statement layout and source controls."""

import re
from datetime import datetime

import pdfplumber

from reconciliation.bank.statement import amount

from .common import MONEY, one


COMPANY = re.compile(r'^(.*?\b(?:SDN\.? BHD\.?|BHD\.?|S/B|PLT|BERHAD))(?:\s|$)')


def duitnow_party(lines):
    """Take the DuitNow name only where the first line or a company suffix marks its end."""
    inline = re.fullmatch(r'DUITNOW TRSF (?:CR|DR) \d+ (\D+)', lines[0])
    if inline:
        return inline[1]
    # Otherwise the name and purpose share a line; only a company suffix splits them safely.
    company = COMPANY.match(lines[1]) if len(lines) > 2 else None
    return company[1] if company else ''


def counterparty(narration, money_in):
    """Read party fields whose end is marked by the bank's own layout, never guessed from prose."""
    lines = narration.splitlines()
    if len(lines) > 1 and lines[0].startswith('TSFR FUND '):
        match = re.fullmatch(r'\d+X+\s+(.+)', lines[1])
        if match:
            return match[1]
    if lines[0].startswith('DUITNOW TRSF '):
        return duitnow_party(lines)
    if len(lines) > 2 and lines[0].startswith('DEP-ECP '):
        # The sending bank code ends line 2 and follows the payer's name on line 3.
        code = lines[1].rsplit(' ', 1)[-1]
        name, found, _ = (lines[2] + ' ').partition(f' {code} ')
        return name if found else ''
    if len(lines) > 1 and lines[0].startswith('GIRO PYMT'):
        match = re.fullmatch(r'JOMPAY - \w+ - (.+)', lines[1])
        return match[1] if match else ''
    return ''


def transaction_cells(line, page):
    """Separate right-aligned PBB amounts from prose that crosses nominal columns."""
    values, boxes = {}, []
    for word in pdfplumber.utils.extract_words(line['chars']):
        for key, edge in [('out', 352.9), ('in', 428.9), ('balance', 525.7)]:
            if abs(word['x1'] - edge) < 1 and re.fullmatch(MONEY, word['text']):
                if key in values:
                    raise ValueError('Multiple amounts in a Public Bank transaction cell.')
                values[key] = word['text']
                boxes.append((word['x0'], word['x1']))
    chars = [c for c in line['chars'] if c['x0'] >= 90 and not any(a <= c['x0'] < b for a, b in boxes)]
    narration = pdfplumber.utils.extract_text(chars, x_tolerance=1).strip() if chars else ''
    date_chars = [c for c in line['chars'] if c['x0'] < 90]
    date = pdfplumber.utils.extract_text(date_chars).strip() if date_chars else ''
    return date, narration, values.get('in', ''), values.get('out', ''), values.get('balance', '')


def specification(cover, whole, texts):
    """Require the issuer-specific account, dates, totals, and column layout."""
    one(r'Account Type\s+(RM Plus Current Account)', cover, 'MYR account type')
    account_pattern = r'Account Number\s+(\d+)'
    period = datetime.strptime(one(r'Statement Date\s+(\d{2} \w{3} \d{4})', cover, 'statement date'), '%d %b %Y')
    opening = amount(one(r'Balance From Last Statement\s+' + MONEY, whole, 'opening balance'))
    closing = amount(one(r'Closing Balance In This Statement\s+' + MONEY, whole, 'closing balance'))
    debit = amount(one(r'Total Debits\s+' + MONEY, cover, 'total debits'))
    credit = amount(one(r'Total Credits\s+' + MONEY, cover, 'total credits'))
    counts = (
        int(one(r'No\. of Debits\s+(\d+)', cover, 'debit count')),
        int(one(r'No\. of Credits\s+(\d+)', cover, 'credit count')),
    )
    header, width, columns = 'DATE TRANSACTION DEBIT CREDIT BALANCE', 612, (90, 310, 375, 460)
    date_format, page_pattern = '%d/%m', r'Page (\d+) of (\d+)'
    return dict(
        carry_dates=True,
        monthly_dates=True,
        allow_zero=True,
        opening_prefix='Balance From Last Statement',
        end_prefix='Closing Balance In This Statement',
        page_end=('Penyata ini dicetak',),
        skip_prefixes=(),
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
