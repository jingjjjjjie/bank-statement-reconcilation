"""Schema-validated, cached codex exec calls using the existing ChatGPT login."""

import hashlib
import json
import os
import shutil
import threading
from contextlib import contextmanager
from copy import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from jsonschema import validate

from reconciliation.core.prompts import load_prompt
from reconciliation.core.settings import DEFAULT_MODEL

# Schemas live in reconciliation.extraction.results.schemas; re-exported for existing callers.
from reconciliation.extraction.results.schemas import EXTRACTION, RECEIPT, TEXT, TEXTS, object_schema  # noqa: F401
from reconciliation.model.processes import ProcessManager, ReviewCancelled
from reconciliation.model.token_usage import FIELDS, record, reported_usage

DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "plugins",
    "remote_plugin",
    "image_generation",
    "shell_tool",
    "unified_exec",
    "multi_agent",
    "multi_agent_v2",
    "goals",
    "sleep_tool",
    "code_mode",
    "code_mode_host",
    "skill_search",
    "memories",
    "hooks",
)
# Codex settings that change responses are part of every cache key.
CACHE_PROFILE = [
    "builtin-instructions",
    DISABLED_FEATURES,
    "skip_host_skill_discovery",
    "web_search=disabled",
    "project_doc_max_bytes=0",
]

#: Default seconds one `codex exec` call may run before it is stopped.
DEFAULT_TIMEOUT = 240
#: Default cap on new model calls in one run; cached answers do not count.
DEFAULT_MAX_CALLS = 1000
#: Seconds allowed for `codex login status`.
LOGIN_CHECK_TIMEOUT = 30


#: Codex installed by the dashboard's Update button, kept in the login volume so it survives restarts.
UPDATED_CODEX = Path.home() / ".codex/cli"


def package_version(executable):
    """Version from the npm package behind a Codex executable, or None when it is not an npm install."""
    package = Path(executable).resolve().parents[1] / "package.json"
    try:
        return tuple(int(part) for part in json.loads(package.read_text(encoding="utf-8"))["version"].split("."))
    except (OSError, ValueError, KeyError):
        return None


def codex_executable():
    """The Codex CLI to run: a newer dashboard-updated copy, else PATH, else the Windows desktop install."""
    bundled = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/OpenAI/Codex/bin/codex.exe"
    installed = shutil.which("codex") or str(bundled)
    updated = UPDATED_CODEX / "node_modules/.bin/codex"
    if updated.is_file() and (package_version(updated) or ()) > (package_version(installed) or ()):
        return str(updated)
    return installed


def request_digest(prompt, schema, model, reasoning, images=()):
    """Content-address one request by prompt, schema, model settings and image bytes."""
    digest = hashlib.sha256(json.dumps([prompt, schema, model, reasoning, CACHE_PROFILE], sort_keys=True).encode())
    for image in images:
        digest.update(Path(image).read_bytes())
    return digest.hexdigest()


def codex_command(executable, schema_path, output_path, model=None, reasoning="default", images=()):
    """Build an isolated, read-only codex exec command that reads its prompt from stdin."""
    command = [
        executable,
        "exec",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--json",
        "--output-schema",
        str(Path(schema_path).resolve()),
        "--output-last-message",
        str(Path(output_path).resolve()),
    ]
    command += ["-c", 'web_search="disabled"', "-c", "project_doc_max_bytes=0"]
    command += ["--enable", "skip_host_skill_discovery"]
    command += ["--enable", "view_image", "-c", "tools.view_image=true"]
    for feature in DISABLED_FEATURES:
        command += ["--disable", feature]
    if model:
        command += ["--model", model]
    if reasoning != "default":
        command += ["-c", f'model_reasoning_effort="{reasoning}"']
    for image in images:
        command += ["--image", str(Path(image).resolve())]
    return command + ["-"]


class BudgetReached(Exception):
    """Stop between calls while retaining completed work."""


class CodexReviewer:
    """Model client backed by `codex exec` and the ChatGPT subscription login (implements `reconciliation.model.client.ModelClient`)."""

    def __init__(
        self,
        work,
        executable=None,
        model=None,
        max_calls=DEFAULT_MAX_CALLS,
        timeout=DEFAULT_TIMEOUT,
        reasoning="default",
        cancel_event=None,
    ):
        """Configure the codex executable, default model, call budget and cache folder under `work`."""
        self.executable = executable or codex_executable()
        self.work, self.model = work, model if model is not None else DEFAULT_MODEL
        self.reasoning = reasoning
        self.max_calls, self.timeout = max_calls, timeout
        self._shared_lock = threading.RLock()
        self._commit_lock = threading.RLock()
        self._calls = [0]
        self._login_checked = [False]
        self._login_lock = threading.Lock()
        self._cancelled = cancel_event if cancel_event is not None else threading.Event()
        self.processes = ProcessManager(self._cancelled)
        self.cache = work / "model-cache"
        self.usage_path = work / "token-usage.jsonl"
        self.run_id = uuid4().hex
        self.stage = "unknown"
        self.last_result = None
        self.cache.mkdir(parents=True, exist_ok=True)

    @property
    def calls(self):
        """Return the shared number of new model attempts in this run."""
        with self._shared_lock:
            return self._calls[0]

    def fork(self):
        """Give one parallel task its own stage and cache-result pointer."""
        worker = copy(self)
        worker.last_result = None
        return worker

    def cancel(self):
        """Wake all process owners to terminate and verify their entire trees."""
        self.processes.cancel()
        # Wait only for a publication already underway, never for model execution.
        with self._commit_lock:
            pass

    @contextmanager
    def acceptance(self):
        """Fence cache publication and checkpoint acceptance against cancellation."""
        with self._commit_lock:
            if self._cancelled.is_set():
                raise ReviewCancelled("Review stopped by user")
            yield

    @property
    def active_count(self):
        """Expose unfinished process cleanup to the dashboard."""
        return self.processes.active_count

    def _record(self, entry):
        """Append token events without interleaving parallel writes."""
        entry = {"event_id": uuid4().hex, **entry}
        with self._shared_lock:
            record(self.usage_path, entry)

    def ask(self, prompt, schema, images=()):
        """Return a schema-valid answer, reusing cached results so runs resume without repeat calls."""
        if self._cancelled.is_set():
            raise ReviewCancelled("Review stopped by user")
        prompt = load_prompt("shared/styles") + "\n\n" + prompt
        folder = self.cache / request_digest(prompt, schema, self.model, self.reasoning, images)
        folder.mkdir(exist_ok=True)
        result_path = folder / "result.json"
        self.last_result = result_path
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            validate(result, schema)
            (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
            self._record(
                {
                    "status": "cached",
                    "run_id": self.run_id,
                    "stage": self.stage,
                    "model": self.model,
                    "request": folder.name,
                    "usage": {field: 0 for field in FIELDS},
                }
            )
            with self.acceptance():
                return result

        # Require subscription login; never silently select an API-key connection.
        with self._login_lock:
            if not self._login_checked[0]:
                login = self.processes.run([self.executable, "login", "status"], timeout=LOGIN_CHECK_TIMEOUT)
                if login.returncode or "chatgpt" not in (login.stdout + login.stderr).lower():
                    raise ValueError("Run codex login using ChatGPT before starting model review")
                self._login_checked[0] = True
        attempt_id = uuid4().hex
        schema_path = folder / f"schema-{attempt_id}.json"
        output_path = folder / f"response-{attempt_id}.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        output_path.unlink(missing_ok=True)
        command = codex_command(self.executable, schema_path, output_path, self.model, self.reasoning, images)
        events_path = folder / f"events-{attempt_id}.jsonl"
        entry = {
            "id": attempt_id,
            "run_id": self.run_id,
            "stage": self.stage,
            "model": self.model,
            "reasoning": self.reasoning,
            "request": folder.name,
            "events": str(events_path),
        }
        with self._shared_lock:
            if self._cancelled.is_set():
                raise ReviewCancelled("Review stopped by user")
            if self._calls[0] >= self.max_calls:
                raise BudgetReached("Call limit reached; resume with the same command")
            self._record({**entry, "status": "started"})
            self._calls[0] += 1
        process_audit = {}
        status = "failed"
        try:
            with (
                TemporaryDirectory(prefix="reconciliation-codex-") as isolated,
                events_path.open("w", encoding="utf-8") as events,
                (folder / f"exec-{attempt_id}.log").open("w", encoding="utf-8") as log,
            ):
                process = self.processes.run(
                    command,
                    input=prompt,
                    timeout=self.timeout,
                    stdout=events,
                    stderr=log,
                    cwd=isolated,
                    audit=process_audit,
                )
                status = "finished" if process.returncode == 0 else "failed"
        except ReviewCancelled:
            status = "cancelled"
            raise
        finally:
            usage = reported_usage(events_path)
            self._record({**entry, "status": status, "usage": usage, **process_audit})
        if self._cancelled.is_set():
            raise ReviewCancelled("Review stopped by user")
        if process.returncode or not output_path.exists():
            raise ValueError(f"codex exec failed; see {folder / f'exec-{attempt_id}.log'}")
        result = json.loads(output_path.read_text(encoding="utf-8-sig"))
        validate(result, schema)
        temporary = folder / f"result-{attempt_id}.json"
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        with self.acceptance():
            temporary.replace(result_path)
        return result

    def invalidate(self):
        """Discard the last cached answer after it fails workflow validation."""
        # Discard structurally valid responses that fail workflow coverage validation.
        if self.last_result is not None:
            self.last_result.unlink(missing_ok=True)
