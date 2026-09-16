"""Exercise both source selectors in a real browser."""
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from dashboard.app import handler_for
from source_selection import SourceSelection


class SourceBrowserTests(unittest.TestCase):
    def test_folder_and_pdf_selectors(self):
        """Keep the supporting folder and bank PDF as separate choices."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            documents = base / "documents"
            documents.mkdir()
            (documents / "receipt.txt").write_text("fixture", encoding="utf-8")
            statement = base / "statement.pdf"
            statement.write_bytes(b"%PDF-1.4\nfixture")
            sources = SourceSelection(base, base / "dashboard-data")
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(None, "test-token", sources))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                        headless=True)
                    try:
                        page = browser.new_page()
                        page.goto(f"http://127.0.0.1:{server.server_port}/source")
                        navigation = page.locator(".rail").bounding_box()
                        heading = page.locator("h1").bounding_box()
                        self.assertLess(navigation["height"], 100)
                        self.assertGreater(heading["y"], navigation["y"] + navigation["height"])
                        expect(page.locator(".source-grid > .settings-card")).to_have_count(2)
                        page.locator('.rail a[href="/bank"]').click()
                        expect(page).to_have_url(f"http://127.0.0.1:{server.server_port}/bank")
                        expect(page.locator("#bank-note")).to_contain_text("No prepared bank statement")
                        page.goto(f"http://127.0.0.1:{server.server_port}/source")
                        page.locator("#source-path").fill(str(documents))
                        page.locator("#select-source").click()
                        expect(page.locator("#selected-source")).to_contain_text(str(documents))
                        page.locator("#browse-bank").click()
                        expect(page.locator("#path-browser")).to_be_visible()
                        page.get_by_role("button", name="Up one level").click()
                        page.get_by_role("button", name="statement.pdf").click()
                        expect(page.locator("#selected-bank")).to_contain_text(str(statement))
                        self.assertEqual(sources.selected(), documents)
                        self.assertEqual(sources.selected_bank(), statement)
                        page.set_viewport_size({"width": 390, "height": 844})
                        expect(page.locator(".rail .nav-item").first).to_be_visible()
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
