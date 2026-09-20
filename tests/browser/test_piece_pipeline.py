"""Verify piece editing, search and live-ledger activation with real local HTTP."""
import json
import threading
import unittest
from pathlib import Path

from PIL import Image
import pymupdf
from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from reconciliation.duplicate_workflow import fingerprint
from tests.browser import browser_options
from tests.http_server import TestServer
from tests.unit import test_receipt_matching as fixtures


class PiecePipelineBrowserTests(unittest.TestCase):
    def test_add_remove_search_and_live_matching(self):
        """Piece identities survive editing and search reaches current matching evidence."""
        fixture = fixtures.ReceiptMatchingTests()
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
        review.workflow_checks = lambda: (False, False, False)
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
            expect(page.get_by_label('Piece type', exact=True)).to_have_count(2)
            expect(page.get_by_label('Document type', exact=True)).to_have_count(0)
            expect(page.locator('[data-field="limitations"]')).to_have_count(0)
            (Path(__file__).resolve().parents[2] / '.tools/field-removal').mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(__file__).resolve().parents[2] / '.tools/field-removal/extraction-desktop.png'), full_page=True)
            page.locator('[data-field="references"]').first.fill('receipt: 000007')
            page.locator('#accept-receipts').click()
            expect(page.locator('#receipt-unit-status')).to_contain_text('Extraction accepted.')
            original = json.loads((fixture.work / 'receipt-matches.json').read_text())['extractions'][digest + ':0']['receipts']
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
            expect(page.locator('#receipt-unit-status')).to_contain_text('Extraction accepted.')
            page.reload()
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(2)
            page.set_viewport_size({'width': 390, 'height': 844})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.screenshot(path=str(Path(__file__).resolve().parents[2] / '.tools/field-removal/extraction-mobile.png'), full_page=True)
            page.goto(f'http://127.0.0.1:{server.server_port}/matching')
            page.locator('#use-pieces').click()
            expect(page.locator('#generate-matches')).to_be_visible()
            expect(page.locator('#matching-counts')).to_have_text('0 of 3 reviewed')
            page.locator('#document-tab').click()
            page.locator('#document-query').fill('Delivery piece')
            expect(page.locator('#unmatched-list')).to_contain_text('Delivery piece')
            page.screenshot(path=str(Path(__file__).resolve().parents[2] / '.tools/field-removal/matching-mobile.png'), full_page=True)
            self.assertFalse(errors)
            browser.close()
