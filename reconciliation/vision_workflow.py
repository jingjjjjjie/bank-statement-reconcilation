"""Prepare and run extraction/receipt assembly; retain legacy comparison decisions."""
import argparse
import itertools
import json
import subprocess
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from reconciliation.paths import WORKSPACE
from reconciliation import development_cache
from reconciliation.prompts import load_prompt
from reconciliation import pdf_routing
from time import sleep

from jsonschema.exceptions import ValidationError

from reconciliation.codex_reviewer import CodexReviewer, BudgetReached, EXTRACTION, SCREEN, COMPARISON
from reconciliation.document_reader import extract
from reconciliation.duplicate_workflow import DEFAULT_MANIFEST, fingerprint, review_files, check as exact_check
from reconciliation.review_settings import CONFIG_PATH, config_for_manifest, load_config, content_settings, model_settings, stage_settings, document_stage, revision, validate as validate_config
from reconciliation.comparison_policy import route as comparison_route
from reconciliation.supporting_inventory import export as export_inventory
from reconciliation.token_usage import summary as token_summary
from reconciliation.receipt_assembly import ASSEMBLY, current_assembly, input_revision, validate_assembly

DEFAULT_WORK = WORKSPACE / "review"
ACCEPTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".xlsx", ".docx"}


class ReviewPending(ValueError):
    """A required earlier workflow step is not complete."""


def read(path):
    # Read existing Windows manifests and regular UTF-8 JSON alike.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    """Atomically save a checkpoint, retrying brief Windows file locks."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(15):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 14:
                raise
            sleep(0.02 * (attempt + 1))


def inventory(root, manifest_path):
    # Keep one model input per exact hash, but retain all source locations.
    result = {}
    for path in review_files(root, read(manifest_path), manifest_path):
        result.setdefault(fingerprint(path), []).append(str(path))
    return result


def prepare(manifest_path, work, config_path=None, refresh=False):
    # Preparation is local and can run while pass-one admin cleanup is pending.
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
    documents = {}
    for number, (digest, paths) in enumerate(sorted(inventory(root, manifest_path).items()), 1):
        # Preserve original claim associations even after copies have been moved.
        originals = [r["OriginalPath"] for r in manifest["Files"] if r["SHA256"] == digest]
        item = {"id": digest, "paths": paths, "original_paths": originals,
                "units": [], "error": None, "accepted": Path(paths[0]).suffix.lower() in ACCEPTED_SUFFIXES}
        if item["accepted"]:
            try:
                item["units"] = extract(Path(paths[0]), work / "assets" / revision(content_settings(config))[:12] / digest, config)
                for unit in item["units"]:
                    if unit["image"]:
                        unit["image_sha256"] = fingerprint(Path(unit["image"]))
                if fingerprint(Path(paths[0])) != digest:
                    raise ValueError("Source changed during extraction")
            except Exception as error:
                item["error"] = f"{type(error).__name__}: {error}"
        documents[digest] = item
        print(f"Prepared {number}: {Path(paths[0]).name}", flush=True)
    index = {"root": str(root), "manifest": str(manifest_path.resolve()), "documents": documents,
             "config": config, "config_path": str(config_path.resolve()) if config_path else None}
    save(index_path, index)
    save(work / "state.json", {"index_sha256": fingerprint(index_path), "units": {},
                              "screens": {}, "pairs": {}, "decisions": {}, "model": None})
    report(work, index, read(work / "state.json"))
    print(f"Prepared {len(documents)} unique documents locally; no model calls made.")


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
    # A decision names an unchanged survivor; chains and contradictory choices block cleanup.
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
    # Only explicitly approved duplicate removals may change the document set.
    current = inventory(Path(index["root"]), Path(index["manifest"]))
    removed = removal_plan(state)
    unknown = set(current) - set(index["documents"])
    missing = set(index["documents"]) - set(current) - set(removed)
    if unknown or missing:
        raise ValueError(f"Sources changed: {len(unknown)} new/modified, {len(missing)} unapproved missing; prepare a new review")
    return current, removed


def pair_key(left, right):
    return ":".join(sorted((left, right)))


def pack(document):
    # Include every extracted unit; never silently truncate an original comparison.
    text, images = [], []
    for unit in document["units"]:
        text.append({"document_id": document["id"], "location": unit["label"], "text": unit["text"],
                     "limitation": unit.get("limitation", "")})
        if unit["image"]:
            images.append(unit["image"])
            text[-1]["image_number"] = len(images)
    return text, images


def run_jobs(jobs, apply, workers, refill=None):
    """Run a bounded number of model jobs and checkpoint every finished result."""
    if workers == 1 and refill is None:
        for job in jobs:
            apply(job())
        return
    pending, remaining, error = {}, iter(jobs), None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        def submit_one():
            """Keep only one queued job per available worker."""
            nonlocal remaining
            try:
                job = next(remaining)
            except StopIteration:
                if refill is None:
                    return False
                remaining = iter(refill())
                job = next(remaining, None)
                if job is None:
                    return False
            pending[pool.submit(job)] = None
            return True

        for _ in range(workers):
            if not submit_one():
                break
        while pending:
            if error is None:
                while len(pending) < workers and submit_one():
                    pass
            completed, _ = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            if not completed:
                continue
            future = next(iter(completed))
            del pending[future]
            try:
                result = future.result()
                apply(result)
            except Exception as failure:
                if error is None:
                    error = failure
            if error is None:
                submit_one()
    if error is not None:
        raise error


def run(work, index, state, reviewer, *, extraction_only=False, regeneration=None, progress=None,
        queued_regenerations=None):
    """Extract and assemble receipts; retain explicit legacy comparison support for old tools."""
    config = active_config(index)
    if config["pdf_mode"] in pdf_routing.MODES and not development_cache.mode()["enabled"]:
        raise ReviewPending("Experimental PDF modes require development mode; choose Vision in Settings")
    if not config["codex_enabled"]:
        raise ReviewPending("Codex is off in review settings; no model calls were made")
    current_inventory(index, state)
    manifest = read(Path(index["manifest"]))
    problems = exact_check(Path(index["root"]), manifest, Path(index["manifest"]))
    if problems:
        raise ReviewPending("Pass-one cleanup is pending; run duplicate_workflow.py check first")
    choices = getattr(reviewer, "stage_choices", stage_settings(config))
    previous = state.get("stage_models")
    if previous is None and state.get("model"):
        previous = {stage: {"model": "" if state["model"] == "codex-default" else state["model"],
                            "reasoning": state.get("reasoning", "default")} for stage in choices}
    if previous is not None and previous != choices:
        raise ReviewPending("Model or reasoning changed; run prepare --refresh to avoid mixing reviews")
    state["stage_models"] = choices
    state["model_config"] = model_settings(config)
    state["extraction_only"] = extraction_only
    documents = index["documents"]
    regeneration = regeneration or {}
    selected = {key: value for key, value in documents.items() if not regeneration or key in regeneration}
    dispatched = set()
    workers = config["max_parallel"] if hasattr(reviewer, "fork") else 1

    def checkpoint():
        save(work / "state.json", state)

    def ask(prompt, schema, images=(), stage="comparison", verify=None):
        # Re-read the switch before each call so disabling Codex stops subsequent calls.
        current = active_config(index)
        if current["pdf_mode"] in pdf_routing.MODES and not development_cache.mode()["enabled"]:
            raise ReviewPending("Development mode was switched off; stopped before the next call")
        if not current["codex_enabled"]:
            raise ReviewPending("Codex was switched off; completed work is saved")
        if model_settings(current) != state["model_config"]:
            raise ReviewPending("Model settings changed during the run; stopped before the next call")
        # Worker copies isolate stage selection and share one atomic request budget.
        worker = reviewer.fork() if workers > 1 else reviewer
        choice = choices["pdf" if stage.startswith("pdf_") else stage]
        worker.model = choice["model"] or None
        worker.reasoning = choice["reasoning"]
        worker.stage = stage
        result = worker.ask(prompt, schema, images)
        if verify is not None:
            try:
                verify(result)
            except Exception:
                if hasattr(worker, "invalidate"):
                    worker.invalidate()
                raise
        return result

    try:
        # Vision reads each page/image; structured text supplies cells and paragraphs.
        def unit_jobs():
            """Yield unread document units without queuing the entire corpus."""
            for digest, document in selected.items():
                if document["error"] or not document.get("accepted", True):
                    continue
                for number, unit in enumerate(document["units"]):
                    if unit.get("blocked"):
                        continue
                    key = f"{digest}:{number}"
                    if key in dispatched:
                        continue
                    if key in state["units"] and digest not in regeneration:
                        continue

                    def job(digest=digest, document=document, unit=unit, key=key):
                        """Read one page, sheet, or image with its selected model."""
                        if progress:
                            progress(digest, "running")
                        def extract_ask(prompt, schema, images=(), **kwargs):
                            """Keep explicit regeneration requests outside previous response caches."""
                            if digest in regeneration:
                                prompt += "\nRegeneration request: " + regeneration[digest]
                            return ask(prompt, schema, images, **kwargs)
                        if document_stage(document["paths"][0]) == "pdf" and config["pdf_mode"] in pdf_routing.MODES:
                            value = pdf_routing.extract_unit(unit, extract_ask, config["pdf_mode"],
                                work / "pdf-routing" / (key.replace(":", "-") + ".json"))
                            return key, digest, unit["label"], value
                        prompt = load_prompt("extraction") + "\n" + json.dumps({
                            "location": unit["label"], "text": unit["text"],
                            "limitation": unit.get("limitation", "")}, ensure_ascii=False)
                        return key, digest, unit["label"], extract_ask(prompt, EXTRACTION,
                            [unit["image"]] if unit["image"] else [],
                            stage=document_stage(document["paths"][0]))

                    dispatched.add(key)
                    yield job

        def apply_unit(result):
            """Save a completed extraction before more work is launched."""
            key, digest, label, value = result
            state["units"][key] = value
            checkpoint()
            if progress and len(documents[digest]["units"]) == 1:
                progress(digest, "completed")
            print(f"Read {digest[:10]} / {label}", flush=True)

        def refill_units():
            """Pick up newly queued documents while extraction workers are occupied."""
            for digest, request_id in queued_regenerations().items():
                if digest not in regeneration:
                    regeneration[digest] = request_id
                    selected[digest] = documents[digest]
            return unit_jobs()

        run_jobs(unit_jobs(), apply_unit, workers, refill_units if queued_regenerations else None)

        def assembly_jobs():
            """Join complete multi-unit evidence without repeating page extraction."""
            for digest, document in selected.items():
                if (not document.get("accepted", True) or document["error"]
                        or len(document["units"]) < 2 or (digest not in regeneration and current_assembly(document, state))):
                    continue
                if any(unit.get("blocked") or f"{digest}:{n}" not in state["units"]
                       for n, unit in enumerate(document["units"])):
                    continue

                def job(digest=digest, document=document):
                    """Inspect all source units before proposing document receipt boundaries."""
                    evidence = document
                    if (Path(document["paths"][0]).suffix.lower() == ".pdf" and config["pictures_enabled"]
                            and config["pdf_mode"] not in pdf_routing.MODES):
                        units = extract(Path(document["paths"][0]), work / "assets" / "receipt-assembly" / digest,
                                        {**config, "pdf_mode": "vision"})
                        evidence = {**document, "units": units}
                    originals, images = pack(evidence)
                    payload = [{"source_unit": n + 1, "original": original,
                                "extraction": state["units"][f"{digest}:{n}"]}
                               for n, original in enumerate(originals)]
                    prompt = load_prompt("receipt_assembly") + "\n" + json.dumps(payload, ensure_ascii=False)
                    if digest in regeneration:
                        prompt += "\nRegeneration request: " + regeneration[digest]
                    if len(images) > 40 or len(prompt) > 100000:
                        raise ReviewPending("Document too large for receipt assembly; boundaries remain unresolved")
                    value = ask(prompt, ASSEMBLY, images, stage=document_stage(document["paths"][0]),
                                verify=lambda result: validate_assembly(result, len(document["units"])))
                    return digest, {**value, "input_revision": input_revision(document, state)}

                yield job

        def apply_assembly(result):
            """Save each assembled document independently for safe resume."""
            digest, value = result
            state.setdefault("assemblies", {})[digest] = value
            checkpoint()
            if progress:
                progress(digest, "completed")
            print(f"Assembled receipts {digest[:10]}", flush=True)

        run_jobs(assembly_jobs(), apply_assembly, workers)

        if extraction_only:
            return

        # Strong local matches go straight to original comparison; screen all other pairs.
        ready = [d for d in documents if documents[d].get("accepted", True) and not documents[d]["error"] and all(
            state["units"].get(f"{d}:{n}", {}).get("readable")
            for n in range(len(documents[d]["units"]))) ]
        summaries = {d: [{"location": unit["label"], **state["units"][f"{d}:{n}"]}
                        for n, unit in enumerate(documents[d]["units"])] for d in ready}
        def screen_jobs():
            """Yield summary batches while preserving direct local candidates."""
            for position, left in enumerate(ready):
                rights = []
                for right in ready[position + 1:]:
                    pair = pair_key(left, right)
                    if pair in state["screens"]:
                        continue
                    route, reason = comparison_route(summaries[left], summaries[right])
                    if route == "direct_compare":
                        state["screens"][pair] = {"right_id": right, "candidate": True,
                            "reason": reason}
                    else:
                        rights.append(right)
                checkpoint()
                for start in range(0, len(rights), 12):
                    batch = rights[start:start + 12]

                    def job(left=left, batch=batch):
                        """Screen one batch and reject incomplete model coverage."""
                        prompt = load_prompt("screening") + "\n" + json.dumps({
                            "left": summaries[left], "right": {r: summaries[r] for r in batch}},
                            ensure_ascii=False)
                        if len(prompt) > 100000:
                            rows = [{"right_id": r, "candidate": True,
                                     "reason": "Summary too large; direct review required"} for r in batch]
                        else:
                            def verify(response):
                                """Require exactly one result for each requested document."""
                                rows = response["comparisons"]
                                if len(rows) != len(batch) or {r["right_id"] for r in rows} != set(batch):
                                    raise ValueError("Model omitted or repeated a comparison; coverage remains incomplete")

                            rows = ask(prompt, SCREEN, verify=verify)["comparisons"]
                        return left, rows

                    yield job

        def apply_screen(result):
            """Save a complete summary batch as its model call finishes."""
            left, rows = result
            for row in rows:
                state["screens"][pair_key(left, row["right_id"])] = row
            checkpoint()

        run_jobs(screen_jobs(), apply_screen, workers)

        # Candidate verdicts inspect original text and visuals, not summaries alone.
        def pair_jobs():
            """Yield candidate originals for complete comparison."""
            for pair, screen in state["screens"].items():
                if not screen["candidate"] or pair in state["pairs"]:
                    continue

                def job(pair=pair):
                    """Compare one pair's original text and images."""
                    left, right = pair.split(":")
                    left_text, left_images = pack(documents[left])
                    right_text, right_images = pack(documents[right])
                    for item in right_text:
                        if "image_number" in item:
                            item["image_number"] += len(left_images)
                    prompt = load_prompt("comparison") + "\n" + json.dumps(
                        {"left": left_text, "right": right_text}, ensure_ascii=False)
                    images = left_images + right_images
                    if len(images) > 40 or len(prompt) > 100000:
                        result = {"classification": "uncertain", "confidence": "low", "evidence": [],
                                  "differences": [], "limitations": ["Too large for one comparison; admin must inspect both complete originals"]}
                    else:
                        result = ask(prompt, COMPARISON, images)
                    return pair, result

                yield job

        def apply_pair(result):
            """Save one whole-document verdict for later admin review."""
            pair, value = result
            state["pairs"][pair] = value
            checkpoint()
            left, right = pair.split(":")
            print(f"Compared {left[:10]} / {right[:10]}", flush=True)

        run_jobs(pair_jobs(), apply_pair, workers)
    finally:
        # Partial work always gets a report and remains visibly incomplete.
        checkpoint()
        report(work, index, state)


def active_config(index):
    # Results from another extraction mode cannot silently satisfy the current review.
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
        raise ReviewPending("Extraction settings changed; run vision_workflow.py prepare --refresh")
    return config


def gate(index, state, *, extraction_only=None):
    # Check both coverage and admin dispositions, including approved manual deletions.
    problems = []
    try:
        current_config = active_config(index)
        if state.get("model_config") and model_settings(current_config) != model_settings(state["model_config"]):
            problems.append("Model settings changed; refresh the review before proceeding")
    except ReviewPending as error:
        problems.append(str(error))
    current, removed = current_inventory(index, state)
    manifest = read(Path(index["manifest"]))
    manifest["Files"] = [r for r in manifest["Files"] if r["SHA256"] not in removed]
    # Removed exact groups may remain as empty directories after admin cleanup.
    original_groups = {r["Group"] for r in read(Path(index["manifest"]))["Files"]}
    active_groups = {r["Group"] for r in manifest["Files"]}
    exact = exact_check(Path(index["root"]), manifest, Path(index["manifest"]))
    approved_empty = {f"Unexpected group: {name}" for name in original_groups - active_groups}
    problems.extend(p for p in exact if p not in approved_empty)
    for digest, document in index["documents"].items():
        if not document.get("accepted", True):
            continue
        if document["error"]:
            problems.append(f"{digest[:10]}: extraction failed: {document['error']}")
        for n in range(len(document["units"])):
            if document["units"][n].get("blocked"):
                problems.append(f"{digest[:10]} unit {n + 1}: {document['units'][n]['blocked']}")
            if not state["units"].get(f"{digest}:{n}", {}).get("readable"):
                problems.append(f"{digest[:10]} unit {n + 1}: unread or unreadable")
    if extraction_only is None:
        extraction_only = state.get("extraction_only", False)
    if extraction_only:
        for digest, document in index["documents"].items():
            if document.get("accepted", True) and len(document["units"]) > 1 and not current_assembly(document, state):
                problems.append(f"{digest[:10]}: receipt assembly pending")
        return problems
    eligible = [digest for digest, doc in index["documents"].items() if doc.get("accepted", True)]
    for left, right in itertools.combinations(eligible, 2):
        pair = pair_key(left, right)
        screen = state["screens"].get(pair)
        if screen is None:
            problems.append(f"{left[:8]} / {right[:8]}: not screened")
        elif screen["candidate"]:
            if pair not in state["pairs"]:
                problems.append(f"{left[:8]} / {right[:8]}: original comparison pending")
            elif pair not in state["decisions"]:
                problems.append(f"{left[:8]} / {right[:8]}: admin verdict pending")
    for loser, keeper in removed.items():
        if loser in current:
            problems.append(f"{loser[:10]}: admin duplicate cleanup pending; retain {keeper[:10]}")
        if keeper not in current:
            problems.append(f"{keeper[:10]}: selected survivor is missing")
    return problems


def report(work, index, state):
    # Markdown is for reading; JSON is the complete machine-readable audit trail.
    documents = index["documents"]
    eligible_count = sum(doc.get("accepted", True) for doc in documents.values())
    try:
        problems = gate(index, state)
    except ValueError as error:
        problems = [str(error)]
    rows = ["# Pass-two duplicate review", "", f"Status: {'PENDING' if problems else 'COMPLETE'}",
            f"Documents: {len(documents)}; units read: {len(state['units'])}; "
            f"pairs screened: {len(state['screens'])}/{eligible_count * (eligible_count - 1) // 2}", "",
            "Model results are review evidence, not proof of duplicate payments. No source files are moved or deleted by pass two.", ""]
    if state.get("extraction_only"):
        rows = ["# Document extraction", "", f"Status: {'PENDING' if problems else 'COMPLETE'}",
                f"Documents: {len(documents)}; units read: {len(state['units'])}", "",
                "Extraction and receipt assembly only. Vision duplicate screening and comparison are disabled.", ""]
    settings = index.get("config", {"pdf_mode": "vision", "pictures_enabled": True})
    rows += [f"Prepared PDF mode: {settings['pdf_mode']}; pictures: {settings['pictures_enabled']}.",
             f"Stage models used: {json.dumps(state.get('stage_models', {}))}.",
             "Text-only PDF units exclude signatures, handwriting and visual differences; blocked units remain unresolved.", ""]
    usage = token_summary(work / "token-usage.jsonl")
    rows += ["## Codex token usage", "",
             f"Recorded attempts: {usage['attempts']}; cache hits: {usage['cache_hits']}; "
             f"attempts with unknown usage: {usage['unknown_attempts']}.",
             f"Reported input: {usage['totals']['input_tokens']:,}; cached input: {usage['totals']['cached_input_tokens']:,}; "
             f"output: {usage['totals']['output_tokens']:,}; reasoning output: {usage['totals']['reasoning_output_tokens']:,}.",
             "Totals cover recorded Codex calls only; unknown attempts are excluded.", ""]
    for pair, result in state["pairs"].items():
        left, right = pair.split(":")
        rows += [f"## {pair}", "", f"Left: {documents[left]['paths'][0]}",
                 f"Right: {documents[right]['paths'][0]}",
                 f"Finding: {result['classification']} ({result['confidence']})", ""]
        for field in ("evidence", "differences", "limitations"):
            rows += [f"{field.title()}: " + "; ".join(result[field]), ""]
        rows += ["Admin: " + json.dumps(state["decisions"].get(pair, "PENDING"), ensure_ascii=False), ""]
    rows += ["## Outstanding checks", "", f"{len(problems)} unresolved checks.", ""]
    rows += [f"- {p}" for p in problems[:100]]
    if len(problems) > 100:
        rows.append("- Full outstanding list is in report.json.")
    (work / "report.md").write_text("\n".join(rows), encoding="utf-8")
    save(work / "report.json", {"documents": documents, "state": state, "problems": problems, "token_usage": usage})
    export_inventory(work / "supporting-inventory.csv", index, state)
    development_cache.capture(Path(index["manifest"]), "content-review")
    return problems


def decide(work, index, state, pair, verdict, reviewer, reason):
    # Admin choices are explicit; deletions are performed by the admin outside this tool.
    if pair not in state["pairs"]:
        raise ValueError("Pair has no completed original-document comparison")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Admin name and reason are required")
    result = state["pairs"][pair]
    if verdict != "keep_both" and result["classification"] != "same_document":
        raise ValueError("Only same_document candidates can be approved for duplicate cleanup")
    decision = {"verdict": verdict, "reviewer": reviewer, "reason": reason,
                "at": datetime.now(timezone.utc).isoformat()}
    previous = state["decisions"].get(pair)
    state["decisions"][pair] = decision
    removal_plan(state)
    state.setdefault("decision_history", []).append({"pair": pair, "previous": previous, **decision})
    save(work / "state.json", state)
    report(work, index, state)


def undo_decision(work, index, state, pair, reviewer, reason):
    """Return an admin decision to pending while preserving its audit history."""
    if pair not in state["decisions"]:
        raise ValueError("There is no decision to undo")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Admin name and reason are required")
    previous = state["decisions"].pop(pair)
    try:
        current_inventory(index, state)
    except ValueError:
        state["decisions"][pair] = previous
        raise
    state.setdefault("decision_history", []).append(
        {"pair": pair, "previous": previous, "verdict": None,
         "reviewer": reviewer.strip(), "reason": reason.strip(),
         "at": datetime.now(timezone.utc).isoformat()})
    save(work / "state.json", state)
    report(work, index, state)


def main(argv=None):
    # Keep each command small and explicit; model work is bounded and resumable.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "check", "decide"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--codex")
    parser.add_argument("--model")
    parser.add_argument("--reasoning")
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--refresh", action="store_true", help="Archive existing review metadata and re-extract using saved settings")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--pair")
    parser.add_argument("--verdict", choices=("keep_both", "keep_left", "keep_right"))
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--reason", default="")
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
                choices = {stage: {"model": args.model if args.model is not None else choice["model"],
                                   "reasoning": args.reasoning if args.reasoning is not None else choice["reasoning"]}
                           for stage, choice in choices.items()}
                validate_config({**config, "stages": choices})
            if max_calls < 1 or args.timeout < 1:
                raise ValueError("Call limit and timeout must be positive")
            engine = CodexReviewer(args.work.resolve(), args.codex, config["model"] or None,
                                   max_calls, args.timeout, config["reasoning"])
            engine.stage_choices = choices
            try:
                run(args.work, index, state, engine, extraction_only=True)
            except BudgetReached as error:
                print(error)
        elif args.action == "decide":
            if not args.pair or not args.verdict:
                raise ValueError("decide requires --pair and --verdict")
            decide(args.work, index, state, args.pair, args.verdict, args.reviewer, args.reason)
        problems = report(args.work, index, state)
        print(f"{'PENDING' if problems else 'COMPLETE'}: {len(problems)} outstanding checks. See {args.work / 'report.md'}")
        return 2 if problems else 0
    except ReviewPending as error:
        print(f"PENDING: {error}")
        return 2
    except (OSError, ValueError, KeyError, TypeError, ValidationError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}. Review remains incomplete.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
