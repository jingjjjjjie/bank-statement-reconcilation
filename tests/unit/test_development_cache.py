"""Verify mode isolation, cross-review cache reuse, and preserved human history."""
import hashlib
import json
import tempfile
import unittest
import threading
import urllib.request
import urllib.error
from tests.http_server import TestServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dashboard import development
from dashboard.review import Review
from dashboard.routes import create_app
from reconciliation import development_cache as cache
from reconciliation.codex_reviewer import CodexReviewer, object_schema
from reconciliation.duplicate_workflow import organize
from tests.helpers import mock_codex


class DevelopmentCacheTests(unittest.TestCase):
    def setUp(self):
        """Keep mode configuration and every cache artifact inside a test workspace."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        workspace = patch.object(cache, "WORKSPACE", self.base)
        workspace.start()
        self.addCleanup(workspace.stop)
        cache.set_mode(True)

    def test_shared_results_survive_new_review_and_mode_off_ignores_them(self):
        """Identical requests reuse results with zero new tokens only in test mode."""
        calls = []

        def fake_run(command, **kwargs):
            """Generate a schema-valid result without invoking Codex."""
            if command[1:3] == ["login", "status"]:
                return SimpleNamespace(returncode=0, stdout="ChatGPT", stderr="")
            calls.append(command)
            Path(command[command.index("--output-last-message") + 1]).write_text('{"ok": true}')
            return SimpleNamespace(returncode=0)

        schema = object_schema({"ok": {"type": "boolean"}})
        root = cache.root_for(self.base)
        with mock_codex(fake_run):
            first = CodexReviewer(self.base / "one")
            first.ask("same request", schema)
            second = CodexReviewer(self.base / "two")
            self.assertTrue(second.ask("same request", schema)["ok"])
            self.assertEqual((len(calls), second.calls), (1, 0))
            events = [json.loads(line) for line in second.usage_path.read_text().splitlines()]
            self.assertEqual(events[0]["status"], "cached")
            self.assertTrue(all(value == 0 for value in events[0]["usage"].values()))
            before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            cache.set_mode(False)
            CodexReviewer(self.base / "three").ask("same request", schema)
            self.assertEqual(len(calls), 2)
            self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()})
            cache.set_mode(True)
            second.invalidate()
            self.assertFalse(list((root / "model-requests").glob("*/result.json")))

    def test_changed_model_or_prompt_does_not_reuse_shared_output(self):
        """The central cache retains the full request identity used by local caches."""
        schema = object_schema({"ok": {"type": "boolean"}})
        calls = []

        def fake_run(command, **kwargs):
            """Count only actual mocked model attempts."""
            if command[1:3] == ["login", "status"]:
                return SimpleNamespace(returncode=0, stdout="ChatGPT", stderr="")
            calls.append(command)
            Path(command[command.index("--output-last-message") + 1]).write_text('{"ok": true}')
            return SimpleNamespace(returncode=0)

        with mock_codex(fake_run):
            CodexReviewer(self.base / "one", model="first").ask("a", schema)
            CodexReviewer(self.base / "two", model="second").ask("a", schema)
            CodexReviewer(self.base / "three", model="first").ask("b", schema)
        self.assertEqual(len(calls), 3)

    def review(self, folder):
        """Organize unchanged source files into an independently located review."""
        folder.mkdir()
        manifest = folder / "duplicate-manifest.json"
        source = self.base / "source"
        source.mkdir(exist_ok=True)
        for name in ("a.txt", "b.txt"):
            (source / name).write_bytes(b"same document")
        organize(source, manifest)
        return Review(manifest, folder / "dashboard-data")

    def test_pinned_human_choices_survive_undo_and_new_review(self):
        """Human choices persist across resets but are never applied automatically."""
        first = self.review(self.base / "first")
        group = next(iter(first.groups))
        first.keep(group, first.groups[group][0])
        self.assertEqual(development.snapshot(first)["exact"], 1)
        development.remember(first)
        first.undo(group)
        second = self.review(self.base / "second")
        self.assertEqual(second.snapshot()["pending"], 1)
        self.assertEqual(development.snapshot(second)["exact"], 1)
        self.assertEqual(development.apply(second, "Tester")["exact_applied"], 1)
        self.assertEqual(second.snapshot()["pending"], 0)
        folder = cache.project_folder(first.manifest_path)
        self.assertGreaterEqual(len(list((folder / "decisions/history").glob("*.json"))), 3)

    def test_outputs_are_versioned_and_deduplicated(self):
        """Retain previous outputs and provenance without overwriting active state."""
        review = self.review(self.base / "project")
        output = review.manifest_path.parent / "bank-output/master_statement.csv"
        output.parent.mkdir()
        output.write_text("first version")
        one = cache.capture(review.manifest_path, "bank")
        self.assertEqual(cache.capture(review.manifest_path, "bank"), one)
        output.write_text("second version")
        two = cache.capture(review.manifest_path, "bank")
        self.assertNotEqual(one, two)
        descriptor = json.loads(one.read_text())["artifacts"]["bank-output/master_statement.csv"]
        digest = descriptor["sha256"]
        blob = cache.root_for(review.manifest_path) / "objects" / digest[:2] / digest
        self.assertEqual(blob.read_text(), "first version")
        self.assertEqual(hashlib.sha256(blob.read_bytes()).hexdigest(), digest)
        cache.set_mode(False)
        self.assertIsNone(cache.capture(review.manifest_path, "bank"))
        self.assertTrue(one.exists())

    def test_switch_gates_actions_and_rejects_changes_during_execution(self):
        """The backend enforces the switch even when an old page remains open."""
        review = self.review(self.base / "project")
        server = TestServer(("127.0.0.1", 0), create_app(review, "token"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def post(path, body):
            """Send an authenticated action to the isolated dashboard."""
            request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}{path}",
                json.dumps(body).encode(), {"X-Review-Token": "token", "Content-Type": "application/json"})
            with urllib.request.urlopen(request) as response:
                return json.load(response)

        self.assertFalse(post("/api/development-mode", {"enabled": False})["enabled"])
        with self.assertRaises(urllib.error.HTTPError):
            post("/api/development/remember", {})
        with self.assertRaises(urllib.error.HTTPError):
            post("/api/development-mode", {"enabled": "false"})
        with patch("dashboard.content_review.execution_status", return_value={"running": True}):
            with self.assertRaises(urllib.error.HTTPError):
                post("/api/development-mode", {"enabled": True})
        self.assertFalse(cache.mode()["enabled"])
        self.assertTrue(post("/api/development-mode", {"enabled": True})["enabled"])
        self.assertTrue((cache.project_folder(review.manifest_path) / "latest-output.json").is_file())
