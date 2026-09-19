"""Verify shared page help against the real Vue build with Python Playwright."""
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from dashboard.review import Review
from dashboard.routes import create_app
from reconciliation.duplicate_workflow import organize
from tests.browser import browser_options
from tests.http_server import TestServer


class PageHelpTests(unittest.TestCase):
    def test_help_on_every_page(self):
        """Check hover, focus, dismissal, touch and viewport bounds for each page."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / 'inputs'
            inputs.mkdir()
            (inputs / 'one.txt').write_text('fixture')
            manifest = root / 'manifest.json'
            organize(inputs, manifest)
            review = Review(manifest, root / 'data')
            app = create_app(review, 'test-token')
            server = TestServer(('127.0.0.1', 0), app)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(**browser_options(), args=['--no-sandbox'])
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    base = f'http://127.0.0.1:{server.server_port}'
                    routes = ['source', 'bank', 'documents', 'review', 'settings',
                              'complete', 'extraction-review', 'matching', 'final-report']
                    for route in routes:
                        with self.subTest(route=route):
                            page.goto(f'{base}/{route}')
                            button = page.get_by_role('button', name='How to use this page')
                            expect(button).to_have_count(1)
                            expect(button).to_be_visible()
                            tooltip = page.locator('.page-help-panel')
                            expect(tooltip).to_be_hidden()
                            button.hover()
                            expect(tooltip).to_be_visible()
                            self.assertTrue(tooltip.inner_text().strip())
                            tooltip.hover()
                            expect(tooltip).to_be_visible()
                            page.keyboard.press('Escape')
                            expect(tooltip).to_be_hidden()
                            button.hover()
                            expect(tooltip).to_be_visible()
                            page.mouse.move(0, 0)
                            expect(tooltip).to_be_hidden()
                            button.focus()
                            expect(tooltip).to_be_visible()
                            page.keyboard.press('Escape')
                            expect(tooltip).to_be_hidden()
                            page.set_viewport_size({'width': 390, 'height': 844})
                            button.click()
                            expect(tooltip).to_be_visible()
                            box = tooltip.bounding_box()
                            self.assertGreaterEqual(box['x'], 0)
                            self.assertLessEqual(box['x'] + box['width'], 390)
                            self.assertGreaterEqual(box['y'], 0)
                            self.assertLessEqual(box['y'] + box['height'], 844)
                            expect(page.get_by_role('navigation', name='Main navigation')).to_have_count(1)
                            expect(page.locator('.app-header a[href="/source"] .header-step.complete svg')).to_have_count(1)
                            expect(page.locator('.app-header a[href="/bank"] .header-step')).to_have_text('4')
                            expect(page.locator('#workflow-progress, .page-navigation')).to_have_count(0)
                            expect(page.get_by_role('link', name='View documents')).to_have_count(0)
                            page.set_viewport_size({'width': 1440, 'height': 1000})
                    # The same route can render the automatic duplicate report.
                    review.manifest['Mode'] = 'exact_report'
                    page.goto(f'{base}/review')
                    expect(page.locator('#page-help-ExactReport')).to_have_count(1)
                    page.get_by_role('button', name='How to use this page').hover()
                    expect(page.get_by_role('tooltip')).to_contain_text('no selection is needed')
                    page.locator('.app-header a[href="/documents"]').click()
                    expect(page).to_have_url(base + '/documents')
                    expect(page.get_by_role('button', name='How to use this page')).to_have_count(1)
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
