"""Keep optimized ranking and header summaries equivalent to full evidence reads."""

from pathlib import Path
from unittest.mock import patch

from dashboard.services.matching import final_review, piece_matching
from reconciliation.matching.ranking import rank
from reconciliation.matching.retrieval import ReferenceIndex, exact_references
from tests.fixtures.piece_pipeline import PiecePipelineFixture


class SnapshotPerformanceTests(PiecePipelineFixture):
    def test_rank_cache_is_isolated_and_invalidates_changed_inputs(self):
        """Reused rankings cannot hide edited facts or leak mutable candidate lists."""
        self.accept()
        piece_matching.activate(self.review)
        banks, items, index, facts = piece_matching.current(self.review)
        piece_matching._candidate_choices.cache_clear()
        with patch('reconciliation.matching.ranking.rank', wraps=rank) as ranking:
            before = piece_matching.candidates(banks, items, facts, index)
            again = piece_matching.candidates(banks, items, facts, index)
            self.assertEqual(before, again)
            self.assertEqual(ranking.call_count, 1)
            again['B1'].append('not-a-real-piece')
            self.assertEqual(piece_matching.candidates(banks, items, facts, index), before)
            next(iter(items.values()))['amount'] = '999'
            piece_matching.candidates(banks, items, facts, index)
            self.assertEqual(ranking.call_count, 2)
            next(iter(banks.values()))['description'] = 'Corrected bank narration'
            piece_matching.candidates(banks, items, facts, index)
            self.assertEqual(ranking.call_count, 3)
            piece_matching.candidates(banks, items, {'documents': {}}, index)
            self.assertEqual(ranking.call_count, 4)

    def test_summary_skips_ranking_and_keeps_approval_and_stale_checks(self):
        """Header status matches full snapshots before approval, after it, and after source changes."""
        view = self.accept()
        ids = [row['piece_id'] for row in view['units'][0]['receipts']]
        piece_matching.activate(self.review)
        full = final_review.snapshot(self.review)
        for stage in ('pending', 'approved', 'stale'):
            if stage == 'approved':
                final_review.decide(
                    self.review,
                    self.decision(
                        allocations=[
                            {'item_id': ids[0], 'amount': '45'},
                            {'item_id': ids[1], 'amount': '15'},
                        ]
                    ),
                )
            if stage == 'stale':
                Path(full['items'][0]['source_path']).write_bytes(b'Changed source')
            full = final_review.snapshot(self.review)
            with patch.object(piece_matching, 'candidates', side_effect=AssertionError('Header ranked candidates')):
                summary = final_review.snapshot(self.review, summary=True)
            self.assertEqual(
                summary['banks'],
                [
                    {key: bank[key] for key in ('confidence', 'review_status', 'stale', 'decision')}
                    for bank in full['banks']
                ],
            )
            if stage == 'stale':
                self.assertTrue(full['banks'][0]['stale'])

    def test_reference_index_preserves_boundaries_and_normalization(self):
        """Prepared references have the same punctuation, Unicode, and identifier boundaries."""
        items = {
            str(index): {'typed_references': [{'type': 'receipt', 'value': value}]}
            for index, value in enumerate(('RCP-001', 'AB/009', 'INV.123', 'PAY-456', '?????'))
        }
        prepared = ReferenceIndex(items)
        for description in ('R C P - 0 0 1', 'xAB/009x', 'Paid AB/009 today', 'INV.1234', 'PAY-456', '?????'):
            bank = {'description': description, 'typed_references': [{'type': 'receipt', 'value': 'INV.123'}]}
            self.assertEqual(prepared.query(bank), {key: exact_references(bank, item) for key, item in items.items()})
