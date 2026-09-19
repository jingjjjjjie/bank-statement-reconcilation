"""Exercise agreed retrieval quotas, references, text ordering and coverage flags."""
import unittest
from unittest.mock import patch

from reconciliation.matching_retrieval import retrieve


def record(key, **fields):
    """Create minimal bank/piece facts without any source or model calls."""
    return {'id': key, 'amount': '250.00', 'currency': 'MYR', 'direction': '',
            'parties': ['Wu Wenjun'], 'description': '', 'references': [],
            'date': '2025-12-01', **fields}


class RetrievalTests(unittest.TestCase):
    def select(self, items, **fields):
        """Retrieve for one outgoing payment and expose its audit."""
        choices, audit = retrieve([record('B', direction='out', **fields)], items)
        return choices['B'], audit['B']

    def test_twenty_each_and_deduplicated_cap(self):
        """Independent name and amount routes each keep twenty, not a shared score cutoff."""
        items = [record(f'N{n:02}', amount='99') for n in range(25)]
        items += [record(f'A{n:02}', parties=['Merchant']) for n in range(25)]
        selected, audit = self.select(items)
        self.assertEqual(len(selected), 40)
        self.assertEqual(sum(k.startswith('N') for k in selected), 20)
        self.assertEqual(sum(k.startswith('A') for k in selected), 20)
        self.assertEqual(audit['omitted'], 10)
        selected, _ = self.select([record(str(n)) for n in range(25)])
        self.assertEqual(len(selected), 20)

    def test_canva_description_precedes_recent_unrelated_amounts(self):
        """An older merchant receipt survives more than twenty same-amount alternatives."""
        items = [record(f'noise{n}', parties=['Other'], description='Wage payment') for n in range(30)]
        items.append(record('canva', parties=['Canva Pty Ltd'], description='Canva Pro subscription', date='2024-11-27'))
        selected, _ = self.select(items, description='Fund Transfer /DEBIT TRANSFER, WU WENJUN, Canva zuotufei')
        self.assertEqual(selected[0], 'canva')
        self.assertEqual(len(selected), 20)

    def test_date_breaks_equal_text_scores(self):
        """Date proximity orders ties without imposing an exclusion window."""
        selected, _ = self.select([record('old', date='2024-01-01'), record('near', date='2025-11-30')])
        self.assertEqual(selected, ['near', 'old'])

    def test_top_up_to_ten_not_ten_more(self):
        """Seven primary candidates receive only three meaningful fallback pieces."""
        items = [record(f'primary{n}') for n in range(7)]
        items += [record(f'fallback{n}', amount='99', parties=['Other'], description='Canva subscription') for n in range(15)]
        selected, audit = self.select(items, description='Canva')
        self.assertEqual(len(selected), 10)
        self.assertEqual(sum(k.startswith('fallback') for k in selected), 3)
        self.assertTrue(audit['search_incomplete'])

    def test_never_pad_with_unrelated_or_excluded_pieces(self):
        """Boilerplate, dates and unknown amounts cannot fabricate eligible candidates."""
        selected, _ = self.select([record('noise', amount='', parties=['Other'], description='Payment receipt fee'),
                                   record('excluded', excluded=True), record('retired', retired=True)],
                                  amount='', description='Fund transfer payment')
        self.assertEqual(selected, [])

    def test_exact_reference_reserved_and_conflict_flagged(self):
        """A reference-linked partial/cross-currency payment is retained as a flagged candidate."""
        items = [record(f'N{n}', amount='99') for n in range(25)]
        items += [record(f'A{n}', parties=['Other']) for n in range(25)]
        items.append(record('ref', amount='1000', currency='USD', parties=['Other'],
                            typed_references=[{'type': 'invoice', 'value': 'INV-00123'}]))
        selected, audit = self.select(items, description='Payment INV-00123')
        self.assertEqual(selected[0], 'ref')
        self.assertEqual(len(selected), 40)
        self.assertTrue(audit['reasons']['ref']['conflict'])

    def test_reference_boundaries_and_tax_ids(self):
        """Never promote prefixes, recurring accounts or tax numbers to transaction references."""
        items = [record(key, amount='99', parties=['Other'], typed_references=[{'type': kind, 'value': value}])
                 for key, kind, value in [('prefix', 'invoice', 'INV-12'), ('tax', 'tax', '123456'),
                                          ('account', 'account', '00999'), ('correct', 'invoice', 'INV-123')]]
        selected, _ = self.select(items, description='INV-123 123456 00999')
        self.assertEqual(selected, ['correct'])

    def test_whitespace_case_and_leading_zeros(self):
        """Normalize whitespace/case, preserving significant leading zero differences."""
        items = [record(key, amount='99', parties=['Other'], typed_references=[{'type': 'invoice', 'value': value}])
                 for key, value in [('yes', 'Inv-00123'), ('no', 'INV-123')]]
        selected, _ = self.select(items, description='payment inv - 00123')
        self.assertEqual(selected, ['yes'])

    def test_reference_overflow_is_explicit(self):
        """More than forty exact references stays bounded and cannot appear exhaustive."""
        items = [record(str(n), typed_references=[{'type': 'invoice', 'value': 'INV-123'}]) for n in range(45)]
        selected, audit = self.select(items, description='INV-123')
        self.assertEqual(len(selected), 40)
        self.assertTrue(audit['reference_overflow'])
        self.assertEqual(audit['omitted'], 5)

    def test_labelled_legacy_references_are_supported(self):
        """Old labelled booking records remain usable without promoting arbitrary words."""
        selected, _ = self.select([record('booking', amount='99', parties=['Other'],
                                           references=['Booking number: B8G43P'])], description='Booking B8G43P')
        self.assertEqual(selected, ['booking'])

    def test_live_payload_keeps_context_but_bounds_allocatable_ids(self):
        """Full parent evidence cannot silently enlarge the selected allocation shortlist."""
        from dashboard import piece_matching
        from tests.unit.test_piece_pipeline import PiecePipelineTests
        fixture = PiecePipelineTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.accept()
        banks, items, index, facts = piece_matching.current(fixture.review)
        key = next(iter(items))
        choices = {'B1': [key]}
        audit = {'B1': {'search_incomplete': True, 'omitted': 1}}
        payload, _, allowed = piece_matching.model_payload(banks, items, index, facts, choices, ['B1'], audit)
        self.assertEqual(allowed['B1'], [key])
        self.assertEqual(len(next(iter(payload['documents'].values()))['pieces']), 2)
        self.assertEqual(payload['retrieval'], audit)
        self.assertEqual(payload['related_bank_entries'], [])

    def test_incomplete_live_search_cannot_publish_definitive_no_match(self):
        """The server enforces incomplete-search wording even if a model overlooks it."""
        from dashboard import piece_matching, piece_match_jobs
        from reconciliation.review_settings import DEFAULTS
        from tests.unit.test_piece_pipeline import PiecePipelineTests
        import json
        fixture = PiecePipelineTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.accept()
        banks, items, _, _ = piece_matching.current(fixture.review)
        key = next(iter(items))
        choices = {bank: [key] for bank in banks}
        audit = {bank: {'search_incomplete': True, 'omitted': 5, 'reference_overflow': False} for bank in banks}

        class Reviewer:
            active_count = 0

            def __init__(self, *args, **kwargs):
                """Use only fixture output, with no model service access."""

            def fork(self):
                """Share the stateless fixture."""
                return self

            def ask(self, prompt, schema, images):
                """Return a no-match assessment to exercise the deterministic guard."""
                supplied = json.loads(prompt.rsplit('\n', 1)[1])
                return {'decisions': [{'bank_id': supplied['banks'][0]['id'], 'assessment': 'none',
                                       'allocations': [], 'reason': 'No match in supplied evidence.'}]}

        config = {**DEFAULTS, 'codex_enabled': True, 'max_parallel': 2}
        with patch.object(piece_match_jobs, 'CodexReviewer', Reviewer), \
                patch.object(piece_match_jobs, 'retrieve', return_value=(choices, audit)), \
                patch.object(piece_match_jobs, 'active_config', return_value=config):
            piece_match_jobs.start(fixture.review)
            fixture.review.piece_match_thread.join(5)
        self.assertFalse(piece_match_jobs.status(fixture.review)['running'])
        self.assertEqual(piece_match_jobs.status(fixture.review)['error'], '')
        result = json.loads((fixture.review.manifest_path.parent / 'final-review/piece-suggestions.json').read_text())
        self.assertTrue(all(row['assessment'] == 'tentative' and '5 eligible pieces' in row['reason']
                            for row in result['decisions']))
