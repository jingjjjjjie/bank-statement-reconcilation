"""Settings defaults and catalog changes tested against a disposable workspace."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from dashboard.services.review import Review
from reconciliation.core.settings import DEFAULTS
from reconciliation.intake.duplicates import organize
from reconciliation.model.token_usage import summary
from tests.browser import browser_options
from tests.http_server import TestServer


class SettingsDefaultsTests(unittest.TestCase):
    def test_reset_discard_save_and_catalog_refresh(self):
        """Reset includes hidden stage overrides and catalog refresh preserves an unsaved choice."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / 'sources'
            source.mkdir()
            (source / 'one.txt').write_text('fixture')
            manifest = base / 'manifest.json'
            organize(source, manifest)
            review = Review(manifest, base / 'data')
            custom = {**DEFAULTS, 'max_parallel': 2, 'stages': {'comparison': {'model': '', 'reasoning': 'default'}}}
            review.config_path.write_text(json.dumps(custom), encoding='utf-8')
            models = [{'id': DEFAULTS['model'], 'name': DEFAULTS['model'], 'reasoning': ['high'], 'vision': True}]
            with patch('reconciliation.core.settings.model_catalog', return_value=models), patch(
                'dashboard.services.review.model_catalog', return_value=models
            ), patch('dashboard.services.review.workspace_summary', return_value=summary(base / 'usage.jsonl')):
                server = TestServer(('127.0.0.1', 0), create_app(review, 'test-token'))
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(**browser_options())
                        page = browser.new_page()
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        job = {'running': False, 'lines': [], 'exit_code': None}
                        status = {'available': True, 'logged_in': True, 'method': 'chatgpt', 'installed': '1.0',
                                  'latest': '1.0', 'update_available': False, 'can_update': True, 'login': job, 'update': job}
                        page.route('**/api/codex/status*', lambda route: route.fulfill(json=status))
                        page.goto(f'http://127.0.0.1:{server.server_port}/settings')
                        expect(page.locator('#max-parallel')).to_have_value('2')
                        page.locator('#reset-settings').click()
                        expect(page.locator('#max-parallel')).to_have_value('4')
                        self.assertEqual(json.loads(review.config_path.read_text()), custom)
                        page.locator('#discard-settings').click()
                        expect(page.locator('#max-parallel')).to_have_value('2')
                        page.locator('#reset-settings').click()
                        page.locator('#save-settings').click()
                        expect(page.locator('#save-state')).to_have_text('All settings saved')
                        self.assertEqual(json.loads(review.config_path.read_text()), DEFAULTS)
                        page.reload()
                        expect(page.locator('#max-parallel')).to_have_value('4')
                        page.locator('#max-calls').fill('12')
                        page.locator('#pdf-reasoning').select_option('high')
                        models[:] = [{'id': 'replacement', 'name': 'Replacement', 'reasoning': ['low'], 'vision': True}]
                        page.locator('#codex-update').click()
                        expect(page.locator('#pdf-model option[value="replacement"]')).to_have_count(1)
                        expect(page.locator('#pdf-model')).to_have_value(DEFAULTS['model'])
                        expect(page.locator('#pdf-model option:checked')).to_contain_text('no longer listed')
                        expect(page.locator('#pdf-reasoning')).to_have_value('high')
                        expect(page.locator('#max-calls')).to_have_value('12')
                        for width in (1440, 390):
                            page.set_viewport_size({'width': width, 'height': 900})
                            expect(page.get_by_role('button', name='How to use this page')).to_have_count(1)
                            page.get_by_role('button', name='How to use this page').click()
                            expect(page.get_by_role('tooltip')).to_be_visible()
                            page.keyboard.press('Escape')
                            expect(page.get_by_role('tooltip')).to_be_hidden()
                            expect(page.locator('.app-header a[href="/settings"]')).to_have_count(1)
                            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                            self.assertEqual(page.locator('.codex-master').evaluate('(e) => getComputedStyle(e).borderBottomWidth'), '0px')
                        # An in-progress installation completing also refreshes the catalog.
                        page.locator('#discard-settings').click()
                        models[:] = [{'id': DEFAULTS['model'], 'name': 'Default', 'reasoning': ['high'], 'vision': True}]
                        page.unroute('**/api/codex/status*')
                        checks = []

                        def update_status(route):
                            """Simulate update completion without installing or contacting Codex."""
                            checks.append(route.request.url)
                            if 'refresh=true' in route.request.url:
                                models.append({'id': 'new-model', 'name': 'New model', 'reasoning': [], 'vision': True})
                            route.fulfill(json={**status, 'update': {**job, 'running': len(checks) == 1}})

                        page.route('**/api/codex/status*', update_status)
                        page.reload()
                        expect(page.locator('#max-calls')).to_be_enabled()
                        page.locator('#max-calls').fill('13')
                        expect(page.locator('#pdf-model option[value="new-model"]')).to_have_count(1, timeout=10000)
                        expect(page.locator('#max-calls')).to_have_value('13')
                        self.assertEqual(errors, [])
                        browser.close()
                finally:
                    server.shutdown()
                    server.server_close()
