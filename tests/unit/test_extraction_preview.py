"""Exercise source previews without depending on browser document plugins."""
import tempfile
import io
import unittest
from pathlib import Path

import pymupdf
from PIL import Image
from openpyxl import Workbook
from zipfile import ZipFile

from dashboard.extraction_preview import describe, image


class ExtractionPreviewTests(unittest.TestCase):
    def setUp(self):
        """Create isolated original documents for preview tests."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)

    def test_images_and_multipage_tiff(self):
        """Every workflow image format renders as a browser-compatible PNG."""
        for suffix in ('png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff'):
            with self.subTest(suffix=suffix):
                path = self.base / f'original.{suffix}'
                Image.new('RGB', (30, 50), 'white').save(path)
                self.assertEqual(describe(path)['kind'], 'image')
                self.assertTrue(image(path, 0).startswith(b'\x89PNG'))
        path = self.base / 'pages.tiff'
        Image.new('RGB', (30, 50)).save(path, save_all=True, append_images=[Image.new('RGB', (20, 40))])
        self.assertEqual(describe(path)['pages'], 2)
        self.assertTrue(image(path, 1).startswith(b'\x89PNG'))
        with self.assertRaises(ValueError):
            image(path, -1)

    def test_pdf_office_text_and_unrenderable(self):
        """PDF pages, all worksheet sections, Word and explicit fallbacks are available."""
        path = self.base / 'source.pdf'
        with pymupdf.open() as pdf:
            pdf.new_page(); pdf.new_page(); pdf.save(path)
        self.assertEqual(describe(path)['pages'], 2)
        self.assertTrue(image(path, 1).startswith(b'\x89PNG'))
        with self.assertRaises(ValueError):
            image(path, 2)
        workbook = Workbook()
        workbook.active['A42'] = 'last row'
        workbook.create_sheet('Second')['A1'] = 'second sheet'
        path = self.base / 'source.xlsx'; workbook.save(path)
        self.assertEqual(describe(path)['pages'], 3)
        path = self.base / 'source.docx'
        with ZipFile(path, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
            picture = io.BytesIO()
            Image.new('RGB', (20, 30)).save(picture, format='PNG')
            archive.writestr('word/media/image1.png', picture.getvalue())
        self.assertEqual(describe(path)['kind'], 'word')
        self.assertEqual(describe(path)['pages'], 2)
        self.assertTrue(image(path, 1).startswith(b'\x89PNG'))
        path = self.base / 'source.txt'; path.write_text('<script>not executable</script>')
        self.assertEqual(describe(path)['kind'], 'text')
        path = self.base / 'source.unknown'; path.write_bytes(b'unsupported')
        self.assertEqual(describe(path)['kind'], 'unsupported')
