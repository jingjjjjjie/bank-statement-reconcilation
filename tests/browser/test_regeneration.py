"""Verify background regeneration controls against real local endpoints."""
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from dashboard import content_review
from dashboard.routes import create_app
from reconciliation.vision_workflow import load, run
from tests.browser import browser_options
from tests.http_server import TestServer
from tests.unit import test_content_review as fixtures


class RegenerationBrowserTests(unittest.TestCase):
    def test_background_indicator_and_automatic_refresh(self):
        """Keep the page usable while a queued model call replaces old results."""
        fixture = fixtures.ContentPageTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        content_review.prepare(fixture.review)
        work = fixture.manifest.parent / "review"
        index, state = load(work)
        run(work, index, state, fixtures.FixtureReviewer(), extraction_only=True)
        release = threading.Event()

        class Reviewer(fixtures.FixtureReviewer):
            def ask(self, prompt, schema, images=()):
                """Return changed relevance only after the UI has shown progress."""
                if not release.wait(timeout=20):
                    raise AssertionError("Browser did not release the model fixture")
                result = super().ask(prompt, schema, images)
                result["supporting_evidence_reason"] = "KWSP contribution report can explain a payment."
                return result

        server = TestServer(("127.0.0.1", 0), create_app(fixture.review, "test-token"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with patch("dashboard.content_review.CodexReviewer", side_effect=lambda *args, **kwargs: Reviewer()), sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/extraction-review")
                button = page.locator("#regenerate-extraction")
                expect(button).to_be_enabled()
                button.click()
                expect(page.locator("#regeneration-status")).to_contain_text("background")
                expect(button).to_be_disabled()
                expect(page.locator("#regeneration-status")).to_have_attribute("aria-busy", "true")
                expect(page.locator("#accept-receipts")).to_be_disabled()
                page.locator("#next-document").click()
                expect(button).to_be_enabled()
                page.locator("#previous-document").click()
                expect(button).to_be_disabled()
                release.set()
                expect(page.locator("#supporting-evidence")).to_contain_text("KWSP contribution report", timeout=10000)
                expect(page.locator("#regeneration-status")).to_contain_text("complete")
                expect(button).to_be_enabled()
                expect(page.locator("#accept-receipts")).to_be_enabled()
                page.screenshot(path=str(Path(__file__).resolve().parents[2] / ".tools/regeneration-review.png"))
                page.reload()
                expect(page.locator("#regeneration-status")).to_contain_text("complete")
                self.assertFalse(errors)
            finally:
                release.set()
                worker = getattr(fixture.review, "content_thread", None)
                if worker:
                    worker.join(timeout=5)
                browser.close()
