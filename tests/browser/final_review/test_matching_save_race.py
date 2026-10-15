"""Keep rapid approvals safe when background snapshots arrive late."""

import threading
import unittest
from types import SimpleNamespace

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from dashboard.services.matching import final_review
from tests.browser import browser_options
from tests.fixtures.final_review import FinalReviewFixture
from tests.http_server import TestServer


class MatchingSaveRaceTests(unittest.TestCase):
    def test_stale_refresh_cannot_roll_back_successful_accept(self):
        """A delayed pre-save snapshot must not break the next explicit approval."""
        fixture = FinalReviewFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {'name': 'Fixture', 'period': 'December'}
        fixture.enable_review_navigation()
        suggestions = final_review.read(fixture.cache / 'decisions.json')
        suggestions[1]['allocations'] = [{'item_id': 'D2', 'amount': '10'}]
        fixture.write(fixture.cache / 'decisions.json', suggestions)
        stale = final_review.snapshot(fixture.review)
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test-token', SimpleNamespace()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page()
            page.add_init_script("""
                window.EventSource = class {
                    constructor() { window.reviewStream = this; }
                    close() {}
                };
            """)
            base = f'http://127.0.0.1:{server.server_port}'
            page.goto(base + '/matching')
            expect(page.locator('#approve-match')).to_be_enabled()
            review_id = page.request.get(base + '/api/session').json()['review_id']
            pending = []
            page.route('**/api/matching', lambda route: pending.append(route))

            def trigger_refresh(version):
                """Deliver a live notification while controlling its HTTP snapshot."""
                page.evaluate(
                    """event => window.reviewStream.onmessage({data: JSON.stringify(event)})""",
                    {
                        'kind': 'snapshot',
                        'path': '/api/matching',
                        'version': version,
                        'review_id': review_id,
                    },
                )
                for _ in range(50):
                    if pending:
                        return
                    page.wait_for_timeout(20)
                self.fail('Expected matching snapshot request')

            trigger_refresh(100)
            page.locator('#approve-match').click()
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B2')
            with page.expect_response('**/api/matching'):
                pending.pop(0).fulfill(json=stale)
            # Also cover a stale cached snapshot requested after the successful save.
            trigger_refresh(101)
            with page.expect_response('**/api/matching'):
                pending.pop(0).fulfill(json=stale)
            # A refresh already in flight must not overwrite the draft during a save.
            current = final_review.snapshot(fixture.review)
            trigger_refresh(102)
            saves = []
            page.route('**/api/matching-decide', lambda route: saves.append(route))
            page.locator('#approve-match').click()
            for _ in range(50):
                if saves:
                    break
                page.wait_for_timeout(20)
            self.assertEqual(len(saves), 1)
            with page.expect_response('**/api/matching'):
                pending.pop(0).fulfill(json=current)
            expect(page.locator('#approve-match')).to_be_disabled()
            with page.expect_response('**/api/matching-decide'):
                saves.pop(0).continue_()
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B3')
            expect(page.locator('#matching-error')).to_be_hidden()
            state = final_review.context(fixture.review)[1]
            self.assertEqual(state['version'], 2)
            self.assertEqual(set(state['decisions']), {'B1', 'B2'})
            self.assertTrue(all(value['status'] == 'approved' for value in state['decisions'].values()))
            # A genuinely newer decision from another reviewer must still appear.
            final_review.decide(fixture.review, fixture.request(bank='B3', action='deny'))
            trigger_refresh(103)
            with page.expect_response('**/api/matching'):
                pending.pop(0).fulfill(json=final_review.snapshot(fixture.review))
            expect(page.locator('.review-state')).to_have_text('Rejected')
            browser.close()
