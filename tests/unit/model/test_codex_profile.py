"""Check isolated Codex workflow arguments without live model calls."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from reconciliation.model.codex import CodexReviewer, object_schema
from tests.fixtures.workflow import mock_codex


class CodexProfileTests(unittest.TestCase):
    """Preserve built-in prompts and evidence while removing unused context."""

    def test_workflow_keeps_builtin_instructions_without_skills_or_computer_use(self):
        """Isolate workflow context while retaining attached evidence and JSON output."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        image = base / "receipt.png"
        image.write_bytes(b"synthetic attachment")
        working_dirs = []

        def fake_run(command, **kwargs):
            """Inspect the model process while its temporary directory exists."""
            if command[1:3] == ["login", "status"]:
                return SimpleNamespace(returncode=0, stdout="ChatGPT", stderr="")
            cwd = Path(kwargs["cwd"])
            working_dirs.append(cwd)
            self.assertTrue(cwd.is_dir())
            self.assertFalse(cwd.is_relative_to(base))
            self.assertFalse(any("model_instructions_file" in arg for arg in command))
            disabled = {command[i + 1] for i, arg in enumerate(command) if arg == "--disable"}
            self.assertTrue({"computer_use", "plugins", "skill_search"} <= disabled)
            self.assertNotIn("view_image", disabled)
            self.assertIn("tools.view_image=true", command)
            self.assertIn("skip_host_skill_discovery", command)
            self.assertIn('web_search="disabled"', command)
            self.assertEqual(command[command.index("--image") + 1], str(image.resolve()))
            schema = Path(command[command.index("--output-schema") + 1])
            self.assertTrue(schema.is_absolute() and schema.is_file())
            Path(command[command.index("--output-last-message") + 1]).write_text('{"ok": true}')
            return SimpleNamespace(returncode=0)

        with mock_codex(fake_run):
            engine = CodexReviewer(base, executable="codex")
            self.assertTrue(engine.ask("test", object_schema({"ok": {"type": "boolean"}}), [image])["ok"])
        self.assertTrue(working_dirs)
        self.assertTrue(all(not path.exists() for path in working_dirs))
