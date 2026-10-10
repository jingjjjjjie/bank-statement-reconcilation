"""Verify piece editing, search and live-ledger activation with real local HTTP."""

import json
import threading
import unittest

import pymupdf
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from reconciliation.core.paths import WORKSPACE
from reconciliation.intake.duplicates import fingerprint
from tests.browser import browser_options
from tests.fixtures import receipt_review as receipt_review_fixture
from tests.http_server import TestServer


class PiecePipelineBrowserTests(unittest.TestCase):
    def test_add_remove_search_and_live_matching(self):
        """Piece identities survive editing and search reaches current matching evidence."""
        fixture = receipt_review_fixture.ReceiptReviewFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        Image.new('RGB', (400, 500), 'white').save(fixture.source)
        digest = fingerprint(fixture.source)
        fixture.index['documents'][digest] = fixture.index['documents'].pop(fixture.digest)
        fixture.state['units'][digest + ':0'] = fixture.state['units'].pop(fixture.key)
        fixture.state['units'][digest + ':0']['review_warnings'] = ['Text and vision disagree; verify the original.']
        (fixture.work / 'index.json').write_text(json.dumps(fixture.index))
        fixture.state['index_sha256'] = fingerprint(fixture.work / 'index.json')
        fixture.save_state()
        bank = fixture.base / 'bank.pdf'
        before = fingerprint(bank)
        with pymupdf.open() as document:
            document.new_page().insert_text((40, 40), 'Fixture bank statement')
            document.save(bank)
        master = fixture.base / 'bank-output/master_statement.csv'
        master.write_text(master.read_text().replace(before, fingerprint(bank)))
        review = fixture.review
        review.root, review.data, review.manifest = fixture.base, fixture.base / 'data', {}
        review.data.mkdir()
        review.workspace = lambda: {'name': 'Fixture', 'period': ''}
        review.workflow_checks = lambda: (False, False, True)
        server = TestServer(('127.0.0.1', 0), create_app(review, 'fixture'))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options(), args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/extraction-review')
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(2)
            expect(page.locator('#receipt-unit-status')).to_contain_text('Text and vision disagree')
            page.locator('[data-field="payee"]').first.fill('Merchant A')
            page.locator('.piece-details summary').first.click()
            expect(page.get_by_label('Type', exact=True)).to_have_count(2)
            expect(page.get_by_label('Document type', exact=True)).to_have_count(0)
            expect(page.locator('[data-field="limitations"]')).to_have_count(0)
            (WORKSPACE / '.tools/field-removal').mkdir(parents=True, exist_ok=True)
            page.screenshot(
                path=str(WORKSPACE / '.tools/field-removal/extraction-desktop.png'),
                full_page=True,
            )
            page.locator('[data-field="references"]').first.fill('receipt: 000007')
            page.locator('#accept-receipts').click()
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Extraction accepted')
            expect(page.locator('#merge-piece')).to_have_count(0)
            page.get_by_role('button', name='Select piece 2', exact=True).click()
            page.locator('#remove-piece').click()
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(1)
            expect(page.locator('#split-piece')).to_have_count(0)
            page.locator('#add-receipt').click()
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(2)
            page.locator('[data-field="total"]').first.fill('45.00')
            page.locator('[data-field="total"]').nth(1).fill('15.00')
            page.locator('[data-field="brief_description"]').nth(1).fill('Delivery piece')
            page.locator('#accept-receipts').click()
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Extraction accepted')
            page.reload()
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(2)
            page.set_viewport_size({'width': 390, 'height': 844})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.screenshot(
                path=str(WORKSPACE / '.tools/field-removal/extraction-mobile.png'),
                full_page=True,
            )
            page.goto(f'http://127.0.0.1:{server.server_port}/matching')
            expect(page.locator('#generate-matches')).to_have_count(0)
            page.route('**/api/bank-statement', lambda route: route.fulfill(json={'available': False}))
            page.route('**/api/source', lambda route: route.fulfill(json={'bank': None}))
            page.locator('.app-header a[href="/bank"]').click()
            page.locator('#load-final-matching').click()
            expect(page.locator('#load-final-matching')).to_be_disabled()
            expect(page.locator('#generate-matches')).to_be_visible()
            expect(page.locator('#generate-matches')).to_be_enabled()
            page.locator('.app-header a[href="/matching"]').click()
            expect(page.locator('#generate-matches, #matching-progress')).to_have_count(0)
            expect(page.locator('#document-tab, #document-view')).to_have_count(0)
            expect(page.locator('#bank-view')).to_be_visible()
            expect(page.locator('.transaction-number[aria-current]')).to_be_visible()
            page.locator('#toggle-candidate-search').click()
            page.locator('#candidate-query').fill('Delivery piece')
            expect(page.locator('#candidate-list')).to_contain_text('Delivery piece')
            page.screenshot(
                path=str(WORKSPACE / '.tools/field-removal/matching-mobile.png'),
                full_page=True,
            )
            self.assertFalse(errors)
            browser.close()
