"""Verify durable Codex token accounting and unknown-usage handling."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from codex_reviewer import CodexReviewer, object_schema
from token_usage import record, summary


class TokenUsageTests(unittest.TestCase):
    def test_reported_usage_cache_and_unknown_attempts(self):
        """Count reported tokens once and keep absent usage visible."""
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            schema = object_schema({"ok": {"type": "boolean"}})

            def fake_run(command, **kwargs):
                """Write a Codex completion event for the first model call only."""
                if command[1:3] == ["login", "status"]:
                    return SimpleNamespace(returncode=0, stdout="ChatGPT", stderr="")
                self.assertIn("--json", command)
                output = Path(command[command.index("--output-last-message") + 1])
                output.write_text('{"ok": true}', encoding="utf-8")
                if kwargs["input"].endswith("first"):
                    kwargs["stdout"].write(json.dumps({"type": "turn.completed", "usage": {
                        "input_tokens": 100, "cached_input_tokens": 40,
                        "output_tokens": 20, "reasoning_output_tokens": 5}}) + "\n")
                return SimpleNamespace(returncode=0)

            reviewer = CodexReviewer(work, executable="codex", model="gpt-5.6-sol")
            reviewer.stage = "pdf"
            with patch("codex_reviewer.subprocess.run", side_effect=fake_run):
                reviewer.ask("first", schema)
                reviewer.ask("first", schema)
                reviewer.stage = "comparison"
                reviewer.ask("second", schema)
            usage = summary(work / "token-usage.jsonl")
            self.assertEqual((usage["attempts"], usage["cache_hits"], usage["unknown_attempts"]), (2, 1, 1))
            self.assertEqual(usage["totals"], {"input_tokens": 100, "cached_input_tokens": 40,
                                               "output_tokens": 20, "reasoning_output_tokens": 5})
            self.assertEqual(usage["by_stage"]["pdf"]["input_tokens"], 100)
            self.assertEqual(usage["by_model"]["gpt-5.6-sol"]["output_tokens"], 20)

    def test_unfinished_attempt_is_unknown(self):
        """An interrupted process leaves its started audit event visible."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "usage.jsonl"
            record(path, {"id": "pending", "status": "started", "stage": "pdf"})
            self.assertEqual(summary(path)["unknown_attempts"], 1)

    def test_timeout_keeps_unknown_usage(self):
        """A timed-out Codex call stays in the audit trail."""
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            reviewer = CodexReviewer(work, executable="codex")

            def fake_run(command, **kwargs):
                """Simulate login followed by a timed-out model call."""
                if command[1:3] == ["login", "status"]:
                    return SimpleNamespace(returncode=0, stdout="ChatGPT", stderr="")
                raise subprocess.TimeoutExpired(command, 1)

            with patch("codex_reviewer.subprocess.run", side_effect=fake_run):
                with self.assertRaises(subprocess.TimeoutExpired):
                    reviewer.ask("receipt", object_schema({"ok": {"type": "boolean"}}))
            usage = summary(work / "token-usage.jsonl")
            self.assertEqual((usage["attempts"], usage["unknown_attempts"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
