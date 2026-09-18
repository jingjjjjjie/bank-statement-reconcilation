"""Exercise both source selectors in a real browser."""
import os
import tempfile
import threading
import unittest
from tests.http_server import TestServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from dashboard.app import Review, create_app
from reconciliation.duplicate_workflow import organize
from reconciliation.source_selection import SourceSelection


class SourceBrowserTests(unittest.TestCase):
    def test_exact_review_shows_undo_and_contextual_next(self):
        """Keep reversal beside the group and reveal the next step after validation."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            documents = base / "documents"
            documents.mkdir()
            (documents / "a.txt").write_text("same", encoding="utf-8")
            (documents / "b.txt").write_text("same", encoding="utf-8")
            manifest = base / "manifest.json"
            organize(documents, manifest)
            review = Review(manifest, base / "dashboard-data")
            server = TestServer(("127.0.0.1", 0), create_app(review, "test-token"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe" if os.name == "nt" else None,
                        headless=True)
                    try:
                        page = browser.new_page()
                        page.goto(f"http://127.0.0.1:{server.server_port}/review")
                        page.get_by_role("button", name="Retain this file").first.click()
                        expect(page.locator(".group-heading-actions #undo")).to_be_visible()
                        page.get_by_role("button", name="Undo selection").click()
                        expect(page.locator("#undo")).to_be_hidden()
                        page.get_by_role("button", name="Retain this file").first.click()
                        page.get_by_role("button", name="Validate exact review").click()
                        expect(page.locator("#next-content")).to_be_visible()
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()

    def test_folder_and_pdf_selectors(self):
        """Select a formatted workspace and discover both inputs together."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            work = base / "December"
            work.mkdir()
            documents = work / "documents"
            documents.mkdir()
            (work / "statement").mkdir()
            (documents / "receipt.txt").write_text("fixture", encoding="utf-8")
            statement = work / "statement/statement.pdf"
            statement.write_bytes(b"%PDF-1.4\nfixture")
            sources = SourceSelection(base, base / "dashboard-data")
            server = TestServer(("127.0.0.1", 0), create_app(None, "test-token", sources))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe" if os.name == "nt" else None,
                        headless=True)
                    try:
                        page = browser.new_page()
                        page.goto(f"http://127.0.0.1:{server.server_port}/")
                        navigation = page.locator(".rail").bounding_box()
                        heading = page.locator("h1").bounding_box()
                        self.assertLess(navigation["height"], 100)
                        self.assertGreater(heading["y"], navigation["y"] + navigation["height"])
                        expect(page.locator(".workspace-card")).to_have_count(1)
                        expect(page.locator(".workflow-step")).to_have_count(5)
                        expect(page.locator(".workflow-check-button")).to_have_count(0)
                        expect(page.locator("#workflow-progress")).to_be_hidden()
                        page.locator('.rail a[href="/bank"]').click()
                        expect(page).to_have_url(f"http://127.0.0.1:{server.server_port}/bank")
                        expect(page.locator("#bank-note")).to_contain_text("No prepared bank statement")
                        page.goto(f"http://127.0.0.1:{server.server_port}/")
                        page.get_by_text("Enter a folder path manually", exact=True).click()
                        page.locator("#source-path").fill(str(work))
                        page.locator("#select-source").click()
                        expect(page.locator("#workspace-name")).to_have_text("December")
                        expect(page.locator("#workspace-status")).to_have_text("Ready to proceed")
                        expect(page.locator("#start-source")).to_be_enabled()
                        expect(page.locator("#selected-source")).to_contain_text("1 bank statement")
                        expect(page.locator("#bank-year")).to_have_count(0)
                        expect(page.get_by_role("button", name="Proceed", exact=True)).to_be_enabled()
                        self.assertEqual(sources.selected(), documents)
                        self.assertEqual(sources.selected_bank(), statement)
                        page.set_viewport_size({"width": 390, "height": 844})
                        expect(page.locator(".rail .nav-item").first).to_be_visible()
                        self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                        page.get_by_role("button", name="Change workspace", exact=True).click()
                        expect(page.locator("#path-browser")).to_be_visible()
                        page.get_by_role("button", name="Up one level").click()
                        page.get_by_role("button", name="Select this workspace", exact=True).click()
                        expect(page.locator("#browser-error")).to_contain_text("documents/ and statement/")
                        self.assertEqual(sources.selected(), documents)
                        page.get_by_role("button", name="Close", exact=True).click()
                        page.get_by_role("button", name="Proceed", exact=True).click()
                        expect(page).to_have_url(f"http://127.0.0.1:{server.server_port}/review")
                        self.assertTrue((documents / "receipt.txt").exists())
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
