"""Codex CLI login status, version check and device-code ChatGPT login for the Settings page."""

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from reconciliation.model.codex import LOGIN_CHECK_TIMEOUT

#: Seconds the latest-release lookup is reused before asking GitHub again.
LATEST_CACHE_SECONDS = 6 * 3600
#: Seconds a device-code login may wait for the user before it is stopped.
LOGIN_TIMEOUT = 15 * 60
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
URL = re.compile(r"https://\S+")
CODE = re.compile(r"\b[A-Z0-9]{4,5}-[A-Z0-9]{4,5}\b")

_lock = threading.Lock()
_latest = {"version": None, "checked": 0.0, "error": ""}
_login = {"process": None, "running": False, "lines": [], "url": "", "code": "", "exit_code": None, "started": 0.0}


def command():
    """The Codex CLI the workflow uses: PATH first, then the Windows desktop install."""
    bundled = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/OpenAI/Codex/bin/codex.exe"
    return [shutil.which("codex") or str(bundled)]


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


def status(refresh=False):
    """Login method, installed and latest versions, and any device login in progress."""
    code, text = run("login", "status")
    lowered = text.lower()
    method = "chatgpt" if "chatgpt" in lowered else "api key" if "api key" in lowered else ""
    version_code, version_text = run("--version")
    installed = re.search(r"\d+\.\d+\.\d+", version_text) if version_code == 0 else None
    latest, latest_error = latest_version(refresh)
    return {
        "available": code is not None,
        "logged_in": code == 0 and bool(method),
        "method": method,
        "detail": text,
        "installed": installed[0] if installed else None,
        "latest": latest,
        "latest_error": latest_error,
        "update_available": bool(installed and latest and _number(latest) > _number(installed[0])),
        "login": login_state(),
    }


def _number(version):
    """Compare dotted versions numerically."""
    return tuple(int(part) for part in version.split("."))


def _view():
    """Public view of the device-code login: link, code, recent output and outcome (lock held)."""
    return {key: _login[key] for key in ("running", "url", "code", "exit_code")} | {"lines": _login["lines"][-8:]}


def login_state():
    """Device-code login state; a login left waiting too long is stopped."""
    with _lock:
        if _login["process"] and time.time() - _login["started"] > LOGIN_TIMEOUT:
            _login["process"].kill()
        return _view()


def start_login():
    """Start `codex login --device-auth` once; the user finishes it in any browser with the shown code."""
    with _lock:
        if _login["running"]:
            return _view()
        process = subprocess.Popen(
            [*command(), "login", "--device-auth"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            env={**os.environ, "NO_COLOR": "1"},
        )
        _login.update(process=process, running=True, lines=[], url="", code="", exit_code=None, started=time.time())
    threading.Thread(target=_follow, args=(process,), daemon=True).start()
    return login_state()


def _follow(process):
    """Collect the login output and pick out the sign-in link and one-time code."""
    for raw in process.stdout:
        line = ANSI.sub("", raw).strip()
        if not line:
            continue
        with _lock:
            _login["lines"].append(line)
            _login["url"] = _login["url"] or (URL.search(line)[0] if URL.search(line) else "")
            _login["code"] = _login["code"] or (CODE.search(line)[0] if CODE.search(line) else "")
    process.wait()
    with _lock:
        _login.update(running=False, exit_code=process.returncode, process=None)


def cancel_login():
    """Stop a device-code login that is still waiting."""
    with _lock:
        if _login["process"]:
            _login["process"].kill()
    return login_state()
