"""Exercise removal and recovery for assembled documents in the real editor."""
import json
import threading
import unittest
from PIL import Image
from playwright.sync_api import sync_playwright, expect
from dashboard.routes import create_app
from reconciliation.duplicate_workflow import fingerprint
from reconciliation.receipt_assembly import input_revision
from tests.browser import browser_options
from tests.http_server import TestServer
from tests.unit import test_receipt_matching as fixtures


class PieceRemovalTests(unittest.TestCase):
    def test_remove_generated_piece_and_recover_from_plain_text_failure(self):
        """Keep the removal draft after an HTTP error and save it intact on retry."""
        fixture = fixtures.ReceiptMatchingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source = fixture.base / 'four-page-invoice.pdf'
        pages = [Image.new('RGB', (200, 300), 'white') for _ in range(4)]
        pages[0].save(source, save_all=True, append_images=pages[1:])
        digest = fingerprint(source)
        document = {'id': digest, 'paths': [str(source)], 'error': None,
                    'units': [{'label': f'page {n}', 'image': None} for n in range(1, 5)]}
        fixture.index['documents'] = {digest: document}
        (fixture.work / 'index.json').write_text(json.dumps(fixture.index))
        fixture.state['index_sha256'] = fingerprint(fixture.work / 'index.json')
        fixture.state['units'] = {}
        fixture.state['assemblies'] = {digest: {
            'input_revision': input_revision(document, fixture.state), 'reviewed_units': [1, 2, 3, 4],
            'limitations': [], 'receipts': [{**piece, 'source_units': [1, 2, 3, 4], 'needs_review': False}
                                           for piece in fixture.pieces]}}
        fixture.save_state()
        fixture.review.manifest = {}
        fixture.review.root = fixture.base
        fixture.review.data = fixture.base / 'dashboard-data'
        fixture.review.workspace = lambda: {'name': 'Fixture', 'period': 'December'}
        fixture.review.workflow_checks = lambda: (False, False, False)
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test-token'))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{server.server_port}/extraction-review')
            expect(page.locator('#receipt-pieces fieldset:visible')).to_have_count(2)
            page.get_by_role('button', name='Select piece 2', exact=True).click()
            page.locator('#remove-piece').click()
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(1)
            page.locator('[data-field=total]').fill('273.48')
            page.route('**/api/receipts/accept', lambda route: route.fulfill(
                status=500, content_type='text/plain', body='Internal Server Error'))
            page.locator('#accept-receipts').click()
            expect(page.locator('#receipt-error')).to_contain_text('HTTP 500')
            expect(page.locator('[data-field=total]')).to_have_value('273.48')
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(1)
            page.unroute('**/api/receipts/accept')
            page.locator('#accept-receipts').click()
            expect(page.locator('#receipt-unit-status')).to_contain_text('Extraction accepted')
            page.reload()
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(1)
            expect(page.locator('[data-field=total]')).to_have_value('273.48')
            browser.close()
