"""Expose pass-two evidence and admin decisions to the local dashboard."""

import threading
from pathlib import Path

from reconciliation.codex_reviewer import BudgetReached, CodexReviewer, ReviewCancelled
from reconciliation.duplicate_workflow import check, fingerprint
from reconciliation.review_settings import load_config, stage_settings
from reconciliation.vision_workflow import active_config, current_inventory, decide as save_decision, load, prepare as prepare_review, run, undo_decision


def work_path(review):
    """Keep each project's content review beside its manifest."""
    return review.manifest_path.parent / "review"


def exact_problems(review):
    """Return pass-one blockers before any content-review action."""
    return check(review.root, review.manifest, review.manifest_path)


def execution_status(review):
    """Report stopped only after process verification and worker finalization."""
    worker = getattr(review, "content_thread", None)
    worker_running = bool(worker and worker.is_alive())
    active = getattr(getattr(review, "content_engine", None), "active_count", 0)
    cancelled = getattr(review, "content_cancel", None)
    requested = bool(cancelled and cancelled.is_set())
    error = getattr(review, "content_error", "")
    running = worker_running or bool(active)
    status = "running" if running else "idle"
    if requested:
        status = "stopping" if worker_running else "stop_failed" if active or error else "stopped"
    if active and not worker_running:
        status = "stop_failed"
        error = error or "Process shutdown could not be verified. Another review cannot start."
    if status == "stopped":
        error = "Review stopped. Completed results are saved; run again to resume."
    return {"running": running, "active_processes": active, "stop_requested": requested,
            "execution_status": status, "run_error": error}


def snapshot(review):
    """Read current pass-two candidates without accepting model output as approval."""
    problems = exact_problems(review)
    work = work_path(review)
    result = {"exact_ready": not problems, "exact_problems": problems[:30],
              "prepared": (work / "index.json").is_file(),
              **execution_status(review), "pairs": []}
    if problems or not result["prepared"]:
        return result
    index, state = load(work)
    if Path(index["manifest"]).resolve() != review.manifest_path.resolve():
        raise ValueError("Prepared review belongs to a different manifest")
    documents = index["documents"]
    for pair, screen in sorted(state["screens"].items()):
        if not screen["candidate"]:
            continue
        left, right = pair.split(":")
        comparison = state["pairs"].get(pair)
        result["pairs"].append({"pair": pair, "left": document_summary(documents[left]),
                                "right": document_summary(documents[right]),
                                "reason": screen["reason"], "comparison": comparison,
                                "decision": state["decisions"].get(pair)})
    result["documents"] = len(documents)
    result["documents_read"] = sum(bool(doc["units"]) and not doc["error"] and
                                   all(f"{digest}:{n}" in state["units"] for n in range(len(doc["units"])))
                                   for digest, doc in documents.items() if doc.get("accepted", True))
    result["units_read"] = len(state["units"])
    result["units_total"] = sum(len(doc["units"]) for doc in documents.values() if doc.get("accepted", True))
    result["pairs_screened"] = len(state["screens"])
    result["comparisons_done"] = len(state["pairs"])
    result["comparisons_total"] = sum(bool(screen["candidate"]) for screen in state["screens"].values())
    eligible = sum(doc.get("accepted", True) for doc in documents.values())
    result["pairs_total"] = eligible * (eligible - 1) // 2
    return result


def document_summary(document):
    """Provide a source link and page labels for one reviewed document."""
    return {"id": document["id"], "name": Path(document["paths"][0]).name,
            "path": document["paths"][0],
            "units": [{"label": unit["label"], "text": unit["text"], "image": bool(unit["image"])}
                      for unit in document["units"]]}


def prepare(review):
    """Prepare local evidence only after exact-copy cleanup is complete."""
    if exact_problems(review):
        raise ValueError("Finish exact duplicate review first")
    work = work_path(review)
    if (work / "index.json").exists():
        raise ValueError("Content review is already prepared")
    prepare_review(review.manifest_path, work, review.config_path)
    return snapshot(review)


def start(review):
    """Run a bounded model batch in the background so the page stays responsive."""
    if exact_problems(review):
        raise ValueError("Finish exact duplicate review first")
    if execution_status(review)["running"]:
        raise ValueError("Content review is already running")
    work = work_path(review)
    if not (work / "index.json").is_file():
        raise ValueError("Prepare content review first")
    index, _ = load(work)
    active_config(index)
    review.content_error = ""
    review.content_cancel = threading.Event()
    review.content_engine = None

    def worker():
        """Resume saved extraction, screening, and comparison work."""
        try:
            index, state = load(work)
            config = load_config(review.config_path)
            engine = CodexReviewer(work, model=config["model"] or None,
                                   max_calls=config["max_calls"], reasoning=config["reasoning"],
                                   cancel_event=review.content_cancel)
            review.content_engine = engine
            engine.stage_choices = stage_settings(config)
            run(work, index, state, engine)
        except BudgetReached:
            pass
        except ReviewCancelled:
            pass
        except Exception as error:
            review.content_error = str(error)

    review.content_thread = threading.Thread(target=worker, daemon=True)
    review.content_thread.start()
    return snapshot(review)


def stop(review):
    """Cancel active model calls and keep all completed review checkpoints."""
    if not execution_status(review)["running"]:
        raise ValueError("No content review is running")
    review.content_cancel.set()
    engine = getattr(review, "content_engine", None)
    if engine is not None:
        engine.cancel()
    return snapshot(review)


def decide(review, pair, verdict, reviewer, reason):
    """Record an explicit admin verdict for one completed candidate comparison."""
    if exact_problems(review):
        raise ValueError("Finish exact duplicate review first")
    if execution_status(review)["running"]:
        raise ValueError("Wait for the current content-review batch to finish")
    work = work_path(review)
    index, state = load(work)
    if Path(index["manifest"]).resolve() != review.manifest_path.resolve():
        raise ValueError("Prepared review belongs to a different manifest")
    current_inventory(index, state)
    save_decision(work, index, state, pair, verdict, reviewer, reason)
    from dashboard import development
    development.capture(review)
    return snapshot(review)


def undo(review, pair, reviewer, reason):
    """Clear one admin verdict and retain an audit entry for the reversal."""
    if exact_problems(review):
        raise ValueError("Finish exact duplicate review first")
    if execution_status(review)["running"]:
        raise ValueError("Wait for the current content-review batch to finish")
    work = work_path(review)
    index, state = load(work)
    if Path(index["manifest"]).resolve() != review.manifest_path.resolve():
        raise ValueError("Prepared review belongs to a different manifest")
    current_inventory(index, state)
    undo_decision(work, index, state, pair, reviewer, reason)
    from dashboard import development
    development.capture(review)
    return snapshot(review)


def source(review, digest):
    """Serve only unchanged documents named in the prepared review."""
    index, _ = load(work_path(review))
    path = Path(index["documents"][digest]["paths"][0])
    if fingerprint(path) != digest:
        raise ValueError("Source changed; refresh the review")
    return path


def image(review, digest, number):
    """Serve only a verified prepared page image."""
    index, _ = load(work_path(review))
    if number < 0:
        raise IndexError("Invalid unit number")
    unit = index["documents"][digest]["units"][number]
    if not unit["image"]:
        raise FileNotFoundError("No image for this unit")
    path = Path(unit["image"])
    if not path.resolve().is_relative_to((work_path(review) / "assets").resolve()):
        raise ValueError("Prepared image escaped review storage")
    return path
