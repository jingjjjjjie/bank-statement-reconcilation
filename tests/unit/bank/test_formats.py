"""Exercise multi-bank extraction and fail-closed checks on synthetic PDFs."""

import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pymupdf
from openpyxl import load_workbook
from pydantic import ValidationError

from dashboard.api.source import BankYear
from reconciliation.bank.excel import export
from reconciliation.bank.formats import check_selection
from reconciliation.bank.statement import extract, read_master, write_master
from reconciliation.intake.workspace import SourceSelection
from tests.fixtures.bank_pdf import ambank_statement, statement, uob_export


class FormatTests(unittest.TestCase):
    """Test actual PDF extraction without committing customer financial records."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def sample(self, bank, **kwargs):
        return statement(self.root / f'{bank}.pdf', bank, **kwargs)

    def test_supported_formats_round_trip_with_source_binding(self):
        for bank in ('public_bank', 'maybank', 'hong_leong', 'cimb'):
            with self.subTest(bank=bank):
                data = extract(self.sample(bank), 2025, bank)
                self.assertEqual(data['closing_balance'], Decimal('105.00'))
                self.assertEqual(len(data['transactions']), 3 if bank == 'public_bank' else 2)
                self.assertEqual(data['transactions'][0]['date'], '2025-01-01')
                self.assertIn('SAMPLE PARTY REFERENCE', data['transactions'][0]['narration'])
                master = self.root / 'master.csv'
                write_master(data, master)
                loaded = read_master(master)
                self.assertEqual(loaded['bank'], bank)
                self.assertEqual(loaded['transactions'][0]['balance'], Decimal('110.00'))

    def test_auto_detect_all_formats_and_preserve_resolved_bank(self):
        """Automatic dispatch must match explicit extraction and persist the real issuer."""
        paths = {bank: self.sample(bank) for bank in ('public_bank', 'maybank', 'hong_leong', 'cimb')}
        paths['ambank'] = ambank_statement(self.root / 'ambank.pdf')
        paths['uob'] = uob_export(self.root / 'uob.pdf')
        for bank, path in paths.items():
            with self.subTest(bank=bank):
                automatic = extract(path, 2025, 'auto')
                self.assertEqual(automatic, extract(path, 2025, bank))
                master = self.root / f'{bank}.csv'
                write_master(automatic, master)
                self.assertEqual(read_master(master)['bank'], bank)
        self.assertEqual(BankYear(year=2025, bank='auto').bank, 'auto')

    def test_auto_detect_does_not_bypass_rejection(self):
        """Ambiguous issuers and invalid layouts or amounts must stop automatic extraction."""
        with self.assertRaisesRegex(ValueError, 'No supported bank name'):
            check_selection('Invoice', 'auto')
        self.assertEqual(check_selection('CIMB BANK BERHAD Malayan Banking Berhad', 'auto'), ['maybank', 'cimb'])
        for bank in ('public_bank', 'maybank', 'hong_leong', 'cimb'):
            for damage in ('bad_balance', 'missing_row', 'missing_header'):
                with self.subTest(bank=bank, damage=damage), self.assertRaises(ValueError):
                    extract(self.sample(bank, **{damage: True}), 2025, 'auto')
        with self.assertRaises(ValueError):
            extract(uob_export(self.root / 'uob.pdf', bad_totals=True), 2025, 'auto')

    def test_auto_reuse_validates_saved_master(self):
        """Automatic reuse verifies existing output and never replaces damaged saved rows."""
        source = self.sample('maybank')
        selection = SourceSelection(self.root, self.root / 'dashboard-data')
        manifest = self.root / 'project' / 'manifest.json'
        with patch.object(selection, 'selected_bank', return_value=source):
            result = selection.prepare_bank(manifest, 2025, 'auto')
            self.assertFalse(result['existing'])
            self.assertTrue(selection.prepare_bank(manifest, 2025, 'auto')['existing'])
            master = Path(result['path'])
            master.write_text(master.read_text(encoding='utf-8-sig').replace('SAMPLE PARTY', 'CHANGED PARTY'), encoding='utf-8-sig')
            saved = master.read_bytes()
            with self.assertRaises(ValueError):
                selection.prepare_bank(manifest, 2025, 'auto')
            self.assertEqual(master.read_bytes(), saved)

    def test_legacy_ambank_master_without_new_metadata(self):
        path = ambank_statement(self.root / 'ambank.pdf')
        data = extract(path, 2025)
        master = self.root / 'legacy.csv'
        write_master(data, master)
        with master.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        removed = (
            'bank',
            'balance_origin',
            'statement_kind',
            'validation_note',
            'opening_balance_origin',
            'header_balance',
            'transaction_datetime',
        )
        fields = [key for key in rows[0] if key not in removed]
        with master.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        loaded = read_master(master)
        self.assertEqual(loaded['bank'], 'ambank')
        self.assertEqual(loaded['transactions'][0]['counterparty'], 'ALICE')
        self.assertEqual(len(loaded['transactions']), 2)

    def test_every_wrong_selection_rejected(self):
        banks = ('public_bank', 'maybank', 'hong_leong', 'cimb')
        for issuer in banks:
            path = self.sample(issuer)
            for selected in ('ambank', 'uob', *banks):
                if issuer != selected:
                    with (
                        self.subTest(issuer=issuer, selected=selected),
                        self.assertRaisesRegex(ValueError, 'Selected.*but this PDF'),
                    ):
                        extract(path, 2025, selected)

    def test_damaged_or_missing_data_rejected(self):
        for bank in ('public_bank', 'maybank', 'hong_leong', 'cimb'):
            for damage in ('bad_balance', 'missing_row', 'missing_header'):
                with self.subTest(bank=bank, damage=damage), self.assertRaises(ValueError):
                    extract(self.sample(bank, **{damage: True}), 2025, bank)

    def test_wrong_year_rejected(self):
        for bank in ('public_bank', 'maybank', 'hong_leong', 'cimb'):
            with self.subTest(bank=bank), self.assertRaisesRegex(ValueError, 'Selected year'):
                extract(self.sample(bank), 2024, bank)

    def test_calculated_balance_is_explicit_and_bound(self):
        data = extract(self.sample('hong_leong'), 2025, 'hong_leong')
        self.assertEqual([r['balance_origin'] for r in data['transactions']], ['calculated', 'printed'])
        master = self.root / 'master.csv'
        write_master(data, master)
        with master.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, list(reader)
        rows[0]['balance_origin'] = 'printed'
        with master.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        with self.assertRaisesRegex(ValueError, 'differs from source extraction'):
            read_master(master)

    def test_public_bank_retains_zero_value_debit(self):
        data = extract(self.sample('public_bank'), 2025, 'public_bank')
        self.assertEqual(data['transactions'][-1]['direction'], 'out')
        self.assertEqual(data['transactions'][-1]['money_out'], 0)

    def test_unknown_ambiguous_and_mismatched_uob_fail_closed(self):
        for text in ('Invoice from a supplier', 'Account Activities UOBM Jln Tengah', 'CIMB BANK BERHAD UOBM'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                check_selection(text, 'maybank')
        self.assertEqual(check_selection('CIMB BANK BERHAD Malayan Banking Berhad', 'maybank'), ['maybank'])

    def test_other_bank_named_in_transaction_still_detected(self):
        """Another issuer's name in a narration must not block or redirect detection."""
        cases = {'maybank': 'CIMB BANK BERHAD', 'public_bank': 'IBG TO AMBANK', 'cimb': 'PUBLIC BANK BERHAD'}
        for bank, mention in cases.items():
            with self.subTest(bank=bank):
                path = statement(self.root / f'{bank}-mention.pdf', bank, mention=mention)
                automatic = extract(path, 2025, 'auto')
                self.assertEqual(automatic['bank'], bank)
                self.assertEqual(automatic, extract(path, 2025, bank))
                self.assertIn(mention, automatic['transactions'][1 if bank != 'cimb' else 0]['narration'])
        damaged = statement(self.root / 'damaged.pdf', 'maybank', mention='CIMB BANK BERHAD', bad_balance=True)
        with self.assertRaisesRegex(ValueError, 'names Maybank and CIMB, but no layout passed'):
            extract(damaged, 2025, 'auto')

    def test_unreadable_pdf_rejected_clearly(self):
        path = self.root / 'not-a-statement.pdf'
        path.write_bytes(b'not a PDF')
        with self.assertRaisesRegex(ValueError, 'Cannot read this PDF'):
            extract(path, 2025, 'maybank')

    def test_foreign_currency_rejected(self):
        for bank in ('hong_leong', 'cimb'):
            with self.subTest(bank=bank), self.assertRaises(ValueError):
                extract(self.sample(bank, foreign=True), 2025, bank)

    def test_page_sequence_rejected(self):
        path = self.sample('cimb')
        with pymupdf.open(path) as doc:
            doc.copy_page(0)
            altered = self.root / 'duplicate-page.pdf'
            doc.save(altered)
        with self.assertRaises(ValueError):
            extract(altered, 2025, 'cimb')

    def test_filename_does_not_determine_bank(self):
        path = self.sample('cimb').rename(self.root / 'Maybank.pdf')
        with self.assertRaisesRegex(ValueError, 'Selected Maybank.*CIMB'):
            extract(path, 2025, 'maybank')
        self.assertEqual(extract(path, 2025, 'cimb')['bank'], 'cimb')

    def test_failed_selection_never_writes_or_replaces_master(self):
        source = self.sample('maybank')
        selection = SourceSelection(self.root, self.root / 'dashboard-data')
        manifest = self.root / 'project' / 'manifest.json'
        output = manifest.parent / 'bank-output/master_statement.csv'
        with patch.object(selection, 'selected_bank', return_value=source):
            with self.assertRaisesRegex(ValueError, 'Selected CIMB'):
                selection.prepare_bank(manifest, 2025, 'cimb')
            self.assertFalse(output.exists())
            selection.prepare_bank(manifest, 2025, 'maybank')
            saved = output.read_bytes()
            with self.assertRaisesRegex(ValueError, 'not replaced'):
                selection.prepare_bank(manifest, 2025, 'cimb')
            self.assertEqual(output.read_bytes(), saved)
            self.assertTrue(selection.prepare_bank(manifest, 2025, 'maybank')['existing'])

    def test_api_requires_supported_bank_and_integer_year(self):
        for body in ({'year': 2025}, {'year': 2025, 'bank': 'unknown'}, {'year': 2025.5, 'bank': 'maybank'}):
            with self.subTest(body=body), self.assertRaises(ValidationError):
                BankYear(**body)

    def test_uob_export_keeps_header_balance_separate(self):
        path = uob_export(self.root / 'uob.pdf')
        data = extract(path, 2025, 'uob')
        self.assertEqual(data['opening_balance'], Decimal('100.00'))
        self.assertEqual(data['closing_balance'], Decimal('105.00'))
        self.assertEqual(data['header_balance'], Decimal('500.00'))
        self.assertEqual(data['statement_kind'], 'activity_export')
        self.assertEqual(data['opening_balance_origin'], 'inferred')
        self.assertIn('completeness is not verified', data['validation_note'])
        self.assertEqual(data['transactions'][1]['date'], '2025-01-03')
        self.assertEqual(data['transactions'][1]['transaction_datetime'], '2025-01-02T15:00:00')
        master = self.root / 'uob.csv'
        write_master(data, master)
        self.assertEqual(read_master(master)['header_balance'], '500.00')
        workbook = self.root / 'uob.xlsx'
        export(master, 'Synthetic company', workbook)
        book = load_workbook(workbook)
        self.addCleanup(book.close)
        self.assertIn('ACCOUNT ACTIVITIES (FILTERED EXPORT)', book.active['A2'].value)
        self.assertIn('completeness is not verified', book.active['A2'].comment.text)
        self.assertEqual(book.active['G5'].value, 'OPENING BALANCE (INFERRED)')
        self.assertEqual(book.active['J5'].value, 100)
        for bank in ('ambank', 'maybank', 'public_bank', 'hong_leong', 'cimb'):
            with self.assertRaisesRegex(ValueError, 'Selected.*UOB'):
                extract(path, 2025, bank)

    def test_uob_corrupted_data_and_wrong_year_rejected(self):
        for damage in ('bad_balance', 'missing_row', 'bad_totals'):
            path = uob_export(self.root / 'uob.pdf', **{damage: True})
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                extract(path, 2025, 'uob')
        with self.assertRaisesRegex(ValueError, 'Selected year'):
            extract(uob_export(self.root / 'uob.pdf'), 2024, 'uob')

    def test_party_fields_do_not_treat_references_as_names(self):
        from reconciliation.bank.statement import describe

        self.assertEqual(
            describe('PAYMENT FR A/C\n12345*\nPAYMENT AGENCY\nREF', 0, 'maybank')['counterparty'], 'PAYMENT AGENCY'
        )
        self.assertEqual(describe('AUTOPAY DR 123\nREF\nBATCH.TXT', 0, 'cimb')['counterparty'], '')
        self.assertEqual(describe('TR IBG 123\nEXAMPLE PAYEE\nREFERENCE', 0, 'cimb')['counterparty'], 'EXAMPLE PAYEE')
