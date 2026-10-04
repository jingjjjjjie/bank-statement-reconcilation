"""Codex CLI login status, a live connection check, version update and device-code ChatGPT login for Settings."""

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

from reconciliation.core.paths import WORKSPACE
from reconciliation.core.settings import DEFAULT_MODEL
from reconciliation.extraction.results.schemas import TEXT, object_schema
from reconciliation.model.codex import LOGIN_CHECK_TIMEOUT, UPDATED_CODEX, CodexReviewer, codex_executable

#: Seconds the latest-release lookup is reused before asking GitHub again.
LATEST_CACHE_SECONDS = 6 * 3600
#: Seconds a device-code login may wait for the user before it is stopped.
LOGIN_TIMEOUT = 15 * 60
#: Seconds an update install may take before it is stopped.
UPDATE_TIMEOUT = 10 * 60
#: Seconds the live connection check may take.
CHECK_TIMEOUT = 120
CHECK_WORK = WORKSPACE / "review/codex-check"
CHECK_SCHEMA = object_schema({"reply": TEXT})
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
URL = re.compile(r"https://\S+")
CODE = re.compile(r"\b[A-Z0-9]{4,5}-[A-Z0-9]{4,5}\b")

_lock = threading.Lock()
_latest = {"version": None, "checked": 0.0, "error": ""}


class Job:
    """One background Codex or npm command whose output the page polls."""

    def __init__(self, timeout):
        """Start idle; `timeout` stops a run that waits too long."""
        self.timeout, self.process, self.started = timeout, None, 0.0
        self.running, self.lines, self.url, self.code, self.exit_code = False, [], "", "", None

    def view(self):
        """Public state (lock held): running, link, code, recent output and exit code."""
        if self.process and time.time() - self.started > self.timeout:
            self.process.kill()
        return {"running": self.running, "url": self.url, "code": self.code, "exit_code": self.exit_code} | {
            "lines": self.lines[-8:]
        }

    def start(self, arguments):
        """Launch the command (lock held) and follow its output in a thread."""
        self.process = subprocess.Popen(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            env={**os.environ, "NO_COLOR": "1"},
        )
        self.running, self.lines, self.url, self.code, self.exit_code = True, [], "", "", None
        self.started = time.time()
        threading.Thread(target=self._follow, args=(self.process,), daemon=True).start()

    def _follow(self, process):
        """Collect output and pick out any sign-in link and one-time code."""
        for raw in process.stdout:
            line = ANSI.sub("", raw).strip()
            if not line:
                continue
            with _lock:
                self.lines.append(line)
                self.url = self.url or (URL.search(line)[0] if URL.search(line) else "")
                self.code = self.code or (CODE.search(line)[0] if CODE.search(line) else "")
        process.wait()
        with _lock:
            self.running, self.exit_code, self.process = False, process.returncode, None

    def cancel(self):
        """Stop the command if it is still running."""
        with _lock:
            if self.process:
                self.process.kill()
            return self.view()


_login, _update = Job(LOGIN_TIMEOUT), Job(UPDATE_TIMEOUT)


def command():
    """The Codex CLI the workflow uses, including a newer copy installed by Update."""
    return [codex_executable()]


def run(*arguments):
    """Run one short Codex command and return its exit code and combined, colourless output."""
    try:
        result = subprocess.run(
            [*command(), *arguments],
            capture_output=True,
            text=True,
            timeout=LOGIN_CHECK_TIMEOUT,
            env={**os.environ, "NO_COLOR": "1"},
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    return result.returncode, ANSI.sub("", result.stdout + result.stderr).strip()


def latest_version(refresh=False):
    """Latest stable Codex release, cached; unknown when GitHub cannot be reached."""
    from scripts.codex.update_codex import latest_version as fetch

    with _lock:
        if refresh or time.time() - _latest["checked"] > LATEST_CACHE_SECONDS:
            try:
                _latest.update(version=fetch(), error="")
            except Exception as error:  # Network and release-format failures leave the version unknown.
                _latest.update(version=None, error=str(error))
            _latest["checked"] = time.time()
        return _latest["version"], _latest["error"]


def _number(version):
    """Compare dotted versions numerically."""
    return tuple(int(part) for part in version.split("."))


def status(refresh=False):
    """Login method, installed and latest versions, and any login or update in progress."""
    code, text = run("login", "status")
    lowered = text.lower()
    method = "chatgpt" if "chatgpt" in lowered else "api key" if "api key" in lowered else ""
    version_code, version_text = run("--version")
    installed = re.search(r"\d+\.\d+\.\d+", version_text) if version_code == 0 else None
    latest, latest_error = latest_version(refresh)
    with _lock:
        login, update = _login.view(), _update.view()
    return {
        "available": code is not None,
        "logged_in": code == 0 and bool(method),
        "method": method,
        "detail": text,
        "installed": installed[0] if installed else None,
        "latest": latest,
        "latest_error": latest_error,
        "update_available": bool(installed and latest and _number(latest) > _number(installed[0])),
        "can_update": bool(shutil.which("npm")),
        "login": login,
        "update": update,
    }


def check_connection():
    """Send one tiny real `codex exec` request; usage is recorded like any workflow call."""
    started = time.time()
    reviewer = CodexReviewer(CHECK_WORK, model=DEFAULT_MODEL, max_calls=1, timeout=CHECK_TIMEOUT)
    reviewer.stage = "connection_check"
    try:
        # A fresh token keeps the request out of the response cache, so the call really reaches Codex.
        result = reviewer.ask(f"Connection check {uuid4().hex}. Reply with the single word: ready.", CHECK_SCHEMA)
        ok, error = "ready" in result["reply"].lower(), ""
    except Exception as failure:  # Login, network, timeout and schema failures are all reported, not raised.
        ok, error = False, str(failure)
    finally:
        if reviewer.last_result is not None:
            shutil.rmtree(reviewer.last_result.parent, ignore_errors=True)
    return {"ok": ok, "error": error, "model": DEFAULT_MODEL, "seconds": round(time.time() - started, 1)}


def login_state():
    """Device-code login state."""
    with _lock:
        return _login.view()


def start_login():
    """Start `codex login --device-auth` once; the user finishes it in any browser with the shown code."""
    with _lock:
        if not _login.running:
            _login.start([*command(), "login", "--device-auth"])
        return _login.view()


def cancel_login():
    """Stop a device-code login that is still waiting."""
    return _login.cancel()


def codex_busy():
    """Whether a workflow `codex exec` call is running (Linux containers expose processes under /proc)."""
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            arguments = path.read_bytes().split(b"\0")
        except OSError:
            continue
        if b"exec" in arguments and any(
            argument.rsplit(b"/", 1)[-1] in (b"codex", b"codex.js") for argument in arguments
        ):
            return True
    return False


def update_state():
    """Update install state."""
    with _lock:
        return _update.view()


def start_update():
    """Install the latest stable Codex into the login volume; later calls use it automatically."""
    latest, error = latest_version(refresh=True)
    npm = shutil.which("npm")
    if not latest or not npm:
        raise ValueError(error or "npm is not available to install Codex")
    if codex_busy():
        raise ValueError("A Codex request is running. Wait for it to finish before updating.")
    with _lock:
        if _login.running:
            raise ValueError("Finish or cancel the login before updating")
        if not _update.running:
            UPDATED_CODEX.mkdir(parents=True, exist_ok=True)
            _update.start(
                [npm, "install", "--prefix", str(UPDATED_CODEX), "--no-audit", "--no-fund", f"@openai/codex@{latest}"]
            )
        return _update.view()
