"""Completed matching hides run controls without hiding resumable or failed work."""

import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from dashboard.services.review import Review
from reconciliation.intake.duplicates import organize
from tests.browser import browser_options
from tests.http_server import TestServer


class MatchingCompletionTests(unittest.TestCase):
    def test_complete_stopped_failed_and_running_controls(self):
        """A late stop flag cannot override a successful completed run."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / 'sources'
            source.mkdir()
            (source / 'receipt.txt').write_text('fixture')
            manifest = base / 'manifest.json'
            organize(source, manifest)
            server = TestServer(('127.0.0.1', 0), create_app(Review(manifest, base / 'data'), 'test-token'))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**browser_options())
                page = browser.new_page()
                page.route('**/api/live', lambda route: route.abort())
                state = {}
                page.route('**/api/matching', lambda route: route.fulfill(json={'live_pieces': True}))
                page.route('**/api/matching-run', lambda route: route.fulfill(json=state))
                for completed, running, stopped, failed, label, hidden in [
                    (240, False, True, 0, 'Matching complete', True),
                    (120, False, True, 0, 'Stopped', False),
                    (240, False, False, 1, 'Finished with errors', False),
                    (120, True, True, 0, 'Stopping…', False),
                    (240, False, False, 0, 'Matching complete', True),
                ]:
                    with self.subTest(completed=completed, running=running, failed=failed):
                        state.update(
                            total=240, completed=completed, running=running, stop_requested=stopped, failed=failed
                        )
                        page.goto(f'http://127.0.0.1:{server.server_port}/bank')
                        expect(page.locator('#matching-run-status')).to_have_text(label)
                        if hidden:
                            expect(page.locator('#generate-matches')).to_be_hidden()
                        else:
                            expect(page.locator('#generate-matches')).to_be_visible()
                        if running:
                            expect(page.locator('#stop-matches')).to_be_visible()
                        else:
                            expect(page.locator('#stop-matches')).to_be_hidden()
                browser.close()
