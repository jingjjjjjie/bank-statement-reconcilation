"""Verify extraction boundaries using small, local document fixtures."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from reconciliation.document_reader import extract
from reconciliation.review_settings import DEFAULTS


class DocumentReaderTests(unittest.TestCase):
    """Keep format dispatch and evidence coverage stable across refactors."""

    def setUp(self):
        """Isolate source documents and generated previews for each test."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.output = self.base / "units"

    def test_word_chunks_keep_all_text_and_embedded_image(self):
        """Long XML text retains its final chunk and its separate image evidence."""
        source = self.base / "receipt.docx"
        text = "a" * 12001
        image = io.BytesIO()
        Image.new("RGB", (8, 6), "white").save(image, format="PNG")
        with zipfile.ZipFile(source, "w") as package:
            package.writestr("word/document.xml", f'<w:document xmlns:w="urn:test"><w:t>{text}</w:t></w:document>')
            package.writestr("word/media/image.png", image.getvalue())
        original = source.read_bytes()
        units = extract(source, self.output)
        self.assertEqual([len(unit["text"]) for unit in units], [12000, 1, 0])
        self.assertEqual("".join(unit["text"] for unit in units), text)
        self.assertEqual(Path(units[2]["image"]).name, "unit-0003.png")
        with Image.open(units[2]["image"]) as preview:
            self.assertEqual(preview.size, (8, 6))
        self.assertEqual(source.read_bytes(), original)
        disabled = extract(source, self.output, {**DEFAULTS, "pictures_enabled": False})
        self.assertTrue(disabled[2]["blocked"])
        self.assertIsNone(disabled[2]["image"])

    def test_multiframe_image_keeps_each_frame(self):
        """A TIFF produces one numbered evidence unit for each frame."""
        source = self.base / "receipt.tiff"
        Image.new("RGB", (8, 6), "white").save(
            source, save_all=True, append_images=[Image.new("RGB", (8, 6), "black")])
        units = extract(source, self.output)
        self.assertEqual([unit["label"] for unit in units], ["image 1 / part 1", "image 2 / part 1"])
        self.assertTrue(all(Path(unit["image"]).is_file() for unit in units))

    def test_embedded_object_remains_unresolved(self):
        """Unsupported Office objects fail extraction instead of losing evidence."""
        source = self.base / "receipt.docx"
        with zipfile.ZipFile(source, "w") as package:
            package.writestr("word/embeddings/object.bin", b"unrendered")
        with self.assertRaisesRegex(ValueError, "Embedded object needs manual rendering"):
            extract(source, self.output)

    def test_empty_and_unsupported_documents_are_rejected(self):
        """Missing evidence cannot appear as a successful empty extraction."""
        source = self.base / "empty.docx"
        with zipfile.ZipFile(source, "w"):
            pass
        with self.assertRaisesRegex(ValueError, "No readable units"):
            extract(source, self.output)
        with self.assertRaisesRegex(ValueError, "Unsupported file type"):
            extract(self.base / "unknown.txt", self.output)


if __name__ == "__main__":
    unittest.main()
