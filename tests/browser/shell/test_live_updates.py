"""Exercise real server-pushed updates across tabs without dropping unsaved edits."""

import threading
import unittest

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from tests.browser import browser_options
from tests.fixtures.receipt_review import ReceiptReviewFixture
from tests.http_server import TestServer


class LiveUpdateTests(unittest.TestCase):
    def test_other_tab_updates_documents_without_progress_polling(self):
        """Accepting evidence updates an idle document tab through the live stream."""
        fixture = ReceiptReviewFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        review = fixture.review
        review.manifest = {}
        review.root = fixture.base
        review.data = fixture.base / 'dashboard-data'
        review.data.mkdir()
        review.workspace = lambda: {'name': 'Live fixture', 'period': ''}
        review.workflow_checks = lambda: (False, False, False)
        fixture.state.update(screens={}, pairs={})
        fixture.save_state()
        app = create_app(review, 'fixture')
        server = TestServer(('127.0.0.1', 0), app)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            documents = browser.new_page()
            editor = browser.new_page()
            requests = []
            documents.on('request', lambda request: requests.append(request.url))
            base = f'http://127.0.0.1:{server.server_port}'
            documents.goto(base + '/documents')
            expect(documents.locator('#document-rows')).to_contain_text('Needs review')
            editor.goto(base + '/extraction-review')
            expect(editor.locator('#review-progress')).to_have_text('0 of 1 reviewed')
            editor.locator('#accept-receipts').click()
            expect(documents.locator('#document-rows')).to_contain_text('Complete')
            documents.wait_for_timeout(1500)
            progress = sum(url.endswith('/api/content/execution') for url in requests)
            documents.wait_for_timeout(1500)
            self.assertEqual(sum(url.endswith('/api/content/execution') for url in requests), progress)
            documents.context.set_offline(True)
            documents.wait_for_timeout(1000)
            editor.locator('#accept-receipts').click()
            expect(editor.locator('#review-progress')).to_have_text('0 of 1 reviewed')
            documents.context.set_offline(False)
            expect(documents.locator('#document-rows')).to_contain_text('Needs review', timeout=15000)
            draft = browser.new_page()
            draft.goto(base + '/extraction-review')
            field = draft.locator('[data-field="brief_description"]').first
            field.fill('Keep my unsaved draft')
            editor.locator('#accept-receipts').click()
            expect(documents.locator('#document-rows')).to_contain_text('Complete')
            expect(field).to_have_value('Keep my unsaved draft')
            racing = browser.new_page()
            racing.goto(base + '/extraction-review')
            racing_field = racing.locator('[data-field="brief_description"]').first
            expect(racing_field).to_be_visible()
            pending = []
            racing.route('**/api/receipts', lambda route: pending.append(route))
            editor.locator('#accept-receipts').click()
            expect(documents.locator('#document-rows')).to_contain_text('Needs review')
            for _ in range(30):
                if pending:
                    break
                racing.wait_for_timeout(100)
            self.assertTrue(pending, 'Expected a background receipt refresh')
            racing_field.fill('Typed while refresh was in flight')
            with racing.expect_response('**/api/receipts'):
                for route in pending:
                    route.continue_()
            racing.wait_for_timeout(300)
            expect(racing_field).to_have_value('Typed while refresh was in flight')
            documents.set_viewport_size({'width': 390, 'height': 844})
            expect(documents.get_by_role('navigation', name='Main navigation')).to_have_count(1)
            self.assertTrue(documents.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            browser.close()
