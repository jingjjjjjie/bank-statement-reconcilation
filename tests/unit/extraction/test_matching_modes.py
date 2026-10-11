"""Verify regeneration and failed-only retry without real model calls."""

import json
from unittest.mock import patch

from dashboard.services.matching import final_review, piece_match_jobs as jobs, piece_matching
from reconciliation.core.settings import DEFAULTS
from tests.fixtures.piece_pipeline import PiecePipelineFixture


class MatchingModeTests(PiecePipelineFixture):
    def test_retry_preserves_success_and_regenerate_requires_confirmation(self):
        """Retry only failed IDs; confirmed regeneration archives and clears the ledger."""
        extracted = self.accept()
        master = self.fixture.base / 'bank-output/master_statement.csv'
        master.write_text(master.read_text().replace('60.00', '45.00'))
        calls = []

        class Reviewer:
            active_count = 0

            def __init__(self, work, **options):
                """Keep this test entirely deterministic."""

            def fork(self):
                """Share the request recorder."""
                return self

            def ask(self, prompt, schema, images):
                """Return valid local suggestions and record requested bank IDs."""
                payload = json.loads(prompt.rsplit('\n', 1)[1])
                calls.append(payload)
                return {
                    'decisions': [
                        {'bank_id': bank['id'], 'assessment': 'none', 'allocations': [], 'reason': 'No support found'}
                        for bank in payload['banks']
                    ]
                }

        config = {**DEFAULTS, 'codex_enabled': True, 'max_parallel': 1}
        with patch.object(jobs, 'CodexReviewer', Reviewer), patch.object(jobs, 'active_config', return_value=config):
            jobs.start(self.review)
            self.review.piece_match_thread.join(5)
            self.assertFalse(jobs.status(self.review)['error'])
            piece = extracted['units'][0]['receipts'][0]['piece_id']
            final_review.decide(self.review, self.decision(allocations=[{'item_id': piece, 'amount': '45'}]))
            directory = self.review.manifest_path.parent / 'final-review'
            ledger = directory / 'decisions.json'
            original_ledger = ledger.read_bytes()
            checkpoint = directory / 'piece-suggestions.json'
            saved = json.loads(checkpoint.read_text())
            success = next(row for row in saved['decisions'] if row['bank_id'] == 'B1')
            saved['decisions'] = [row for row in saved['decisions'] if row['bank_id'] != 'B3']
            next(row for row in saved['decisions'] if row['bank_id'] == 'B2')['reason'] = 'Matching unresolved: failed'
            checkpoint.write_text(json.dumps(saved))
            calls.clear()
            checkpoint.write_text(json.dumps({**saved, 'request_revision': 'changed'}))
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                jobs.start(self.review, 'retry_failed')
            self.assertEqual(ledger.read_bytes(), original_ledger)
            checkpoint.write_text(json.dumps(saved))
            jobs.start(self.review, 'retry_failed')
            self.review.piece_match_thread.join(5)
            self.assertEqual([b['id'] for call in calls for b in call['banks']], ['B2'])
            self.assertTrue(calls[0]['retry_attempt'])
            self.assertEqual(ledger.read_bytes(), original_ledger)
            retried = json.loads(checkpoint.read_text())
            self.assertEqual(next(row for row in retried['decisions'] if row['bank_id'] == 'B1'), success)
            self.assertNotIn('B3', [row['bank_id'] for row in retried['decisions']])
            with self.assertRaisesRegex(ValueError, 'no failed'):
                jobs.start(self.review, 'retry_failed')
            with self.assertRaisesRegex(ValueError, 'confirm regeneration'):
                jobs.start(self.review, 'regenerate')
            self.assertEqual(ledger.read_bytes(), original_ledger)
            state = piece_matching.context(self.review)[1]
            with self.assertRaisesRegex(ValueError, 'confirm regeneration'):
                jobs.start(
                    self.review,
                    'regenerate',
                    {'confirm_clear': True, 'binding': state['binding'], 'version': state['version'] - 1},
                )
            calls.clear()
            jobs.start(
                self.review,
                'regenerate',
                {'confirm_clear': True, 'binding': state['binding'], 'version': state['version']},
            )
            self.review.piece_match_thread.join(5)
            self.assertFalse(jobs.status(self.review)['error'])
            self.assertEqual({b['id'] for call in calls for b in call['banks']}, {'B1', 'B2', 'B3'})
            self.assertTrue(all(call['matching_run'] for call in calls))
            reset = json.loads(ledger.read_text())
            self.assertEqual(reset['decisions'], {})
            self.assertEqual(reset['version'], state['version'] + 1)
            self.assertEqual(reset['history'][-1]['action'], 'regenerate')
            backup = json.loads(next((directory / 'backups').glob('regenerate-*.json')).read_text())
            self.assertEqual(backup['ledger']['decisions'], json.loads(original_ledger)['decisions'])
