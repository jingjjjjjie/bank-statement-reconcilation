"""Verify PDF batching, complete evidence, resume and atomic failure without live models."""
import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

import pymupdf
from jsonschema import validate

from reconciliation import pieces, vision_workflow as workflow
from reconciliation.duplicate_workflow import organize
from reconciliation.pdf_document import whole_request
from reconciliation.receipt_assembly import current_assembly
from reconciliation.review_settings import DEFAULTS


class Reviewer:
    """Return validated source-bound pieces while counting actual workflow requests."""
    model = 'fixture'

    def __init__(self, pages):
        """Describe one invoice spanning every supplied page."""
        self.pages, self.calls, self.invalid, self.fail = pages, [], False, False

    def ask(self, prompt, schema, images=()):
        """Capture stage and evidence and simulate canonical model output."""
        self.calls.append({'stage': self.stage, 'prompt': prompt, 'images': list(images)})
        if self.fail:
            raise ValueError('Model request failed')
        piece = {'piece_type': 'invoice', 'payee': 'Supplier', 'description': 'Supplies',
            'references': [{'type': 'invoice', 'value': 'INV-001'}], 'dates': [],
            'amount': '45.00', 'currency': 'RM', 'amount_basis': 'invoice total',
            'source_locations': ['pages 1 through ' + str(self.pages)]}
        result = {'readable': True, 'summary': 'Invoice', 'totals': [
            {'label': 'Invoice total', 'amount': '45.00', 'currency': 'RM', 'location': 'last page'}],
            'pieces': [piece]}
        if schema == pieces.ASSEMBLY:
            result['reviewed_units'] = list(range(1, self.pages + 1))
            piece.update(source_units=list(range(1, self.pages + 1)))
            if self.invalid:
                result['reviewed_units'].pop()
        validate(result, schema)
        return result


class PdfDocumentTests(unittest.TestCase):
    def prepare_pdf(self, pages, limit=5):
        """Prepare an isolated PDF and explicit config without customer inputs."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        root = base / 'documents'
        root.mkdir()
        with pymupdf.open() as pdf:
            for page in range(1, pages + 1):
                pdf.new_page().insert_text((40, 40), f'INV-001 page {page} of {pages} Supplies total MYR 45.00')
            pdf.save(root / 'invoice.pdf')
        config = base / 'config.json'
        config.write_text(json.dumps({**DEFAULTS, 'model': '', 'pdf_whole_document_max_pages': limit}))
        manifest, work = base / 'manifest.json', base / 'review'
        organize(root, manifest)
        workflow.prepare(manifest, work, config)
        index, state = workflow.load(work)
        return work, index, state

    def test_model_currency_fields_allow_other_currencies(self):
        """The schemas accept other currencies; normalization belongs to Python."""
        for schema in (pieces.EXTRACTION, pieces.ASSEMBLY):
            for field in ('pieces', 'totals'):
                currency_schema = schema['properties'][field]['items']['properties']['currency']
                for value in ('', 'MYR', 'RM', 'USD', 'SGD', 'EUR'):
                    validate(value, currency_schema)

    def test_threshold_and_override_count_calls(self):
        """Five pages use one call, six use seven, and the configured limit changes routing."""
        for pages, limit, expected in ((1, 5, 1), (5, 5, 1), (6, 5, 7), (6, 6, 1), (2, 1, 3)):
            with self.subTest(pages=pages, limit=limit):
                work, index, state = self.prepare_pdf(pages, limit)
                reviewer = Reviewer(pages)
                workflow.run(work, index, state, reviewer, extraction_only=True)
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
                workflow.run(work, index, state, reviewer, extraction_only=True)
                self.assertEqual(len(reviewer.calls), expected)

    def test_regeneration_is_one_call_even_with_worker_refill(self):
        """Queued regeneration does not dispatch extra page or assembly calls after whole-PDF completion."""
        work, index, state = self.prepare_pdf(3)
        reviewer = Reviewer(3)
        workflow.run(work, index, state, reviewer, extraction_only=True)
        digest = next(iter(index['documents']))
        workflow.run(work, index, state, reviewer, extraction_only=True,
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
                    workflow.run(work, index, state, reviewer, extraction_only=True)
                self.assertEqual(state['units'], {})
                self.assertFalse(state.get('assemblies'))
                self.assertEqual(workflow.load(work)[1]['units'], {})
                reviewer.fail = reviewer.invalid = False
                workflow.run(work, index, state, reviewer, extraction_only=True)
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
        workflow.run(work, index, state, reviewer, extraction_only=True)
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
