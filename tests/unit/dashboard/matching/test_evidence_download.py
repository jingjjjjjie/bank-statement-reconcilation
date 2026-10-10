"""Export only verified, approved originals for the chosen transaction."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from dashboard.api.files import matching_evidence_download
from dashboard.services.matching import final_review
from tests.fixtures.final_review import FinalReviewFixture


class EvidenceDownloadTests(FinalReviewFixture):
    def download(self, bank_id='B1'):
        """Invoke the same handler used by the authenticated local dashboard."""
        return matching_evidence_download(bank_id, SimpleNamespace(review=self.review))

    def test_one_document_returns_exact_original(self):
        """One approved original downloads directly with its source filename."""
        final_review.decide(self.review, self.request())
        ledger = (self.project / 'final-review/decisions.json').read_bytes()
        response = self.download()
        self.assertEqual(response.body, (self.review.root / 'receipt-1.txt').read_bytes())
        self.assertIn("filename*=UTF-8''receipt-1.txt", response.headers['Content-Disposition'])
        self.assertEqual(ledger, (self.project / 'final-review/decisions.json').read_bytes())

    def test_multiple_documents_return_zip_with_exact_bytes_and_cleanup(self):
        """ZIPs include approved documents once, with original names and bytes."""
        final_review.decide(
            self.review,
            self.request(
                allocations=[
                    {'item_id': 'D1', 'amount': '4'},
                    {'item_id': 'D2', 'amount': '6'},
                    {'item_id': 'E1', 'amount': ''},
                ]
            ),
        )
        response = self.download()
        try:
            self.assertEqual(response.media_type, 'application/zip')
            with ZipFile(response.path) as archive:
                self.assertEqual(archive.namelist(), ['receipt-1.txt', 'receipt-2.txt'])
                for name in archive.namelist():
                    self.assertEqual(archive.read(name), (self.review.root / name).read_bytes())
        finally:
            asyncio.run(response.background())
        self.assertFalse(response.path.exists())

    def test_multiple_pieces_in_one_document_are_not_zipped(self):
        """Two approved entries referencing one original still return one file."""
        final_review.decide(
            self.review,
            self.request(
                allocations=[
                    {'item_id': 'D2', 'amount': '10'},
                    {'item_id': 'E1', 'amount': ''},
                ]
            ),
        )
        self.assertEqual(self.download().body, (self.review.root / 'receipt-2.txt').read_bytes())

    def test_context_only_approval_can_download(self):
        """Current contextual approvals retain access to their approved evidence."""
        final_review.decide(self.review, self.request(allocations=[{'item_id': 'E1', 'amount': ''}]))
        self.assertEqual(self.download().body, (self.review.root / 'receipt-2.txt').read_bytes())

    def test_pending_rejected_and_unknown_transactions_fail(self):
        """Suggestions and rejected matches cannot be exported as approved evidence."""
        with self.assertRaisesRegex(ValueError, 'current approval'):
            self.download()
        final_review.decide(self.review, self.request(action='deny'))
        with self.assertRaisesRegex(ValueError, 'current approval'):
            self.download()
        with self.assertRaises(KeyError):
            self.download('../another-project')

    def test_changed_original_rejects_entire_group(self):
        """A multi-document export never quietly omits a changed approved source."""
        final_review.decide(
            self.review,
            self.request(
                allocations=[
                    {'item_id': 'D1', 'amount': '4'},
                    {'item_id': 'D2', 'amount': '6'},
                ]
            ),
        )
        (self.review.root / 'receipt-2.txt').write_bytes(b'changed evidence')
        with self.assertRaisesRegex(ValueError, 'current approval'):
            self.download()

    def test_changed_bytes_during_single_file_export_fail(self):
        """Verify the exact downloaded bytes even after source resolution succeeds."""
        source = self.review.root / 'receipt-1.txt'
        with patch(
            'dashboard.services.matching.evidence_download.approved_files',
            return_value=[(source, source.name, '0' * 64)],
        ):
            with self.assertRaisesRegex(ValueError, 'changed during export'):
                self.download()

    def test_equal_basenames_preserve_relative_folders(self):
        """Different originals named alike remain separate files in the ZIP."""
        index_path = self.cache / 'index.json'
        index = final_review.read(index_path)
        for number, document in enumerate(index['documents'].values()):
            source = self.review.root / f'receipt-{number + 1}.txt'
            destination = self.review.root / str(number) / 'receipt.txt'
            destination.parent.mkdir()
            source.rename(destination)
            document['paths'] = [str(destination)]
        self.write(index_path, index)
        final_review.decide(
            self.review,
            self.request(
                allocations=[
                    {'item_id': 'D1', 'amount': '4'},
                    {'item_id': 'D2', 'amount': '6'},
                ]
            ),
        )
        response = self.download()
        try:
            with ZipFile(response.path) as archive:
                self.assertEqual(archive.namelist(), ['0/receipt.txt', '1/receipt.txt'])
                self.assertNotEqual(archive.read('0/receipt.txt'), archive.read('1/receipt.txt'))
        finally:
            asyncio.run(response.background())
