"""Verify editable instructions reach Codex and invalidate cached requests."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from reconciliation.codex_reviewer import CodexReviewer, object_schema
from reconciliation.prompts import load_prompt
from tests.helpers import mock_codex


class PromptTests(unittest.TestCase):
    def test_edits_reach_process_and_bypass_old_cache(self):
        """Reload task and style edits without restarting an existing reviewer."""
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "styles.md").write_text("Original rules\n", encoding="utf-8")
            (folder / "extraction.md").write_text("Original task\n", encoding="utf-8")
            received = []

            def fake_run(command, **kwargs):
                """Capture standard input and return schema-valid fixture output."""
                if command[1:3] == ["login", "status"]:
                    return SimpleNamespace(returncode=0, stdout="ChatGPT", stderr="")
                received.append(kwargs["input"])
                Path(command[command.index("--output-last-message") + 1]).write_text(
                    '{"ok": true}', encoding="utf-8")
                return SimpleNamespace(returncode=0)

            reviewer = CodexReviewer(folder / "review", executable="codex")
            schema = object_schema({"ok": {"type": "boolean"}})
            with patch("reconciliation.prompts.PROMPTS", folder), mock_codex(fake_run):
                reviewer.ask(load_prompt("extraction"), schema)
                reviewer.ask(load_prompt("extraction"), schema)
                (folder / "extraction.md").write_text("Edited task", encoding="utf-8")
                reviewer.ask(load_prompt("extraction"), schema)
                (folder / "styles.md").write_text("Edited rules", encoding="utf-8-sig")
                reviewer.ask(load_prompt("extraction"), schema)
            self.assertEqual(received, ["Original rules\n\nOriginal task",
                                        "Original rules\n\nEdited task",
                                        "Edited rules\n\nEdited task"])
            saved = {path.read_text(encoding="utf-8")
                     for path in reviewer.cache.glob("*/prompt.txt")}
            self.assertEqual(saved, set(received))

    def test_missing_and_empty_files_fail(self):
        """Never substitute hidden instructions when editable files are invalid."""
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with patch("reconciliation.prompts.PROMPTS", folder):
                with self.assertRaises(FileNotFoundError):
                    load_prompt("extraction")
                (folder / "extraction.md").write_text(" \n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Prompt file is empty"):
                    load_prompt("extraction")
