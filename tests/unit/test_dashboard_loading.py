"""Keep display acceleration separate from fresh action validation."""
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from tests.http_server import TestServer
from pathlib import Path
from unittest.mock import patch

from reconciliation.duplicate_workflow import organize, supporting_files, fingerprint


class DashboardLoadingTests(unittest.TestCase):
    def setUp(self):
        """Use isolated files and a local server without any model calls."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.file = self.source / "a.txt"
        self.file.write_bytes(b"first")

    def test_hashes_always_read_fresh_bytes(self):
        """Same-size edits with restored timestamps still invalidate the hash."""
        original = fingerprint(self.file)
        stat = self.file.stat()
        self.file.write_bytes(b"other")
        os.utime(self.file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertNotEqual(fingerprint(self.file), original)

    def test_scan_rejects_linked_entries(self):
        """Directory traversal must still reject links to outside sources."""
        link = self.source / "linked"
        try:
            link.symlink_to(self.base, target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaisesRegex(ValueError, "Linked paths"):
            supporting_files(self.source)

    def test_scan_preserves_exclusions(self):
        """Canonical directory traversal still excludes the requested file."""
        self.assertEqual(supporting_files(self.source, [self.file]), [])
        self.assertEqual(supporting_files(self.source), [self.file])

    @unittest.skipUnless(os.name == "nt", "Windows junction behavior")
    def test_scan_rejects_windows_junction(self):
        """Windows junctions remain blocked without following their targets."""
        link = self.source / "junction"
        target = self.base / "outside"
        target.mkdir()
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True)
        try:
            with self.assertRaisesRegex(ValueError, "Linked paths"):
                supporting_files(self.source)
        finally:
            link.rmdir()

    def test_static_assets_and_session_do_not_wait_for_review_scan(self):
        """A blocked review read cannot stall page assets or session loading."""
        from dashboard.routes import create_app
        from dashboard.review import Review
        manifest = self.base / "manifest.json"
        organize(self.source, manifest)
        review = Review(manifest, self.base / "data")
        app = create_app(review, "token")
        queued = threading.Event()
        received = 0

        @app.middleware("http")
        async def count_reads(request, call_next):
            """Observe a burst larger than the default request-worker pool."""
            nonlocal received
            if request.url.path == "/api/state":
                received += 1
                if received == 45:
                    queued.set()
            return await call_next(request)

        server = TestServer(("127.0.0.1", 0), app)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        entered, release = threading.Event(), threading.Event()

        def slow_snapshot():
            """Hold the review lock until the test finishes loading assets."""
            entered.set()
            release.wait(10)
            return {}

        def load_state():
            """Issue a competing review request in the background."""
            with urllib.request.urlopen(base + "/api/state") as response:
                response.read()

        with patch.object(review, "snapshot", side_effect=slow_snapshot):
            requests = [threading.Thread(target=load_state) for _ in range(45)]
            for request in requests:
                request.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(queued.wait(5))
                for path in ("/bank", "/api/session"):
                    with urllib.request.urlopen(base + path, timeout=2) as response:
                        self.assertEqual(response.status, 200)
                with urllib.request.urlopen(base + "/bank") as response:
                    etag = response.headers["ETag"]
                    self.assertIn("no-cache", response.headers["Cache-Control"])
                conditional = urllib.request.Request(base + "/bank", headers={"If-None-Match": etag})
                with self.assertRaises(urllib.error.HTTPError) as result:
                    urllib.request.urlopen(conditional)
                self.assertEqual(result.exception.code, 304)
            finally:
                release.set()
                for request in requests:
                    request.join(5)
