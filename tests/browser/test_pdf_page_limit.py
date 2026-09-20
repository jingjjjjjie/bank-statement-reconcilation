"""Walk through PDF threshold settings and whole-document review using isolated fixtures."""
import threading
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from dashboard.review import Review
from dashboard.routes import create_app
from reconciliation import vision_workflow
from reconciliation.review_settings import load_config
from tests.browser import browser_options
from tests.http_server import TestServer
from tests.unit import test_pdf_document as fixtures


class PdfPageLimitBrowserTests(unittest.TestCase):
    def test_save_reload_and_review_whole_pdf(self):
        """Save the limit without erasing results and accept one cross-page piece on desktop/mobile."""
        fixture = fixtures.PdfDocumentTests()
        self.addCleanup(fixture.doCleanups)
        work, index, state = fixture.prepare_pdf(3)
        engine = fixtures.Reviewer(3)
        vision_workflow.run(work, index, state, engine, extraction_only=True)
        self.assertEqual(len(engine.calls), 1)
        review = Review(Path(index['manifest']), work.parent / 'data')
        review.config_path = Path(index['config_path'])
        server = TestServer(('127.0.0.1', 0), create_app(review, 'test-token'))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        output = Path(__file__).resolve().parents[2] / '.tools/pdf-page-limit'
        output.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options(), args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            base = f'http://127.0.0.1:{server.server_port}'
            page.goto(base + '/settings')
            limit = page.get_by_label('Whole-document PDF page limit', exact=False)
            expect(limit).to_have_value('5')
            expect(page.locator('#call-example')).to_contain_text('pause before request 1001')
            limit.fill('6')
            page.get_by_role('button', name='Save settings', exact=True).click()
            expect(page.locator('#save-state')).to_have_text('All settings saved')
            self.assertEqual(load_config(review.config_path)['pdf_whole_document_max_pages'], 6)
            expect(page.locator('#settings-refresh')).to_be_hidden()
            page.reload()
            expect(limit).to_have_value('6')
            limit.fill('0')
            self.assertFalse(limit.evaluate('(element) => element.validity.valid'))
            page.get_by_role('button', name='Discard changes', exact=True).click()
            expect(limit).to_have_value('6')
            page.screenshot(path=str(output / 'settings-desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            help_button = page.get_by_role('button', name='How to use this page')
            expect(help_button).to_have_count(1)
            help_button.click()
            expect(page.get_by_role('tooltip')).to_contain_text('defaults to 5')
            panel = page.get_by_role('tooltip').bounding_box()
            self.assertGreaterEqual(panel['x'], 0)
            self.assertLessEqual(panel['x'] + panel['width'], 390)
            page.keyboard.press('Escape')
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            expect(page.get_by_role('navigation', name='Main navigation')).to_have_count(1)
            page.screenshot(path=str(output / 'settings-mobile.png'), full_page=True)
            page.goto(base + '/extraction-review')
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(1)
            expect(page.locator('[data-field="total"]')).to_have_value('45.00')
            page.locator('.piece-details summary').click()
            expect(page.locator('[data-field="source_units"]')).to_have_value('1\n2\n3')
            expect(page.locator('[data-field="limitations"]')).to_have_count(0)
            expect(page.locator('input[data-field="currency"]')).to_have_value('MYR')
            page.locator('input[data-field="currency"]').fill('RM')
            page.locator('#accept-receipts').click()
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Extraction accepted')
            page.reload()
            expect(page.locator('#receipt-pieces fieldset')).to_have_count(1)
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Extraction accepted')
            expect(page.locator('input[data-field="currency"]')).to_have_value('MYR')
            expect(page.locator('#original-preview img')).to_be_visible()
            page.wait_for_function("document.querySelector('#original-preview img')?.naturalWidth > 0")
            page.screenshot(path=str(output / 'whole-pdf-review-mobile.png'), full_page=True)
            self.assertEqual(errors, [])
            browser.close()
