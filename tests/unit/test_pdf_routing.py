"""Exercise risky PDF detection, evidence failures and cancellation propagation."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from reconciliation.codex_reviewer import BudgetReached, EXTRACTION
from reconciliation.document_reader import extract
from reconciliation.pdf_routing import extract_unit, inspect_page
from reconciliation.review_settings import DEFAULTS
from tests.unit.test_vision_workflow import FakeReviewer
from tests.unit import test_vision_workflow as workflow_fixtures
from reconciliation import vision_workflow
from reconciliation.duplicate_workflow import organize


class PdfRoutingTests(unittest.TestCase):
    def setUp(self):
        """Build a native PDF and a fully source-backed receipt response."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        path = self.root / "invoice.pdf"
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((30, 30), "Invoice TEST-1 Supplier Example Corporation Total MYR 1.00")
            pdf.save(path)
        self.unit = extract(path, self.root / "assets", {**DEFAULTS, "pdf_mode": "compare"})[0]
        self.result = FakeReviewer().ask("", EXTRACTION)
        self.result['receipts'] = [{"location": "page 1", "document_type": "receipt", "invoice_numbers": ["TEST-1"],
            "brief_description": "Example", "total": "1.00", "currency": "MYR", "limitations": []}]
        self.calls = []

    def ask(self, prompt, schema, images=(), stage=None):
        """Capture whether each request sees original pixels."""
        self.calls.append(stage)
        return copy.deepcopy(self.result)

    def run_route(self, selected="compare", ask=None, approved=None):
        """Run the routing layer with development enabled and inspect its audit."""
        with patch('reconciliation.pdf_routing.mode', return_value={"enabled": True}):
            result = extract_unit(self.unit, ask or self.ask, selected, self.root / 'audit.json', approved or set())
        return result, json.loads((self.root / 'audit.json').read_text())

    def test_compare_runs_both_and_retains_evidence(self):
        """Clean native text gets independently compared without automatic acceptance."""
        result, audit = self.run_route()
        self.assertEqual(self.calls, ['pdf_text', 'pdf_vision'])
        self.assertTrue(audit['critical_fields_agree'])
        self.assertTrue(audit['evidence'][0]['matches'])

    def test_unknown_layout_skips_text(self):
        """Unapproved geometry never silently bypasses vision."""
        _, audit = self.run_route('hybrid')
        self.assertEqual(self.calls, ['pdf_vision'])
        self.assertIn('layout_not_validated', audit['reasons'])

    def test_validated_layout_can_use_text_without_vision(self):
        """Only approved, evidenced, non-audit pages take the cheaper route."""
        while int(hashlib.sha256(self.unit['text'].encode()).hexdigest()[:8], 16) % 10 == 0:
            self.unit['text'] += '\n'
        _, audit = self.run_route('hybrid', approved={self.unit['pdf_probe']['layout']})
        self.assertEqual(self.calls, ['pdf_text'])
        self.assertEqual(audit['route'], 'text')

    def test_new_extraction_without_document_type_can_use_text(self):
        """Canonical piece type keeps approved text routing usable after field removal."""
        from reconciliation.pieces import canonical, legacy_result
        piece = canonical(self.result['receipts'][0])
        piece.pop('limitations')
        self.result = legacy_result({'readable': True, 'summary': 'Receipt', 'totals': [], 'pieces': [piece]})
        while int(hashlib.sha256(self.unit['text'].encode()).hexdigest()[:8], 16) % 10 == 0:
            self.unit['text'] += '\n'
        _, audit = self.run_route('hybrid', approved={self.unit['pdf_probe']['layout']})
        self.assertEqual(self.calls, ['pdf_text'])
        self.assertEqual(audit['route'], 'text')

    def test_invalid_response_uses_original_image(self):
        """Malformed text output is recorded and replaced by full-page vision."""
        def ask(prompt, schema, images=(), stage=None):
            """Return an invalid text object and a valid visual extraction."""
            return self.ask(prompt, schema, images, stage) if images else {"receipts": ["invalid"]}
        _, audit = self.run_route(ask=ask)
        self.assertEqual(audit['route'], 'vision')
        self.assertTrue(any(r.startswith('text_attempt_failed:') for r in audit['reasons']))

    def test_workflow_runs_comparison_with_existing_budget_wrapper(self):
        """Prepared PDF units reach both routes and retain resumable workflow state."""
        fixture = workflow_fixtures.WorkflowTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((30, 30), 'Invoice TEST-1 Supplier Example Corporation Total MYR 1.00')
            pdf.save(fixture.root / 'native.pdf')
        config = fixture.base / 'config.json'
        config.write_text(json.dumps({**DEFAULTS, 'pdf_mode': 'compare'}))
        organize(fixture.root, fixture.manifest)
        with patch('reconciliation.development_cache.mode', return_value={'enabled': True}), patch('reconciliation.pdf_routing.mode', return_value={'enabled': True}):
            vision_workflow.prepare(fixture.manifest, fixture.work, config)
            index, state = vision_workflow.load(fixture.work)
            vision_workflow.run(fixture.work, index, state, FakeReviewer())
        audits = list((fixture.work / 'pdf-routing').glob('*.json'))
        self.assertEqual(len(audits), 1)
        self.assertEqual(json.loads(audits[0].read_text())['status'], 'finished')
        self.assertEqual(len(state['units']), 3)

    def test_unsupported_amount_falls_back_and_flags_disagreement(self):
        """A plausible invented amount fails exact source evidence checks."""
        def ask(prompt, schema, images=(), stage=None):
            """Invent a text-only amount while keeping vision unchanged."""
            value = self.ask(prompt, schema, images, stage)
            if not images:
                value['receipts'][0]['total'] = '99.00'
            return value
        result, audit = self.run_route('hybrid', ask, {self.unit['pdf_probe']['layout']})
        self.assertEqual(self.calls, ['pdf_text', 'pdf_vision'])
        self.assertIn('unsupported_total', audit['reasons'])
        self.assertTrue(result['review_warnings'])
        self.assertFalse(result['limitations'])

    def test_old_system_disagreement_remains_visible(self):
        """Only the known system warning survives legacy storage in the removed field."""
        from reconciliation.pdf_routing import DISAGREEMENT_WARNING, review_warnings
        saved = {'limitations': ['Old model prose', DISAGREEMENT_WARNING]}
        before = copy.deepcopy(saved)
        self.assertEqual(review_warnings(saved), [DISAGREEMENT_WARNING])
        self.assertEqual(saved, before)

    def test_budget_stop_does_not_launch_fallback(self):
        """Stop signals remain unresolved rather than spending another call."""
        def stop(*args, **kwargs):
            """Simulate exhausted user request budget."""
            raise BudgetReached('stop')
        with self.assertRaises(BudgetReached):
            self.run_route(ask=stop)
        self.assertEqual(json.loads((self.root / 'audit.json').read_text())['status'], 'unresolved')

    def test_hidden_text_is_rejected(self):
        """Selectable invisible OCR cannot qualify as safe native text."""
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((30, 30), 'Hidden OCR invoice total MYR 1.00', render_mode=3)
            self.assertIn('hidden_or_translucent_text', inspect_page(page)['reasons'])

    def test_switch_off_blocks_experiment(self):
        """Disabling development prevents both experimental routes."""
        with patch('reconciliation.pdf_routing.mode', return_value={"enabled": False}):
            with self.assertRaisesRegex(ValueError, 'development mode'):
                extract_unit(self.unit, self.ask, 'compare', self.root / 'audit.json')
        self.assertEqual(self.calls, [])
