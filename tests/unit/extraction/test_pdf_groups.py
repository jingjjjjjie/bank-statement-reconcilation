"""Verify PDF batching, complete evidence, resume and atomic failure without live models."""
import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

import pymupdf
from jsonschema import validate

from reconciliation.core.settings import DEFAULTS
from reconciliation.extraction import pieces, workflow
from reconciliation.extraction.assembly import current_assembly
from reconciliation.extraction.pdf_groups import chunk_requests, whole_request
from reconciliation.intake.duplicates import organize
from tests.fixtures.pdf_groups import PdfGroupsFixture, Reviewer


class PdfDocumentTests(PdfGroupsFixture):

    def test_model_currency_fields_allow_other_currencies(self):
        """The schemas accept other currencies; normalization belongs to Python."""
        for schema in (pieces.EXTRACTION, pieces.ASSEMBLY):
            for field in ('pieces', 'totals'):
                currency_schema = schema['properties'][field]['items']['properties']['currency']
                for value in ('', 'MYR', 'RM', 'USD', 'SGD', 'EUR'):
                    validate(value, currency_schema)

    def test_threshold_and_override_count_calls(self):
        """Short PDFs use one call; longer PDFs use bounded groups plus final assembly."""
        for pages, limit, expected in ((1, 5, 1), (5, 5, 1), (6, 5, 3), (6, 6, 1), (2, 1, 3)):
            with self.subTest(pages=pages, limit=limit):
                work, index, state = self.prepare_pdf(pages, limit)
                reviewer = Reviewer(pages)
                workflow.run(work, index, state, reviewer)
                self.assertEqual(len(reviewer.calls), expected)
                if pages > 1 and expected == 1:
                    self.assertEqual(reviewer.calls[0]['stage'], 'pdf_document')
                    self.assertEqual(len(reviewer.calls[0]['images']), pages)
                    document = next(iter(index['documents'].values()))
                    assembled = current_assembly(document, state)
                    self.assertEqual(assembled['reviewed_units'], list(range(1, pages + 1)))
                    self.assertEqual(assembled['receipts'][0]['source_units'], list(range(1, pages + 1)))
                    self.assertEqual(assembled['extraction_mode'], 'whole_pdf')
                    self.assertEqual(assembled['receipts'][0]['currency'], 'MYR')
                    self.assertEqual(assembled['totals'][0]['currency'], 'MYR')
                    self.assertEqual(sum(len(v['receipts']) for v in state['units'].values()), 1)
                    self.assertEqual(sum(len(v['totals']) for v in state['units'].values()), 1)
                    with (work / 'supporting-inventory.csv').open(encoding='utf-8-sig') as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual(sum(len(json.loads(row['receipts'])) for row in rows), 1)
                self.assertEqual(workflow.gate(index, state), [])
                workflow.run(work, index, state, reviewer)
                self.assertEqual(len(reviewer.calls), expected)

    def test_regeneration_is_one_call_even_with_worker_refill(self):
        """Queued regeneration does not dispatch extra page or assembly calls after whole-PDF completion."""
        work, index, state = self.prepare_pdf(3)
        reviewer = Reviewer(3)
        workflow.run(work, index, state, reviewer)
        digest = next(iter(index['documents']))
        workflow.run(work, index, state, reviewer,
                     regeneration={digest: 'fresh'}, queued_regenerations=lambda: {digest: 'fresh'})
        self.assertEqual(len(reviewer.calls), 2)
        self.assertIn('Regeneration request: fresh', reviewer.calls[-1]['prompt'])

    def test_failed_or_missing_page_result_does_not_publish_partial_state(self):
        """Model failures and omitted coverage stay unresolved and retry the whole request."""
        for fail in (True, False):
            with self.subTest(failure=fail):
                work, index, state = self.prepare_pdf(3)
                reviewer = Reviewer(3)
                reviewer.fail, reviewer.invalid = fail, not fail
                with self.assertRaises(ValueError):
                    workflow.run(work, index, state, reviewer)
                self.assertEqual(state['units'], {})
                self.assertFalse(state.get('assemblies'))
                self.assertEqual(workflow.load(work)[1]['units'], {})
                reviewer.fail = reviewer.invalid = False
                workflow.run(work, index, state, reviewer)
                self.assertEqual(len(reviewer.calls), 2)

    def test_partial_page_run_resumes_without_reextracting_completed_page(self):
        """Changing the threshold preserves existing successful page checkpoints."""
        work, index, state = self.prepare_pdf(3)
        digest = next(iter(index['documents']))
        reviewer = Reviewer(3)
        reviewer.stage = 'pdf'
        state['units'][digest + ':0'] = pieces.legacy_result(reviewer.ask('', pieces.EXTRACTION))
        before = copy.deepcopy(state['units'][digest + ':0'])
        reviewer.calls.clear()
        workflow.run(work, index, state, reviewer)
        self.assertEqual(len(reviewer.calls), 3)
        self.assertEqual(state['units'][digest + ':0'], before)
        self.assertNotIn('pdf_document', [call['stage'] for call in reviewer.calls])

    def test_experimental_blocked_and_oversized_inputs_keep_existing_route(self):
        """Grouping cannot bypass page audits, blocked evidence or bounded requests."""
        work, index, state = self.prepare_pdf(2)
        document = next(iter(index['documents'].values()))
        config = {**DEFAULTS, 'pdf_mode': 'compare'}
        self.assertIsNone(whole_request(document, config, state))
        config['pdf_mode'] = 'vision'
        document['units'][0]['blocked'] = 'unreadable source'
        self.assertIsNone(whole_request(document, config, state))
        document['units'][0]['blocked'] = ''
        document['units'][0]['text'] = 'x' * 100001
        self.assertIsNone(whole_request(document, config, state))

    def test_actual_pages_not_text_chunks_control_threshold(self):
        """Several text units on one page do not count as extra PDF pages."""
        work, index, state = self.prepare_pdf(2, 2)
        document = next(iter(index['documents'].values()))
        document['units'].insert(1, {**document['units'][0], 'label': 'page 1 / part 2', 'image': None})
        request = whole_request(document, {**DEFAULTS, 'pdf_whole_document_max_pages': 2}, state)
        self.assertIsNotNone(request)
        self.assertIn('"source_unit": 3', request[0])

    def test_thirteen_pages_use_three_groups_and_one_complete_assembly(self):
        """Retain global page IDs and revisit all originals for cross-group continuations."""
        work, index, state = self.prepare_pdf(13)
        reviewer = Reviewer(13)
        workflow.run(work, index, state, reviewer)
        self.assertEqual([len(call['images']) for call in reviewer.calls], [5, 5, 3, 13])
        self.assertEqual([call['stage'] for call in reviewer.calls], ['pdf_chunk'] * 3 + ['pdf'])
        payloads = [json.loads(call['prompt'].splitlines()[-1]) for call in reviewer.calls]
        self.assertEqual([[u['source_unit'] for u in payload] for payload in payloads[:3]],
                         [list(range(1, 6)), list(range(6, 11)), list(range(11, 14))])
        self.assertEqual(payloads[3][5]['extraction']['receipts'][0]['source_units'], list(range(6, 11)))
        document = next(iter(index['documents'].values()))
        assembly = current_assembly(document, state)
        self.assertEqual(len(assembly['receipts']), 1)
        self.assertEqual(assembly['receipts'][0]['source_units'], list(range(1, 14)))
        self.assertEqual(len(state['units']), 13)
        self.assertEqual(workflow.gate(index, state), [])
        workflow.run(work, index, state, reviewer)
        self.assertEqual(len(reviewer.calls), 4)
        workflow.run(work, index, state, reviewer,
                     regeneration={document['id']: 'fresh'}, queued_regenerations=lambda: {document['id']: 'fresh'})
        self.assertEqual(len(reviewer.calls), 8)

    def test_failed_group_resumes_without_repeating_saved_pages(self):
        """Publish no partial group on failure and preserve the first successful group."""
        work, index, state = self.prepare_pdf(13)
        reviewer = Reviewer(13)
        reviewer.fail_at = 2
        with self.assertRaisesRegex(ValueError, 'Model request failed'):
            workflow.run(work, index, state, reviewer)
        self.assertEqual(len(state['units']), 5)
        self.assertFalse(state.get('assemblies'))
        saved = copy.deepcopy(state['units'])
        index, state = workflow.load(work)
        reviewer.fail_at = None
        workflow.run(work, index, state, reviewer)
        self.assertEqual([len(call['images']) for call in reviewer.calls], [5, 5, 5, 3, 13])
        self.assertTrue(all(state['units'][key] == value for key, value in saved.items()))

    def test_group_cannot_renumber_original_pages(self):
        """Pages six through ten cannot be returned as pages one through five."""
        work, index, state = self.prepare_pdf(6)
        reviewer = Reviewer(6)
        reviewer.renumber = True
        with self.assertRaisesRegex(ValueError, 'did not review every source unit'):
            workflow.run(work, index, state, reviewer)
        self.assertEqual(len(state['units']), 5)
        self.assertFalse(state.get('assemblies'))

    def test_parallel_groups_finish_before_assembly_and_resume_assembly_failure(self):
        """Parallel results retain page identity; a final failure retries only assembly."""
        work, index, state = self.prepare_pdf(13)
        reviewer = Reviewer(13)

        def fork():
            """Share captured calls but isolate the stage on each simulated worker."""
            child = Reviewer(13)
            child.calls = reviewer.calls
            child.fail_at = 4
            return child

        reviewer.fork = fork
        with self.assertRaisesRegex(ValueError, 'Model request failed'):
            workflow.run(work, index, state, reviewer)
        self.assertEqual(len(state['units']), 13)
        self.assertFalse(state.get('assemblies'))
        self.assertEqual(reviewer.calls[-1]['stage'], 'pdf')
        del reviewer.fork
        workflow.run(work, index, state, reviewer)
        self.assertEqual(len(reviewer.calls), 5)
        self.assertEqual(len(reviewer.calls[-1]['images']), 13)

    def test_chunk_routing_respects_limits_and_saved_parts(self):
        """Group physical pages without skipping size checks or overwriting partial reads."""
        _, index, state = self.prepare_pdf(6)
        document = next(iter(index['documents'].values()))
        document['units'].insert(1, {**document['units'][0], 'label': 'page 1 / part 2', 'image': None})
        state['units'][document['id'] + ':0'] = {'saved': True}
        groups = list(chunk_requests(document, DEFAULTS, state))
        self.assertEqual([group[0] for group in groups], [(2, 3, 4, 5, 6), (7,)])
        self.assertEqual(list(chunk_requests(document, {**DEFAULTS, 'pdf_mode': 'compare'}, state)), [])
        document['units'][1]['text'] = 'x' * 100001
        self.assertEqual([group[0] for group in chunk_requests(document, DEFAULTS, state)], [(7,)])
