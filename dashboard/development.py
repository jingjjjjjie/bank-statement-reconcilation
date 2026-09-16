"""Remember human duplicate decisions for repeat local test runs."""

import json
from datetime import datetime, timezone
from pathlib import Path

from dashboard import content_review
from vision_workflow import load


def path(review):
    """Keep the test preset beside the dashboard's recoverable decisions."""
    return review.data / "development-decisions.json"


def snapshot(review):
    """Report whether a saved preset exists without applying it."""
    target = path(review)
    if not target.is_file():
        return {"saved": False, "exact": 0, "content": 0}
    data = json.loads(target.read_text(encoding="utf-8"))
    return {"saved": True, "at": data["at"], "exact": len(data["exact"]),
            "content": len(data["content"])}


def remember(review):
    """Save completed human choices using original paths and content hashes."""
    exact = []
    for group in review.snapshot()["groups"]:
        if group["status"] == "reviewed" and group["kept"]:
            record = review.records[group["kept"]]
            exact.append({"hash": record["SHA256"], "original": record["OriginalPath"]})
    content = {}
    work = content_review.work_path(review)
    if (work / "index.json").is_file():
        index, state = load(work)
        if Path(index["manifest"]).resolve() != review.manifest_path:
            raise ValueError("Prepared content review belongs to another manifest")
        for pair, decision in state["decisions"].items():
            if pair in state["pairs"]:
                content[pair] = {"verdict": decision["verdict"], "reason": decision["reason"]}
    data = {"at": datetime.now(timezone.utc).isoformat(), "exact": exact, "content": content}
    target = path(review)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return snapshot(review)


def apply(review, reviewer):
    """Replay matching human choices only after an explicit named action."""
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("Enter your name before applying remembered decisions")
    if getattr(review, "content_thread", None) and review.content_thread.is_alive():
        raise ValueError("Wait for the current content-review batch to finish")
    target = path(review)
    if not target.is_file():
        raise ValueError("Remember decisions first")
    data = json.loads(target.read_text(encoding="utf-8"))
    exact_count = content_count = 0
    for saved in data["exact"]:
        matches = [(group, file_id) for group, ids in review.groups.items() for file_id in ids
                   if review.records[file_id]["SHA256"] == saved["hash"] and
                   review.records[file_id]["OriginalPath"] == saved["original"]]
        if len(matches) != 1:
            continue
        group, file_id = matches[0]
        current = next(item for item in review.snapshot()["groups"] if item["id"] == group)
        if current["status"] == "pending":
            review.keep(group, file_id)
            exact_count += 1
    work = content_review.work_path(review)
    if (work / "index.json").is_file() and not content_review.exact_problems(review):
        index, state = load(work)
        if Path(index["manifest"]).resolve() != review.manifest_path:
            raise ValueError("Prepared content review belongs to another manifest")
        for pair, saved in data["content"].items():
            result = state["pairs"].get(pair)
            if result and pair not in state["decisions"] and (saved["verdict"] == "keep_both" or
                    result["classification"] == "same_document"):
                content_review.decide(review, pair, saved["verdict"], reviewer.strip(),
                                      "Development replay: " + saved["reason"])
                content_count += 1
    return {"exact_applied": exact_count, "content_applied": content_count,
            "saved": snapshot(review)}
