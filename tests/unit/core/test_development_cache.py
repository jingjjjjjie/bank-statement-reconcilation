"""Preserve local response caches and reject retired development controls."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from dashboard.routes import create_app
from reconciliation.core.development_cache import mode, write_json
from reconciliation.model.codex import CodexReviewer, object_schema
from tests.fixtures.workflow import mock_codex
from tests.http_server import TestServer


class RetiredDevelopmentTests(unittest.TestCase):
    def setUp(self):
        """Keep every response and token audit inside a temporary workspace."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def test_local_cache_resume_records_zero_usage_and_invalidation_retries(self):
        """Per-review resumability survives retirement of the shared development cache."""
        calls = []

        def fake_run(command, **kwargs):
            """Return structured results without invoking a subscription model."""
            if command[1:3] == ['login', 'status']:
                return SimpleNamespace(returncode=0, stdout='ChatGPT', stderr='')
            calls.append(command)
            Path(command[command.index('--output-last-message') + 1]).write_text('{"ok":true}')
            return SimpleNamespace(returncode=0)

        schema = object_schema({'ok': {'type': 'boolean'}})
        with mock_codex(fake_run):
            first = CodexReviewer(self.base / 'review')
            first.ask('same request', schema)
            resumed = CodexReviewer(self.base / 'review')
            self.assertTrue(resumed.ask('same request', schema)['ok'])
            self.assertEqual((len(calls), resumed.calls), (1, 0))
            events = [json.loads(line) for line in resumed.usage_path.read_text().splitlines()]
            cached = [event for event in events if event['status'] == 'cached']
            self.assertEqual(len(cached), 1)
            self.assertTrue(all(value == 0 for value in cached[0]['usage'].values()))
            resumed.invalidate()
            resumed.ask('same request', schema)
            self.assertEqual(len(calls), 2)
            independent = CodexReviewer(self.base / 'other-review')
            independent.ask('same request', schema)
            self.assertEqual(len(calls), 3)
            self.assertFalse((self.base / 'duplicated/development-cache').exists())

    def test_retired_development_actions_are_unavailable(self):
        """Old browser tabs cannot reenable caches or replay human decisions."""
        server = TestServer(('127.0.0.1', 0), create_app(None, 'token'))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for path in ('/api/development-mode', '/api/development/remember', '/api/development/apply'):
            request = urllib.request.Request(
                f'http://127.0.0.1:{server.server_port}{path}',
                json.dumps({'enabled': True, 'reviewer': 'Tester'}).encode(),
                {'X-Review-Token': 'token', 'Content-Type': 'application/json'},
            )
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 405)

    def test_saved_development_flag_cannot_reenable_tools(self):
        """Historical flags never unlock retired actions or experimental PDF modes."""
        path = self.base / 'resources/development.local.json'
        write_json(path, {'enabled': True})
        self.assertEqual(json.loads(path.read_text()), {'enabled': True})
        self.assertEqual(mode(), {'enabled': False})

    def test_json_publication_keeps_no_temporary_files(self):
        """The remaining helper safely publishes JSON for PDF routing and benchmarks."""
        path = self.base / 'nested/result.json'
        write_json(path, {'first': True})
        write_json(path, {'second': 'verified'})
        self.assertEqual(json.loads(path.read_text()), {'second': 'verified'})
        self.assertEqual(list(path.parent.iterdir()), [path])
