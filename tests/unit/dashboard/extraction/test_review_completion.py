"""Verify header completion follows saved document review outcomes."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dashboard.services.review import workflow_guide


class ReviewCompletionTests(unittest.TestCase):
    def test_review_completion_states(self):
        """Accept/discard complete review; pending, failed, empty and stale work do not."""
        review = SimpleNamespace(manifest={}, workflow_checks=lambda: (False, False, False))
        for statuses, complete in [
            ([], False), (["Complete"], True), (["Complete", "Trash"], True),
            (["Needs review"], False), (["Complete", "Queued"], False),
            (["Complete", "Needs attention"], False), (["Processing"], False),
        ]:
            with self.subTest(statuses=statuses):
                rows = [{"status": status, "approved_duplicate": False} for status in statuses]
                rows.append({"status": "Needs review", "approved_duplicate": True})
                with patch("dashboard.services.extraction.document_status.snapshot", return_value={"documents": rows}):
                    step = next(step for step in workflow_guide(review)["steps"] if step["href"] == "/extraction-review")
                self.assertEqual(step["checked"], complete)

    def test_no_workspace_or_invalid_evidence(self):
        """Missing workspaces or invalid source bindings never show a review tick."""
        review = SimpleNamespace(manifest={}, workflow_checks=lambda: (False, False, False))
        with patch("dashboard.services.extraction.document_status.snapshot", side_effect=ValueError("Stale source")):
            for current in (None, review):
                step = next(step for step in workflow_guide(current)["steps"] if step["href"] == "/extraction-review")
                self.assertFalse(step["checked"])
