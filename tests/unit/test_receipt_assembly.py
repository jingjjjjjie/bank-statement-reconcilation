"""Verify cross-page boundaries, coverage, and stale approval protection."""
import copy
import json
import unittest

import pymupdf

from reconciliation import vision_workflow as workflow
from reconciliation.receipt_assembly import ASSEMBLY, current_assembly, input_revision, validate_assembly
from reconciliation.duplicate_workflow import fingerprint
from tests.unit import test_vision_workflow as workflow_fixtures
from tests.unit.test_vision_workflow import FakeReviewer
from tests.unit import test_receipt_matching as receipt_fixtures


def piece(units, total="45.00"):
    """Build a receipt spanning named source units with one printed total."""
    return {"location": "pages " + ", ".join(map(str, units)), "document_type": "receipt",
            "invoice_numbers": ["INV-1"], "brief_description": "Supplies", "total": total,
            "currency": "MYR", "limitations": [], "source_units": units, "needs_review": False}


class AssemblyWorkflowTests(unittest.TestCase):
    setUp = workflow_fixtures.WorkflowTests.setUp
    prepared = workflow_fixtures.WorkflowTests.prepared

    def test_pages_are_assembled_once_with_original_images(self):
        """A continuation does not double a total, and resume skips the saved assembly."""
        with pymupdf.open() as pdf:
            for text in ("INV-1 supplies continued on next page", "INV-1 final total MYR 45.00"):
                pdf.new_page().insert_text((40, 40), text)
            pdf.save(self.root / "invoice.pdf")
        index, state = self.prepared()
        calls = []

        class Reviewer(FakeReviewer):
            def ask(self, prompt, schema, images=()):
                """Return one receipt across two source pages without live calls."""
                if schema == ASSEMBLY:
                    calls.append(list(images))
                    return {"receipts": [piece([1, 2])], "reviewed_units": [1, 2], "limitations": []}
                return super().ask(prompt, schema, images)

        workflow.run(self.work, index, state, Reviewer())
        workflow.run(self.work, index, state, Reviewer())
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 2)
        assembled = next(iter(state["assemblies"].values()))
        self.assertEqual(assembled["receipts"][0]["total"], "45.00")
        document = next(doc for doc in index["documents"].values() if len(doc["units"]) == 2)
        state["units"][document["id"] + ":0"]["details"] = "Changed extraction"
        self.assertIsNone(current_assembly(document, state))

    def test_missing_or_unknown_pages_are_rejected(self):
        """Coverage cannot silently omit a page or reference nonexistent evidence."""
        value = {"receipts": [piece([1, 2])], "reviewed_units": [1], "limitations": []}
        with self.assertRaises(ValueError):
            validate_assembly(value, 2)
        value["reviewed_units"] = [1, 2]
        value["receipts"][0]["source_units"] = [3]
        with self.assertRaises(ValueError):
            validate_assembly(value, 2)
        value["receipts"] = [piece([1, 2]), piece([2], "15.00")]
        validate_assembly(value, 2)


class AssemblyApprovalTests(unittest.TestCase):
    setUp = receipt_fixtures.ReceiptMatchingTests.setUp
    save_state = receipt_fixtures.ReceiptMatchingTests.save_state
    view = receipt_fixtures.ReceiptMatchingTests.view
    accept_pieces = receipt_fixtures.ReceiptMatchingTests.accept_pieces

    def test_assembled_receipts_replace_page_pieces_and_require_resolved_boundaries(self):
        """Only document receipts become allocatable, and page refresh invalidates approval."""
        document = self.index["documents"][self.digest]
        document["id"] = self.digest
        document["units"].append({"label": "page 2", "image": None})
        (self.work / "index.json").write_text(json.dumps(self.index))
        self.state["index_sha256"] = fingerprint(self.work / "index.json")
        self.state["units"][self.digest + ":1"] = copy.deepcopy(self.state["units"][self.key])
        self.key = self.digest + ":-1"
        self.save_state()
        self.assertTrue(self.view()["units"][0]["assembly_pending"])
        with self.assertRaisesRegex(ValueError, "finish receipt assembly"):
            self.accept_pieces([piece([1, 2])])
        self.state["assemblies"] = {self.digest: {"receipts": [piece([1, 2])],
            "reviewed_units": [1, 2], "limitations": [], "input_revision": input_revision(document, self.state)}}
        self.save_state()
        flagged = {**piece([1, 2]), "needs_review": True}
        with self.assertRaisesRegex(ValueError, "Resolve flagged"):
            self.accept_pieces([flagged])
        view = self.accept_pieces([piece([1, 2])])
        self.assertEqual(len(view["receipts"]), 1)
        self.assertTrue(view["receipts"][0]["accepted"])
        self.state["units"][self.digest + ":1"]["details"] = "new result"
        self.save_state()
        self.assertFalse(self.view()["units"][0]["accepted"])


if __name__ == "__main__":
    unittest.main()
