"""Check selection and responsive editing in a long extraction result."""
import json
import threading
import unittest
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from reconciliation.duplicate_workflow import fingerprint
from tests.browser import browser_options
from tests.http_server import TestServer
from tests.unit import test_receipt_matching as fixtures


class ReviewLayoutTests(unittest.TestCase):
    def test_twenty_one_pieces_and_selected_actions(self):
        """Keep every piece editable, target actions explicitly, and avoid mobile overlap."""
        fixture = fixtures.ReceiptMatchingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        Image.new('RGB', (600, 800), '#faf8f2').save(fixture.source)
        digest = fingerprint(fixture.source)
        fixture.index['documents'][digest] = fixture.index['documents'].pop(fixture.digest)
        raw = fixture.state['units'].pop(fixture.key)
        raw['receipts'] = [{**fixture.pieces[0], 'payee': f'Merchant {n + 1}',
                            'brief_description': f'Receipt {n + 1}'} for n in range(21)]
        fixture.state['units'][digest + ':0'] = raw
        (fixture.work / 'index.json').write_text(json.dumps(fixture.index))
        fixture.state['index_sha256'] = fingerprint(fixture.work / 'index.json')
        fixture.save_state()
        review = fixture.review
        review.root, review.manifest, review.data = fixture.base, {}, fixture.base / 'data'
        review.data.mkdir()
        review.workspace = lambda: {'name': 'Fixture', 'period': ''}
        review.workflow_checks = lambda: (False, False, False)
        server = TestServer(('127.0.0.1', 0), create_app(review, 'token'))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        folder = Path(__file__).resolve().parents[2] / '.tools/review-layout'
        folder.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options(), args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/extraction-review')
            expect(page.locator('#piece-count')).to_have_text('21 entries')
            expect(page.get_by_role('button', name='Split', exact=True)).to_have_count(0)
            expect(page.get_by_role('link', name='Download original')).to_have_attribute('download', 'photo.png')
            page.get_by_role('button', name='Select piece 21', exact=True).click()
            expect(page.locator('.active-piece .piece-number')).to_have_text('21')
            expect(page.locator('#merge-piece')).to_have_count(0)
            expect(page.locator('.piece-selection')).to_have_count(0)
            expect(page.get_by_role('button', name='+ Add entry', exact=True)).to_be_visible()
            page.locator('#add-receipt').click()
            expect(page.locator('#piece-count')).to_have_text('22 entries')
            expect(page.locator('.active-piece .piece-number')).to_have_text('22')
            page.locator('#remove-piece').click()
            expect(page.locator('#piece-count')).to_have_text('21 entries')
            expect(page.locator('[data-field="payee"]').last).to_have_value('Merchant 21')
            page.get_by_role('button', name='Select piece 1', exact=True).click()
            page.locator('.piece-details summary').first.click()
            page.screenshot(path=str(folder / 'desktop.png'))
            for width in (900, 390, 360):
                page.set_viewport_size({'width': width, 'height': 900})
                expect(page.get_by_role('heading', name='Review results', exact=True)).to_be_visible()
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                if width < 650:
                    page.locator('#accept-receipts').scroll_into_view_if_needed()
                    footer = page.locator('.editor-footer').bounding_box()
                    last = page.locator('#receipt-pieces fieldset').last.bounding_box()
                    self.assertGreaterEqual(footer['y'], last['y'] + last['height'])
                    page.locator('.entry-toolbar').scroll_into_view_if_needed()
                    page.screenshot(path=str(folder / f'mobile-{width}.png'))
            self.assertEqual(errors, [])
            browser.close()
