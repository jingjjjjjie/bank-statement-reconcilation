"""Edit exported PARTICULAR wording without changing evidence decisions."""

import io
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from openpyxl import load_workbook
from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from dashboard.services.matching import final_review
from tests.browser import browser_options
from tests.fixtures.final_review import FinalReviewFixture
from tests.http_server import TestServer


class ExportDescriptionTests(unittest.TestCase):
    def test_unicode_description_uses_character_limit(self):
        """A valid 4,000-character description may exceed the default control request byte limit."""
        with sync_playwright() as playwright:
            client = playwright.request.new_context(base_url=self.url)
            session = client.get('/api/session').json()
            snapshot = client.get('/api/matching').json()
            text = '费用' * 2000
            response = client.post(
                '/api/matching-description',
                data={
                    'bank_id': 'B1',
                    'description': text,
                    'binding': snapshot['binding'],
                    'version': snapshot['version'],
                },
                headers={'X-Review-Token': session['token'], 'X-Review-Id': session['review_id']},
            )
            self.assertEqual(response.status, 200, response.text())
            self.assertEqual(response.json()['particular'], text)
            client.dispose()

    def setUp(self):
        """Serve a synthetic ledger containing an approved and two pending transactions."""
        fixture = FinalReviewFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        final_review.decide(fixture.review, fixture.request())
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {'name': 'Synthetic export', 'period': 'December'}
        fixture.enable_review_navigation()
        fixture.review.completion = lambda: {'complete': False}
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test-token', SimpleNamespace()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f'http://127.0.0.1:{server.server_port}'

    def test_save_cancel_reset_and_export_desktop_and_mobile(self):
        """Pencil edits reach both workbooks; cancellation, reset, focus and narrow layout work."""
        before = deepcopy(final_review.context(self.fixture.review)[1]['decisions'])
        screenshots = Path('.tools/export-description')
        screenshots.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.url + '/final-report')
            expect(page.locator('.report-table tbody tr')).to_have_count(3)
            expect(page.get_by_role('columnheader', name='Review', exact=True)).to_have_count(0)
            expect(page.get_by_role('columnheader', name='Description', exact=True)).to_be_visible()
            help_button = page.get_by_role('button', name='How to use this page')
            expect(help_button).to_have_count(1)
            help_button.hover()
            expect(page.get_by_role('tooltip')).to_contain_text('PARTICULAR in Excel')
            page.keyboard.press('Escape')
            expect(page.get_by_role('tooltip')).not_to_be_visible()
            expect(page.locator('.particular-text').first).to_have_text('Receipt : 10.00')
            trigger = page.get_by_role('button', name='Edit description for B1', exact=True)
            expect(trigger.locator('img')).to_have_js_property('complete', True)
            self.assertGreater(trigger.locator('img').evaluate('(image) => image.naturalWidth'), 0)
            trigger.click()
            editor = page.get_by_role('textbox', name='Description', exact=True)
            expect(editor).to_be_focused()
            editor.fill('Cancelled text')
            page.get_by_role('button', name='Cancel', exact=True).click()
            expect(trigger).to_be_focused()
            expect(page.locator('.particular-text').first).to_have_text('Receipt : 10.00')
            trigger.click()
            text = 'Office stationery\nDecember reimbursement'
            editor.fill(text)
            page.screenshot(path=str(screenshots / '02-editor-desktop.png'), full_page=True)
            page.get_by_role('button', name='Save', exact=True).click()
            expect(page.locator('.description-dialog')).not_to_be_visible()
            expect(page.locator('.particular-text').first).to_have_text(text)
            page.reload()
            expect(page.locator('.particular-text').first).to_have_text(text)
            page.screenshot(path=str(screenshots / '01-export-desktop.png'), full_page=True)
            for paths in ('true', 'false'):
                response = page.request.get(self.url + '/api/matching-workbook?include_evidence_paths=' + paths)
                self.assertEqual(response.status, 200)
                book = load_workbook(io.BytesIO(response.body()))
                self.assertEqual(book.active['G6'].value, text)
                self.assertEqual(book.active['K6'].value, 'OK')
                book.close()
            page.get_by_label('Find a transaction').fill('December reimbursement')
            expect(page.locator('.report-table tbody tr')).to_have_count(1)
            page.get_by_label('Find a transaction').fill('')
            page.set_viewport_size({'width': 390, 'height': 844})
            help_button.click()
            expect(page.get_by_role('tooltip')).to_be_visible()
            bounds = page.get_by_role('tooltip').bounding_box()
            self.assertGreaterEqual(bounds['x'], 0)
            self.assertLessEqual(bounds['x'] + bounds['width'], 390)
            page.keyboard.press('Escape')
            page.screenshot(path=str(screenshots / '03-export-mobile.png'), full_page=True)
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.get_by_role('button', name='Edit description for B1', exact=True).click()
            page.get_by_role('button', name='Reset to generated').click()
            expect(editor).to_have_value('Receipt : 10.00')
            page.screenshot(path=str(screenshots / '04-editor-mobile.png'), full_page=True)
            self.assertTrue(page.evaluate('document.querySelector(".description-dialog").scrollWidth <= innerWidth'))
            for _ in range(8):
                page.keyboard.press('Tab')
                self.assertTrue(
                    page.evaluate('document.querySelector(".description-dialog").contains(document.activeElement)')
                )
            page.get_by_role('button', name='Save', exact=True).click()
            expect(page.locator('.particular-text').first).to_have_text('Receipt : 10.00')
            page.get_by_role('button', name='Edit description for B2', exact=True).click()
            editor.fill('Bank fee')
            page.get_by_role('button', name='Save', exact=True).click()
            expect(page.locator('.particular-text').nth(1)).to_have_text('Bank fee')
            expect(page.locator('.report-status').nth(1)).to_have_text('No supporting')
            expect(page.get_by_role('navigation', name='Main navigation')).to_have_count(1)
            self.assertEqual(final_review.context(self.fixture.review)[1]['decisions'], before)
            self.assertEqual(errors, [])
            browser.close()

    def test_conflict_keeps_draft_and_does_not_overwrite_another_save(self):
        """A second ledger write rejects an old editor version and preserves its local text."""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page()
            page.goto(self.url + '/final-report')
            page.get_by_role('button', name='Edit description for B1', exact=True).click()
            editor = page.get_by_role('textbox', name='Description', exact=True)
            editor.fill('Keep this draft')
            final_review.decide(self.fixture.review, self.fixture.request(bank='B2', action='deny'))
            page.get_by_role('button', name='Save', exact=True).click()
            expect(page.locator('.description-error')).to_contain_text('report changed')
            expect(editor).to_have_value('Keep this draft')
            self.assertNotIn('descriptions', final_review.context(self.fixture.review)[1])
            page.keyboard.press('Escape')
            expect(page.locator('.description-dialog')).not_to_be_visible()
            browser.close()
