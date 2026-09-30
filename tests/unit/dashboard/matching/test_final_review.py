"""Exercise the final human ledger without model calls or real customer decisions."""

import csv
import unittest
from unittest.mock import patch

from dashboard.services.matching import final_review as matching
from tests.fixtures.final_review import FinalReviewFixture


class MatchingReviewTests(FinalReviewFixture):
    def test_trash_document_cannot_be_approved_as_support(self):
        """Final review respects explicit document trash classifications."""
        item = matching.context(self.review)[3]['D1']
        folder = self.project / 'review'
        folder.mkdir()
        self.write(
            folder / 'receipt-matches.json', {'matches': {}, 'trash': {item['document']: {'classification': 'trash'}}}
        )
        data = matching.snapshot(self.review)
        self.assertTrue(next(entry for entry in data['items'] if entry['id'] == 'D1')['excluded'])
        with self.assertRaisesRegex(ValueError, 'excluded'):
            matching.decide(self.review, self.request())

    def test_confidence_is_separate_from_approval_and_downgrades_stale_evidence(self):
        """High never approves a pairing; missing or changed support is not high confidence."""
        suggestions = matching.read(self.cache / 'decisions.json')
        suggestions[0]['assessment'] = 'strong'
        suggestions[2]['allocations'] = []
        self.write(self.cache / 'decisions.json', suggestions)
        data = matching.snapshot(self.review)
        self.assertEqual([b['confidence']['level'] for b in data['banks']], ['high', 'low', None])
        self.assertTrue(all(b['review_status'] == 'pending' for b in data['banks']))
        self.assertTrue(all(b['support_status'] == 'No supporting' for b in data['banks']))
        matching.decide(self.review, self.request())
        self.assertEqual(matching.snapshot(self.review)['banks'][0]['confidence']['level'], 'high')
        (self.review.root / 'receipt-1.txt').write_text('Changed evidence')
        self.assertEqual(matching.snapshot(self.review)['banks'][0]['confidence']['level'], 'low')

    def test_high_confidence_requires_full_amount_and_current_selection(self):
        """Amount gaps and manually changed pairings cannot inherit a high label."""
        suggestions = matching.read(self.cache / 'decisions.json')
        suggestions[0]['assessment'] = 'strong'
        suggestions[0]['allocations'][0]['amount'] = '5'
        self.write(self.cache / 'decisions.json', suggestions)
        self.assertEqual(matching.snapshot(self.review)['banks'][0]['confidence']['level'], 'low')
        matching.decide(self.review, self.request(allocations=[{'item_id': 'D2', 'amount': '10'}]))
        self.assertIn('selection changed', matching.snapshot(self.review)['banks'][0]['confidence']['reason'])

    def test_evidence_explanations_do_not_turn_amounts_into_matches(self):
        """Explain name/currency gaps and stale evidence without changing decisions."""
        bank = {'parties': ['Nur Fajrina'], 'amount': '150', 'currency': 'MYR'}
        item = {'parties': [' nur   FAJRINA '], 'amount': '150.00', 'currency': 'MYR'}
        self.assertIn('Same extracted party name and amount', matching.evidence_reason(bank, item))
        self.assertIn('Amount alone', matching.evidence_reason(bank, {**item, 'parties': ['Siti']}))
        self.assertIn('differs or is unknown', matching.evidence_reason(bank, {**item, 'currency': 'USD'}))
        self.assertIn('differs or is unknown', matching.evidence_reason(bank, {**item, 'amount': ''}))
        self.assertIn('Unavailable', matching.evidence_reason(bank, {**item, 'stale': True}))
        self.assertIn('No exact', matching.evidence_reason(bank, {**item, 'parties': [], 'amount': ''}))
        before = matching.context(self.review)[1]
        snapshot = matching.snapshot(self.review)
        self.assertIn('Same extracted', snapshot['banks'][0]['evidence_reasons']['D1'])
        self.assertEqual(before, matching.context(self.review)[1])

    def test_approval_persists_and_undo_releases_capacity(self):
        """Only an explicit approval changes support; undo retains history and frees amounts."""
        self.assertTrue(all(b['support_status'] == 'No supporting' for b in matching.snapshot(self.review)['banks']))
        matching.decide(self.review, self.request())
        data = matching.snapshot(self.review)
        self.assertEqual(data['banks'][0]['support_status'], 'Supporting')
        self.assertEqual(data['items'][0]['remaining'], '0')
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            matching.decide(self.review, self.request('B2'))
        matching.decide(self.review, self.request(action='undo'))
        data = matching.snapshot(self.review)
        self.assertEqual(data['banks'][0]['review_status'], 'pending')
        self.assertEqual(len(data['banks'][0]['history']), 2)
        self.assertEqual(data['items'][0]['remaining'], '10')

    def test_stale_tab_and_unknown_items_are_rejected(self):
        """Concurrent tabs cannot overwrite a newer decision or submit invented evidence."""
        stale = self.request('B2')
        matching.decide(self.review, self.request(action='deny'))
        with self.assertRaisesRegex(ValueError, 'Another decision'):
            matching.decide(self.review, stale)
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            matching.decide(self.review, self.request(allocations=[{'item_id': 'fake', 'amount': '10'}]))

    def test_partial_and_contextual_support_stay_flagged(self):
        """A human approval cannot hide missing or partially allocated monetary evidence."""
        matching.decide(
            self.review, self.request(allocations=[{'item_id': 'D1', 'amount': '5'}], note='', acknowledged=False)
        )
        data = matching.snapshot(self.review)
        self.assertEqual(data['banks'][0]['decision']['difference'], '5')
        self.assertEqual(data['banks'][0]['support_status'], 'No supporting')
        matching.decide(self.review, self.request('B2', allocations=[{'item_id': 'E1', 'amount': ''}]))
        self.assertTrue(matching.snapshot(self.review)['banks'][1]['decision']['context_only'])
        with self.assertRaisesRegex(ValueError, 'Unknown or different'):
            matching.decide(self.review, self.request('B2', allocations=[{'item_id': 'E1', 'amount': '10'}]))

    def test_split_payments_share_capacity_without_double_spending(self):
        """A partially used receipt can support another payment up to its remaining amount."""
        matching.decide(self.review, self.request(allocations=[{'item_id': 'D1', 'amount': '5'}]))
        matching.decide(self.review, self.request('B3', allocations=[{'item_id': 'D1', 'amount': '5'}]))
        self.assertEqual(matching.snapshot(self.review)['items'][0]['remaining'], '0')

    def test_changed_source_stays_reserved_but_not_supported(self):
        """Changed originals revoke displayed support without silently freeing their allocations."""
        matching.decide(self.review, self.request())
        source = matching.evidence(self.review, 'item', 'D1')
        source.write_text('Changed original', encoding='utf-8')
        data = matching.snapshot(self.review)
        self.assertTrue(data['banks'][0]['stale'])
        self.assertEqual(data['banks'][0]['support_status'], 'No supporting')
        self.assertEqual(data['items'][0]['remaining'], '0')
        with self.assertRaisesRegex(ValueError, 'changed'):
            matching.evidence(self.review, 'item', 'D1')

    def test_denial_and_export_include_every_transaction(self):
        """Denied suggestions remain separate from originals and export with unreviewed rows."""
        matching.decide(self.review, self.request(action='deny', note='=not a formula'))
        exported = matching.export_csv(self.review).decode('utf-8-sig')
        self.assertIn('denied', exported)
        self.assertIn("'=not a formula", exported)
        self.assertEqual(len(list(csv.DictReader(exported.splitlines()))), 3)

    def test_statement_export_options_and_match_marker(self):
        """Both layouts retain every row; only full support gets OK and paths are optional."""
        matching.decide(self.review, self.request())
        matching.decide(self.review, self.request('B2', action='deny'))
        with_paths = list(csv.DictReader(matching.export_csv(self.review).decode('utf-8-sig').splitlines()))
        without_paths = list(csv.DictReader(matching.export_csv(self.review, False).decode('utf-8-sig').splitlines()))
        self.assertEqual(
            list(with_paths[0])[:11],
            [
                'DATE',
                'LEDGER',
                'SQL',
                'SALES TYPE',
                'PV/OR',
                'PAY TO',
                'PARTICULAR',
                'DR',
                'CR',
                'TOTAL',
                'REMARK',
            ],
        )
        self.assertEqual([row['REMARK'] for row in with_paths], ['OK', '', ''])
        self.assertEqual(with_paths[0]['CR'], '10')
        self.assertEqual(with_paths[0]['DR'], '')
        self.assertEqual(with_paths[0]['PARTICULAR'], 'Receipt')
        self.assertEqual(with_paths[1]['PARTICULAR'], '')
        self.assertEqual(with_paths[0]['Supporting evidence paths'], str(matching.evidence(self.review, 'item', 'D1')))
        self.assertEqual([row['Supporting evidence paths'] for row in with_paths[1:]], ['', ''])
        self.assertEqual(
            without_paths,
            [{key: value for key, value in row.items() if key != 'Supporting evidence paths'} for row in with_paths],
        )
        source = matching.evidence(self.review, 'item', 'D1')
        source.write_text('Changed evidence', encoding='utf-8')
        changed = list(csv.DictReader(matching.export_csv(self.review).decode('utf-8-sig').splitlines()))
        self.assertEqual(changed[0]['REMARK'], '')
        self.assertEqual(changed[0]['PARTICULAR'], '')
        self.assertEqual(changed[0]['Stale evidence'], 'True')

    def test_statement_export_preserves_bank_columns(self):
        """Read debit, credit and balance from the bound master without recomputing totals."""
        master = self.project / 'bank-output/master_statement.csv'
        with master.open(newline='', encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream))
        rows[0].update(money_in='0.00', money_out='10.00', balance='123.45')
        with master.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        facts = matching.read(self.cache / 'facts.json')
        facts['bank_hash'] = matching.source_hash(master)
        self.write(self.cache / 'facts.json', facts)
        exported = list(csv.DictReader(matching.export_csv(self.review).decode('utf-8-sig').splitlines()))
        self.assertEqual([exported[0][field] for field in ('DR', 'CR', 'TOTAL')], ['0.00', '10.00', '123.45'])
        self.assertEqual([exported[0][field] for field in ('LEDGER', 'SQL', 'SALES TYPE', 'PV/OR')], ['', '', '', ''])

    def test_partial_approval_exports_blank_match(self):
        """An approved allocation with a difference must not export OK."""
        matching.decide(self.review, self.request(allocations=[{'item_id': 'D1', 'amount': '4'}]))
        rows = list(csv.DictReader(matching.export_csv(self.review, False).decode('utf-8-sig').splitlines()))
        self.assertEqual(rows[0]['REMARK'], '')
        self.assertEqual(rows[0]['Difference'], '6')

    def test_cache_changes_and_workspace_changes_do_not_reuse_approvals(self):
        """The ledger is tied to one exact cache and workspace, not reusable sequence IDs."""
        matching.decide(self.review, self.request())
        facts = matching.read(self.cache / 'facts.json')
        facts['items'][0]['amount'] = '20'
        self.write(self.cache / 'facts.json', facts)
        with self.assertRaisesRegex(ValueError, 'Cached evidence changed'):
            matching.context(self.review)
        self.review.manifest_path = self.root / 'another-manifest.json'
        with self.assertRaisesRegex(ValueError, 'different workspace'):
            matching.context(self.review)

    def test_unassembled_pages_cannot_create_new_capacity(self):
        """Switching page IDs cannot bypass a reservation on the same unfinished receipt."""
        facts = matching.read(self.cache / 'facts.json')
        facts['items'][0]['boundary_unresolved'] = True
        facts['items'].append({**facts['items'][0], 'id': 'D4', 'unit': 1})
        self.write(self.cache / 'facts.json', facts)
        matching.decide(self.review, self.request(allocations=[{'item_id': 'D1', 'amount': '5'}]))
        with self.assertRaisesRegex(ValueError, 'different page'):
            matching.decide(self.review, self.request('B3', allocations=[{'item_id': 'D4', 'amount': '5'}]))

    def test_legacy_approvals_cannot_be_ignored(self):
        """The cached ledger refuses to double-reserve evidence accepted by the old flow."""
        path = self.project / 'review/receipt-matches.json'
        path.parent.mkdir()
        self.write(path, {'matches': {'old': {'review_status': 'accepted'}}})
        with self.assertRaisesRegex(ValueError, 'migrated or undone'):
            matching.context(self.review)

    def test_save_response_matches_snapshot_without_reloading_context(self):
        """Save deltas cover approval, replacement and undo with correct balances."""
        for action, allocations in [
            ('approve', [{'item_id': 'D1', 'amount': '10'}]),
            ('approve', [{'item_id': 'D2', 'amount': '10'}]),
            ('undo', []),
        ]:
            request = self.request(action=action, allocations=allocations)
            with patch.object(matching, 'context', wraps=matching.context) as contexts:
                result = matching.decide(self.review, request)
                self.assertEqual(contexts.call_count, 1)
            snapshot = matching.snapshot(self.review)
            bank = next(row for row in snapshot['banks'] if row['id'] == 'B1')
            for key, value in result['bank'].items():
                self.assertEqual(value, bank[key], key)
            for updated in result['items']:
                item = next(row for row in snapshot['items'] if row['id'] == updated['id'])
                self.assertEqual(updated['remaining'], item['remaining'])
                self.assertEqual(updated['used'], item['used'])


if __name__ == '__main__':
    unittest.main()
