"""Keep saved primary date corrections consistent with typed date evidence."""

import threading
import unittest

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from reconciliation.extraction.results.pieces import canonical
from tests.browser import browser_options
from tests.fixtures.receipt_review import ReceiptReviewFixture
from tests.http_server import TestServer


class DateCorrectionTests(unittest.TestCase):
    def test_change_and_clear_primary_date_preserve_other_date_facts(self):
        """Accept, reload and inspect canonical facts after changing then clearing Date."""
        fixture = ReceiptReviewFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {'name': 'Fixture', 'period': 'December'}
        fixture.review.workflow_checks = lambda: (False, False, False)
        fixture.review.root = fixture.base
        fixture.review.data = fixture.base / 'dashboard-data'
        fixture.review.data.mkdir()
        other_date = {'type': 'due', 'value': '2025-12-20'}
        fixture.pieces[0].update(date='2025-12-01', dates=[{'type': 'date', 'value': '2025-12-01'}, other_date])
        fixture.save_state()
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test-token'))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{server.server_port}/extraction-review')
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(2)
            for value, expected_dates in (
                ('2025-12-02', [{'type': 'date', 'value': '2025-12-02'}, other_date]),
                ('', [other_date]),
            ):
                page.locator('.piece-details > summary').first.click()
                page.locator('[data-field="date"]').first.fill(value)
                page.locator('#accept-receipts').click()
                expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Extraction accepted')
                saved = fixture.view()['units'][0]['receipts'][0]
                self.assertEqual(saved['date'], value)
                self.assertEqual(canonical(saved)['dates'], expected_dates)
                page.reload()
                expect(page.locator('[data-field="date"]').first).to_have_value(value)
            browser.close()
