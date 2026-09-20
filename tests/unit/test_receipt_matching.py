"""Exercise multiple receipts per image and audited bank allocation decisions."""
import csv
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from dashboard import receipt_review
from reconciliation.duplicate_workflow import fingerprint


class ReceiptMatchingTests(unittest.TestCase):
    def setUp(self):
        """Create two pieces in one source image and three independent bank entries."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.review = SimpleNamespace(manifest_path=self.base / "manifest.json")
        self.work = self.base / "review"
        self.work.mkdir()
        self.source = self.base / "photo.png"
        self.source.write_bytes(b"two separate receipt images")
        self.digest = fingerprint(self.source)
        self.key = self.digest + ":0"
        self.pieces = [{"location": location, "document_type": "receipt", "invoice_numbers": [],
                        "brief_description": description, "total": total, "currency": "MYR", "limitations": []}
                       for location, description, total in (("top", "Office supplies", "45.00"),
                                                            ("bottom", "Delivery", "15.00"))]
        self.index = {"manifest": str(self.review.manifest_path), "documents": {self.digest: {
            "paths": [str(self.source)], "error": None, "units": [{"label": "image 1", "image": None}]}}}
        (self.work / "index.json").write_text(json.dumps(self.index))
        self.state = {"index_sha256": fingerprint(self.work / "index.json"), "decisions": {},
                      "units": {self.key: {"readable": True, "receipts": self.pieces}}}
        self.save_state()
        bank = self.base / "bank.pdf"
        bank.write_bytes(b"original bank statement")
        (self.base / "bank-output").mkdir()
        with (self.base / "bank-output/master_statement.csv").open("w", newline="") as stream:
            fields = ["transaction_id", "source", "source_sha256", "currency", "money_in", "money_out", "balance_checks"]
            writer = csv.DictWriter(stream, fields)
            writer.writeheader()
            for key, total in (("combined", "60.00"), ("first", "45.00"), ("second", "15.00")):
                writer.writerow({"transaction_id": key, "source": str(bank), "source_sha256": fingerprint(bank),
                                 "currency": "MYR", "money_in": "0.00", "money_out": total, "balance_checks": "passed"})

    def save_state(self):
        """Publish a changed synthetic extraction checkpoint."""
        (self.work / "state.json").write_text(json.dumps(self.state))

    def view(self):
        """Read the current persisted review and revision."""
        return receipt_review.snapshot(self.review)

    def accept_pieces(self, pieces=None):
        """Explicitly accept the supplied extraction as a named fixture reviewer."""
        return receipt_review.accept_extraction(self.review, {"revision": self.view()["revision"],
            "key": self.key, "receipts": self.pieces if pieces is None else pieces, "reviewer": "Tester"})

    def test_accept_all_saves_draft_once_and_rejects_stale_repeat(self):
        """Bulk acceptance retains edits and audits them without matching bank entries."""
        view = self.view()
        draft = view['units'][0]['receipts']
        draft[0]['total'] = '42.00'
        body = {'revision': view['revision'], 'draft': {'key': self.key, 'receipts': draft}}
        result = receipt_review.accept_all_extractions(self.review, body)
        self.assertEqual(result['bulk'], {'accepted': 1, 'skipped': []})
        self.assertEqual(result['units'][0]['receipts'][0]['total'], '42.00')
        self.assertEqual(result['matches'], [])
        saved = json.loads((self.work / 'receipt-matches.json').read_text())
        self.assertTrue(saved['history'][0]['bulk'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            receipt_review.accept_all_extractions(self.review, body)
        repeated = receipt_review.accept_all_extractions(self.review, {'revision': self.view()['revision']})
        self.assertEqual(repeated['bulk']['accepted'], 0)

    def test_accept_all_skips_unreadable_and_changed_sources(self):
        """Unresolved extraction and changed original bytes cannot become bulk approvals."""
        self.state['units'][self.key]['readable'] = False
        self.save_state()
        result = receipt_review.accept_all_extractions(self.review, {'revision': self.view()['revision']})
        self.assertEqual(result['bulk']['accepted'], 0)
        self.assertEqual(len(result['bulk']['skipped']), 1)
        self.state['units'][self.key]['readable'] = True
        self.save_state()
        self.source.write_bytes(b'changed original')
        result = receipt_review.accept_all_extractions(self.review, {'revision': self.view()['revision']})
        self.assertEqual(result['bulk']['accepted'], 0)
        self.assertIn('source changed', result['bulk']['skipped'][0]['reason'])
        self.assertFalse((self.work / 'receipt-matches.json').exists())

    def test_system_warning_requires_individual_review(self):
        """PDF disagreements stay visible and cannot pass an untouched bulk acceptance."""
        warning = 'Text and vision disagree; verify the original.'
        self.state['units'][self.key]['review_warnings'] = [warning]
        self.save_state()
        view = self.view()
        self.assertEqual(view['units'][0]['review_warnings'], [warning])
        result = receipt_review.accept_all_extractions(self.review, {'revision': view['revision']})
        self.assertEqual(result['bulk']['accepted'], 0)
        self.assertIn('individually', result['bulk']['skipped'][0]['reason'])

    def test_accept_all_rejects_invalid_draft_without_writing(self):
        """Invalid edits stay unsaved rather than being dropped during a bulk action."""
        view = self.view()
        draft = view['units'][0]['receipts']
        draft[0]['total'] = 'invalid'
        with self.assertRaises(ValueError):
            receipt_review.accept_all_extractions(self.review, {'revision': view['revision'],
                'draft': {'key': self.key, 'receipts': draft}})
        self.assertFalse((self.work / 'receipt-matches.json').exists())

    def test_remove_assembled_piece_preserves_extended_fields(self):
        """Removing a generated piece from four pages accepts the remaining editor fields."""
        from reconciliation.receipt_assembly import input_revision
        document = self.index['documents'][self.digest]
        document['id'] = self.digest
        document['units'] = [{'label': f'page {n}', 'image': None} for n in range(1, 5)]
        (self.work / 'index.json').write_text(json.dumps(self.index))
        self.state['index_sha256'] = fingerprint(self.work / 'index.json')
        self.state['assemblies'] = {self.digest: {
            'input_revision': input_revision(document, self.state), 'reviewed_units': [1, 2, 3, 4],
            'limitations': [], 'receipts': [{**piece, 'source_units': [1, 2, 3, 4], 'needs_review': False}
                                           for piece in self.pieces]}}
        self.save_state()
        view = self.view()
        unit = view['units'][0]
        remaining = {**unit['receipts'][0], 'payee': '', 'references': [{'type': 'invoice', 'value': '336617430'}],
                     'dates': [], 'amount_basis': '', 'total': '273.48'}
        result = receipt_review.accept_extraction(self.review, {
            'revision': view['revision'], 'key': unit['key'], 'receipts': [remaining]})
        self.assertEqual(len(result['units'][0]['receipts']), 1)
        self.assertEqual(result['units'][0]['receipts'][0]['total'], '273.48')
        self.assertEqual(result['units'][0]['receipts'][0]['references'], remaining['references'])
        self.assertEqual(result, self.view())

    def test_parallel_validation_rejects_modified_prepared_image(self):
        """Faster review reads and saves must still reject tampered derived evidence."""
        image = self.work / 'page.png'
        image.write_bytes(b'prepared image')
        self.index['documents'][self.digest]['units'][0].update(
            image=str(image), image_sha256=fingerprint(image))
        (self.work / 'index.json').write_text(json.dumps(self.index))
        self.state['index_sha256'] = fingerprint(self.work / 'index.json')
        self.save_state()
        revision = self.view()['revision']
        image.write_bytes(b'changed image')
        with self.assertRaisesRegex(ValueError, 'Prepared image changed'):
            receipt_review.accept_extraction(self.review, {
                'revision': revision, 'key': self.key, 'receipts': self.pieces})
        self.assertFalse((self.work / 'receipt-matches.json').exists())

    def test_accept_extraction_without_reviewer_keeps_audit_history(self):
        """Removing the name field still records the explicit approval and its time."""
        receipt_review.accept_extraction(self.review, {"revision": self.view()["revision"],
            "key": self.key, "receipts": self.pieces})
        saved = json.loads((self.work / "receipt-matches.json").read_text())
        self.assertEqual(saved["history"][-1]["action"], "accept_extraction")
        self.assertIsNone(saved["history"][-1]["reviewer"])
        self.assertTrue(saved["history"][-1]["at"])

    def test_accept_response_matches_reload_with_one_evidence_scan(self):
        """Reuse verified evidence while keeping revised pieces and stale matches exact."""
        self.accept_pieces()
        self.change("combined", "propose", [(0, "45.00"), (1, "15.00")])
        expected = self.view()["revision"]
        pieces = [{**self.pieces[0], "total": "42.00"}]
        with patch.object(receipt_review, "context", wraps=receipt_review.context) as scans:
            result = receipt_review.accept_extraction(self.review, {
                "revision": expected, "key": self.key, "receipts": pieces})
        self.assertEqual(scans.call_count, 1)
        self.assertEqual(result, self.view())
        self.assertTrue(result["matches"][0]["stale"])

    def test_trash_is_audited_reversible_and_excluded_from_receipts(self):
        """Discarding preserves original bytes and makes pending evidence unusable."""
        from dashboard import document_status
        self.accept_pieces()
        self.change("combined", "propose", [(0, "45.00"), (1, "15.00")])
        original = self.source.read_bytes()
        discarded = receipt_review.classify_extraction(self.review, {
            "revision": self.view()["revision"], "key": self.key, "action": "trash"})
        self.assertTrue(discarded["units"][0]["trash"])
        self.assertFalse(discarded["units"][0]["accepted"])
        self.assertEqual(discarded["receipts"], [])
        self.assertTrue(discarded["matches"][0]["stale"])
        self.assertEqual(discarded, self.view())
        self.assertEqual(document_status.snapshot(self.review)["documents"][0]["status"], "Trash")
        with self.assertRaisesRegex(ValueError, "Restore"):
            receipt_review.accept_extraction(self.review, {
                "revision": discarded["revision"], "key": self.key, "receipts": self.pieces})
        restored = receipt_review.classify_extraction(self.review, {
            "revision": discarded["revision"], "key": self.key, "action": "restore"})
        self.assertFalse(restored["units"][0]["trash"])
        self.assertEqual(len(restored["receipts"]), 2)
        self.assertEqual(restored, self.view())
        self.assertEqual(self.source.read_bytes(), original)
        history = json.loads((self.work / "receipt-matches.json").read_text())["history"]
        self.assertEqual([entry["action"] for entry in history[-2:]], ["trash_extraction", "restore_extraction"])

    def test_trash_rejects_stale_requests_and_approved_allocations(self):
        """Keep approved support intact and reject old or changed-source decisions."""
        old = self.view()["revision"]
        self.accept_pieces()
        with self.assertRaisesRegex(ValueError, "reload"):
            receipt_review.classify_extraction(self.review, {"revision": old, "key": self.key, "action": "trash"})
        self.change("combined", "propose", [(0, "45.00"), (1, "15.00")])
        self.change("combined", "accept")
        with self.assertRaisesRegex(ValueError, "Undo accepted matches"):
            receipt_review.classify_extraction(self.review, {
                "revision": self.view()["revision"], "key": self.key, "action": "trash"})

        self.change("combined", "undo")
        self.source.write_bytes(b"changed original")
        with self.assertRaisesRegex(ValueError, "source changed"):
            receipt_review.classify_extraction(self.review, {
                "revision": self.view()["revision"], "key": self.key, "action": "trash"})

    def test_trash_requires_undo_of_final_review_approval(self):
        """A discard cannot silently remove evidence reserved by the final ledger."""
        from dashboard import matching_review
        folder = self.base / "final-review"
        folder.mkdir()
        (folder / "decisions.json").write_text('{}')
        ledger = {"decisions": {"B1": {"status": "approved", "allocations": [{"item_id": "D1"}]}}}
        final_context = (None, ledger, {}, {"D1": {"document": self.digest}}, {}, {})
        expected = self.view()["revision"]
        with patch.object(matching_review, "context", return_value=final_context):
            with self.assertRaisesRegex(ValueError, "Undo approved Final review"):
                receipt_review.classify_extraction(self.review, {
                    "revision": expected, "key": self.key, "action": "trash"})
        self.assertFalse(self.view()["units"][0]["trash"])

    def change(self, bank, action, items=None, reason=""):
        """Submit one revision-checked match action."""
        return receipt_review.change_match(self.review, {"revision": self.view()["revision"],
            "bank_transaction_id": bank, "action": action, "reviewer": "Tester", "reason": reason,
            "supporting_items": [{"receipt_id": f"{self.digest}:u0:r{number}", "allocated_amount": value}
                                 for number, value in items or []]})

    def test_combined_match_is_pending_until_acceptance_and_survives_reload(self):
        """Two pieces support one bank entry without merging their underlying records."""
        self.accept_pieces()
        view = self.change("combined", "propose", [(0, "45.00"), (1, "15.00")])
        match = view["matches"][0]
        self.assertEqual((match["supporting_total"], match["difference"], match["review_status"]), ("60.00", "0.00", "pending"))
        self.assertEqual([r["remaining_amount"] for r in view["receipts"]], ["45.00", "15.00"])
        self.change("combined", "accept")
        self.assertEqual([r["remaining_amount"] for r in self.view()["receipts"]], ["0.00", "0.00"])
        self.assertEqual(len(self.view()["units"][0]["receipts"]), 2)
        self.assertEqual(self.source.read_bytes(), b"two separate receipt images")
        self.change("combined", "undo")
        self.assertEqual(self.view()["receipts"][0]["remaining_amount"], "45.00")
        history = json.loads((self.work / "receipt-matches.json").read_text())["history"]
        self.assertEqual([entry["action"] for entry in history], ["accept_extraction", "propose", "accept", "undo"])

    def test_separate_bank_entries_use_separate_receipts_from_same_photo(self):
        """Each piece can independently support its corresponding bank transaction."""
        self.accept_pieces()
        self.change("first", "propose", [(0, "45.00")])
        self.change("first", "accept")
        self.change("second", "propose", [(1, "15.00")])
        self.change("second", "accept")
        self.assertEqual([m["difference"] for m in self.view()["matches"]], ["0.00", "0.00"])

    def test_pending_proposals_cannot_double_allocate_on_acceptance(self):
        """Recheck remaining amounts after another pending proposal is accepted."""
        self.accept_pieces()
        self.change("combined", "propose", [(0, "45.00"), (1, "15.00")])
        self.change("first", "propose", [(0, "45.00")])
        self.change("combined", "accept")
        with self.assertRaisesRegex(ValueError, "remaining amount"):
            self.change("first", "accept")
        with self.assertRaisesRegex(ValueError, "Undo accepted matches"):
            self.accept_pieces()

    def test_partial_allocations_and_discrepancies_remain_explicit(self):
        """One receipt can cover instalments without hiding an amount difference."""
        self.accept_pieces()
        self.change("second", "propose", [(0, "15.00")])
        self.change("second", "accept")
        self.change("first", "propose", [(0, "30.00")])
        with self.assertRaisesRegex(ValueError, "Explain the amount difference"):
            self.change("first", "accept")
        view = self.change("first", "accept", reason="Remaining support is missing")
        self.assertEqual(view["matches"][1]["difference"], "15.00")
        self.assertEqual(view["receipts"][0]["remaining_amount"], "0.00")

    def test_missing_values_currency_and_duplicate_ids_are_not_guessed(self):
        """Unapproved, incomplete, mixed-currency, or repeated pieces cannot allocate."""
        with self.assertRaisesRegex(ValueError, "accept the receipt"):
            self.change("first", "propose", [(0, "45.00")])
        self.accept_pieces()
        with self.assertRaisesRegex(ValueError, "only once"):
            self.change("first", "propose", [(0, "15.00"), (0, "15.00")])
        self.pieces[0]["currency"] = "USD"
        self.accept_pieces()
        with self.assertRaisesRegex(ValueError, "currencies differ"):
            self.change("first", "propose", [(0, "45.00")])
        self.pieces[0].update(total="", currency="MYR")
        self.accept_pieces()
        with self.assertRaisesRegex(ValueError, "Enter an amount"):
            self.change("first", "propose", [(0, "45.00")])
        self.assertEqual(self.view()["receipts"][0]["total"], "")

    def test_changed_extraction_and_source_bytes_block_acceptance(self):
        """Refresh or source tampering cannot silently preserve a proposal's evidence."""
        self.accept_pieces()
        self.change("combined", "propose", [(0, "45.00"), (1, "15.00")])
        self.source.write_bytes(b"changed")
        self.assertTrue(self.view()["matches"][0]["stale"])
        with self.assertRaisesRegex(ValueError, "current pending"):
            self.change("combined", "accept")
        self.source.write_bytes(b"two separate receipt images")
        self.state["units"][self.key]["receipts"][0]["total"] = "40.00"
        self.save_state()
        self.assertTrue(self.view()["matches"][0]["stale"])
        with self.assertRaisesRegex(ValueError, "current pending"):
            self.change("combined", "accept")

    def test_stale_browser_submission_and_negative_amount_fail(self):
        """Prevent lost updates and invalid monetary input without writing a match."""
        old = self.view()["revision"]
        self.accept_pieces()
        with self.assertRaisesRegex(ValueError, "reload"):
            receipt_review.accept_extraction(self.review, {"revision": old})
        for invalid in ("-1", "NaN", "1.001", ""):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.change("first", "propose", [(0, invalid)])

    def test_changed_bank_source_marks_match_stale_but_keeps_undo_available(self):
        """Do not silently preserve approval after the original bank evidence changes."""
        self.accept_pieces()
        self.change("combined", "propose", [(0, "45.00"), (1, "15.00")])
        self.change("combined", "accept")
        (self.base / "bank.pdf").write_bytes(b"replaced bank statement")
        view = self.view()
        self.assertTrue(view["matches"][0]["stale"])
        self.assertEqual(view["receipts"][0]["remaining_amount"], "0.00")
        self.change("combined", "undo")
        self.assertEqual(self.view()["receipts"][0]["remaining_amount"], "45.00")
