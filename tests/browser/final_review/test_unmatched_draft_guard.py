"""Protect unsaved matching allocations when linking unmatched evidence."""

import threading
import unittest
from types import SimpleNamespace

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from tests.browser import browser_options
from tests.fixtures.final_review import FinalReviewFixture
from tests.http_server import TestServer


class UnmatchedDraftGuardTests(unittest.TestCase):
    def test_linking_same_or_other_transaction_requires_discard_confirmation(self):
        """Cancelling preserves the draft and tab; accepting opens the requested link."""
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
            page.get_by_role('button', name='Review options').click()
            page.locator('#document-tab').click()
            for destination in ('B1', 'B2'):
                page.locator('#unmatched-bank').select_option(destination)
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.locator('.unmatched-row').nth(1).get_by_role('button').click()
                expect(page.locator('#document-view')).to_be_visible()
                expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B1')
                expect(page.locator('[aria-label="Allocation D1"]')).to_have_value('4.00')
            page.once('dialog', lambda dialog: dialog.accept())
            page.locator('.unmatched-row').nth(1).get_by_role('button').click()
            expect(page.locator('#bank-view')).to_be_visible()
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B2')
            expect(page.locator('#selected-candidates [data-item-id="D2"]')).to_be_visible()
            self.assertFalse((fixture.project / 'final-review/decisions.json').exists())
            browser.close()
