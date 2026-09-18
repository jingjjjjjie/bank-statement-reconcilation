"""Exercise content-review stop and resume from the browser without Codex calls."""
import json
import tempfile
import threading
import unittest
from tests.http_server import TestServer
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from reconciliation.codex_reviewer import ReviewCancelled
from dashboard.app import Review, create_app
from tests.unit.test_content_review import FixtureReviewer
from reconciliation.duplicate_workflow import organize
from reconciliation.vision_workflow import load, prepare


class StopBrowserTests(unittest.TestCase):
    def test_stop_and_resume_preserves_saved_review(self):
        """Stop a blocked extraction, then resume from the same checkpoint."""
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if not chrome.is_file():
            self.skipTest("Installed Chrome is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "sources"
            source.mkdir()
            Image.new("RGB", (20, 20), "white").save(source / "first.png")
            Image.new("RGB", (20, 20), "black").save(source / "second.png")
            manifest = base / "manifest.json"
            organize(source, manifest)
            (base / "review_config.json").write_text(json.dumps({"pdf_mode": "auto", "pictures_enabled": True,
                "codex_enabled": True, "max_calls": 20, "model": "", "reasoning": "default", "stages": {}}), encoding="utf-8")
            review = Review(manifest, base / "data")
            work = base / "review"
            prepare(manifest, work, review.config_path)
            started, cancelled = threading.Event(), threading.Event()

            class WaitingReviewer(FixtureReviewer):
                def ask(self, prompt, schema, images=()):
                    """Wait until the browser requests cancellation."""
                    started.set()
                    cancelled.wait(timeout=10)
                    raise ReviewCancelled("Review stopped by user")

                def cancel(self):
                    """Release the blocked fixture request."""
                    cancelled.set()

            reviewers = iter((WaitingReviewer(), FixtureReviewer()))
            server = TestServer(("127.0.0.1", 0), create_app(review, "test-token"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch("dashboard.content_review.CodexReviewer", side_effect=lambda *args, **kwargs: next(reviewers)):
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
                        page = browser.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(f"http://127.0.0.1:{server.server_port}/documents")
                        page.get_by_role("button", name="Run all documents").click()
                        self.assertTrue(started.wait(timeout=5))
                        expect(page.get_by_role("button", name="Stop", exact=True)).to_be_visible()
                        page.get_by_role("button", name="Stop", exact=True).click()
                        expect(page.locator("#run-documents")).to_be_enabled()
                        self.assertEqual(load(work)[1]["units"], {})
                        expect(page.locator("#document-run-status")).to_contain_text("stopped")
                        page.get_by_role("button", name="Run all documents").click()
                        expect(page.locator("#document-progress-bar")).to_have_attribute("value", "100", timeout=15000)
                        self.assertEqual(len(load(work)[1]["units"]), 2, review.content_error)
                        self.assertEqual(load(work)[1]["pairs"], {})
                        page.reload()
                        expect(page.locator(".document-status").first).to_have_text("Needs review")
                        self.assertFalse(errors)
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
