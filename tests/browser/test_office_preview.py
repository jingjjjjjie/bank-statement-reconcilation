"""Verify Word and Excel previews through the dashboard browser."""
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook
from playwright.sync_api import sync_playwright, expect

from dashboard.app import Review, handler_for
from reconciliation.duplicate_workflow import organize


class OfficePreviewTests(unittest.TestCase):
    def test_word_and_excel_show_visual_pages(self):
        """Render structured pages without showing extraction text or JSON."""
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if not chrome.is_file():
            self.skipTest("Installed Chrome is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            word = source / "report.docx"
            with ZipFile(word, "w") as archive:
                archive.writestr("word/document.xml", """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Quarterly report</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Approved</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>""")
            (source / "report-copy.docx").write_bytes(word.read_bytes())
            book = Workbook()
            book.active.title = "Accounts"
            book.active["A1"] = "Balance"
            book.active["B1"] = 42
            excel = source / "accounts.xlsx"
            book.save(excel)
            (source / "accounts-copy.xlsx").write_bytes(excel.read_bytes())
            manifest = base / "manifest.json"
            organize(source, manifest)
            review = Review(manifest, base / "data")
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(review, "test-token"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
                    page = browser.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_port}/")
                    page.locator(".group-item").filter(has_text="accounts").first.click()
                    expect(page.locator(".sheet-title").first).to_have_text("Accounts")
                    expect(page.locator(".sheet-table td").first).to_have_text("Balance")
                    page.locator(".group-item").filter(has_text="report").first.click()
                    expect(page.locator(".word-page .heading1").first).to_have_text("Quarterly report")
                    expect(page.locator(".word-page td").first).to_have_text("Approved")
                    self.assertFalse(errors)
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
