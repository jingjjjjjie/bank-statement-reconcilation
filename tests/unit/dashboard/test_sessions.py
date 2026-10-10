"""Exercise independent browsers and exclusive project ownership over real HTTP."""

import http.cookiejar
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from dashboard.routes import create_app
from dashboard.services.sessions import COOKIE, LEASE_SECONDS
from reconciliation.intake.workspace import SourceSelection
from tests.http_server import TestServer


class Browser:
    """Keep one independent browser cookie jar and its current save guards."""

    def __init__(self, base):
        """Bootstrap a browser without sharing another editor's token or selection."""
        self.base = base
        self.cookies = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.session = self.request('/api/session')[1]

    def request(self, path, body=None, **headers):
        """Return HTTP status and JSON, including deliberate conflict responses."""
        if body is not None:
            headers = {'Content-Type': 'application/json', 'X-Review-Token': self.session['token'],
                       'X-Review-Id': self.session['review_id'], **headers}
        request = urllib.request.Request(self.base + path,
                                         None if body is None else json.dumps(body).encode(), headers)
        try:
            response = self.http.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def select(self, work):
        """Select and hash a workspace while leaving the current project open."""
        status, _ = self.request('/api/source/workspace-select', {'path': str(work)})
        assert status == 200
        return self.request('/api/source/preview')[1]['token']

    def open(self, work):
        """Open one selected workspace and refresh this browser's save identity."""
        result = self.request('/api/source/start', {'preview': self.select(work)})
        if result[0] == 200:
            self.session = self.request('/api/session')[1]
        return result


class SessionTests(unittest.TestCase):
    """Never use customer workspaces, authenticated users or live model calls."""

    def setUp(self):
        """Serve two tiny synthetic workspaces with actual independent cookies."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('first', 'second'):
            work = self.root / name
            (work / 'documents').mkdir(parents=True)
            (work / 'statement').mkdir()
            (work / 'documents/receipt.txt').write_text(name)
            (work / 'statement/bank.pdf').write_bytes(b'fixture')
        self.app = create_app(sources=SourceSelection(self.root, self.root / 'data'))
        self.server = TestServer(('127.0.0.1', 0), self.app, isolated_sessions=True)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.a, self.b = Browser(self.base), Browser(self.base)

    def state(self, browser):
        """Inspect the issued fixture identity without guessing cookies."""
        identity = next(cookie.value for cookie in browser.cookies if cookie.name == COOKIE)
        return self.app.state.sessions.entries[identity]

    def test_independent_projects_tokens_and_evidence(self):
        """Different browsers retain their own project, pending selection and originals."""
        self.assertNotEqual(self.a.session['token'], self.b.session['token'])
        self.assertEqual(self.a.open(self.root / 'first')[0], 200)
        self.assertFalse(self.b.request('/api/session')[1]['active'])
        self.assertEqual(self.b.request('/api/source')[1]['selected'], None)
        self.assertEqual(self.b.open(self.root / 'second')[0], 200)
        for browser, name in ((self.a, 'first'), (self.b, 'second')):
            self.assertEqual(browser.request('/api/source')[1]['active'], str(self.root / name / 'documents'))
            self.assertEqual(browser.request('/api/workspace')[1]['name'], name)
        status, _ = self.b.request('/api/source/close', {}, **{'X-Review-Token': self.a.session['token']})
        self.assertEqual(status, 403)
        self.assertTrue(self.b.request('/api/session')[1]['active'])
        self.assertIsNot(self.state(self.a).live, self.state(self.b).live)

    def test_atomic_claim_and_explicit_release(self):
        """Simultaneous opens have exactly one winner; closing permits the other editor."""
        previews = [browser.select(self.root / 'first') for browser in (self.a, self.b)]
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(browser.request, '/api/source/start', {'preview': preview})
                       for browser, preview in zip((self.a, self.b), previews, strict=True)]
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(sorted(result[0] for result in results), [200, 409])
        owner, other = (self.a, self.b) if results[0][0] == 200 else (self.b, self.a)
        owner.session = owner.request('/api/session')[1]
        projects = other.request('/api/projects')[1]['projects']
        self.assertTrue(projects[0]['in_use'])
        self.assertEqual(owner.request('/api/source/close', {})[0], 200)
        self.assertEqual(other.open(self.root / 'first')[0], 200)
        self.assertFalse(owner.request('/api/session')[1]['active'])

    def test_failed_switch_keeps_old_lease_and_releases_reservation(self):
        """A rejected preview cannot strand a new project or lose the existing one."""
        self.assertEqual(self.a.open(self.root / 'first')[0], 200)
        self.a.select(self.root / 'second')
        self.assertEqual(self.a.request('/api/source/start', {'preview': 'stale'})[0], 400)
        self.assertEqual(self.b.open(self.root / 'first')[0], 409)
        self.assertEqual(self.b.open(self.root / 'second')[0], 200)
        self.assertEqual(self.a.request('/api/source')[1]['active'], str(self.root / 'first/documents'))

    def test_project_operations_cannot_bypass_another_editors_lease(self):
        """Reset/delete cannot change originals or saved work owned by another browser."""
        self.assertEqual(self.a.open(self.root / 'first')[0], 200)
        identity = self.b.request('/api/projects')[1]['projects'][0]['id']
        original = (self.root / 'first/documents/receipt.txt').read_bytes()
        for path in ('/api/projects/reset', '/api/projects/delete'):
            self.assertEqual(self.b.request(path, {'id': identity})[0], 409)
        self.assertEqual((self.root / 'first/documents/receipt.txt').read_bytes(), original)
        self.assertTrue(self.a.request('/api/session')[1]['active'])
        self.assertEqual(self.b.open(self.root / 'first')[0], 409)

    def test_expired_editor_cannot_save_after_takeover(self):
        """An abandoned lease can transfer; the old page keeps its stale-save guard."""
        self.assertEqual(self.a.open(self.root / 'first')[0], 200)
        old = self.a.session['review_id']
        self.state(self.a).last_seen = time.monotonic() - LEASE_SECONDS - 1
        self.assertEqual(self.b.open(self.root / 'first')[0], 200)
        status, error = self.a.request('/api/source/close', {}, **{'X-Review-Id': old})
        self.assertEqual(status, 409)
        self.assertIn('workspace changed', error['error'])
        self.assertTrue(self.b.request('/api/session')[1]['active'])

    def test_jobs_pin_lease_and_block_close_until_process_exit(self):
        """Do not hand over evidence while a worker or unverified child process owns it."""
        self.assertEqual(self.a.open(self.root / 'first')[0], 200)
        state = self.state(self.a)
        for attribute, job in (('content_thread', SimpleNamespace(is_alive=lambda: True)),
                               ('piece_match_engine', SimpleNamespace(active_count=1))):
            setattr(state.review, attribute, job)
            state.last_seen = time.monotonic() - LEASE_SECONDS - 1
            self.assertEqual(self.b.open(self.root / 'first')[0], 409)
            self.assertEqual(self.a.request('/api/source/close', {})[0], 400)
            setattr(state.review, attribute, None)
        self.assertEqual(self.a.request('/api/source/close', {})[0], 200)
        self.assertEqual(self.b.open(self.root / 'first')[0], 200)
