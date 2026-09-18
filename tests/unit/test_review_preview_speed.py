"""Keep next-document previews independent of unrelated prepared image scans."""
import io
import json
import unittest
from unittest.mock import patch

from PIL import Image

from dashboard import content_review, extraction_preview, receipt_review
from reconciliation import vision_workflow
from reconciliation.duplicate_workflow import fingerprint
from tests.unit import test_receipt_matching as fixtures


class ReviewPreviewSpeedTests(unittest.TestCase):
    def setUp(self):
        """Create a review with a source and a separately prepared page."""
        self.fixture = fixtures.ReceiptMatchingTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        fixture = self.fixture
        self.preview = fixture.work / 'prepared.png'
        self.preview.write_bytes(b'prepared page')
        fixture.index['documents'][fixture.digest]['units'][0].update(
            image=str(self.preview), image_sha256=fingerprint(self.preview))
        (fixture.work / 'index.json').write_text(json.dumps(fixture.index))
        fixture.state['index_sha256'] = fingerprint(fixture.work / 'index.json')
        fixture.save_state()

    def test_original_preview_skips_derived_images_but_acceptance_checks_them(self):
        """Preview lookup reads no derived images; saving still rejects tampering."""
        fixture = self.fixture
        revision = fixture.view()['revision']
        with patch.object(vision_workflow, 'fingerprint', wraps=fingerprint) as hashes:
            self.assertEqual(content_review.source(fixture.review, fixture.digest), fixture.source)
        self.assertEqual([call.args[0] for call in hashes.call_args_list],
                         [fixture.work / 'index.json'])
        self.preview.write_bytes(b'changed page')
        self.assertEqual(content_review.source(fixture.review, fixture.digest), fixture.source)
        with self.assertRaisesRegex(ValueError, 'Prepared image changed'):
            content_review.image(fixture.review, fixture.digest, 0)
        with self.assertRaisesRegex(ValueError, 'Prepared image changed'):
            receipt_review.accept_extraction(fixture.review, {
                "revision": revision, "key": fixture.key, "receipts": fixture.pieces})

    def test_changed_original_and_index_are_rejected(self):
        """The faster lookup still hashes current source bytes and metadata."""
        fixture = self.fixture
        fixture.source.write_bytes(b'changed original')
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            content_review.source(fixture.review, fixture.digest)
        with (fixture.work / 'index.json').open('a') as stream:
            stream.write(' ')
        with self.assertRaisesRegex(ValueError, 'Prepared index changed'):
            content_review.source(fixture.review, fixture.digest)

    def test_faster_png_encoding_preserves_every_pixel(self):
        """Lower compression changes only encoding effort, not evidence resolution."""
        path = self.fixture.base / 'pixels.png'
        original = Image.effect_noise((720, 960), 80).convert('RGB')
        original.save(path)
        with Image.open(io.BytesIO(extraction_preview.image(path, 0))) as rendered:
            self.assertEqual(rendered.size, original.size)
            self.assertEqual(rendered.tobytes(), original.tobytes())
