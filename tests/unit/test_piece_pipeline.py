"""Exercise persistent identities, live matching, migration and complete model evidence."""
import copy
import json
import threading
from pathlib import Path
import unittest
from unittest.mock import patch

from jsonschema import validate

from dashboard import receipt_review, matching_review, piece_matching
from dashboard.piece_match_jobs import validate_result
from reconciliation import pieces
from reconciliation.duplicate_workflow import fingerprint
from tests.unit import test_receipt_matching as fixtures


class PiecePipelineTests(unittest.TestCase):
    def setUp(self):
        """Use isolated two-receipt evidence and three bank payments."""
        self.fixture = fixtures.ReceiptMatchingTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.review = self.fixture.review
        self.review.root = self.fixture.base

    def accept(self, values=None):
        """Submit exactly the current editable piece records."""
        view = receipt_review.snapshot(self.review)
        return receipt_review.accept_extraction(self.review, {'revision': view['revision'],
            'key': self.fixture.key, 'receipts': values if values is not None else view['units'][0]['receipts']})

    def decision(self, bank='B1', action='approve', allocations=None):
        """Prepare a current final-review request with an explicit human decision."""
        view = matching_review.snapshot(self.review)
        return {'binding': view['binding'], 'version': view['version'], 'bank_id': bank, 'action': action,
            'allocations': allocations or [], 'reviewer': 'Test', 'note': 'Checked separate receipts', 'acknowledged': True}

    def test_ids_survive_edits_reordering_and_new_pieces(self):
        """Editing and reordering never reassign another piece's identity."""
        view = self.accept()
        before = view['units'][0]['receipts']
        changed = copy.deepcopy(before[::-1])
        changed[0]['brief_description'] = 'Corrected delivery'
        after = self.accept(changed)['units'][0]['receipts']
        self.assertEqual([p['piece_id'] for p in after], [p['piece_id'] for p in before[::-1]])
        children = [{**after[0], 'piece_id': '', 'parent_piece_ids': [after[0]['piece_id']], 'total': '5'},
                    {**after[0], 'piece_id': '', 'parent_piece_ids': [after[0]['piece_id']], 'total': '10'}, after[1]]
        split = self.accept(children)['units'][0]['receipts']
        self.assertEqual(len({p['piece_id'] for p in split}), 3)
        self.assertNotIn(after[0]['piece_id'], [p['piece_id'] for p in split])
        with self.assertRaisesRegex(ValueError, 'Unknown or repeated'):
            self.accept([split[0], split[0]])

    def test_live_pieces_allocations_and_stale_changes(self):
        """Current pieces drive matching, and edits retain stale reservations until undo."""
        view = self.accept()
        ids = [p['piece_id'] for p in view['units'][0]['receipts']]
        piece_matching.activate(self.review)
        matching_review.decide(self.review, self.decision(allocations=[
            {'item_id': ids[0], 'amount': '45'}, {'item_id': ids[1], 'amount': '15'}]))
        self.assertEqual(matching_review.snapshot(self.review)['banks'][0]['support_status'], 'Supporting')
        with self.assertRaisesRegex(ValueError, 'available'):
            matching_review.decide(self.review, self.decision('B2', allocations=[{'item_id': ids[0], 'amount': '45'}]))
        edited = copy.deepcopy(view['units'][0]['receipts'])
        edited[0]['payee'] = 'Corrected merchant'
        self.accept(edited)
        data = matching_review.snapshot(self.review)
        self.assertTrue(data['banks'][0]['stale'])
        self.assertEqual(data['banks'][0]['support_status'], 'No supporting')
        self.assertIn('No supporting', matching_review.export_csv(self.review).decode())
        with self.assertRaisesRegex(ValueError, 'stale allocations'):
            matching_review.decide(self.review, self.decision('B2', allocations=[{'item_id': ids[0], 'amount': '45'}]))
        matching_review.decide(self.review, self.decision(action='undo'))
        matching_review.decide(self.review, self.decision('B2', allocations=[{'item_id': ids[0], 'amount': '45'}]))
        self.assertEqual(matching_review.snapshot(self.review)['banks'][1]['support_status'], 'Supporting')

    def test_historical_rm_displays_and_matches_as_myr_without_rewriting_evidence(self):
        """Normalize read-only projections and comparisons while preserving approval bindings."""
        self.accept()
        path = self.fixture.work / 'receipt-matches.json'
        saved = json.loads(path.read_text())
        first = saved['extractions'][self.fixture.key]['receipts'][0]
        first['currency'] = 'RM'
        key = first['piece_id']
        path.write_text(json.dumps(saved))
        before = path.read_bytes()
        piece_matching.activate(self.review)
        matching_review.decide(self.review, self.decision('B2', allocations=[{'item_id': key, 'amount': '45'}]))
        view = matching_review.snapshot(self.review)
        self.assertEqual(next(item for item in view['items'] if item['id'] == key)['currency'], 'MYR')
        bank = next(bank for bank in view['banks'] if bank['id'] == 'B2')
        self.assertFalse(bank['stale'])
        self.assertEqual(bank['support_status'], 'Supporting')
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_review_flag_does_not_warn_in_live_matching(self):
        """Ignore old model flags without rewriting saved evidence or approvals."""
        self.accept()
        path = self.fixture.work / 'receipt-matches.json'
        saved = json.loads(path.read_text())
        saved['extractions'][self.fixture.key]['receipts'][0]['needs_review'] = True
        path.write_text(json.dumps(saved))
        before = path.read_bytes()
        piece_matching.activate(self.review)
        self.assertFalse(any(item['boundary_unresolved'] for item in matching_review.snapshot(self.review)['items']))
        self.assertEqual(path.read_bytes(), before)

    def test_removed_piece_stays_visible_in_saved_approval(self):
        """Removing a piece cannot delete its saved allocation history or reservation."""
        view = self.accept()
        first, second = view['units'][0]['receipts']
        piece_matching.activate(self.review)
        matching_review.decide(self.review, self.decision('B2', allocations=[{'item_id': first['piece_id'], 'amount': '45'}]))
        self.accept([second])
        data = matching_review.snapshot(self.review)
        removed = next(i for i in data['items'] if i['id'] == first['piece_id'])
        self.assertTrue(removed['retired'])
        self.assertEqual(removed['used'], '45')
        self.assertTrue(data['banks'][1]['stale'])
        matching_review.decide(self.review, self.decision('B2', action='undo'))

    def test_unreviewed_piece_cannot_be_approved(self):
        """Model extraction alone never becomes accepted support."""
        piece_matching.activate(self.review)
        key = matching_review.snapshot(self.review)['items'][0]['id']
        with self.assertRaisesRegex(ValueError, 'Accept the piece'):
            matching_review.decide(self.review, self.decision('B2', allocations=[{'item_id': key, 'amount': '45'}]))

    def test_model_receives_whole_document_and_other_pieces(self):
        """A piece shortlist expands to complete parent context without inventing totals."""
        self.accept()
        banks, items, index, facts = piece_matching.current(self.review)
        keys = list(items)
        index['documents'][self.fixture.digest]['units'][0]['text'] = 'Document total 60; receipt A 45 and receipt B 15'
        payload, images, allowed = piece_matching.model_payload(banks, items, index, facts, {'B1': [keys[0]]}, ['B1'])
        document = payload['documents'][self.fixture.digest]
        self.assertEqual(len(document['pieces']), 2)
        self.assertNotIn('limitations', document)
        self.assertNotIn('document_type', document)
        for piece in document['pieces']:
            self.assertNotIn('limitations', piece)
            self.assertNotIn('document_type', piece)
            self.assertIn('piece_type', piece)
        self.assertIn('Document total 60', document['sources'][0]['text'])
        self.assertEqual(set(allowed['B1']), set(keys))
        self.assertEqual(images, [])
        result = {'decisions': [{'bank_id': 'B1', 'assessment': 'strong', 'allocations': [
            {'item_id': keys[0], 'amount': '45'}, {'item_id': keys[1], 'amount': '15'}], 'reason': 'Two receipts'}]}
        self.assertEqual(validate_result(result, ['B1'], allowed, banks, items), result['decisions'])
        result['decisions'][0]['allocations'][0]['amount'] = '60'
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            validate_result(result, ['B1'], allowed, banks, items)

    def test_canonical_schema_and_legacy_adapter(self):
        """The model emits only document context and pieces, preserving typed facts."""
        piece = pieces.canonical({**self.fixture.pieces[0], 'payee': 'Merchant',
            'references': [{'type': 'receipt', 'value': '000123'}]})
        result = {'readable': True, 'summary': 'Two receipts',
            'totals': [], 'pieces': [piece, pieces.canonical(self.fixture.pieces[1])]}
        for piece in result['pieces']:
            piece.pop('limitations', None)
        validate(result, pieces.EXTRACTION)
        adapted = pieces.legacy_result(result)
        self.assertEqual(adapted['receipts'][0]['references'][0]['value'], '000123')
        self.assertEqual(adapted['receipts'][0]['invoice_numbers'], [])
        self.assertNotIn('pieces', adapted)
        self.assertNotIn('money', pieces.EXTRACTION['properties'])
        self.assertEqual(len(adapted['receipts']), 2)

    def test_outdated_and_failed_proposals_remain_visible(self):
        """A stale run retains saved evidence and failures instead of becoming no-match rows."""
        self.accept()
        piece_matching.activate(self.review)
        banks, items, _, _ = piece_matching.current(self.review)
        key = next(iter(items))
        path = self.fixture.base / 'final-review/piece-suggestions.json'
        path.write_text(json.dumps({'binding': 'older-evidence', 'decisions': [
            {'bank_id': 'B1', 'assessment': 'strong', 'allocations': [{'item_id': key, 'amount': '45'}], 'reason': 'Saved evidence'},
            {'bank_id': 'B2', 'assessment': 'tentative', 'allocations': [], 'reason': 'Matching unresolved: currency'},
        ], 'errors': ['B2: currency'], 'total': 3}))
        view = matching_review.snapshot(self.review)
        self.assertEqual(view['banks'][0]['confidence']['level'], 'outdated')
        self.assertEqual(view['banks'][0]['suggestion']['allocations'][0]['item_id'], key)
        self.assertEqual(view['banks'][1]['confidence']['level'], 'failed')
        self.assertEqual(view['proposal_counts']['outdated'], 1)
        self.assertEqual(view['proposal_counts']['failed'], 1)
        from dashboard.piece_match_jobs import status
        self.assertEqual(status(self.review)['failed'], 1)
        self.assertEqual(status(self.review)['total'], 3)

    def test_historical_approval_migration_is_stale_and_preserved(self):
        """Cached decisions remain explicit history rather than becoming fresh piece approvals."""
        self.accept()
        banks, items, _, _ = piece_matching.current(self.review)
        item = next(iter(items.values()))
        old_item = {**item, 'id': 'D1'}
        old = {'version': 2, 'binding': 'old', 'history': [], 'decisions': {'B2': {
            'status': 'approved', 'allocations': [{'item_id': 'D1', 'amount': '45', 'document': item['document']}],
            'difference': '0', 'context_only': False}}}
        path = self.fixture.base / 'final-review/decisions.json'
        path.parent.mkdir()
        path.write_text(json.dumps(old))
        with patch.object(matching_review, 'context', return_value=(path, old, banks, {'D1': old_item}, {}, {})):
            piece_matching.activate(self.review)
        data = matching_review.snapshot(self.review)
        self.assertEqual(data['banks'][1]['review_status'], 'approved')
        self.assertTrue(data['banks'][1]['stale'])
        self.assertEqual(data['banks'][1]['support_status'], 'No supporting')
        self.assertTrue(list(path.parent.glob('pre-pieces-*.json')))
        with self.assertRaisesRegex(ValueError, 'stale allocations'):
            matching_review.decide(self.review, self.decision('B1', allocations=[{'item_id': item['id'], 'amount': '45'}]))

    def test_strict_model_schemas_require_every_property(self):
        """Both actual model contracts satisfy Codex strict structured-output rules."""
        def inspect(schema):
            """Check objects recursively, including typed references and array entries."""
            if schema.get('type') == 'object':
                self.assertEqual(set(schema['required']), set(schema['properties']))
                self.assertFalse(schema['additionalProperties'])
                for value in schema['properties'].values():
                    inspect(value)
            if schema.get('type') == 'array':
                inspect(schema['items'])
        inspect(pieces.EXTRACTION)
        inspect(pieces.ASSEMBLY)
        from dashboard.piece_match_jobs import SCHEMA
        inspect(SCHEMA)

    def test_payment_schedule_keeps_seven_rows_through_matching(self):
        """Equal amounts and shared project codes keep distinct recipient identities."""
        from dashboard.piece_match_jobs import SCHEMA
        amounts = ['150', '150', '90', '90', '750', '200', '600']
        rows = [pieces.canonical({**self.fixture.pieces[0], 'payee': f'Recipient {n}',
            'total': value, 'references': [{'type': 'other', 'value': 'shared-project'}],
            'dates': [{'type': 'other', 'value': '26/11/2025'}],
            'location': f'Sheet1 row {n + 9}'}) for n, value in enumerate(amounts)]
        result = {'readable': True, 'summary': 'Seven recipients',
            'totals': [{'label': 'Grand total', 'amount': '2030', 'currency': 'MYR', 'location': 'Sheet1 I16'}],
            'pieces': rows}
        for piece in result['pieces']:
            piece.pop('limitations', None)
        validate(result, pieces.EXTRACTION)
        self.fixture.state['units'][self.fixture.key] = pieces.legacy_result(result)
        self.fixture.save_state()
        banks, items, index, facts = piece_matching.current(self.review)
        keys = list(items)
        payload, _, allowed = piece_matching.model_payload(banks, items, index, facts, {'B1': [keys[0]]}, ['B1'])
        document = payload['documents'][self.fixture.digest]
        self.assertEqual(len(document['pieces']), 7)
        self.assertEqual(len(set(allowed['B1'])), 7)
        self.assertEqual(document['totals'], result['totals'])
        self.assertEqual([item['amount'] for item in items.values()], amounts)
        self.assertEqual([item['payee'] for item in items.values()], [r['payee'] for r in rows])
        banks['B1']['amount'] = '150'
        response = {'decisions': [{'bank_id': 'B1', 'assessment': 'strong',
            'allocations': [{'item_id': keys[0], 'amount': '150'}], 'reason': 'Identified recipient'}]}
        validate(response, SCHEMA)
        validate_result(response, ['B1'], allowed, banks, items)
        response['decisions'][0]['allocations'][0]['item_id'] = 'schedule-total'
        with self.assertRaisesRegex(ValueError, 'unknown'):
            validate_result(response, ['B1'], allowed, banks, items)

    def test_matching_worker_refills_slots_and_checkpoints_full_context(self):
        """A slow bank request cannot hold up a free worker or approve test proposals."""
        from dashboard import piece_match_jobs
        from reconciliation.review_settings import DEFAULTS
        self.accept()
        master = self.fixture.base / 'bank-output/master_statement.csv'
        master.write_text(master.read_text().replace('60.00', '45.00'))
        release, third = threading.Event(), threading.Event()
        calls = []

        class Reviewer:
            active_count = 0

            def __init__(self, work, **options):
                """Create only local checkpoint directories; never call a model."""
                work.mkdir(parents=True, exist_ok=True)

            def fork(self):
                """Share the deterministic fixture's request recorder."""
                return self

            def ask(self, prompt, schema, images):
                """Hold the first request while later requests complete."""
                data = json.loads(prompt.rsplit('\n', 1)[1])
                key = data['banks'][0]['id']
                calls.append(data)
                if key == 'B1':
                    release.wait(5)
                if key == 'B3':
                    third.set()
                return {'decisions': [{'bank_id': key, 'assessment': 'tentative', 'allocations': [], 'reason': 'Fixture'}]}

        config = {**DEFAULTS, 'codex_enabled': True, 'max_parallel': 2}
        with patch.object(piece_match_jobs, 'CodexReviewer', Reviewer), patch.object(piece_match_jobs, 'active_config', return_value=config):
            piece_match_jobs.start(self.review)
            try:
                self.assertTrue(third.wait(5), 'Free worker did not start the third bank request')
            finally:
                release.set()
                self.review.piece_match_thread.join(5)
        self.assertFalse(piece_match_jobs.status(self.review)['running'])
        self.assertEqual(piece_match_jobs.status(self.review)['error'], '')
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(len(next(iter(c['documents'].values()))['pieces']) == 2 for c in calls))
        self.assertTrue(all(not b['decision'] for b in matching_review.snapshot(self.review)['banks']))

    def test_verified_bank_import_survives_activation(self):
        """An existing verified bank branch remains usable after the cache is disconnected."""
        self.accept()
        banks, items, index, facts = piece_matching.current(self.review)
        master = self.fixture.base / 'bank-output/master_statement.csv'
        bank_hash = fingerprint(master)
        master.unlink()
        statement_hash = next(iter(banks.values()))['source_sha256']
        old = {'version': 0, 'decisions': {}, 'history': []}
        frozen = (None, old, banks, items, index, {'statement_hash': statement_hash, 'bank_hash': bank_hash})
        with patch.object(matching_review, 'frozen_context', return_value=frozen):
            piece_matching.activate(self.review)
        data = matching_review.snapshot(self.review)
        self.assertEqual(len(data['banks']), 3)
        self.assertFalse(any(b['stale'] for b in data['banks']))
        self.assertTrue((self.fixture.base / 'final-review/bank-import.json').exists())

    def test_canonical_model_output_reaches_saved_review_pieces(self):
        """Actual extraction orchestration requests the new contract and retains its facts."""
        from tests.unit import test_vision_workflow as fixtures
        from reconciliation import vision_workflow
        fixture = fixtures.WorkflowTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        index, state = fixture.prepared()
        supplied = {'readable': True, 'summary': 'Two receipts',
            'totals': [], 'pieces': [pieces.canonical(p) for p in self.fixture.pieces]}
        for piece in supplied['pieces']:
            piece.pop('limitations', None)
        supplied['pieces'][0]['payee'] = 'Merchant A'
        calls = []

        class Reviewer:
            model = 'fixture'

            def ask(self, prompt, schema, images=()):
                """Return schema-validated canonical output without spending model tokens."""
                self_schema = pieces.EXTRACTION
                if schema != self_schema:
                    raise AssertionError('Legacy schema sent to the model')
                validate(supplied, schema)
                calls.append(schema)
                return copy.deepcopy(supplied)

        vision_workflow.run(fixture.work, index, state, Reviewer(), extraction_only=True)
        self.assertEqual(len(calls), 2)
        for result in state['units'].values():
            self.assertEqual(result['receipts'][0]['payee'], 'Merchant A')
            self.assertEqual(len(result['receipts']), 2)
            self.assertNotIn('pieces', result)
