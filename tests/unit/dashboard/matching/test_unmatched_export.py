"""Verify unmatched ZIP contents, duplicate provenance and unchanged inputs."""

from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from dashboard.services.matching import final_review, unmatched_export
from reconciliation.intake.duplicates import fingerprint, organize
from tests.fixtures.final_review import FinalReviewFixture


class UnmatchedExportTests(FinalReviewFixture):
    """Export a synthetic ledger and nested original files without deleting inputs."""

    def setUp(self):
        """Give the frozen fixture a source manifest usable by the inventory scanner."""
        super().setUp()
        self.write(
            self.review.manifest_path,
            {
                'SupportingRoot': str(self.review.root),
                'Files': [],
                'Mode': 'exact_report',
            },
        )

    def archive(self):
        """Read and remove a generated temporary archive after validating its CRCs."""
        path = unmatched_export.export_zip(self.review)
        try:
            with ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                return {name: archive.read(name) for name in archive.namelist()}
        finally:
            path.unlink()

    def content_decision(self):
        """Confirm receipt 2 as a content duplicate of receipt 1 in a bound review."""
        digests = [fingerprint(self.review.root / f'receipt-{n}.txt') for n in (1, 2)]
        work = self.project / 'review'
        work.mkdir(exist_ok=True)
        self.write(work / 'index.json', {'manifest': str(self.review.manifest_path)})
        self.write(
            work / 'state.json',
            {
                'index_sha256': fingerprint(work / 'index.json'),
                'decisions': {':'.join(digests): {'verdict': 'keep_left'}},
            },
        )

    def test_partial_match_excludes_whole_document_and_exact_copies(self):
        """Any approved allocation removes its complete source and all exact copies."""
        root = self.review.root
        (root / 'nested').mkdir()
        (root / 'nested/copy.txt').write_bytes((root / 'receipt-1.txt').read_bytes())
        (root / 'nested/unprocessed.bin').write_bytes(b'Unprocessed original')
        (root / 'nested/second-copy.txt').write_bytes((root / 'receipt-2.txt').read_bytes())
        before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
        final_review.decide(self.review, self.request(allocations=[{'item_id': 'D1', 'amount': '4'}]))
        ledger = (self.project / 'final-review/decisions.json').read_bytes()
        exported = self.archive()
        self.assertEqual(
            set(exported), {'uploads/', 'uploads/nested/second-copy.txt', 'uploads/nested/unprocessed.bin'}
        )
        self.assertEqual(exported['uploads/nested/second-copy.txt'], before[root / 'receipt-2.txt'])
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual((self.project / 'final-review/decisions.json').read_bytes(), ledger)

    def test_contextual_approval_excludes_document(self):
        """A human-approved contextual link also qualifies as an approved match."""
        final_review.decide(self.review, self.request(allocations=[{'item_id': 'E1', 'amount': ''}]))
        self.assertEqual(set(self.archive()), {'uploads/', 'uploads/receipt-1.txt'})

    def test_unapproved_rejected_and_stale_matches_keep_sources(self):
        """Suggestions, rejection and obsolete source approvals cannot hide originals."""
        expected = {'uploads/', 'uploads/receipt-1.txt', 'uploads/receipt-2.txt'}
        self.assertEqual(set(self.archive()), expected)
        final_review.decide(self.review, self.request(action='deny'))
        self.assertEqual(set(self.archive()), expected)
        final_review.decide(self.review, self.request())
        (self.review.root / 'receipt-1.txt').write_text('Changed original', encoding='utf-8')
        self.assertEqual(set(self.archive()), expected)

    def test_content_duplicates_require_surviving_kept_bytes(self):
        """Confirmed duplicates are omitted, but not when their survivor has changed."""
        self.content_decision()
        self.assertEqual(set(self.archive()), {'uploads/', 'uploads/receipt-1.txt'})
        (self.review.root / 'receipt-1.txt').write_text('Changed survivor', encoding='utf-8')
        self.assertEqual(set(self.archive()), {'uploads/', 'uploads/receipt-1.txt', 'uploads/receipt-2.txt'})

    def test_legacy_organized_copy_uses_original_folder(self):
        """Legacy review locations never replace the original relative ZIP hierarchy."""
        root = self.root / 'legacy'
        (root / 'nested').mkdir(parents=True)
        (root / 'nested/a.txt').write_bytes(b'Exact copy')
        (root / 'nested/b.txt').write_bytes(b'Exact copy')
        manifest = self.root / 'legacy-project/manifest.json'
        manifest.parent.mkdir()
        organize(root, manifest)
        review = SimpleNamespace(root=root, manifest_path=manifest)
        path = unmatched_export.export_zip(review)
        try:
            with ZipFile(path) as archive:
                self.assertEqual(archive.namelist(), ['uploads/', 'uploads/nested/a.txt'])
                self.assertEqual(archive.read('uploads/nested/a.txt'), b'Exact copy')
        finally:
            path.unlink()

    def test_changed_file_aborts_archive(self):
        """Never return a successful archive when its bytes changed after planning."""
        source = self.review.root / 'receipt-1.txt'
        with patch.object(unmatched_export, 'archive_files', return_value=[(source, 'uploads/file.txt', 'wrong')]):
            with self.assertRaisesRegex(ValueError, 'changed during export'):
                unmatched_export.export_zip(self.review)

    def test_empty_result_has_uploads_folder(self):
        """An entirely matched deduplicated folder still downloads as a valid ZIP."""
        self.content_decision()
        final_review.decide(self.review, self.request())
        self.assertEqual(self.archive(), {'uploads/': b''})

    def test_linked_source_is_rejected(self):
        """ZIP creation must not follow links into unrelated folders."""
        target = self.root / 'outside.txt'
        target.write_text('Outside scope', encoding='utf-8')
        link = self.review.root / 'link.txt'
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('Creating symlinks requires additional host privileges')
        with self.assertRaisesRegex(ValueError, 'Linked paths'):
            self.archive()
