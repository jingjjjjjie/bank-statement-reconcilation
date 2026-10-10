"""Preview routing stays fast without trusting cached original bytes or decisions."""

import os
from unittest.mock import patch

from dashboard.services.matching import final_review, piece_matching
from tests.fixtures.piece_pipeline import PiecePipelineFixture


class PreviewSourcesTests(PiecePipelineFixture):
    def setUp(self):
        """Activate real live-piece routing over isolated source files."""
        super().setUp()
        self.pieces = self.accept()['units'][0]['receipts']
        self.ids = [piece['piece_id'] for piece in self.pieces]
        piece_matching.activate(self.review)

    def test_repeated_previews_hash_only_the_selected_original(self):
        """Switching pieces and bank pages reuses routing, but hashes each original."""
        final_review.evidence(self.review, 'item', self.ids[0])
        with (
            patch.object(piece_matching, 'context', side_effect=AssertionError('Full rebuild')),
            patch.object(final_review, 'source_hash', wraps=final_review.source_hash) as hashes,
        ):
            self.assertEqual(final_review.evidence(self.review, 'item', self.ids[1]), self.fixture.source)
            self.assertEqual(final_review.evidence(self.review, 'bank', 'B1'), self.fixture.base / 'bank.pdf')
        self.assertEqual(
            [str(call.args[0]) for call in hashes.call_args_list],
            [str(self.fixture.source), str(self.fixture.base / 'bank.pdf')],
        )

    def test_changed_and_missing_originals_fail_with_warm_routing(self):
        """Same-size edits with restored timestamps cannot bypass byte verification."""
        source = self.fixture.source
        final_review.evidence(self.review, 'item', self.ids[0])
        stat = source.stat()
        source.write_bytes(b'x' * stat.st_size)
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'Original evidence changed'):
            final_review.evidence(self.review, 'item', self.ids[0])
        source.unlink()
        with self.assertRaisesRegex(ValueError, 'Original evidence changed'):
            final_review.evidence(self.review, 'item', self.ids[0])

    def test_removed_piece_invalidates_routing(self):
        """A saved removal cannot leave an old piece reachable in the warm map."""
        final_review.evidence(self.review, 'item', self.ids[0])
        self.accept(self.pieces[1:])
        with self.assertRaises(KeyError):
            final_review.evidence(self.review, 'item', self.ids[0])
        self.assertEqual(final_review.evidence(self.review, 'item', self.ids[1]), self.fixture.source)

    def test_metadata_content_invalidates_even_with_same_timestamp(self):
        """Saved metadata contents, rather than mtime or size, invalidate routing."""
        final_review.evidence(self.review, 'item', self.ids[0])
        path = self.fixture.work / 'receipt-matches.json'
        stat = path.stat()
        before = path.read_text()
        self.assertIn('Office supplies', before)
        path.write_text(before.replace('Office supplies', 'Office supplied'))
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with patch.object(piece_matching, 'context', wraps=piece_matching.context) as context:
            final_review.evidence(self.review, 'item', self.ids[0])
        self.assertEqual(context.call_count, 1)

    def test_unknown_ids_and_types_are_rejected(self):
        """A cached map never permits caller-selected paths or unknown kinds."""
        final_review.evidence(self.review, 'item', self.ids[0])
        with self.assertRaises(KeyError):
            final_review.evidence(self.review, 'item', str(self.fixture.source))
        with self.assertRaisesRegex(ValueError, 'Unknown evidence type'):
            final_review.evidence(self.review, 'other', self.ids[0])

    def test_warm_preview_does_not_authorize_approval(self):
        """Approvals still validate the complete current evidence, outside this cache."""
        request = self.decision(allocations=[{'item_id': self.ids[0], 'amount': '45'}])
        final_review.evidence(self.review, 'item', self.ids[0])
        self.fixture.source.write_bytes(b'changed original')
        with self.assertRaises(ValueError):
            final_review.decide(self.review, request)
        self.assertEqual(final_review.context(self.review)[1]['version'], 1)
