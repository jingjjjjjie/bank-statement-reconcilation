"""Keep active background work attached to its workspace until shutdown finishes."""

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
from reconciliation.intake.workspace import SourceSelection
from tests.http_server import TestServer


class WorkspaceSwitchTests(unittest.TestCase):
    def setUp(self):
        """Start an isolated app with two synthetic workspaces and no model calls."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = create_app(None, 'token', SourceSelection(self.root, self.root / 'data'))
        self.server = TestServer(('127.0.0.1', 0), self.app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        for name in ('first', 'second'):
            work = self.root / name
            (work / 'documents').mkdir(parents=True)
            (work / 'statement').mkdir()
            (work / 'statement/bank.pdf').write_bytes(b'synthetic statement')
        self.select('first')
        self.post('/api/source/start', {'preview': self.preview})
        self.old = self.app.state.context.review
        self.old_id = self.app.state.context.review_id

    def select(self, name):
        """Select and hash one fixture workspace without activating it."""
        sources = self.app.state.context.sources
        sources.save_workspace(self.root / name)
        self.preview = sources.preview()['token']

    def post(self, path, body):
        """Make a real local request with the application's browser write token."""
        request = urllib.request.Request(
            self.base + path,
            json.dumps(body).encode(),
            {'Content-Type': 'application/json', 'X-Review-Token': 'token'},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def assert_switch_blocked(self):
        """Verify rejection preserves the original review and cancellation target."""
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post('/api/source/start', {'preview': self.preview})
        self.assertEqual(error.exception.code, 400)
        self.assertIn('matching', json.load(error.exception)['error'])
        self.assertIs(self.app.state.context.review, self.old)
        self.assertEqual(self.app.state.context.review_id, self.old_id)
        self.assertFalse((self.root / 'second/output').exists())

    def test_running_and_stopping_matching_prevent_switch(self):
        """A live worker or unverified active process keeps Stop attached to its project."""
        self.select('second')
        scenarios = [(True, False, 0), (True, True, 0), (False, True, 1)]
        for alive, stopping, active in scenarios:
            with self.subTest(worker=alive, stopping=stopping, active=active):
                self.old.piece_match_thread = SimpleNamespace(is_alive=lambda: alive)
                self.old.piece_match_engine = SimpleNamespace(active_count=active, cancel=lambda: None)
                self.old.piece_match_stopping = stopping
                self.assert_switch_blocked()
                self.post('/api/matching-stop', {})
                self.assertTrue(self.old.piece_match_stopping)
        self.old.piece_match_engine.active_count = 0
        self.post('/api/source/start', {'preview': self.preview})
        self.assertIsNot(self.app.state.context.review, self.old)

    def test_active_matching_allows_same_workspace_resume(self):
        """Resuming the current project keeps its worker and review identity attached."""
        self.old.piece_match_thread = SimpleNamespace(is_alive=lambda: True)
        self.select('first')
        result = self.post('/api/source/start', {'preview': self.preview})
        self.assertTrue(result['resumed'])
        self.assertIs(self.app.state.context.review, self.old)
        self.assertEqual(self.app.state.context.review_id, self.old_id)

    def test_switch_waits_for_matching_launch_before_checking_worker(self):
        """Concurrent launch and switch requests serialize before the switch guard runs."""
        entered, release, switch_sent = threading.Event(), threading.Event(), threading.Event()
        launch_errors, switch_errors = [], []

        def launch(review):
            """Hold launch in its HTTP lock, then expose an inert active worker."""
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Synthetic launch timed out')
            review.piece_match_thread = SimpleNamespace(is_alive=lambda: True)
            return {'running': True}

        def run_request():
            """Exercise the real matching launch route without model calls."""
            try:
                self.post('/api/matching-run', {})
            except Exception as error:
                launch_errors.append(error)

        def switch_request():
            """Queue activation while the matching request owns the context lock."""
            switch_sent.set()
            try:
                self.post('/api/source/start', {'preview': self.preview})
            except Exception as error:
                switch_errors.append(error)

        self.select('second')
        with patch('dashboard.services.matching.piece_match_jobs.start', side_effect=launch):
            launch_thread = threading.Thread(target=run_request)
            launch_thread.start()
            self.assertTrue(entered.wait(5))
            switch_thread = threading.Thread(target=switch_request)
            switch_thread.start()
            self.assertTrue(switch_sent.wait(5))
            release.set()
            launch_thread.join(10)
            switch_thread.join(10)
        self.assertFalse(launch_thread.is_alive())
        self.assertFalse(switch_thread.is_alive())
        self.assertEqual(launch_errors, [])
        self.assertEqual(len(switch_errors), 1)
        self.assertIsInstance(switch_errors[0], urllib.error.HTTPError)
        self.assertEqual(switch_errors[0].code, 400)
        self.assertIs(self.app.state.context.review, self.old)
