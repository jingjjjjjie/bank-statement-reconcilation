"""Completed and outdated matching keep generation available without hiding progress."""

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
                bank = {'available': False}
                page.route('**/api/bank-statement', lambda route: route.fulfill(json=bank))
                page.route('**/api/source', lambda route: route.fulfill(json={}))
                page.route('**/api/matching', lambda route: route.fulfill(json={'live_pieces': True, 'binding': 'fixture', 'version': 4}))
                submitted = []

                def matching_run(route):
                    """Record clicked actions without running any matching jobs."""
                    if route.request.method == 'POST':
                        submitted.append(route.request.post_data_json)
                    route.fulfill(json=state)

                page.route('**/api/matching-run', matching_run)
                for width in (1440, 390):
                    page.set_viewport_size({'width': width, 'height': 900})
                    page.goto(f'http://127.0.0.1:{server.server_port}/bank')
                    expect(page.locator('#bank-note')).to_have_text('No prepared bank statement was found.')
                    expect(page.locator('#final-matching')).to_be_hidden()
                    expect(page.locator('.page-help-button')).to_have_count(1)
                bank.update(available=True, balance_checks='failed', transactions=[{'page': 1}], count=1)
                page.reload()
                expect(page.locator('#bank-content')).to_be_visible()
                expect(page.locator('#final-matching')).to_be_hidden()
                bank['balance_checks'] = 'passed'
                for completed, running, stopped, failed, outdated, label, action in [
                    (240, False, True, 0, False, 'Matching complete', 'Regenerate matches'),
                    (120, False, True, 0, False, 'Stopped', 'Resume matching'),
                    (240, False, False, 1, False, 'Finished with errors', 'Regenerate matches'),
                    (120, True, True, 0, False, 'Stopping…', 'Stopping...'),
                    (240, False, False, 0, False, 'Matching complete', 'Regenerate matches'),
                    (240, False, False, 0, True, 'Matches need updating', 'Regenerate matches'),
                ]:
                    with self.subTest(completed=completed, running=running, failed=failed):
                        state.update(
                            total=240,
                            completed=completed,
                            running=running,
                            stop_requested=stopped,
                            failed=failed,
                            outdated=outdated,
                        )
                        page.goto(f'http://127.0.0.1:{server.server_port}/bank')
                        expect(page.locator('#matching-run-status')).to_have_text(label)
                        generate = page.locator('#generate-matches')
                        expect(generate).to_be_visible()
                        expect(generate).to_have_text(action)
                        if running:
                            expect(generate).to_be_disabled()
                        else:
                            expect(generate).to_be_enabled()
                        if running:
                            expect(page.locator('#stop-matches')).to_be_visible()
                        else:
                            expect(page.locator('#stop-matches')).to_be_hidden()
                with page.expect_event('dialog') as prompt:
                    generate.click()
                self.assertIn('clear all saved supporting', prompt.value.message)
                prompt.value.dismiss()
                self.assertEqual(submitted, [])
                with page.expect_event('dialog') as prompt:
                    generate.click()
                with page.expect_response(lambda response: response.url.endswith('/api/matching-run')
                                          and response.request.method == 'POST'):
                    prompt.value.accept()
                self.assertEqual(submitted[-1]['mode'], 'regenerate')
                self.assertTrue(submitted[-1]['confirm_clear'])
                self.assertEqual(submitted[-1]['binding'], 'fixture')
                self.assertEqual(submitted[-1]['version'], 4)
                state.update(failed=2, outdated=False)
                page.reload()
                retry = page.locator('#retry-failed-matches')
                expect(retry).to_be_visible()
                with page.expect_response(lambda response: response.url.endswith('/api/matching-run')
                                          and response.request.method == 'POST'):
                    retry.click()
                self.assertEqual(submitted[-1], {'mode': 'retry_failed'})
                browser.close()
