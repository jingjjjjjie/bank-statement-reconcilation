"""Check Codex login status parsing and device-code login with a stand-in CLI (no real Codex)."""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from dashboard.services import codex_account

FAKE = """import sys
args = sys.argv[1:]
if args == ['--version']:
    print('codex-cli 0.160.0')
elif args == ['login', 'status']:
    print('Logged in using ChatGPT')
elif args == ['login', '--device-auth']:
    print('\\x1b[1mOpen https://auth.example.com/codex/device\\x1b[0m')
    print('Enter this one-time code: ABCD-12345')
"""


class CodexAccountTests(unittest.TestCase):
    def setUp(self):
        """Point the service at a stand-in CLI and a fixed latest release."""
        folder = Path(tempfile.mkdtemp())
        (folder / "codex.py").write_text(FAKE, encoding="utf-8")
        patches = [
            mock.patch.object(codex_account, "command", lambda: [sys.executable, str(folder / "codex.py")]),
            mock.patch.object(codex_account, "latest_version", lambda refresh=False: ("0.161.0", "")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_status_reports_chatgpt_login_and_update(self):
        """ChatGPT login is recognised and a newer release is flagged."""
        data = codex_account.status()
        self.assertEqual((data["logged_in"], data["method"]), (True, "chatgpt"))
        self.assertEqual((data["installed"], data["update_available"]), ("0.160.0", True))

    def test_device_login_shows_link_and_code(self):
        """The sign-in link and one-time code are picked out of colourised output."""
        codex_account.start_login()
        deadline = time.time() + 10
        while codex_account.login_state()["running"] and time.time() < deadline:
            time.sleep(0.05)
        state = codex_account.login_state()
        self.assertEqual(state["url"], "https://auth.example.com/codex/device")
        self.assertEqual((state["code"], state["exit_code"]), ("ABCD-12345", 0))


if __name__ == "__main__":
    unittest.main()
