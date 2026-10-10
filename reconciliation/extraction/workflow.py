"""Prepare, run, check and report a supporting-document extraction review."""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import sleep

from jsonschema.exceptions import ValidationError

from reconciliation.core import development_cache
from reconciliation.core.money import normalize_currencies
from reconciliation.core.paths import WORKSPACE
from reconciliation.core.settings import (
    CONFIG_PATH,
    config_for_manifest,
    content_settings,
    load_config,
    model_settings,
    revision,
    stage_settings,
    validate as validate_config,
)
from reconciliation.extraction.pipeline.assembly import ASSEMBLY, current_assembly
from reconciliation.extraction.pipeline.job_runner import run_jobs  # noqa: F401  (re-exported for existing callers)
from reconciliation.extraction.pipeline.stages import ReceiptAssembly, ReviewPending, RunContext, UnitExtraction
from reconciliation.extraction.results import pieces
from reconciliation.extraction.results.inventory import export as export_inventory
from reconciliation.extraction.results.records import Index, State
from reconciliation.extraction.results.report import render as render_report
from reconciliation.extraction.results.schemas import EXTRACTION
from reconciliation.extraction.sources import pdf_routing
from reconciliation.extraction.sources.reader import SUPPORTED_SUFFIXES, extract
from reconciliation.intake.duplicates import DEFAULT_MANIFEST, check as exact_check, fingerprint, review_files
from reconciliation.model.client import acceptance, invalidate, supports_parallel, worker_for
from reconciliation.model.codex import BudgetReached, CodexReviewer
from reconciliation.model.token_usage import summary as token_summary

DEFAULT_WORK = WORKSPACE / "review"
ACCEPTED_SUFFIXES = SUPPORTED_SUFFIXES

#: Windows briefly locks files that antivirus or indexers are reading; retry the checkpoint rename this often.
SAVE_RETRIES = 15
#: Seconds added to the wait before each further retry (linear backoff: 0.02, 0.04, ...).
SAVE_RETRY_STEP = 0.02
#: Upper bound on processes rendering documents in parallel during `prepare`.
MAX_PREPARE_WORKERS = 8
#: Default seconds one `codex exec` call may run from the command line.
DEFAULT_CALL_TIMEOUT = 240


def read(path):
    """Read JSON, accepting the BOM that Windows tools write into manifests."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    """Atomically save a checkpoint, retrying brief Windows file locks."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(SAVE_RETRIES):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == SAVE_RETRIES - 1:
                raise
            sleep(SAVE_RETRY_STEP * (attempt + 1))


def inventory(root, manifest_path):
    """Map each document hash to every path holding those bytes; one model input per hash."""
    result = {}
    for path in review_files(root, read(manifest_path), manifest_path):
        result.setdefault(fingerprint(path), []).append(str(path))
    return result


def prepare(manifest_path, work, config_path=None, refresh=False):
    """Split every supporting document into units locally and write a fresh review; no model calls.

    Args:
        manifest_path: Exact-duplicate manifest naming the supporting folder.
        work: Review folder to create (must be outside the supporting folder).
        config_path: Review settings file; defaults to the shared config.
        refresh: Archive an existing review under `history/` and prepare again.

    Raises:
        ValueError: The review exists without `refresh`, or paths or settings are invalid.
    """
    if config_path is not None and not Path(config_path).is_file():
        raise ValueError(f"Review configuration is missing: {config_path}")
    manifest = read(manifest_path)
    root = Path(manifest["SupportingRoot"]).resolve(strict=True)
    if work.resolve().is_relative_to(root):
        raise ValueError("Review output must be outside the supporting folder")
    work.mkdir(parents=True, exist_ok=True)
    index_path = work / "index.json"
    if index_path.exists():
        if not refresh:
            raise ValueError("Prepared review exists; use prepare --refresh after settings changes")
        # Preserve existing decisions and reports before preparing different inputs.
        import shutil

        history = work / "history" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        history.mkdir(parents=True)
        for name in ("index.json", "state.json", "report.md", "report.json"):
            if (work / name).exists():
                shutil.copy2(work / name, history / name)
    config = load_config(config_path)
    assets = work / "assets" / revision(content_settings(config))[:12]
    jobs = [
        (digest, paths, [r["OriginalPath"] for r in manifest["Files"] if r["SHA256"] == digest], assets, config)
        for digest, paths in sorted(inventory(root, manifest_path).items())
    ]
    # Rendering is CPU-bound, so separate processes read several documents at once.
    workers = min(MAX_PREPARE_WORKERS, os.cpu_count() or 1, len(jobs)) or 1
    documents = {}
    with ProcessPoolExecutor(workers) as pool:
        for number, item in enumerate(pool.map(prepare_document, jobs), 1):
            documents[item["id"]] = item
            print(f"Prepared {number}: {Path(item['paths'][0]).name}", flush=True)
    index = {
        "root": str(root),
        "manifest": str(manifest_path.resolve()),
        "documents": documents,
        "config": config,
        "config_path": str(config_path.resolve()) if config_path else None,
    }
    save(index_path, index)
    save(work / "state.json", {"index_sha256": fingerprint(index_path), "units": {}, "decisions": {}, "model": None})
    report(work, index, read(work / "state.json"))
    print(f"Prepared {len(documents)} unique documents locally; no model calls made.")


def prepare_document(job):
    """Read one document into units and fingerprint its images; errors stay on the item."""
    digest, paths, originals, assets, config = job
    # Preserve original claim associations even after copies have been moved.
    item = {
        "id": digest,
        "paths": paths,
        "original_paths": originals,
        "units": [],
        "error": None,
        "accepted": Path(paths[0]).suffix.lower() in ACCEPTED_SUFFIXES,
    }
    if item["accepted"]:
        try:
            item["units"] = extract(Path(paths[0]), assets / digest, config)
            for unit in item["units"]:
                if unit["image"]:
                    unit["image_sha256"] = fingerprint(Path(unit["image"]))
            if fingerprint(Path(paths[0])) != digest:
                raise ValueError("Source changed during extraction")
        except Exception as error:
            item["error"] = f"{type(error).__name__}: {error}"
    return item


def load_index(work):
    """Validate prepared metadata without reading derived page images."""
    index, state = read(work / "index.json"), read(work / "state.json")
    if fingerprint(work / "index.json") != state["index_sha256"]:
        raise ValueError("Prepared index changed; create a new review")
    return index, state


def load(work):
    """Validate metadata and every prepared image before using extraction evidence."""
    index, state = load_index(work)
    for document in index["documents"].values():
        for unit in document["units"]:
            if unit["image"] and fingerprint(Path(unit["image"])) != unit["image_sha256"]:
                raise ValueError("Prepared image changed; create a new review")
    return index, state


def removal_plan(state):
    """Return `{removed hash: kept hash}` from admin decisions.

    Raises:
        ValueError: Choices conflict or chain (a survivor is also removed).
    """
    removed = {}
    for pair, decision in state["decisions"].items():
        left, right = pair.split(":")
        verdict = decision["verdict"]
        if verdict == "keep_left":
            loser, keeper = right, left
        elif verdict == "keep_right":
            loser, keeper = left, right
        else:
            continue
        if loser in removed and removed[loser] != keeper:
            raise ValueError("Conflicting survivor choices; resolve decisions before cleanup")
        removed[loser] = keeper
    if set(removed) & set(removed.values()):
        raise ValueError("A selected survivor is also marked for deletion; resolve decisions")
    return removed


def current_inventory(index, state):
    """Return the current source inventory and approved removals.

    Raises:
        ValueError: Sources changed other than by approved duplicate removals.
    """
    current = inventory(Path(index["root"]), Path(index["manifest"]))
    removed = removal_plan(state)
    unknown = set(current) - set(index["documents"])
    missing = set(index["documents"]) - set(current) - set(removed)
    if unknown or missing:
        raise ValueError(
            f"Sources changed: {len(unknown)} new/modified, {len(missing)} unapproved missing; prepare a new review"
        )
    return current, removed


def check_run_allowed(config):
    """Refuse to start model work when settings forbid it."""
    if config["pdf_mode"] in pdf_routing.MODES and not development_cache.mode()["enabled"]:
        raise ReviewPending("Experimental PDF modes require development mode; choose Vision in Settings")
    if not config["codex_enabled"]:
        raise ReviewPending("Codex is off in review settings; no model calls were made")


def lock_stage_models(state, reviewer, config):
    """Pin per-stage model choices in `state` so one review never mixes models."""
    choices = getattr(reviewer, "stage_choices", stage_settings(config))
    previous = state.get("stage_models")
    if previous is None and state.get("model"):
        previous = {
            stage: {
                "model": "" if state["model"] == "codex-default" else state["model"],
                "reasoning": state.get("reasoning", "default"),
            }
            for stage in choices
        }
    if previous is not None and previous != choices:
        raise ReviewPending("Model or reasoning changed; run prepare --refresh to avoid mixing reviews")
    state["stage_models"] = choices
    state["model_config"] = model_settings(config)
    return choices


def model_gate(index, config, state, reviewer, choices, parallel):
    """Wrap `reviewer.ask` with the checks and conversions every workflow call needs.

    The returned `ask(prompt, schema, images=(), stage=..., verify=None)` rechecks
    settings before each call, selects the stage's model, converts between the lean
    model schemas and stored legacy records, and invalidates cached answers that
    fail `verify`.
    """

    def ask(prompt, schema, images=(), stage="comparison", verify=None):
        """Make one model call for a stage, re-reading settings first so switching Codex off stops the next call."""
        current = active_config(index)
        if current["pdf_mode"] in pdf_routing.MODES and not development_cache.mode()["enabled"]:
            raise ReviewPending("Development mode was switched off; stopped before the next call")
        if not current["codex_enabled"]:
            raise ReviewPending("Codex was switched off; completed work is saved")
        if current["pdf_whole_document_max_pages"] != config["pdf_whole_document_max_pages"]:
            raise ReviewPending("PDF page limit changed; run again to continue")
        if model_settings(current) != state["model_config"]:
            raise ReviewPending("Model settings changed during the run; stopped before the next call")
        # Worker copies isolate stage selection and share one atomic request budget.
        worker = worker_for(reviewer, parallel)
        choice = choices["pdf" if stage.startswith("pdf_") else stage]
        worker.model = choice["model"] or None
        worker.reasoning = choice["reasoning"]
        worker.stage = stage
        model_schema = (
            pieces.model_schema("extraction")
            if schema is EXTRACTION
            else pieces.model_schema("receipt_assembly")
            if schema is ASSEMBLY
            else schema
        )
        result = normalize_currencies(worker.ask(prompt, model_schema, images))
        if schema is EXTRACTION:
            result = pieces.legacy_result(pieces.clean_result(result))
        elif schema is ASSEMBLY and "pieces" in result:
            result = pieces.clean_result(result)
            result = {k: v for k, v in result.items() if k != "pieces"} | {
                "receipts": [pieces.legacy_piece(p) for p in result["pieces"]],
                "limitations": result.get("limitations", []),
            }
        if verify is not None:
            try:
                verify(result)
            except Exception:
                invalidate(worker)
                raise
        return result

    return ask


def run(work, index: Index, state: State, reviewer, *, regeneration=None, progress=None, queued_regenerations=None):
    """Extract every document unit, then assemble multi-unit documents into receipts.

    Args:
        work: Review folder holding `index.json`, `state.json` and model caches.
        index: Prepared documents from `prepare`.
        state: Checkpoint updated in place and saved after every result.
        reviewer: Any `reconciliation.model.client.ModelClient`, for example `CodexReviewer`.
        regeneration: `{document hash: request}` to re-extract despite saved results.
        progress: Optional `progress(document_hash, "running" | "completed")` callback.
        queued_regenerations: Optional callable returning regenerations queued mid-run.

    Raises:
        ReviewPending: Settings, sources or earlier steps block model work.
        BudgetReached: The shared call limit stopped the run; finished work is saved.
    """
    config = active_config(index)
    check_run_allowed(config)
    current_inventory(index, state)
    if exact_check(Path(index["root"]), read(Path(index["manifest"])), Path(index["manifest"])):
        raise ReviewPending("Pass-one cleanup is pending; run `python -m reconciliation.intake.duplicates check` first")
    choices = lock_stage_models(state, reviewer, config)
    regeneration = regeneration or {}
    documents = index["documents"]
    workers = config["max_parallel"] if supports_parallel(reviewer) else 1
    ctx = RunContext(
        work=work,
        config=config,
        state=state,
        documents=documents,
        regeneration=regeneration,
        selected={key: value for key, value in documents.items() if not regeneration or key in regeneration},
        ask=model_gate(index, config, state, reviewer, choices, parallel=workers > 1),
        checkpoint=lambda: save(work / "state.json", state),
        progress=progress,
    )
    stages = [UnitExtraction(ctx, queued_regenerations), ReceiptAssembly(ctx)]
    try:
        for stage in stages:
            run_jobs(stage.jobs(), stage.apply, workers, stage.refill, acceptance=acceptance(reviewer))
    finally:
        # Partial work always gets a report and remains visibly incomplete.
        ctx.checkpoint()
        report(work, index, state)


def active_config(index):
    """Load the review's current settings, resolving moved or legacy config paths.

    Raises:
        ReviewPending: The config is missing, or extraction settings changed since preparation.
    """
    path = index.get("config_path", str(CONFIG_PATH))
    if path and Path(path) == CONFIG_PATH.parent.parent / "review_config.json" and not Path(path).exists():
        path = CONFIG_PATH
    if path and not Path(path).is_file() and index.get("manifest"):
        legacy = Path(index["manifest"]).resolve().parent / "review_config.json"
        if Path(path).resolve() == legacy:
            path = config_for_manifest(index["manifest"])
    if path and not Path(path).is_file():
        raise ReviewPending("The review configuration is missing; restore it before proceeding")
    config = load_config(path)
    previous = index.get("config", {"pdf_mode": "vision", "pictures_enabled": True})
    if content_settings(config) != content_settings(previous):
        raise ReviewPending(
            "Extraction settings changed; run `python -m reconciliation.extraction.workflow prepare --refresh`"
        )
    return config


def gate(index, state):
    """Return every outstanding check blocking completion; an empty list means complete.

    Covers settings drift, exact-duplicate cleanup, unread units, pending assemblies
    and admin-approved duplicate removals that are not yet carried out.
    """
    problems = []
    try:
        current_config = active_config(index)
        if state.get("model_config") and model_settings(current_config) != model_settings(state["model_config"]):
            problems.append("Model settings changed; refresh the review before proceeding")
    except ReviewPending as error:
        problems.append(str(error))
    current, removed = current_inventory(index, state)
    problems += exact_problems(index, removed)
    for digest, document in index["documents"].items():
        if document.get("accepted", True):
            problems += document_problems(digest, document, state)
    for loser, keeper in removed.items():
        if loser in current:
            problems.append(f"{loser[:10]}: admin duplicate cleanup pending; retain {keeper[:10]}")
        if keeper not in current:
            problems.append(f"{keeper[:10]}: selected survivor is missing")
    return problems


def exact_problems(index, removed):
    """Run the exact-duplicate check, ignoring groups emptied by approved removals."""
    original = read(Path(index["manifest"]))
    manifest = {**original, "Files": [r for r in original["Files"] if r["SHA256"] not in removed]}
    emptied = {r["Group"] for r in original["Files"]} - {r["Group"] for r in manifest["Files"]}
    approved_empty = {f"Unexpected group: {name}" for name in emptied}
    return [p for p in exact_check(Path(index["root"]), manifest, Path(index["manifest"])) if p not in approved_empty]


def document_problems(digest, document, state):
    """List why one accepted document is not fully extracted and assembled."""
    problems = [f"{digest[:10]}: extraction failed: {document['error']}"] if document["error"] else []
    for n, unit in enumerate(document["units"]):
        if unit.get("blocked"):
            problems.append(f"{digest[:10]} unit {n + 1}: {unit['blocked']}")
        if not state["units"].get(f"{digest}:{n}", {}).get("readable"):
            problems.append(f"{digest[:10]} unit {n + 1}: unread or unreadable")
    if len(document["units"]) > 1 and not current_assembly(document, state):
        problems.append(f"{digest[:10]}: receipt assembly pending")
    return problems


def report(work, index, state):
    """Write report.md, report.json and the supporting inventory; return outstanding checks."""
    try:
        problems = gate(index, state)
    except ValueError as error:
        problems = [str(error)]
    usage = token_summary(work / "token-usage.jsonl")
    (work / "report.md").write_text(render_report(index, state, problems, usage), encoding="utf-8")
    save(
        work / "report.json",
        {"documents": index["documents"], "state": state, "problems": problems, "token_usage": usage},
    )
    try:
        removed = removal_plan(state)
    except ValueError:
        removed = {}  # Conflicting decisions are already listed in `problems`.
    export_inventory(work / "supporting-inventory.csv", index, state, removed)
    return problems


def main(argv=None):
    """Run the prepare / run / check command line; return the process exit code."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "check"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--codex")
    parser.add_argument("--model")
    parser.add_argument("--reasoning")
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument(
        "--refresh", action="store_true", help="Archive existing review metadata and re-extract using saved settings"
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_CALL_TIMEOUT)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            prepare(args.manifest, args.work.resolve(), args.config, args.refresh)
            return 0
        index, state = load(args.work)
        if args.action == "run":
            config = active_config(index)
            max_calls = args.max_calls if args.max_calls is not None else config["max_calls"]
            choices = stage_settings(config)
            if args.model is not None or args.reasoning is not None:
                choices = {
                    stage: {
                        "model": args.model if args.model is not None else choice["model"],
                        "reasoning": args.reasoning if args.reasoning is not None else choice["reasoning"],
                    }
                    for stage, choice in choices.items()
                }
                validate_config({**config, "stages": choices})
            if max_calls < 1 or args.timeout < 1:
                raise ValueError("Call limit and timeout must be positive")
            engine = CodexReviewer(
                args.work.resolve(), args.codex, config["model"] or None, max_calls, args.timeout, config["reasoning"]
            )
            engine.stage_choices = choices
            try:
                run(args.work, index, state, engine)
            except BudgetReached as error:
                print(error)
        problems = report(args.work, index, state)
        print(
            f"{'PENDING' if problems else 'COMPLETE'}: {len(problems)} outstanding checks. See {args.work / 'report.md'}"
        )
        return 2 if problems else 0
    except ReviewPending as error:
        print(f"PENDING: {error}")
        return 2
    except (OSError, ValueError, KeyError, TypeError, ValidationError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}. Review remains incomplete.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
