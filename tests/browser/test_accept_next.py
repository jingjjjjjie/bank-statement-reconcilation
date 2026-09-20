"""Check fast, save-confirmed extraction navigation with twelve synthetic documents."""
import json
import threading
import unittest

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from reconciliation.duplicate_workflow import fingerprint
from tests.browser import browser_options
from tests.http_server import TestServer
from tests.unit import test_receipt_matching as fixtures


class AcceptNextTests(unittest.TestCase):
    def test_save_failure_then_next_and_numbered_groups(self):
        """Keep failed edits, prevent double saves, and open only the next preview."""
        fixture = fixtures.ReceiptMatchingTests()
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
            fixture.index['documents'][digest] = {'paths': [str(source)], 'error': None,
                'units': [{'label': 'image 1', 'image': None}]}
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
            page.on('request', lambda request: previews.append(request.url)
                    if '/api/extraction-preview?' in request.url else None)
            page.goto(f'http://127.0.0.1:{server.server_port}/extraction-review')
            expect(page.locator('#current-document-name')).to_have_text('receipt-1.png')
            expect(page.locator('#original-preview img')).to_be_visible()
            expect(page.locator('#document-buttons button')).to_have_count(10)
            expect(page.locator('select#receipt-unit')).to_have_count(0)
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Not reviewed')
            expect(page.locator('#accept-receipts')).to_have_text('Accept')
            page.locator('[data-field="total"]').first.fill('42.00')
            page.route('**/api/receipts/accept', lambda route: held.append(route))
            page.locator('#accept-receipts').click()
            expect(page.locator('#accept-receipts')).to_have_text('Saving…')
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
            expect(page.locator('#accept-receipts')).to_have_text('Saving…')
            held.pop().continue_()
            expect(page.locator('#accept-receipts')).to_have_text('Undo accept')
            expect(page.locator('#receipt-unit')).to_have_value(keys[0])
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Extraction accepted')
            page.locator('#accept-receipts').click()
            expect(page.locator('#accept-receipts')).to_have_text('Accept')
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Not reviewed')
            expect(page.locator('[data-field="total"]').first).to_have_value('42.00')
            page.reload()
            expect(page.locator('#accept-receipts')).to_have_text('Accept')
            expect(page.locator('[data-field="total"]').first).to_have_value('42.00')
            previews.clear()
            page.locator('#next-review-document').click()
            expect(page.locator('#receipt-unit')).to_have_value(keys[1])
            expect(page.locator('#current-document-name')).to_have_text('receipt-2.png')
            expect(page.locator('#original-preview img')).to_be_visible()
            self.assertEqual(len(previews), 1)
            self.assertIn(keys[1].split(':')[0], previews[0])
            self.assertEqual(held, [])  # Next must not submit an acceptance.
            page.locator('#discard-document').click()
            expect(page.locator('#receipt-unit')).to_have_value(keys[1])
            expect(page.locator('#document-buttons button').nth(1)).to_have_class('trash')
            page.get_by_role('button', name='Document 2, trash', exact=True).click()
            expect(page.locator('#receipt-unit-status')).to_contain_text('Trash')
            expect(page.locator('#accept-receipts')).to_be_hidden()
            page.reload()
            expect(page.get_by_role('button', name='Document 2, trash', exact=True)).to_be_visible()
            page.get_by_role('button', name='Document 2, trash', exact=True).click()
            page.get_by_role('button', name='Undo discard', exact=True).click()
            expect(page.locator('#accept-receipts')).to_be_visible()
            expect(page.locator('#receipt-unit')).to_have_value(keys[1])
            expect(page.get_by_role('button', name='Document 2, not reviewed', exact=True)).to_be_visible()
            page.get_by_role('button', name='Next 10 documents', exact=True).click()
            expect(page.locator('#document-buttons button')).to_have_count(2)
            expect(page.locator('#current-document-name')).to_have_text('receipt-11.png')
            expect(page.locator('#next-document')).to_be_disabled()
            page.get_by_role('button', name='Previous 10 documents', exact=True).click()
            expect(page.locator('#document-buttons button')).to_have_count(10)
            expect(page.locator('[data-field="total"]').first).to_have_value('42.00')
            page.locator('[data-field="total"]').first.fill('41.00')
            page.locator('#accept-all-receipts').click()
            expect(page.locator('#review-progress')).to_have_text('12 of 12 reviewed')
            expect(page.locator('[data-field="total"]').first).to_have_value('41.00')
            page.reload()
            expect(page.locator('#review-progress')).to_have_text('12 of 12 reviewed')
            expect(page.locator('[data-field="total"]').first).to_have_value('41.00')
            expect(page.locator('#accept-receipts')).to_have_text('Undo accept')
            expect(page.locator('#accept-receipts')).to_be_enabled()
            page.locator('[data-field="total"]').first.fill('40.00')
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Unsaved changes')
            expect(page.locator('#accept-receipts')).to_have_text('Save changes')
            expect(page.locator('#accept-receipts')).to_be_enabled()
            page.locator('#accept-receipts').click()
            expect(page.locator('#accept-receipts')).to_contain_text('Saving')
            held.pop().continue_()
            expect(page.locator('#accept-receipts')).to_have_text('Undo accept')
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Extraction accepted')
            saved = json.loads((fixture.work / 'receipt-matches.json').read_text())
            self.assertEqual(len(saved['extractions']), 12)
            self.assertEqual(saved['matches'], {})
            page.locator('[data-field="total"]').first.fill('39.00')
            page.once('dialog', lambda dialog: dialog.dismiss())
            page.locator('#next-review-document').click()
            expect(page.locator('#receipt-unit')).to_have_value(keys[0])
            expect(page.locator('[data-field="total"]').first).to_have_value('39.00')
            page.once('dialog', lambda dialog: dialog.accept())
            page.locator('#next-review-document').click()
            expect(page.locator('#receipt-unit')).to_have_value(keys[1])
            page.get_by_role('button', name='Next 10 documents', exact=True).click()
            page.locator('#next-review-document').click()
            expect(page.locator('#receipt-unit')).to_have_value(keys[11])
            expect(page.locator('#next-review-document')).to_be_disabled()
            page.set_viewport_size({'width': 390, 'height': 844})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            self.assertEqual(errors, [])
            browser.close()
