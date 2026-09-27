"""Receipt review: accepting, editing, discarding and bulk-accepting extracted pieces."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dashboard.services import receipt_review
from reconciliation.intake.duplicates import fingerprint
from tests.fixtures.receipt_review import ReceiptReviewFixture


class ReceiptReviewTests(ReceiptReviewFixture):


    def test_accept_all_saves_draft_once_and_rejects_stale_repeat(self):
        """Bulk acceptance retains edits and audits them without matching bank entries."""
        view = self.view()
        draft = view['units'][0]['receipts']
        draft[0]['total'] = '42.00'
        body = {'revision': view['revision'], 'draft': {'key': self.key, 'receipts': draft}}
        result = receipt_review.accept_all_extractions(self.review, body)
        self.assertEqual(result['bulk'], {'accepted': 1, 'skipped': []})
        self.assertEqual(result['units'][0]['receipts'][0]['total'], '42.00')
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
        from reconciliation.extraction.assembly import input_revision
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

    def test_ground_truth_exports_only_saved_human_reviews(self):
        """Pending results carry no pieces; accepted edits and discards are exported."""
        pending = receipt_review.ground_truth(self.review)
        self.assertEqual(pending["counts"], {"accepted": 0, "discarded": 0, "pending": 1})
        self.assertEqual(pending["documents"][0]["pieces"], [])
        edited = [dict(self.pieces[0], total="46.00", currency="RM"), self.pieces[1]]
        self.accept_pieces(edited)
        accepted = receipt_review.ground_truth(self.review)["documents"][0]
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual([(p["amount"], p["currency"]) for p in accepted["pieces"]],
                         [("46.00", "MYR"), ("15.00", "MYR")])
        self.assertTrue(all(p["piece_id"] and "limitations" not in p for p in accepted["pieces"]))
        receipt_review.classify_extraction(self.review, {"revision": self.view()["revision"],
                                                         "key": self.key, "action": "trash"})
        discarded = receipt_review.ground_truth(self.review)
        self.assertEqual(discarded["documents"][0]["status"], "discarded")
        self.assertEqual(discarded["documents"][0]["pieces"], [])

    def test_accept_extraction_without_reviewer_keeps_audit_history(self):
        """Removing the name field still records the explicit approval and its time."""
        receipt_review.accept_extraction(self.review, {"revision": self.view()["revision"],
            "key": self.key, "receipts": self.pieces})
        saved = json.loads((self.work / "receipt-matches.json").read_text())
        self.assertEqual(saved["history"][-1]["action"], "accept_extraction")
        self.assertIsNone(saved["history"][-1]["reviewer"])
        self.assertTrue(saved["history"][-1]["at"])

    def test_undo_accept_preserves_corrections_and_requires_fresh_revision(self):
        """Reopening preserves identities and edits but removes matching eligibility."""
        accepted = self.accept_pieces([{**self.pieces[0], "total": "42.00"}])
        original = self.source.read_bytes()
        body = {"revision": accepted["revision"], "key": self.key}
        reopened = receipt_review.undo_accept_extraction(self.review, body)
        self.assertFalse(reopened["units"][0]["accepted"])
        self.assertFalse(reopened["receipts"][0]["accepted"])
        self.assertEqual(reopened["units"][0]["receipts"], accepted["units"][0]["receipts"])
        self.assertEqual(reopened, self.view())
        self.assertEqual(self.source.read_bytes(), original)
        with self.assertRaisesRegex(ValueError, "reload"):
            receipt_review.undo_accept_extraction(self.review, body)
        history = json.loads((self.work / "receipt-matches.json").read_text())["history"]
        self.assertEqual(history[-1]["action"], "undo_accept_extraction")
        discarded = receipt_review.classify_extraction(self.review, {
            "revision": reopened["revision"], "key": self.key, "action": "trash"})
        restored = receipt_review.classify_extraction(self.review, {
            "revision": discarded["revision"], "key": self.key, "action": "restore"})
        self.assertFalse(restored["units"][0]["accepted"])
        self.assertEqual(restored, self.view())
        reaccepted = self.accept_pieces(restored["units"][0]["receipts"])
        self.assertTrue(reaccepted["units"][0]["accepted"])
        self.assertEqual(reaccepted, self.view())

    def test_undo_accept_protects_approved_matching_evidence(self):
        """An extraction cannot reopen while approved allocations depend on it."""
        self.accept_pieces()
        self.seed_accepted_allocation()
        with self.assertRaisesRegex(ValueError, "Undo accepted matches"):
            receipt_review.undo_accept_extraction(self.review, {
                "revision": self.view()["revision"], "key": self.key})
        self.clear_allocations()
        from dashboard.services import final_review
        folder = self.base / "final-review"
        folder.mkdir()
        (folder / "decisions.json").write_text('{}')
        ledger = {"decisions": {"B1": {"status": "approved", "allocations": [{"item_id": "D1"}]}}}
        with patch.object(final_review, "context", return_value=(
                None, ledger, {}, {"D1": {"document": self.digest}}, {}, {})):
            with self.assertRaisesRegex(ValueError, "Undo approved Final review"):
                receipt_review.undo_accept_extraction(self.review, {
                    "revision": self.view()["revision"], "key": self.key})
        self.assertTrue(self.view()["units"][0]["accepted"])

    def test_accept_response_matches_reload_with_one_evidence_scan(self):
        """Reuse verified evidence while keeping revised pieces exact."""
        self.accept_pieces()
        expected = self.view()["revision"]
        pieces = [{**self.pieces[0], "total": "42.00"}]
        with patch.object(receipt_review, "context", wraps=receipt_review.context) as scans:
            result = receipt_review.accept_extraction(self.review, {
                "revision": expected, "key": self.key, "receipts": pieces})
        self.assertEqual(scans.call_count, 1)
        self.assertEqual(result, self.view())

    def test_trash_is_audited_reversible_and_excluded_from_receipts(self):
        """Discarding preserves original bytes and makes pending evidence unusable."""
        from dashboard.services import document_status
        self.accept_pieces()
        original = self.source.read_bytes()
        discarded = receipt_review.classify_extraction(self.review, {
            "revision": self.view()["revision"], "key": self.key, "action": "trash"})
        self.assertTrue(discarded["units"][0]["trash"])
        self.assertFalse(discarded["units"][0]["accepted"])
        self.assertEqual(discarded["receipts"], [])
        self.assertEqual(discarded, self.view())
        self.assertEqual(document_status.snapshot(self.review)["documents"][0]["status"], "Trash")
        restored = receipt_review.classify_extraction(self.review, {
            "revision": discarded["revision"], "key": self.key, "action": "restore"})
        self.assertFalse(restored["units"][0]["trash"])
        self.assertEqual(len(restored["receipts"]), 2)
        self.assertEqual(restored, self.view())
        self.assertEqual(self.source.read_bytes(), original)
        history = json.loads((self.work / "receipt-matches.json").read_text())["history"]
        self.assertEqual([entry["action"] for entry in history[-2:]], ["trash_extraction", "restore_extraction"])

    def test_accept_replaces_discard_atomically_and_preserves_pieces(self):
        """Direct status changes preserve corrections, validate first and audit both states."""
        accepted = self.accept_pieces([{**self.pieces[0], "total": "42.00"}])
        discarded = receipt_review.classify_extraction(self.review, {
            "revision": accepted["revision"], "key": self.key, "action": "trash"})
        pieces = discarded["units"][0]["receipts"]
        before = (self.work / "receipt-matches.json").read_bytes()
        with self.assertRaises(ValueError):
            receipt_review.accept_extraction(self.review, {
                "revision": discarded["revision"], "key": self.key,
                "receipts": [{**pieces[0], "total": "invalid"}]})
        self.assertEqual((self.work / "receipt-matches.json").read_bytes(), before)
        result = receipt_review.accept_extraction(self.review, {
            "revision": discarded["revision"], "key": self.key, "receipts": pieces})
        self.assertTrue(result["units"][0]["accepted"])
        self.assertFalse(result["units"][0]["trash"])
        self.assertEqual(result["units"][0]["receipts"], pieces)
        self.assertEqual(result, self.view())
        history = json.loads((self.work / "receipt-matches.json").read_text())["history"]
        self.assertEqual([entry["action"] for entry in history[-2:]],
                         ["restore_extraction", "accept_extraction"])

    def test_trash_rejects_stale_requests_and_approved_allocations(self):
        """Keep approved support intact and reject old or changed-source decisions."""
        old = self.view()["revision"]
        self.accept_pieces()
        with self.assertRaisesRegex(ValueError, "reload"):
            receipt_review.classify_extraction(self.review, {"revision": old, "key": self.key, "action": "trash"})
        self.seed_accepted_allocation()
        with self.assertRaisesRegex(ValueError, "Undo accepted matches"):
            receipt_review.classify_extraction(self.review, {
                "revision": self.view()["revision"], "key": self.key, "action": "trash"})

        self.clear_allocations()
        self.source.write_bytes(b"changed original")
        with self.assertRaisesRegex(ValueError, "source changed"):
            receipt_review.classify_extraction(self.review, {
                "revision": self.view()["revision"], "key": self.key, "action": "trash"})

    def test_trash_requires_undo_of_final_review_approval(self):
        """A discard cannot silently remove evidence reserved by the final ledger."""
        from dashboard.services import final_review
        folder = self.base / "final-review"
        folder.mkdir()
        (folder / "decisions.json").write_text('{}')
        ledger = {"decisions": {"B1": {"status": "approved", "allocations": [{"item_id": "D1"}]}}}
        final_context = (None, ledger, {}, {"D1": {"document": self.digest}}, {}, {})
        expected = self.view()["revision"]
        with patch.object(final_review, "context", return_value=final_context):
            with self.assertRaisesRegex(ValueError, "Undo approved Final review"):
                receipt_review.classify_extraction(self.review, {
                    "revision": expected, "key": self.key, "action": "trash"})
        self.assertFalse(self.view()["units"][0]["trash"])

    def test_ringgit_alias_is_normalized_only_when_accepting(self):
        """New edits store MYR, retain unknown currency and leave supplied evidence untouched."""
        self.pieces[0]['currency'] = ' rm '
        self.pieces[1]['currency'] = ''
        view = self.accept_pieces()
        self.assertEqual([p['currency'] for p in view['receipts']], ['MYR', ''])
        self.assertEqual(self.pieces[0]['currency'], ' rm ')

    def test_stale_browser_submission_fails(self):
        """A revision from before the last save is rejected."""
        old = self.view()["revision"]
        self.accept_pieces()
        with self.assertRaisesRegex(ValueError, "reload"):
            receipt_review.accept_extraction(self.review, {"revision": old})
