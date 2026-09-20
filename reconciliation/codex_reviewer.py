"""Schema-validated, cached codex exec calls using the existing ChatGPT login."""
import hashlib
import json
import os
import shutil
import threading
from contextlib import contextmanager
from copy import copy
from uuid import uuid4
from pathlib import Path

from jsonschema import validate
from reconciliation.review_settings import DEFAULT_MODEL
from reconciliation.prompts import load_prompt, load_schema
from reconciliation.process_manager import ProcessManager, ReviewCancelled
from reconciliation import development_cache
from reconciliation.token_usage import FIELDS, record, reported_usage


def object_schema(properties):
    # Codex structured output requires every field and rejects extra fields.
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


TEXT = {"type": "string"}
TEXTS = {"type": "array", "items": TEXT}
EXTRACTION = load_schema("extraction.legacy")
MONEY = EXTRACTION["properties"]["money"]["items"]
RECEIPT = EXTRACTION["properties"]["receipts"]["items"]
from reconciliation.pieces import FACTS, TOTALS
# Old saved receipts remain valid; the model uses the lean canonical schema.
RECEIPT['properties'].update({'payee': TEXT, 'references': FACTS, 'dates': FACTS, 'amount_basis': TEXT,
    'piece_id': TEXT, 'parent_piece_ids': TEXTS})
EXTRACTION['properties'].update({'summary': TEXT, 'totals': TOTALS, 'review_warnings': TEXTS})
SCREEN = object_schema({"comparisons": {"type": "array", "items": object_schema({
    "right_id": TEXT, "candidate": {"type": "boolean"}, "reason": TEXT,
})}})
COMPARISON = object_schema({
    "classification": {"type": "string", "enum": ["same_document", "revised_or_conflicting",
        "partial_overlap", "related_support", "distinct", "uncertain"]},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    "evidence": TEXTS, "differences": TEXTS, "limitations": TEXTS,
})


class BudgetReached(Exception):
    """Stop between calls while retaining completed work."""


class CodexReviewer:
    def __init__(self, work, executable=None, model=None, max_calls=1000, timeout=240, reasoning="default", cancel_event=None):
        # Keep response caches scoped to model, prompt, schema and image bytes.
        bundled = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/OpenAI/Codex/bin/codex.exe"
        self.executable = executable or shutil.which("codex") or str(bundled)
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
            shared = development_cache.root_for(self.work)
            if shared is not None:
                record(shared / "runs" / self.run_id / "token-usage.jsonl", entry)

    def ask(self, prompt, schema, images=()):
        # Content-addressed requests are resumable without repeating successful calls.
        if self._cancelled.is_set():
            raise ReviewCancelled("Review stopped by user")
        prompt = load_prompt("styles") + "\n\n" + prompt
        digest = hashlib.sha256(json.dumps([prompt, schema, self.model, self.reasoning], sort_keys=True).encode())
        for image in images:
            digest.update(Path(image).read_bytes())
        folder = self.cache / digest.hexdigest()
        folder.mkdir(exist_ok=True)
        result_path = folder / "result.json"
        self.last_result = result_path
        self.last_shared = None
        shared = development_cache.root_for(self.work)
        if shared is not None:
            self.last_shared = shared / "model-requests" / folder.name / "result.json"
            if not result_path.exists() and self.last_shared.is_file():
                shared_result = json.loads(self.last_shared.read_text(encoding="utf-8"))
                validate(shared_result, schema)
                with self.acceptance():
                    development_cache.write_json(result_path, shared_result)
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            validate(result, schema)
            (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
            development_cache.share_request(self.work, folder)
            self._record({"status": "cached", "run_id": self.run_id,
                          "stage": self.stage, "model": self.model, "request": folder.name,
                          "usage": {field: 0 for field in FIELDS}})
            with self.acceptance():
                return result

        # Require subscription login; never silently select an API-key connection.
        with self._login_lock:
            if not self._login_checked[0]:
                login = self.processes.run([self.executable, "login", "status"], timeout=30)
                if login.returncode or "chatgpt" not in (login.stdout + login.stderr).lower():
                    raise ValueError("Run codex login using ChatGPT before starting model review")
                self._login_checked[0] = True
        attempt_id = uuid4().hex
        schema_path = folder / f"schema-{attempt_id}.json"
        output_path = folder / f"response-{attempt_id}.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        output_path.unlink(missing_ok=True)
        command = [self.executable, "exec", "--ignore-user-config", "--skip-git-repo-check",
                   "--ephemeral", "--sandbox", "read-only", "--color", "never", "--json",
                   "--output-schema", str(schema_path.resolve()),
                   "--output-last-message", str(output_path.resolve())]
        if self.model:
            command += ["--model", self.model]
        if self.reasoning != "default":
            command += ["-c", f'model_reasoning_effort="{self.reasoning}"']
        for image in images:
            command += ["--image", str(Path(image).resolve())]
        command += ["-"]
        events_path = folder / f"events-{attempt_id}.jsonl"
        entry = {"id": attempt_id, "run_id": self.run_id, "stage": self.stage,
                 "model": self.model, "reasoning": self.reasoning, "request": folder.name,
                 "events": str(events_path)}
        with self._shared_lock:
            if self._cancelled.is_set():
                raise ReviewCancelled("Review stopped by user")
            if self._calls[0] >= self.max_calls:
                raise BudgetReached("Call limit reached; resume with the same command")
            self._record({**entry, "status": "started"})
            self._calls[0] += 1
        development_cache.share_request(self.work, folder)
        process_audit = {}
        status = "failed"
        try:
            with events_path.open("w", encoding="utf-8") as events, (folder / f"exec-{attempt_id}.log").open("w", encoding="utf-8") as log:
                process = self.processes.run(command, input=prompt, timeout=self.timeout,
                                             stdout=events, stderr=log, cwd=folder, audit=process_audit)
                status = "finished" if process.returncode == 0 else "failed"
        except ReviewCancelled:
            status = "cancelled"
            raise
        finally:
            usage = reported_usage(events_path)
            self._record({**entry, "status": status,
                          "usage": usage, **process_audit})
            development_cache.share_request(self.work, folder)
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
            if self.last_shared is not None:
                development_cache.copy_atomic(result_path, self.last_shared)
        return result

    def invalidate(self):
        # Discard structurally valid responses that fail workflow coverage validation.
        self.last_result.unlink(missing_ok=True)
        if self.last_shared is not None and development_cache.root_for(self.work) is not None:
            self.last_shared.unlink(missing_ok=True)
