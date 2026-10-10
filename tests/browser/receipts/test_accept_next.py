"""Check fast, save-confirmed extraction navigation with twelve synthetic documents."""

import json
import threading
import unittest

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from reconciliation.intake.duplicates import fingerprint
from tests.browser import browser_options
from tests.fixtures import receipt_review as receipt_review_fixture
from tests.http_server import TestServer


class AcceptNextTests(unittest.TestCase):
    def test_save_failure_then_next_and_numbered_groups(self):
        """Keep failed edits, prevent double saves, and open only the next preview."""
        fixture = receipt_review_fixture.ReceiptReviewFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.index['documents'] = {}
        fixture.state['units'] = {}
        fixture.state.update(screens={}, pairs={})
        keys = []
        for number in range(12):
            source = fixture.base / f'receipt-{number + 1}.png'
            Image.new('RGB', (160, 220), (number * 15, 100, 100)).save(source)
            digest = fingerprint(source)
            keys.append(digest + ':0')
            fixture.index['documents'][digest] = {
                'paths': [str(source)],
                'error': None,
                'units': [{'label': 'image 1', 'image': None}],
            }
            fixture.state['units'][keys[-1]] = {'readable': True, 'receipts': fixture.pieces}
        (fixture.work / 'index.json').write_text(json.dumps(fixture.index))
        fixture.state['index_sha256'] = fingerprint(fixture.work / 'index.json')
        fixture.save_state()
        fixture.review.manifest = {}
        fixture.review.data = fixture.base / 'dashboard-data'
        fixture.review.data.mkdir()
        fixture.review.root = fixture.base
        fixture.review.workspace = lambda: {'name': 'Fixture', 'period': 'December'}
        fixture.review.workflow_checks = lambda: (False, False, False)
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test-token'))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options(), args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors, held, previews = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on(
                'request',
                lambda request: previews.append(request.url) if '/api/extraction-preview?' in request.url else None,
            )
            page.goto(f'http://127.0.0.1:{server.server_port}/extraction-review')
            expect(page.locator('#current-document-name')).to_have_text('receipt-1.png')
            expect(page.locator('#original-preview img')).to_be_visible()
            expect(page.locator('#document-buttons button')).to_have_count(10)
            expect(page.locator('select#receipt-unit')).to_have_count(0)
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Not reviewed')
            expect(page.locator('#accept-receipts')).to_have_text('Accept')
            expect(page.locator('.editor-footer button')).to_have_count(3)
            expect(page.locator('.extraction-original #accept-receipts')).to_have_count(1)
            for width in [1536, 390, 320]:
                page.set_viewport_size({'width': width, 'height': 900})
                buttons = page.locator('.editor-footer button')
                for index in range(3):
                    bounds = buttons.nth(index).bounding_box()
                    self.assertEqual(bounds['height'], 34)
                    self.assertLessEqual(bounds['width'], 140)
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.locator('[data-field="total"]').first.fill('42.00')
            page.route('**/api/receipts/accept', lambda route: held.append(route))
            page.locator('#accept-receipts').click()
            expect(page.locator('#accept-receipts')).to_contain_text('Saving')
            expect(page.locator('#accept-receipts')).to_be_disabled()
            expect(page.locator('#document-buttons button').first).to_be_disabled()
            self.assertEqual(len(held), 1)
            held.pop().fulfill(status=500, content_type='application/json', body='{"error":"Save failed"}')
            expect(page.locator('#receipt-error')).to_have_text('Save failed')
            expect(page.locator('[data-field="total"]').first).to_have_value('42.00')
            expect(page.locator('#receipt-unit')).to_have_value(keys[0])
            expect(page.locator('#accept-receipts')).to_be_enabled()
            previews.clear()
            page.locator('#accept-receipts').click()
            expect(page.locator('#accept-receipts')).to_contain_text('Saving')
            held.pop().continue_()
            expect(page.locator('#receipt-unit')).to_have_value(keys[1])
            expect(page.locator('#current-document-name')).to_have_text('receipt-2.png')
            expect(page.locator('#original-preview img')).to_be_visible()
            self.assertEqual(len(previews), 1)
            self.assertIn(keys[1].split(':')[0], previews[0])
            self.assertEqual(held, [])
            page.unroute('**/api/receipts/accept')
            saved = json.loads((fixture.work / 'receipt-matches.json').read_text())
            self.assertEqual(saved['extractions'][keys[0]]['receipts'][0]['total'], '42.00')
            self.assertEqual(saved['matches'], {})
            page.locator('#discard-document').click()
            expect(page.locator('#receipt-unit')).to_have_value(keys[2])
            page.get_by_role('button', name='Document 2, trash', exact=True).click()
            expect(page.locator('#add-receipt')).to_be_disabled()
            expect(page.locator('#discard-document')).to_have_text('Rejected · Undo')
            self.assertEqual(page.locator('#discard-document').evaluate('(e)=>getComputedStyle(e).backgroundColor'), 'rgb(179, 62, 53)')
            self.assertEqual(page.locator('#discard-document').evaluate('(e)=>getComputedStyle(e).color'), 'rgb(255, 255, 255)')
            page.reload()
            page.get_by_role('button', name='Document 2, trash', exact=True).click()
            expect(page.locator('#receipt-unit')).to_have_value(keys[1])
            page.locator('#accept-receipts').click()
            expect(page.locator('#receipt-unit')).to_have_value(keys[2])
            page.get_by_role('button', name='Document 2, reviewed', exact=True).click()
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(2)
            page.locator('#discard-document').click()
            page.get_by_role('button', name='Document 2, trash', exact=True).click()
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Discarded')
            page.get_by_role('button', name='Rejected · Undo', exact=True).click()
            expect(page.get_by_role('button', name='Document 2, reviewed', exact=True)).to_be_visible()
            page.locator('#document-buttons button').first.click()
            expect(page.locator('#accept-receipts')).to_have_text('Accepted · Undo')
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Extraction accepted')
            page.locator('#accept-receipts').click()
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Not reviewed')
            expect(page.locator('[data-field="total"]').first).to_have_value('42.00')
            page.reload()
            expect(page.locator('[data-field="total"]').first).to_have_value('42.00')
            page.locator('[data-field="total"]').first.fill('41.00')
            page.once('dialog', lambda dialog: dialog.dismiss())
            page.locator('#next-review-document').click()
            expect(page.locator('#receipt-unit')).to_have_value(keys[0])
            expect(page.locator('[data-field="total"]').first).to_have_value('41.00')
            page.get_by_role('button', name='Review Extraction options', exact=True).click()
            page.locator('#accept-all-receipts').click()
            expect(page.locator('#review-progress')).to_have_text('12 of 12 reviewed')
            page.reload()
            expect(page.locator('#review-progress')).to_have_text('12 of 12 reviewed')
            expect(page.locator('[data-field="total"]').first).to_have_value('41.00')
            page.get_by_role('button', name='Next 10 documents', exact=True).click()
            expect(page.locator('#document-buttons button')).to_have_count(2)
            expect(page.locator('#receipt-unit')).to_have_value(keys[10])
            page.locator('#next-review-document').click()
            expect(page.locator('#receipt-unit')).to_have_value(keys[11])
            expect(page.locator('#next-review-document')).to_be_disabled()
            expect(page.locator('#next-document')).to_be_disabled()
            page.get_by_role('button', name='Previous 10 documents', exact=True).click()
            expect(page.locator('#document-buttons button')).to_have_count(10)
            page.set_viewport_size({'width': 390, 'height': 844})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            self.assertEqual(errors, [])
            browser.close()
