"""Persist document regeneration requests for the shared extraction worker."""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dashboard.review import write_json


def queue_path(review):
    """Keep requests beside the project's extraction checkpoints."""
    return review.manifest_path.parent / "review" / "regeneration.json"


def read_queue(review):
    """Read queue data while the caller holds the review lock."""
    path = queue_path(review)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"jobs": {}, "history": []}


def snapshot(review):
    """Expose interrupted requests as unresolved after a server restart."""
    if not queue_path(review).exists():
        return {}
    with review.lock:
        data = read_queue(review)
        worker = getattr(review, "content_thread", None)
        if not worker or not worker.is_alive():
            changed = False
            for job in data["jobs"].values():
                if job["status"] in {"queued", "running"}:
                    job.update(status="failed", error="Regeneration interrupted; retry to finish.")
                    changed = True
            if changed:
                write_json(queue_path(review), data)
        return data["jobs"]


def update(review, digest, status, error=""):
    """Checkpoint progress without overwriting other queued requests."""
    with review.lock:
        data = read_queue(review)
        job = data["jobs"][digest]
        if job["status"] == "completed" or job["status"] == status:
            return
        job.update(status=status, error=error)
        write_json(queue_path(review), data)


def enqueue(review, digest):
    """Validate and enqueue a fresh whole-document extraction without blocking HTTP."""
    from dashboard import content_review
    from reconciliation.vision_workflow import active_config, current_inventory, load, removal_plan

    with review.lock:
        if content_review.exact_problems(review):
            raise ValueError("Finish exact duplicate review first")
        index, state = load(content_review.work_path(review))
        if Path(index["manifest"]).resolve() != review.manifest_path.resolve():
            raise ValueError("Prepared review belongs to another manifest")
        config = active_config(index)
        if not config["codex_enabled"]:
            raise ValueError("Enable Codex in Settings before regenerating")
        current_inventory(index, state)
        document = index["documents"][digest]
        if (digest in removal_plan(state) or document["error"] or not document.get("accepted", True)
                or not document["units"] or any(unit.get("blocked") for unit in document["units"])):
            raise ValueError("Resolve document preparation problems before regenerating")
        running = content_review.execution_status(review)
        if running["running"] and (running["stop_requested"] or not getattr(review, "content_accepting", False)):
            raise ValueError("Wait for the current worker to stop before regenerating")
        jobs = snapshot(review)
        if jobs.get(digest, {}).get("status") in {"queued", "running"}:
            return jobs
        data = read_queue(review)
        previous = data["jobs"].get(digest)
        if previous:
            data["history"].append(previous)
        data["jobs"][digest] = {"id": uuid4().hex, "document_id": digest, "status": "queued",
                                "requested_at": datetime.now(timezone.utc).isoformat(), "error": ""}
        write_json(queue_path(review), data)
        if not running["running"]:
            try:
                content_review.start(review, regeneration_only=True)
            except Exception as error:
                update(review, digest, "failed", str(error))
                raise
        return read_queue(review)["jobs"]


def drain(review, work, engine):
    """Drain requested documents through the same bounded parallel extraction runner."""
    from reconciliation.vision_workflow import load, run

    def queued():
        """Offer new requests whenever the shared pool has spare capacity."""
        with review.lock:
            if review.content_cancel.is_set():
                return {}
            return {digest: job["id"] for digest, job in read_queue(review)["jobs"].items()
                    if job["status"] == "queued"}

    while True:
        with review.lock:
            batch = {digest: job["id"] for digest, job in read_queue(review)["jobs"].items()
                     if job["status"] == "queued"}
            if not batch or review.content_cancel.is_set():
                review.content_accepting = False
                return
        index, state = load(work)
        run(work, index, state, engine, extraction_only=True, regeneration=batch,
            progress=lambda digest, status: update(review, digest, status), queued_regenerations=queued)
        for digest in batch:
            with review.lock:
                job = read_queue(review)["jobs"][digest]
                if job["id"] == batch[digest] and job["status"] != "completed":
                    update(review, digest, "failed", "Extraction is incomplete; retry to finish.")


def finish(review, error):
    """Leave cancelled, failed, or unstarted requests visibly unresolved."""
    with review.lock:
        review.content_accepting = False
        data = read_queue(review)
        for digest, job in data["jobs"].items():
            if job["status"] in {"queued", "running"}:
                update(review, digest, "failed", error or "Regeneration stopped; retry to finish.")
