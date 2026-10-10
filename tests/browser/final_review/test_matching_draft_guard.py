"""Protect unsaved matching allocations when changing transactions."""

import threading
import unittest
from types import SimpleNamespace

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from tests.browser import browser_options
from tests.fixtures.final_review import FinalReviewFixture
from tests.http_server import TestServer


class MatchingDraftGuardTests(unittest.TestCase):
    def test_next_transaction_requires_discard_confirmation(self):
        """Cancelling keeps the current draft; confirming opens the next transaction."""
        fixture = FinalReviewFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {'name': 'Fixture', 'period': 'December'}
        fixture.enable_review_navigation()
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test-token', SimpleNamespace()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{server.server_port}/matching')
            expect(page.locator('.transaction-number[aria-current]')).to_be_visible()
            page.locator('[aria-label="Edit allocation D1"]').click()
            allocation = page.get_by_role('textbox', name='Allocation D1', exact=True)
            allocation.fill('4.00')
            expect(page.locator('#document-tab, #document-view')).to_have_count(0)
            page.once('dialog', lambda dialog: dialog.dismiss())
            page.locator('#next-review-transaction').click()
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B1')
            expect(allocation).to_have_value('4.00')
            page.once('dialog', lambda dialog: dialog.accept())
            page.locator('#next-review-transaction').click()
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B2')
            browser.close()
