"""Verify matching progress states without launching subscription calls."""
import json
import threading
import unittest
from types import SimpleNamespace
from playwright.sync_api import sync_playwright, expect
from dashboard.routes import create_app
from tests.browser import browser_options
from tests.http_server import TestServer
from tests.unit import test_matching_review as fixtures


class MatchingProgressTests(unittest.TestCase):
    def test_start_progress_stop_and_failed_completion(self):
        """The bar reflects real counts and preserves failures at one hundred percent."""
        fixture = fixtures.MatchingReviewTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {'name': 'Fixture', 'period': ''}
        fixture.review.workflow_checks = lambda: (False, False, False)
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test', SimpleNamespace()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            state = {'running': False}
            held = []
            def snapshot(route):
                """Expose fixture evidence as a live piece workflow."""
                response = route.fetch()
                data = response.json()
                data['live_pieces'] = True
                route.fulfill(response=response, json=data)
            def progress(route):
                """Hold startup to verify immediate feedback and duplicate-click protection."""
                if route.request.method == 'POST':
                    held.append(route)
                else:
                    route.fulfill(json=state)
            page.route('**/api/matching', snapshot)
            page.route('**/api/matching-run', progress)
            page.route('**/api/matching-stop', lambda route: route.fulfill(json={**state, 'stop_requested': True}))
            page.goto(f'http://127.0.0.1:{server.server_port}/matching')
            page.locator('#generate-matches').click()
            expect(page.locator('#generate-matches')).to_be_disabled()
            expect(page.locator('#matching-run-status')).to_contain_text('Starting')
            state.update(running=True, completed=3, total=10, active_processes=2)
            held.pop().fulfill(json=state)
            expect(page.locator('#matching-progress-count')).to_have_text('3 / 10 processed (30%)')
            expect(page.locator('#matching-progress-bar')).to_have_attribute('value', '30')
            expect(page.locator('#matching-progress-detail')).to_contain_text('2 active')
            page.locator('#stop-matches').click()
            expect(page.locator('#matching-run-status')).to_contain_text('Stopping')
            state.update(running=False, stop_requested=True)
            expect(page.locator('#matching-run-status')).to_have_text('Stopped', timeout=10000)
            state.update(completed=10, stop_requested=False, failed=1, error='One model call failed')
            expect(page.locator('#matching-run-status')).to_have_text('Finished with errors', timeout=10000)
            expect(page.locator('#matching-progress-count')).to_have_text('10 / 10 processed (100%)')
            expect(page.locator('#matching-progress-detail')).to_have_text('1 failed')
            state.update(failed=0, error='')
            expect(page.locator('#matching-run-status')).to_have_text('Matching complete', timeout=10000)
            page.set_viewport_size({'width': 390, 'height': 844})
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
            browser.close()
