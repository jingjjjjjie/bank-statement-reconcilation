"""Observed maybank statement layout and source controls."""

from datetime import datetime

from statement_extraction.statement import amount

from .common import MONEY, one


def counterparty(narration, money_in):
    """Read named transfer fields; payment references are not party names."""
    lines = narration.splitlines()
    if len(lines) > 1 and lines[0].startswith(('TRANSFER TO A/C', 'TRANSFER FR A/C', 'ELECTRONIC REMITTANCE')):
        return lines[1].rstrip('* ').strip()
    if len(lines) > 2 and lines[0] == 'PAYMENT FR A/C':
        return lines[2]
    return ''


def specification(cover, whole, texts):
    """Require the issuer-specific account, dates, totals, and column layout."""
    one(r'\b(CCA SME FIRST ACCOUNT)\b', cover, 'supported account type')
    account_pattern = r'戶號\s*:\s*(\d+)'
    period = datetime.strptime(one(r'結單日期\s*:\s*(\d{2}/\d{2}/\d{2})', cover, 'statement date'), '%d/%m/%y')
    opening = amount(one(r'BEGINNING BALANCE\s+' + MONEY, whole, 'opening balance'))
    closing = amount(one(r'ENDING BALANCE\s*:\s*' + MONEY, whole, 'closing balance'))
    debit = amount(one(r'TOTAL DEBIT\s*:\s*' + MONEY, whole, 'total debits'))
    credit = amount(one(r'TOTAL CREDIT\s*:\s*' + MONEY, whole, 'total credits'))
    counts = None
    header = 'ENTRY DATE VALUE DATE TRANSACTION DESCRIPTION TRANSACTION AMOUNT STATEMENT BALANCE'
    width, columns, date_format, page_pattern = 510, (125, 325, 408), '%d/%m', r'/PAGE\s*:\s*(\d+)'
    return dict(
        signed=True,
        monthly_dates=True,
        entry_date_right=75,
        opening_prefix='BEGINNING BALANCE',
        end_prefix='ENDING BALANCE :',
        page_end=('BAKI LEGAR',),
        skip_prefixes=('TOTAL DEBIT', 'TOTAL CREDIT', 'LEDGER BALANCE'),
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
