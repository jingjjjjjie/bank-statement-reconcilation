"""Small synthetic digital statements with source columns and independent totals."""

import pymupdf

HEADERS = {
    'public_bank': 'DATE TRANSACTION DEBIT CREDIT BALANCE',
    'maybank': 'ENTRY DATE VALUE DATE TRANSACTION DESCRIPTION TRANSACTION AMOUNT STATEMENT BALANCE',
    'hong_leong': 'Date Transaction Description Deposit Withdrawal Balance',
    'cimb': 'Date Description Cheque / Ref No Withdrawal Deposits Balance',
}


def statement(
    path, bank, *, bad_balance=False, missing_row=False, missing_header=False, foreign=False, mention=None
):
    """Write fictional evidence that exercises actual PDF text and column extraction."""
    width = {'public_bank': 612, 'maybank': 510, 'hong_leong': 595.44, 'cimb': 595}[bank]
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=864)

    def put(x, y, text, right=False, chinese=False):
        """Place a six-point source label or a right-aligned amount."""
        if right:
            x -= pymupdf.get_text_length(text, fontsize=6)
        page.insert_text((x, y), text, fontsize=6, fontname='china-s' if chinese else 'helv')

    cover = {
        'public_bank': [
            'PUBLIC BANK',
            'Account Number 1234567890',
            'Statement Date 31 Jan 2025',
            'Account Type RM Plus Current Account',
            'Total Debits 5.00',
            'Total Credits 10.00',
            'No. of Debits 2',
            'No. of Credits 1',
            'Page 1 of 1',
        ],
        'maybank': ['Malayan Banking Berhad', 'MUKA/ /PAGE : 1', 'CCA SME FIRST ACCOUNT'],
        'hong_leong': [
            'Hong Leong Bank Berhad',
            'Page No / No Mukasurat : 1 of 1',
            'Date / Tarikh : 31-01-2025',
            'A/C No /No Akaun : 1234567890 MYR',
            'Statement Period / : 01/01/25 - 31/01/25',
        ],
        'cimb': [
            'CIMB BANK BERHAD',
            'Page 1 of 1',
            'Statement Date / Tarikh Penyata 31/01/2025',
            'Account No / No Akaun 80-1234567-8',
        ],
    }[bank]
    for i, text in enumerate(cover):
        put(20, 20 + i * 10, text.replace('MYR', 'USD') if foreign else text)
    if bank == 'maybank':
        put(20, 65, '\u6236\u865f : 1234567890', chinese=True)
        put(20, 80, '\u7d50\u55ae\u65e5\u671f : 31/01/25', chinese=True)
    put(20, 180, 'Unknown table layout' if missing_header else HEADERS[bank])
    if bank == 'cimb':
        put(340, 190, '(USD) (USD) (USD)' if foreign else '(RM) (RM) (RM)')
    starts = {'public_bank': 93, 'maybank': 126, 'hong_leong': 102, 'cimb': 99}
    start = starts[bank]
    opening_label = {
        'public_bank': 'Balance From Last Statement',
        'maybank': 'BEGINNING BALANCE',
        'hong_leong': 'Balance from previous statement',
        'cimb': 'Opening Balance',
    }[bank]
    put(start, 205, opening_label)
    put(525.7 if bank == 'public_bank' else width - 30, 205, '100.00', right=True)
    rows = [('01', 'INCOMING TRANSFER', '10.00', '', '110.00'), ('02', 'OUTGOING TRANSFER', '', '5.00', '105.00')]
    if bank == 'public_bank':
        rows.append(('02', 'GST DR', '', '0.00', '105.00'))
    if bank == 'cimb':
        rows.reverse()
    for i, (day, narration, incoming, outgoing, balance) in enumerate(rows):
        if missing_row and i == 0:
            continue
        y = 230 + i * 35
        date = f'{day}-01-2025' if bank == 'hong_leong' else f'{day}/01/2025' if bank == 'cimb' else f'{day}/01'
        put(55 if bank == 'public_bank' else 30, y, '' if bank == 'public_bank' and i == 2 else date)
        put(start, y, narration)
        # A transaction may name another bank, e.g. a transfer to its customer.
        put(start, y + 12, mention if mention and i == 1 else 'SAMPLE PARTY REFERENCE')
        if bank == 'maybank':
            put(400, y, incoming + '+' if incoming else outgoing + '-', right=True)
        else:
            out_edge, in_edge = {'public_bank': (352.9, 428.9), 'hong_leong': (475, 395), 'cimb': (400, 470)}[bank]
            if incoming:
                put(in_edge, y, incoming, right=True)
            if outgoing:
                put(out_edge, y, outgoing, right=True)
        if bank != 'hong_leong' or i > 0:
            put(
                525.7 if bank == 'public_bank' else width - 30,
                y,
                '999.00' if bad_balance and i == len(rows) - 1 else balance,
                right=True,
            )
    footer = {
        'public_bank': ['Closing Balance In This Statement 105.00'],
        'maybank': ['ENDING BALANCE : 105.00', 'TOTAL DEBIT : 5.00', 'TOTAL CREDIT : 10.00'],
        'hong_leong': [
            'Total Withdrawals / Jumlah Pengeluaran : 1 5.00',
            'Total Deposits / Jumlah Simpanan : 1 10.00',
            'Closing Balance / Baki Akhir: 105.00',
        ],
        'cimb': ['CLOSING BALANCE / BAKI PENUTUP 105.00', '1 1 5.00 10.00'],
    }[bank]
    for i, text in enumerate(footer):
        put(start, 400 + i * 12, text)
    doc.save(path)
    doc.close()
    return path


def uob_export(path, *, bad_balance=False, missing_row=False, bad_totals=False, header_balance='500.00'):
    """Write a filtered export whose current header balance differs from its period balance."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for i, text in enumerate(
        [
            'Account Activities',
            'CURRENT_ACCOUNT UOBM Jln Tengah',
            'MYR 1234567890',
            'Ledger Balance',
            'MYR ' + header_balance,
            '01/01/2025 - 31/01/2025',
            '2 Record(s) (Note: This is a filtered table.)',
        ]
    ):
        page.insert_text((20, 20 + i * 12), text, fontsize=7)
    bounds = (20, 100, 187, 310, 383, 473, 575)
    headers = [
        'Statement Date',
        'Transaction Date',
        'Description',
        'Deposit(MYR)',
        'Withdrawal(MYR)',
        'Ledger Balance(MYR)',
    ]
    for left, right, text in zip(bounds, bounds[1:], headers):
        page.draw_rect((left, 150, right, 175), width=0.5)
        page.insert_text((left + 4, 165), text, fontsize=6)
    for i, values in enumerate(
        [
            ['01/01/2025', '01/01/2025 10:00:00\nAM', 'Transfer\nFIRST PARTY', '10.00', '0.00', '110.00'],
            [
                '03/01/2025',
                '02/01/2025 03:00:00\nPM',
                'Transfer\nSECOND PARTY',
                '0.00',
                '5.00',
                '999.00' if bad_balance else '105.00',
            ],
        ]
    ):
        if missing_row and i == 1:
            continue
        top = 175 + i * 55
        page.draw_rect((20, top, 575, top + 55), width=0.5)
        for left, value in zip(bounds, values):
            page.insert_text((left + 4, top + 17), value, fontsize=6)
    page.insert_text((280, 815), '1 of 2', fontsize=7)
    page = doc.new_page(width=595, height=842)
    page.insert_text((20, 30), 'Account Activities', fontsize=7)
    page.insert_text((20, 60), 'Total Deposits(MYR) Total Withdrawals(MYR)', fontsize=7)
    page.insert_text((20, 80), '10.00 6.00' if bad_totals else '10.00 5.00', fontsize=7)
    page.insert_text((280, 815), '2 of 2', fontsize=7)
    doc.save(path)
    doc.close()
    return path


def ambank_statement(path):
    """Write the legacy AmBank layout to protect existing master compatibility."""
    doc = pymupdf.open()
    page = doc.new_page(width=595.28, height=842)
    labels = [
        (20, 30, 'AMBANK'),
        (20, 45, '1234567890 MYR 105.00'),
        (20, 150, 'DATE TRANSACTION CHEQUE NO. DEBIT CREDIT BALANCE'),
        (20, 170, 'Balance Brought Fwd'),
        (500, 170, '100.00'),
        (20, 200, '01-Jan'),
        (110, 200, 'Fund Transfer, ALICE, REF'),
        (420, 200, '10.00'),
        (500, 200, '110.00'),
        (20, 225, '02-Jan'),
        (110, 225, 'Fund Transfer, BOB, REF'),
        (330, 225, '5.00'),
        (500, 225, '105.00'),
        (20, 250, 'TOTAL / JUMLAH'),
        (330, 250, '5.00'),
        (420, 250, '10.00'),
    ]
    for x, y, text in labels:
        page.insert_text((x, y), text, fontsize=7)
    doc.save(path)
    doc.close()
    return path
