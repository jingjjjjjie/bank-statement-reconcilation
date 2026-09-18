"""Run the real ASGI application over an ephemeral loopback port in tests."""
import socket
import threading

import uvicorn


class TestServer:
    """Small socket-owning test fixture with deterministic shutdown."""

    def __init__(self, address, app):
        """Reserve the port before test clients are allowed to connect."""
        self.socket = socket.socket()
        self.socket.bind(address)
        self.socket.listen(128)
        self.server_port = self.socket.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
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
