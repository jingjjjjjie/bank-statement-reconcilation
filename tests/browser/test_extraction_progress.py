"""Verify cumulative progress and priority Stop in the built document view."""
import threading
import unittest

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from tests.browser import browser_options
from tests.http_server import TestServer


class ExtractionProgressTests(unittest.TestCase):
    def test_progress_and_stop_while_start_response_is_pending(self):
        """Keep Stop clickable during Start, and never reset progress for assembly."""
        server = TestServer(("127.0.0.1", 0), create_app(token="fixture"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        execution = {"running": False, "stop_requested": False, "active_processes": 0,
                     "execution_status": "idle", "run_error": ""}
        rows = [{"id": str(n), "name": f"receipt-{n}.pdf", "path": f"/fixture/{n}.pdf",
                 "status": "Needs review" if n == 1 else "Queued", "extracted": n == 1,
                 "units_read": 1 if n == 1 else 0, "units_total": n,
                 "assembly_done": 0, "assembly_total": n - 1} for n in (1, 2)]
        starts, stops, errors = [], [], []
        fail_start = [False]
        prepared, preparations = [False], []

        def respond(route):
            """Supply deterministic API snapshots without spending model tokens."""
            path = route.request.url.split('/api/')[1]
            if path == 'content/prepare':
                preparations.append(route)
                return
            if path == "content/run":
                if fail_start[0]:
                    route.fulfill(status=400, json={"error": "Extraction settings changed; re-prepare the review."})
                    return
                execution.update(running=True, active_processes=3, execution_status="running")
                starts.append(route)
                return
            if path == "content/stop":
                stops.append(True)
                execution.update(stop_requested=True, execution_status="stopping")
            data = {"session": {"active": True, "review_id": "fixture", "token": "fixture"},
                    "workspace": {"name": "Fixture", "period": ""}, "workflow-checks": {"steps": []},
                    "development-mode": {"enabled": False},
                    "document-status": {"prepared": prepared[0], "documents": rows if prepared[0] else [], **execution},
                    "content/execution": execution, "content/stop": execution}.get(path, {})
            route.fulfill(json=data)

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**browser_options(), args=['--no-sandbox'])
                page = browser.new_page(viewport={"width": 1200, "height": 850})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/api/**", respond)
                page.goto(f"http://127.0.0.1:{server.server_port}/documents")
                expect(page.locator('#document-progress-stage')).to_have_text('Ready to extract')
                page.locator('#run-documents').click()
                expect(page.locator('#document-progress-stage')).to_have_text('Preparing documents...')
                expect(page.locator('#document-progress-count')).to_have_text('')
                expect(page.locator('#document-progress-track')).to_have_attribute('data-busy', 'true')
                expect(page.locator('#run-documents')).to_have_text('Preparing...')
                prepared[0] = True
                preparations.pop().fulfill(json={'prepared': True})
                expect(page.locator('#document-progress-stage')).to_have_text('1 / 2 documents processed')
                expect(page.locator('#document-progress-count')).to_have_text('1 / 4 steps (25%)')
                expect(page.locator('#stop-documents')).to_be_enabled()
                expect(page.locator('#run-documents')).to_have_text('Extracting...')
                expect(page.locator('#document-run-status')).to_contain_text('3 active processes')
                self.assertEqual(len(starts), 1)
                page.locator('#stop-documents').click()
                expect(page.locator('#stop-documents')).to_have_text('Stopping...')
                self.assertEqual(stops, [True])
                expect(page.locator('#run-documents')).to_be_disabled()
                # Deliver an old Start reply after Stop: it must not undo cancellation.
                starts.pop().fulfill(json={"running": True, "stop_requested": False})
                expect(page.locator('#document-run-status')).to_contain_text('3 active processes')
                execution.update(running=False, active_processes=0, execution_status="stopped",
                                 run_error="Review stopped. Completed results are saved; run again to resume.")
                expect(page.locator('#document-run-status')).to_contain_text('Review stopped.')
                rows[1]['units_read'] = 2
                expect(page.locator('#document-progress-count')).to_have_text('3 / 4 steps (75%)')
                rows[1].update(assembly_done=1, extracted=False, status='Needs attention')
                expect(page.locator('#document-progress-stage')).to_have_text('2 / 2 documents processed')
                expect(page.get_by_text('Needs attention', exact=True).last).to_be_visible()
                expect(page.locator('#document-progress-count')).to_have_text('4 / 4 steps (100%)')
                page.set_viewport_size({"width": 390, "height": 844})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                fail_start[0] = True
                rows[1].update(assembly_done=0, extracted=False, units_read=0, status='Queued')
                execution.update(stop_requested=False, run_error='')
                page.reload()
                expect(page.locator('#run-documents')).to_be_enabled()
                page.locator('#run-documents').click()
                expect(page.locator('.settings-card #receipt-error')).to_be_visible()
                expect(page.locator('#receipt-error')).to_contain_text('Extraction settings changed')
                self.assertFalse(errors)
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
