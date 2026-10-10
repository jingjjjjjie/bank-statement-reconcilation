"""Check independent browser workspaces, project-in-use feedback and extraction admission."""

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from dashboard.services.extraction import extraction_runs
from reconciliation.intake.workspace import SourceSelection
from tests.browser import browser_options
from tests.http_server import TestServer


class BrowserSessionTests(unittest.TestCase):
    def test_projects_are_isolated_and_busy_controls_are_clear(self):
        """Two browser profiles see separate projects and cannot take an occupied editor slot."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = SourceSelection(root, root / 'data')
            for name in ('April', 'May'):
                work = root / name
                (work / 'documents').mkdir(parents=True)
                (work / 'statement').mkdir()
                (work / 'documents/receipt.txt').write_text(name)
                (work / 'statement/bank.pdf').write_bytes(b'fixture')
                sources.save_workspace(work)
                sources.start()
            app = create_app(sources=sources)
            server = TestServer(('127.0.0.1', 0), app, isolated_sessions=True)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            base = f'http://127.0.0.1:{server.server_port}'
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**browser_options())
                first, second = browser.new_context(), browser.new_context()
                a, b = first.new_page(), second.new_page()
                errors = []
                a.on('pageerror', lambda error: errors.append(str(error)))
                b.on('pageerror', lambda error: errors.append(str(error)))
                a.goto(base + '/projects')
                b.goto(base + '/projects')
                a.get_by_role('button', name='Resume April').click()
                expect(a).to_have_url(base + '/documents')
                b.get_by_role('button', name='Refresh', exact=True).click()
                row = b.locator('.project-row').filter(has=b.get_by_role('heading', name='April', exact=True))
                expect(row.get_by_role('button', name='Resume April')).to_be_disabled()
                expect(row.get_by_text('Project in use', exact=True)).to_have_count(2)
                b.get_by_role('button', name='Resume May').click()
                expect(b).to_have_url(base + '/documents')
                state = next(state for state in app.state.sessions.entries.values()
                             if state.review and state.review.root == root / 'April/documents')
                state.review.content_thread = SimpleNamespace(is_alive=lambda: True)
                try:
                    with patch.object(extraction_runs, '_batch_owner', state.review):
                        expect(b.locator('#run-documents')).to_be_disabled()
                        expect(b.locator('#document-run-status')).to_have_text(extraction_runs.BLOCKED_MESSAGE)
                        expect(a.locator('#stop-documents')).to_be_enabled()
                        # Closing a different idle project never releases the running owner's slot.
                        b.goto(base + '/projects')
                        b.get_by_role('button', name='Close project').click()
                        expect(b.locator('.project-row').filter(has=b.get_by_role('heading', name='May', exact=True))
                               .get_by_role('button', name='Resume May')).to_be_enabled()
                finally:
                    state.review.content_thread = None
                a.goto(base + '/projects')
                a.get_by_role('button', name='Close project').click()
                expect(a.get_by_text('Active workspace', exact=True)).to_have_count(0)
                b.get_by_role('button', name='Refresh', exact=True).click()
                expect(row.get_by_role('button', name='Resume April')).to_be_enabled()
                b.get_by_role('button', name='Resume April').click()
                expect(b).to_have_url(base + '/documents')
                a.set_viewport_size({'width': 390, 'height': 844})
                a.get_by_role('button', name='Refresh', exact=True).click()
                expect(a.get_by_role('button', name='Resume April')).to_be_disabled()
                self.assertTrue(a.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                expect(a.locator('.page-help-button')).to_have_count(1)
                expect(a.get_by_role('navigation', name='Main navigation')).to_have_count(1)
                self.assertEqual(errors, [])
                output = Path('.tools/session-checks')
                output.mkdir(parents=True, exist_ok=True)
                a.screenshot(path=str(output / 'project-in-use-mobile.png'), full_page=True)
                browser.close()
