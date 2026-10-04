"""Verify header completion follows saved document review outcomes."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dashboard.services.review import workflow_guide


class ReviewCompletionTests(unittest.TestCase):
    def test_review_pages_require_their_extracted_inputs(self):
        """Partial extraction permits source review; matching also needs a verified bank."""
        for documents, bank, extraction_ready, matching_ready in [
            ([], False, False, False),
            ([True, False], False, True, False),
            ([True], False, True, False),
            ([True, False], True, True, False),
            ([True], True, True, True),
        ]:
            review = SimpleNamespace(manifest={}, workflow_checks=lambda: (False, False, bank))
            rows = [{'extracted': value, 'status': 'Needs review', 'approved_duplicate': False} for value in documents]
            with (
                self.subTest(documents=documents, bank=bank),
                patch('dashboard.services.extraction.document_status.snapshot', return_value={'documents': rows}),
            ):
                steps = {step['href']: step for step in workflow_guide(review)['steps']}
                self.assertEqual(steps['/extraction-review']['available'], extraction_ready)
                self.assertEqual(steps['/matching']['available'], matching_ready)
                self.assertTrue(steps['/final-report']['available'])

    def test_final_review_tick_requires_current_decisions_for_both_confidences(self):
        """High/low proposals need saved decisions; undo and stale evidence remove the tick."""
        review = SimpleNamespace(manifest={}, manifest_path='fixture', workflow_checks=lambda: (False, False, False))
        for status, stale, expected in [
            ('pending', False, False),
            ('approved', False, True),
            ('denied', False, True),
            ('approved', True, False),
        ]:
            rows = [
                {'confidence': {'level': 'high'}, 'review_status': 'approved', 'stale': False},
                {'confidence': {'level': 'low'}, 'review_status': status, 'stale': stale},
                {'confidence': {'level': 'none'}, 'review_status': 'pending', 'stale': False},
            ]
            with (
                self.subTest(status=status, stale=stale),
                patch('dashboard.services.extraction.document_status.snapshot', return_value={'documents': []}),
                patch('dashboard.services.matching.final_review.snapshot', return_value={'banks': rows}),
            ):
                step = next(step for step in workflow_guide(review)['steps'] if step['href'] == '/matching')
                self.assertEqual(step['checked'], expected)

    def test_documents_tick_follows_extraction_not_human_review(self):
        """Finished extraction ticks Documents even while human reviews remain pending."""
        review = SimpleNamespace(manifest={'Mode': 'exact_report'}, workflow_checks=lambda: (True, False, False))
        for extracted, expected in [([], False), ([True], True), ([True, False], False)]:
            with self.subTest(extracted=extracted):
                rows = [
                    {'status': 'Needs review', 'extracted': value, 'approved_duplicate': False} for value in extracted
                ]
                rows.append({'status': 'Queued', 'extracted': False, 'approved_duplicate': True})
                with patch('dashboard.services.extraction.document_status.snapshot', return_value={'documents': rows}):
                    steps = {step['href']: step for step in workflow_guide(review)['steps']}
                self.assertEqual(steps['/documents']['checked'], expected)
                self.assertFalse(steps['/extraction-review']['checked'])

    def test_review_completion_states(self):
        """Accept/discard complete review; pending, failed, empty and stale work do not."""
        review = SimpleNamespace(manifest={}, workflow_checks=lambda: (False, False, False))
        for statuses, complete in [
            ([], False),
            (["Complete"], True),
            (["Complete", "Trash"], True),
            (["Needs review"], False),
            (["Complete", "Queued"], False),
            (["Complete", "Needs attention"], False),
            (["Processing"], False),
        ]:
            with self.subTest(statuses=statuses):
                rows = [{"status": status, "approved_duplicate": False} for status in statuses]
                rows.append({"status": "Needs review", "approved_duplicate": True})
                with patch("dashboard.services.extraction.document_status.snapshot", return_value={"documents": rows}):
                    step = next(
                        step for step in workflow_guide(review)["steps"] if step["href"] == "/extraction-review"
                    )
                self.assertEqual(step["checked"], complete)

    def test_no_workspace_or_invalid_evidence(self):
        """Missing workspaces or invalid source bindings never show a review tick."""
        review = SimpleNamespace(manifest={}, workflow_checks=lambda: (False, False, False))
        with patch("dashboard.services.extraction.document_status.snapshot", side_effect=ValueError("Stale source")):
            for current in (None, review):
                step = next(step for step in workflow_guide(current)["steps"] if step["href"] == "/extraction-review")
                self.assertFalse(step["checked"])
