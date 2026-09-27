"""Run document extraction in a background thread for the dashboard: prepare, start, stop, status."""

import threading
from pathlib import Path
from time import monotonic

from reconciliation.core.settings import load_config, stage_settings
from reconciliation.extraction.workflow import active_config, load, load_index, prepare as prepare_review, run
from reconciliation.intake.duplicates import check, fingerprint
from reconciliation.model.codex import BudgetReached, CodexReviewer, ReviewCancelled


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
    started = getattr(review, "content_started", None)
    return {
        "running": running,
        "active_processes": active,
        "stop_requested": requested,
        "phase": getattr(review, "content_phase", ""),
        "elapsed_seconds": int(monotonic() - started) if running and started is not None else 0,
        "execution_status": status,
        "run_error": error,
    }


def prepare(review):
    """Prepare local evidence only after exact-copy cleanup is complete."""
    if exact_problems(review):
        raise ValueError("Finish exact duplicate review first")
    work = work_path(review)
    if (work / "index.json").exists():
        raise ValueError("Content review is already prepared")
    prepare_review(review.manifest_path, work, review.config_path)
    return {"prepared": True, **execution_status(review)}


def start(review, *, regeneration_only=False):
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
    review.content_accepting = True
    review.content_started = monotonic()
    review.content_phase = "Checking prepared documents"

    def worker():
        """Resume extraction and receipt assembly without vision duplicate passes."""
        try:
            index, state = load(work)
            config = load_config(review.config_path)
            engine = CodexReviewer(
                work,
                model=config["model"] or None,
                max_calls=config["max_calls"],
                reasoning=config["reasoning"],
                cancel_event=review.content_cancel,
            )
            review.content_engine = engine
            engine.stage_choices = stage_settings(config)
            review.content_phase = "Extracting supporting documents"
            if not regeneration_only:
                run(work, index, state, engine)
            from dashboard.services.extraction import regeneration

            regeneration.drain(review, work, engine)
        except BudgetReached as error:
            review.content_error = str(error)
        except ReviewCancelled:
            pass
        except Exception as error:
            review.content_error = str(error)
        finally:
            from dashboard.services.extraction import regeneration

            regeneration.finish(review, review.content_error)

    review.content_thread = threading.Thread(target=worker, daemon=True)
    review.content_thread.start()
    return execution_status(review)


def stop(review):
    """Cancel active model calls and keep all completed review checkpoints."""
    if not execution_status(review)["running"]:
        raise ValueError("No content review is running")
    review.content_cancel.set()
    engine = getattr(review, "content_engine", None)
    if engine is not None:
        engine.cancel()
    return execution_status(review)


def source(review, digest):
    """Verify the original and its index without scanning unrelated derived previews."""
    index, _ = load_index(work_path(review))
    path = Path(index["documents"][digest]["paths"][0])
    if fingerprint(path) != digest:
        raise ValueError("Source changed; refresh the review")
    return path
