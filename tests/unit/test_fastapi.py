"""Exercise migration-specific HTTP validation and stale-workspace protection."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from dashboard.routes import create_app
from reconciliation.source_selection import SourceSelection
from tests.http_server import TestServer


class FastApiTests(unittest.TestCase):
    def test_resume_keeps_session_and_switch_replaces_it(self):
        """Only activating a different workspace invalidates cached browser views."""
        state = self.app.state.context
        identities = []
        for name in ("first", "first", "second"):
            work = state.sources.workspace / name
            (work / "documents").mkdir(parents=True, exist_ok=True)
            (work / "statement").mkdir(exist_ok=True)
            (work / "statement/bank.pdf").write_bytes(b"fixture")
            state.sources.save_workspace(work)
            request = urllib.request.Request(self.base + "/api/source/start",
                json.dumps({"preview": state.sources.preview()["token"]}).encode(),
                {"Content-Type": "application/json", "X-Review-Token": "token"})
            with urllib.request.urlopen(request) as response:
                result = json.load(response)
            self.assertEqual(result["resumed"], len(identities) == 1)
            identities.append(state.review_id)
        self.assertEqual(identities[0], identities[1])
        self.assertNotEqual(identities[1], identities[2])

    def setUp(self):
        """Start a session without any customer files or model calls."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.app = create_app(None, "token", SourceSelection(root, root / "data"))
        self.server = TestServer(("127.0.0.1", 0), self.app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def post_error(self, path, data, expected, headers=None):
        """Check a rejected request without changing fixture state."""
        request = urllib.request.Request(self.base + path, json.dumps(data).encode(),
            {"Content-Type": "application/json", "X-Review-Token": "token", **(headers or {})})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, expected)
        return json.load(error.exception)

    def test_schema_validation_returns_readable_json(self):
        """Invalid evidence must not turn into a plain-text 500 response."""
        from unittest.mock import patch
        from jsonschema import validate

        def invalid_path(path):
            """Raise the same validator class used by receipt saves."""
            validate({'unexpected': True}, {'type': 'object', 'additionalProperties': False})

        with patch.object(self.app.state.context.sources, 'save_workspace', side_effect=invalid_path):
            error = self.post_error('/api/source/workspace-select', {'path': 'fixture'}, 422)
        self.assertIn('Additional properties', error['error'])

    def test_stale_workspace_cannot_mutate_current_project(self):
        """A cached tab may not write after another tab switches workspaces."""
        result = self.post_error("/api/source/workspace-select",
                                 {"path": "unused"}, 409, {"X-Review-Id": "old-workspace"})
        self.assertIn("workspace changed", result["error"])

    def test_default_selection_is_local_to_the_supplied_review(self):
        """Fixture and embedded apps must never overwrite another project's selection."""
        base = self.app.state.context.sources.workspace
        review = SimpleNamespace(manifest_path=base / "manifest.json", data=base / "review-data")
        sources = create_app(review, "token").state.context.sources
        self.assertEqual(sources.workspace, base)
        self.assertEqual(sources.data, review.data)

    def test_typed_body_and_size_limit(self):
        """Bad booleans, malformed selections, and oversized requests are rejected."""
        self.post_error("/api/development-mode", {"enabled": "false"}, 422)
        self.post_error("/api/source/workspace-select", {"path": []}, 422)
        self.post_error("/api/source/workspace-select", {"path": "x" * 9000}, 413)

    def test_inactive_api_is_json_not_an_html_redirect(self):
        """Clients receive an actionable error when a review has not been selected."""
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.base + "/api/state")
        self.assertEqual(error.exception.code, 409)
        self.assertIn("Select a workspace", json.load(error.exception)["error"])

    def test_unknown_and_traversal_routes_do_not_serve_files(self):
        """Only the declared Vue paths and built assets are public."""
        for route in ("/unknown", "/assets/../index.html", "/api/unknown"):
            with self.subTest(route=route), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base + route)
            self.assertEqual(error.exception.code, 404)
