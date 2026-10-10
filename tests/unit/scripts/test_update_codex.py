"""Protect user settings and running work during Codex upgrades."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.codex import update_codex as updater


class CodexUpdateTests(unittest.TestCase):
    """Exercise update failures without Docker, downloads or model calls."""

    def setUp(self):
        """Create realistic pins with unrelated settings and Windows line endings."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        values = {
            '.env': 'UPLOADS_PATH="C:/My Files"\r\nCODEX_VERSION=0.1.0\r\n',
            '.env.example': 'CODEX_VERSION=0.1.0\n',
            'docker/Dockerfile': 'ARG CODEX_VERSION=0.1.0\n',
            'docker/compose.yaml': 'CODEX_VERSION: ${CODEX_VERSION:-0.1.0}\n',
        }
        for name, text in values.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
        for target, value in [('ROOT', self.root), ('latest_version', None), ('installed_version', None)]:
            mock = (
                patch.object(updater, target, value)
                if value is not None
                else patch.object(updater, target, return_value='0.2.0' if target == 'latest_version' else '0.1.0')
            )
            mock.start()
            self.addCleanup(mock.stop)

    def test_pin_edits_preserve_user_settings_and_crlf(self):
        """Only the version changes in existing configuration files."""
        _, after = updater.planned_pins('0.2.0')[self.root / '.env']
        self.assertEqual(after, b'UPLOADS_PATH="C:/My Files"\r\nCODEX_VERSION=0.2.0\r\n')

    def test_check_does_not_write_or_build(self):
        """Read-only checking cannot stop or rebuild the dashboard."""
        with patch.object(updater, 'compose') as compose:
            updater.update(check=True)
        compose.assert_not_called()
        self.assertIn(b'0.1.0', (self.root / '.env').read_bytes())

    def test_busy_workflow_blocks_build(self):
        """An active workflow prevents any container or pin mutation."""
        with (
            patch.object(updater, 'ensure_idle', side_effect=ValueError('busy')),
            patch.object(updater, 'compose') as compose,
        ):
            with self.assertRaisesRegex(ValueError, 'busy'):
                updater.update()
        compose.assert_not_called()
        self.assertIn(b'0.1.0', (self.root / '.env').read_bytes())

    def test_failed_build_leaves_pins_and_service_untouched(self):
        """A failed download/build must not replace the running container."""
        with (
            patch.object(updater, 'ensure_idle'),
            patch.object(updater, 'compose', side_effect=subprocess.CalledProcessError(1, 'build')) as compose,
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                updater.update()
        self.assertEqual(compose.call_count, 1)
        self.assertEqual(compose.call_args.args[0], 'build')
        self.assertIn(b'0.1.0', (self.root / '.env').read_bytes())

    def test_success_rechecks_idle_and_verifies_installed_version(self):
        """Replacement follows a successful build and a second idle check."""
        with (
            patch.object(updater, 'ensure_idle') as idle,
            patch.object(updater, 'compose') as compose,
            patch.object(updater, 'installed_version', side_effect=['0.1.0', '0.2.0']),
        ):
            updater.update()
        self.assertEqual(idle.call_count, 2)
        self.assertEqual([call.args[0] for call in compose.call_args_list], ['build', 'up'])
        self.assertIn(b'0.2.0', (self.root / '.env').read_bytes())


if __name__ == '__main__':
    unittest.main()
