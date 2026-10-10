"""Verify browser fixtures close even when an event stream remains connected."""

import threading
import unittest
import urllib.request

from dashboard.routes import create_app
from tests.http_server import TestServer


class HttpShutdownTests(unittest.TestCase):
    def test_connected_event_stream_does_not_hold_fixture_shutdown(self):
        """Cancel lingering live requests before lifespan releases the fixture state."""
        app = create_app(token="fixture")
        server = TestServer(("127.0.0.1", 0), app)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/live", timeout=5) as stream:
            self.assertEqual(stream.readline(), b": connected\n")
            server.shutdown()
        self.assertTrue(app.state.live.closed)
        self.assertFalse(app.state.live.listeners)
