"""Observed cimb statement layout and source controls."""

from datetime import datetime

from reconciliation.bank.statement import amount

from .common import MONEY, one


def counterparty(narration, money_in):
    """Read known beneficiary/payer slots; leave fees and batch debits unidentified."""
    lines = narration.splitlines()
    if len(lines) > 1 and lines[0].startswith(('TR IBG ', 'TR TO C/A ')):
        return lines[1]
    # CIMB's name field holds 20 characters; a longer line also carries the payment purpose.
    if len(lines) > 1 and lines[0].startswith('TR TO SAVINGS ') and len(lines[1]) <= 20:
        return lines[1]
    if len(lines) >= 4 and money_in and lines[0].startswith(('DUITNOW TO ACCOUNT ', 'IBG CREDIT ')):
        return lines[-1]
    return ''


def specification(cover, whole, texts):
    """Require the issuer-specific account, dates, totals, and column layout."""
    one(r'^(\(RM\) \(RM\) \(RM\))$', cover, 'MYR columns')
    account_pattern = r'Account No / No Akaun\s+(\d{2}-\d{7}-\d)'
    period = datetime.strptime(
        one(r'Statement Date / Tarikh Penyata\s+(\d{2}/\d{2}/\d{4})', cover, 'statement date'), '%d/%m/%Y'
    )
    opening = amount(one(r'Opening Balance\s+' + MONEY, whole, 'opening balance'))
    closing = amount(one(r'CLOSING BALANCE / BAKI PENUTUP\s+' + MONEY, whole, 'closing balance'))
    out_count, in_count, debit_text, credit_text = one(
        r'^(\d+)\s+(\d+)\s+' + MONEY + r'\s+' + MONEY + '$', texts[-1], 'statement totals'
    )
    debit, credit, counts = amount(debit_text), amount(credit_text), (int(out_count), int(in_count))
    header, width, columns = 'Date Description Cheque / Ref No Withdrawal Deposits Balance', 595, (98, 340, 410, 480)
    date_format, page_pattern = '%d/%m/%Y', r'Page (\d+) of (\d+)'
    return dict(
        reverse=True,
        account_each_page=False,
        opening_prefix='Opening Balance',
        end_prefix='CLOSING BALANCE /',
        page_end=('CONTINUE NEXT PAGE', 'You can perform'),
        skip_prefixes=('Tarikh Diskripsi', '(RM)'),
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
