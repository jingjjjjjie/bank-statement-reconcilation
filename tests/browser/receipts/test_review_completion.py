"""Check the header tick follows real saved accept, undo and discard actions."""

import threading
import unittest

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from tests.browser import browser_options
from tests.fixtures.receipt_review import ReceiptReviewFixture
from tests.http_server import TestServer


class ReviewCompletionBrowserTests(unittest.TestCase):
    def test_header_tracks_review_decisions(self):
        """Update the tick without reload and preserve it at mobile width and on reload."""
        fixture = ReceiptReviewFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        review = fixture.review
        review.manifest = {}
        review.root = fixture.base
        review.data = fixture.base / "dashboard-data"
        review.data.mkdir()
        review.workspace = lambda: {"name": "Fixture", "period": ""}
        review.workflow_checks = lambda: (False, False, False)
        fixture.state.update(screens={}, pairs={})
        fixture.save_state()
        server = TestServer(("127.0.0.1", 0), create_app(review, "fixture"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page.goto(f"http://127.0.0.1:{server.server_port}/extraction-review")
            tick = page.locator('.app-header a[href="/extraction-review"] .header-step.complete')
            expect(page.locator("#review-progress")).to_have_text("0 of 1 reviewed")
            expect(tick).to_have_count(0)
            # Returning to this cached page must not wait for another readiness request.
            checks = []
            page.on('request', lambda request: checks.append(request.url)
                    if request.url.endswith('/api/workflow-checks') else None)
            page.locator('.app-header a[href="/documents"]').click()
            expect(page.locator('#document-summary')).to_be_visible()
            page.wait_for_timeout(500)
            before = len(checks)
            page.locator('.app-header a[href="/extraction-review"]').click()
            expect(page.locator('#review-progress')).to_have_text('0 of 1 reviewed')
            self.assertEqual(len(checks), before)
            page.locator("#accept-receipts").click()
            expect(tick).to_have_count(1)
            page.locator("#accept-receipts").click()
            expect(tick).to_have_count(0)
            page.get_by_role("button", name="Reject", exact=True).click()
            expect(tick).to_have_count(1)
            page.set_viewport_size({"width": 390, "height": 844})
            tick.scroll_into_view_if_needed()
            expect(tick).to_be_visible()
            expect(page.get_by_role("navigation", name="Main navigation")).to_have_count(1)
            page.reload()
            expect(tick).to_have_count(1)
            page.get_by_role("button", name="Rejected · Undo", exact=True).click()
            expect(tick).to_have_count(0)
            browser.close()
