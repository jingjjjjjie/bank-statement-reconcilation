"""Verify exact merge arithmetic and fresh evidence identities on acceptance."""
import unittest

from reconciliation.pieces import merge_all
from dashboard import receipt_review
from tests.unit import test_receipt_matching as fixtures


class MergeAllTests(unittest.TestCase):
    def test_sum_and_lineage(self):
        """Keep exact cents, original references and parent identities."""
        value = merge_all([
            {'piece_id': 'a', 'total': '0.10', 'currency': 'RM', 'payee': 'A', 'source_units': [1]},
            {'piece_id': 'b', 'total': '0.20', 'currency': 'MYR', 'payee': 'B', 'source_units': [1, 2]}])
        self.assertEqual(value['total'], '0.30')
        self.assertEqual(value['payee'], 'A / B')
        self.assertEqual(value['source_units'], [1, 2])
        self.assertEqual(value['parent_piece_ids'], ['a', 'b'])
        self.assertNotIn('piece_id', value)

    def test_unknown_total_and_mixed_currencies(self):
        """Never present a partial sum or add different currencies."""
        rows = [{'total': '10.00', 'currency': 'MYR'}, {'total': '', 'currency': 'MYR'}]
        self.assertEqual(merge_all(rows)['total'], '')
        rows[1]['currency'] = 'USD'
        with self.assertRaisesRegex(ValueError, 'same currency'):
            merge_all(rows)

    def test_accepted_merge_gets_new_identity(self):
        """Preview leaves saved entries intact; acceptance records parent lineage."""
        fixture = fixtures.ReceiptMatchingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        before = receipt_review.snapshot(fixture.review)
        rows = before['units'][0]['receipts']
        for row in rows:
            row['currency'] = 'MYR'
        merged = merge_all(rows)
        self.assertEqual(len(receipt_review.snapshot(fixture.review)['units'][0]['receipts']), 2)
        after = receipt_review.accept_extraction(fixture.review, {
            'revision': before['revision'], 'key': fixture.key, 'receipts': [merged]})
        entry = after['units'][0]['receipts'][0]
        self.assertEqual(entry['parent_piece_ids'], [row['piece_id'] for row in rows])
        self.assertNotIn(entry['piece_id'], entry['parent_piece_ids'])

    def test_reset_restores_original_after_accepted_merge(self):
        """Reset restores model entries as a draft, with fresh IDs on acceptance."""
        fixture = fixtures.ReceiptMatchingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        before = receipt_review.snapshot(fixture.review)
        original = before['units'][0]['receipts']
        merged = merge_all(original)
        merged['total'] = '123.45'
        accepted = receipt_review.accept_extraction(fixture.review, {
            'revision': before['revision'], 'key': fixture.key, 'receipts': [merged]})
        with self.assertRaisesRegex(ValueError, 'changed'):
            receipt_review.original_extraction(fixture.review, {'revision': before['revision'], 'key': fixture.key})
        draft = receipt_review.original_extraction(fixture.review, {
            'revision': accepted['revision'], 'key': fixture.key})
        self.assertEqual([p['total'] for p in draft['receipts']], [p['total'] for p in original])
        self.assertEqual(len(receipt_review.snapshot(fixture.review)['units'][0]['receipts']), 1)
        restored = receipt_review.accept_extraction(fixture.review, {
            'revision': accepted['revision'], 'key': fixture.key, 'receipts': draft['receipts']})
        self.assertEqual(len(restored['units'][0]['receipts']), 2)
        previous_id = accepted['units'][0]['receipts'][0]['piece_id']
        self.assertTrue(all(p['parent_piece_ids'] == [previous_id] for p in restored['units'][0]['receipts']))
