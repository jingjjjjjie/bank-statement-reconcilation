"""Pass two: prepare, run Codex review, record admin decisions, and check completion."""
import argparse
import itertools
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema.exceptions import ValidationError

from codex_reviewer import CodexReviewer, BudgetReached, EXTRACTION, SCREEN, COMPARISON
from document_reader import extract
from duplicate_workflow import DEFAULT_MANIFEST, fingerprint, review_files, check as exact_check
from review_settings import CONFIG_PATH, load_config, content_settings, model_settings, stage_settings, document_stage, revision, validate as validate_config
from supporting_inventory import export as export_inventory
from token_usage import summary as token_summary

DEFAULT_WORK = Path(__file__).with_name("review")


class ReviewPending(ValueError):
    """A required earlier workflow step is not complete."""


def read(path):
    # Read existing Windows manifests and regular UTF-8 JSON alike.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    # Atomic replacement keeps interrupted runs resumable.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def inventory(root, manifest_path):
    # Keep one model input per exact hash, but retain all source locations.
    result = {}
    for path in review_files(root, read(manifest_path), manifest_path):
        result.setdefault(fingerprint(path), []).append(str(path))
    return result


def prepare(manifest_path, work, config_path=None, refresh=False):
    # Preparation is local and can run while pass-one admin cleanup is pending.
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
                "units": [], "error": None}
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


def load(work):
    # Refuse edited input metadata or tampered previews instead of trusting stale approvals.
    index, state = read(work / "index.json"), read(work / "state.json")
    if fingerprint(work / "index.json") != state["index_sha256"]:
        raise ValueError("Prepared index changed; create a new review")
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


def run(work, index, state, reviewer):
    # Pass-one cleanup must finish before spending subscription usage on pass two.
    config = active_config(index)
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
    documents = index["documents"]

    def checkpoint():
        save(work / "state.json", state)

    def ask(prompt, schema, images=(), stage="comparison"):
        # Re-read the switch before each call so disabling Codex stops subsequent calls.
        current = active_config(index)
        if not current["codex_enabled"]:
            raise ReviewPending("Codex was switched off; completed work is saved")
        if model_settings(current) != state["model_config"]:
            raise ReviewPending("Model settings changed during the run; stopped before the next call")
        # One engine keeps a shared request budget across all stage/model changes.
        reviewer.model = choices[stage]["model"] or None
        reviewer.reasoning = choices[stage]["reasoning"]
        reviewer.stage = stage
        return reviewer.ask(prompt, schema, images)

    try:
        # Vision reads each page/image; structured text supplies cells and paragraphs.
        for digest, document in documents.items():
            if document["error"]:
                continue
            for number, unit in enumerate(document["units"]):
                if unit.get("blocked"):
                    continue
                key = f"{digest}:{number}"
                if key not in state["units"]:
                    prompt = ("Extract this entire review unit for later duplicate comparison. "
                              "Record all references, dates, currencies, totals and line-item detail; "
                              "note unclear text, missing context and signatures.\n" +
                              json.dumps({"location": unit["label"], "text": unit["text"],
                                          "limitation": unit.get("limitation", "")}, ensure_ascii=False))
                    state["units"][key] = ask(prompt, EXTRACTION,
                                                      [unit["image"]] if unit["image"] else [],
                                                      stage=document_stage(document["paths"][0]))
                    checkpoint()
                    print(f"Read {digest[:10]} / {unit['label']}", flush=True)

        # Screen every document pair through summaries, in bounded batches.
        ready = [d for d in documents if not documents[d]["error"] and all(
            state["units"].get(f"{d}:{n}", {}).get("readable")
            for n in range(len(documents[d]["units"]))) ]
        summaries = {d: [{"location": unit["label"], **state["units"][f"{d}:{n}"]}
                        for n, unit in enumerate(documents[d]["units"])] for d in ready}
        for position, left in enumerate(ready):
            rights = [r for r in ready[position + 1:] if pair_key(left, r) not in state["screens"]]
            for start in range(0, len(rights), 12):
                batch = rights[start:start + 12]
                prompt = ("Screen LEFT against EACH right document. Candidate=true for any possible "
                          "same document, revised version, overlap, complementary evidence or uncertainty. "
                          "False only for clearly distinct documents. Return exactly one comparison per right_id.\n" +
                          json.dumps({"left": summaries[left], "right": {r: summaries[r] for r in batch}}, ensure_ascii=False))
                if len(prompt) > 100000:
                    # Large summaries remain candidates rather than being omitted.
                    rows = [{"right_id": r, "candidate": True, "reason": "Summary too large; direct review required"} for r in batch]
                else:
                    rows = ask(prompt, SCREEN)["comparisons"]
                if len(rows) != len(batch) or {r["right_id"] for r in rows} != set(batch):
                    if hasattr(reviewer, "invalidate"):
                        reviewer.invalidate()
                    raise ValueError("Model omitted or repeated a comparison; coverage remains incomplete")
                for row in rows:
                    state["screens"][pair_key(left, row["right_id"])] = row
                checkpoint()

        # Candidate verdicts inspect original text and visuals, not summaries alone.
        for pair, screen in state["screens"].items():
            if not screen["candidate"] or pair in state["pairs"]:
                continue
            left, right = pair.split(":")
            left_text, left_images = pack(documents[left])
            right_text, right_images = pack(documents[right])
            for item in right_text:
                if "image_number" in item:
                    item["image_number"] += len(left_images)
            prompt = ("Compare these whole documents. Cite supplied document IDs and page/sheet/unit locations "
                      "in evidence and differences. same_document requires equivalent complete evidence; "
                      "different annotations, bank details, signatures or missing pages must be distinguished.\n" +
                      json.dumps({"left": left_text, "right": right_text}, ensure_ascii=False))
            images = left_images + right_images
            if len(images) > 40 or len(prompt) > 100000:
                state["pairs"][pair] = {"classification": "uncertain", "confidence": "low",
                    "evidence": [], "differences": [], "limitations": ["Too large for one comparison; admin must inspect both complete originals"]}
            else:
                state["pairs"][pair] = ask(prompt, COMPARISON, images)
            checkpoint()
            print(f"Compared {left[:10]} / {right[:10]}", flush=True)
    finally:
        # Partial work always gets a report and remains visibly incomplete.
        checkpoint()
        report(work, index, state)


def active_config(index):
    # Results from another extraction mode cannot silently satisfy the current review.
    path = index.get("config_path", str(CONFIG_PATH))
    if path and not Path(path).is_file():
        raise ReviewPending("The review configuration is missing; restore it before proceeding")
    config = load_config(path)
    previous = index.get("config", {"pdf_mode": "vision", "pictures_enabled": True})
    if content_settings(config) != content_settings(previous):
        raise ReviewPending("Extraction settings changed; run vision_workflow.py prepare --refresh")
    return config


def gate(index, state):
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
        if document["error"]:
            problems.append(f"{digest[:10]}: extraction failed: {document['error']}")
        for n in range(len(document["units"])):
            if document["units"][n].get("blocked"):
                problems.append(f"{digest[:10]} unit {n + 1}: {document['units'][n]['blocked']}")
            if not state["units"].get(f"{digest}:{n}", {}).get("readable"):
                problems.append(f"{digest[:10]} unit {n + 1}: unread or unreadable")
    for left, right in itertools.combinations(index["documents"], 2):
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
    try:
        problems = gate(index, state)
    except ValueError as error:
        problems = [str(error)]
    rows = ["# Pass-two duplicate review", "", f"Status: {'PENDING' if problems else 'COMPLETE'}",
            f"Documents: {len(documents)}; units read: {len(state['units'])}; "
            f"pairs screened: {len(state['screens'])}/{len(documents) * (len(documents) - 1) // 2}", "",
            "Model results are review evidence, not proof of duplicate payments. No source files are moved or deleted by pass two.", ""]
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
                run(args.work, index, state, engine)
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
