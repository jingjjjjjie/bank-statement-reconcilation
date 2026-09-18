"""Verify actual Vue navigation, cached edits, and page lifecycle in Chrome."""
import os
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from dashboard.review import Review
from reconciliation.duplicate_workflow import organize
from tests.http_server import TestServer


class NavigationTests(unittest.TestCase):
    def test_cached_navigation_and_history(self):
        """Switch views without new documents, losing edits, or hidden-page polling."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            inputs.mkdir()
            (inputs / "a.txt").write_text("one")
            manifest = root / "manifest.json"
            organize(inputs, manifest)
            review = Review(manifest, root / "data")
            server = TestServer(("127.0.0.1", 0), create_app(review, "test-token"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, executable_path=
                        r"C:\Program Files\Google\Chrome\Application\chrome.exe" if os.name == "nt" else None)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors, documents, polls = [], [], []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("request", lambda request: documents.append(request.url) if request.resource_type == "document" else None)
                    page.on("request", lambda request: polls.append(request.url) if request.url.endswith('/api/document-status') else None)
                    base = f"http://127.0.0.1:{server.server_port}"
                    page.goto(base + "/documents")
                    expect(page.locator('#document-summary')).to_contain_text('Run documents to prepare')
                    page.locator('#document-search').fill('preserved filter')
                    page.evaluate("window.savedInput = document.querySelector('#document-search'); window.savedRail = document.querySelector('.rail')")
                    page.locator('.rail a[href="/settings"]').click()
                    expect(page.locator('#save-state')).not_to_have_text('Loading settings…')
                    expect(page.locator('#max-calls')).to_be_enabled()
                    page.locator('#max-calls').fill('42')
                    expect(page.locator('#save-state')).to_have_text('Unsaved changes')
                    page.locator('.rail a[href="/bank"]').click()
                    expect(page.locator('#bank-note')).to_contain_text('No prepared bank statement')
                    paused = len(polls)
                    page.wait_for_timeout(5500)
                    self.assertEqual(len(polls), paused)
                    page.go_back()
                    expect(page.locator('#max-calls')).to_have_value('42')
                    expect(page.locator('#save-state')).to_have_text('Unsaved changes')
                    page.go_back()
                    expect(page.locator('#document-search')).to_have_value('preserved filter')
                    self.assertTrue(page.evaluate("window.savedInput === document.querySelector('#document-search')"))
                    self.assertTrue(page.evaluate("window.savedRail === document.querySelector('.rail')"))
                    self.assertEqual(len(documents), 1)
                    page.wait_for_timeout(5500)
                    self.assertGreater(len(polls), paused)
                    self.assertEqual(errors, [])
                    page.close(run_before_unload=False)
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
