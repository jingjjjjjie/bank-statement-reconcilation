"""Verify workspace reset/delete boundaries, preserved history and editor guards."""

import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dashboard.routes import create_app
from dashboard.services.project_actions import change, locate
from dashboard.services.projects import list_projects
from dashboard.services.review import Review
from reconciliation.intake.exact_report import prepare
from reconciliation.intake.workspace import SourceSelection
from tests.http_server import TestServer


class ProjectActionTests(unittest.TestCase):
    def setUp(self):
        """Prepare synthetic originals and distinct saved processing artifacts."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.work = self.root / 'April'
        (self.work / 'documents').mkdir(parents=True)
        (self.work / 'statement').mkdir()
        self.originals = {
            self.work / 'documents/a.txt': b'receipt',
            self.work / 'documents/b.txt': b'receipt',
            self.work / 'statement/bank.pdf': b'bank fixture',
        }
        for path, content in self.originals.items():
            path.write_bytes(content)
        self.sources = SourceSelection(self.root, self.root / 'data')
        self.sources.save_workspace(self.work)
        self.manifest, data = self.sources.start()
        self.review = Review(self.manifest, data)
        self.identity = list_projects(self.sources)[0]['id']
        self.saved = json.loads(self.manifest.read_text())
        self.artifacts = {
            'review/state.json': b'{"accepted":true}',
            'review/token-usage.jsonl': b'{"event_id":"preserve-me"}\n',
            'bank-output/master_statement.csv': b'old bank master',
            'final-review/decisions.json': b'{"approved":true}',
        }
        for name, content in self.artifacts.items():
            path = self.manifest.parent / name
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_bytes(content)

    def assert_originals(self):
        """Check input bytes instead of trusting names or file counts."""
        for path, content in self.originals.items():
            self.assertEqual(path.read_bytes(), content)

    def test_reset_preserves_inputs_and_history_but_clears_progress(self):
        fresh = change(self.sources, self.manifest, self.review.root, self.saved, 'reset')
        self.assert_originals()
        self.assertEqual(fresh.root, self.review.root)
        self.assertEqual(len(list_projects(self.sources)), 1)
        archive = next((self.root / 'duplicated/project-history').iterdir())
        for name, content in self.artifacts.items():
            self.assertFalse((self.manifest.parent / name).exists())
            self.assertEqual((archive / 'project' / name).read_bytes(), content)
        self.assertTrue((self.work / 'output/duplicates/report.json').is_file())
        self.assertTrue(list((self.work / 'output/.reconciliation-history').glob('*/duplicates/report.json')))

    def test_delete_removes_listing_and_allows_fresh_recreation(self):
        change(self.sources, self.manifest, self.review.root, self.saved, 'delete')
        self.assertEqual(list_projects(self.sources), [])
        self.assert_originals()
        self.assertFalse((self.work / 'output/duplicates').exists())
        manifest, _ = self.sources.start()
        self.assertEqual(manifest, self.manifest)
        self.assertFalse((manifest.parent / 'review/state.json').exists())

    def test_failed_reset_restores_previous_outputs(self):
        report = (self.work / 'output/duplicates/report.json').read_bytes()

        def fail_after_preparing(source, manifest):
            """Simulate a failure after replacement duplicate output has been written."""
            prepare(source, manifest)
            raise ValueError('incomplete')

        with patch('dashboard.services.project_actions.prepare', side_effect=fail_after_preparing):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                change(self.sources, self.manifest, self.review.root, self.saved, 'reset')
        self.assert_originals()
        for name, content in self.artifacts.items():
            self.assertEqual((self.manifest.parent / name).read_bytes(), content)
        self.assertEqual((self.work / 'output/duplicates/report.json').read_bytes(), report)

    def test_failed_archive_does_not_move_duplicate_output(self):
        report = (self.work / 'output/duplicates/report.json').read_bytes()
        with patch.object(Path, 'rename', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                change(self.sources, self.manifest, self.review.root, self.saved, 'reset')
        self.assertTrue(self.manifest.exists())
        self.assertEqual((self.work / 'output/duplicates/report.json').read_bytes(), report)
        self.assert_originals()

    def test_unknown_identity_cannot_choose_a_filesystem_path(self):
        with self.assertRaises(ValueError):
            locate(self.sources, '../April')
        self.assertTrue(self.manifest.exists())

    def start_server(self):
        """Expose independent cookie sessions over the real HTTP middleware."""
        self.app = create_app(self.review, 'fixture', self.sources)
        options = {'isolated_sessions': True} if hasattr(self.app.state, 'sessions') else {}
        server = TestServer(('127.0.0.1', 0), self.app, **options)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f'http://127.0.0.1:{server.server_port}'
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, browser, path, body=None, session=None):
        """Send authenticated writes and preserve readable rejected-action responses."""
        headers = {'Content-Type': 'application/json'}
        if session:
            headers.update({'X-Review-Token': session['token'], 'X-Review-Id': session['review_id']})
        request = urllib.request.Request(self.url + path, None if body is None else json.dumps(body).encode(), headers)
        try:
            with browser.open(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_active_reset_invalidates_stale_writes_and_delete_closes_session(self):
        browser = self.start_server()
        _, old = self.request(browser, '/api/session')
        self.assertEqual(self.request(browser, '/api/projects/reset', {'id': self.identity}, old)[0], 200)
        _, fresh = self.request(browser, '/api/session')
        self.assertTrue(fresh['active'])
        self.assertNotEqual(old['review_id'], fresh['review_id'])
        self.assertEqual(self.request(browser, '/api/projects/delete', {'id': self.identity}, old)[0], 409)
        self.assertEqual(self.request(browser, '/api/projects/delete', {'id': self.identity}, fresh)[0], 200)
        self.assertFalse(self.request(browser, '/api/session')[1]['active'])
        self.assertEqual(self.request(browser, '/api/projects')[1]['projects'], [])
        self.assert_originals()

    def test_other_editor_and_running_workers_block_changes(self):
        browser = self.start_server()
        _, session = self.request(browser, '/api/session')
        other = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        _, second = self.request(other, '/api/session')
        if hasattr(self.app.state, 'sessions'):
            for action in ('reset', 'delete'):
                self.assertEqual(self.request(other, '/api/projects/' + action, {'id': self.identity}, second)[0], 409)
        self.review.content_engine = SimpleNamespace(active_count=1)
        for action in ('reset', 'delete'):
            self.assertEqual(self.request(browser, '/api/projects/' + action, {'id': self.identity}, session)[0], 400)
        self.review.content_engine.active_count = 0
        self.assertTrue(self.manifest.exists())
        self.assert_originals()
