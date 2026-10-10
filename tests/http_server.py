"""Run the real ASGI application over an ephemeral loopback port in tests."""

import socket
import threading

import uvicorn


class TestServer:
    """Small socket-owning test fixture with deterministic shutdown."""

    def __init__(self, address, app, *, isolated_sessions=False):
        """Reserve the port before test clients are allowed to connect."""
        if not isolated_sessions:
            identity = app.state.sessions.fixture().session_id
            original = app

            async def fixture_session(scope, receive, send):
                """Treat stateless fixture requests as one browser, retaining real session guards."""
                if scope['type'] == 'http' and not any(key == b'cookie' for key, _ in scope['headers']):
                    scope = {**scope, 'headers': [*scope['headers'],
                             (b'cookie', ('accounting_session=' + identity).encode())]}
                await original(scope, receive, send)

            app = fixture_session
        self.socket = socket.socket()
        self.socket.bind(address)
        self.socket.listen(128)
        self.server_port = self.socket.getsockname()[1]
        self.server = uvicorn.Server(
            uvicorn.Config(app, log_level="error", access_log=False, timeout_graceful_shutdown=2)
        )
        self.stopped = threading.Event()

    def serve_forever(self):
        """Serve real HTTP requests on the reserved socket."""
        try:
            self.server.run(sockets=[self.socket])
        finally:
            self.stopped.set()

    def shutdown(self):
        """Wait for request workers to finish before deleting temporary fixtures."""
        self.server.should_exit = True
        if not self.stopped.wait(10):
            raise RuntimeError("Test server did not stop")

    def server_close(self):
        """Release the reserved loopback socket."""
        self.socket.close()
