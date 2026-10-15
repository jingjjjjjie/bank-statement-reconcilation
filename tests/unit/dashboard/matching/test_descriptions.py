"""Manual export descriptions remain audited and independent of evidence approvals."""

import csv
import io
from copy import deepcopy

from openpyxl import load_workbook

from dashboard.services.matching import descriptions, final_export, final_review
from tests.fixtures.final_review import FinalReviewFixture


class DescriptionTests(FinalReviewFixture):
    def save_description(self, text, bank='B1', **extra):
        """Submit wording against the current shared ledger revision."""
        return descriptions.save(self.review, {**self.request(bank=bank), 'description': text, **extra})

    def test_manual_text_exports_without_approving_support(self):
        """Both workbook variants and CSV use literal manual wording even on an unmatched row."""
        text = '=Literal wording\nBank charges for December'
        self.save_description(text)
        bank = final_review.snapshot(self.review)['banks'][0]
        self.assertEqual(bank['particular'], text)
        self.assertTrue(bank['particular_edited'])
        self.assertEqual(bank['review_status'], 'pending')
        self.assertEqual(bank['support_status'], 'No supporting')
        for paths in (False, True):
            with self.subTest(paths=paths):
                book = load_workbook(io.BytesIO(final_export.export_workbook(self.review, paths)))
                self.assertEqual(book.active['G6'].value, text)
                self.assertEqual(book.active['G6'].data_type, 's')
                self.assertIsNone(book.active['K6'].value)
                book.close()
        rows = list(csv.DictReader(io.StringIO(final_review.export_csv(self.review).decode('utf-8-sig'))))
        self.assertEqual(rows[0]['PARTICULAR'], "'" + text)
        state = final_review.context(self.review)[1]
        self.assertEqual(state['decisions'], {})
        self.assertEqual(state['history'][-1]['action'], 'edit_description')
        self.assertEqual(state['history'][-1]['after']['text'], text)

    def test_reset_and_blank_preserve_approval_and_allocations(self):
        """An explicit blank differs from reset; neither modifies saved matching decisions."""
        final_review.decide(self.review, self.request())
        before = deepcopy(final_review.context(self.review)[1]['decisions'])
        generated = final_review.snapshot(self.review)['banks'][0]['particular']
        self.assertTrue(generated)
        self.save_description('Custom receipt wording')
        self.save_description('')
        self.assertEqual(final_review.snapshot(self.review)['banks'][0]['particular'], '')
        result = self.save_description(None)
        self.assertEqual(result['particular'], generated)
        self.assertFalse(result['particular_edited'])
        state = final_review.context(self.review)[1]
        self.assertEqual(state['decisions'], before)
        self.assertEqual(state['history'][-1]['action'], 'reset_description')
        self.assertNotIn('B1', state['descriptions'])

    def test_conflicts_and_invalid_text_do_not_write(self):
        """Reject stale clients, invalid payloads and changed bank originals without losing saved text."""
        stale = self.request()
        self.save_description('Saved text')
        ledger = self.project / 'final-review/decisions.json'
        original = ledger.read_bytes()
        with self.assertRaisesRegex(ValueError, 'report changed'):
            descriptions.save(self.review, {**stale, 'description': 'Overwritten'})
        for text in (12, [], 'a' * 4001, 'bad\x00text'):
            with self.subTest(text_type=type(text).__name__), self.assertRaises(ValueError):
                self.save_description(text)
        with self.assertRaises(ValueError):
            descriptions.save(self.review, self.request())
        with self.assertRaises(ValueError):
            self.save_description('Invalid bank', bank='missing')
        (self.root / 'statement.txt').write_text('Changed bank evidence', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'bank statement changed'):
            self.save_description('New text')
        bank = final_review.snapshot(self.review)['banks'][0]
        self.assertTrue(bank['particular_stale'])
        self.assertEqual(bank['particular'], '')
        self.assertEqual(ledger.read_bytes(), original)

    def test_manual_text_survives_matching_undo_without_claiming_support(self):
        """Review decisions and manual export wording have independent lifecycles."""
        final_review.decide(self.review, self.request())
        self.save_description('Manual description')
        final_review.decide(self.review, self.request(action='undo'))
        bank = final_review.snapshot(self.review)['banks'][0]
        self.assertEqual(bank['particular'], 'Manual description')
        self.assertEqual(bank['support_status'], 'No supporting')
        self.assertEqual(bank['review_status'], 'pending')
