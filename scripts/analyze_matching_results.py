"""Re-score durable experiment responses and total only reported token usage."""
import json
import argparse
from pathlib import Path

from scripts.benchmark_matching import build_candidates, fastlane, guard_allocations, save, score, shortlist


def analyze(root):
    """Use saved inputs and responses, keeping strict statuses separate from safe abstention."""
    rows = []
    for experiment in (root, root / "refined", root / "hybrid", root / "wide"):
        data = json.loads((experiment / "fixtures.json").read_text(encoding="utf-8"))
        pool, ranked, _ = build_candidates(data["banks"], data["documents"], specific=experiment != root)
        for folder in sorted(experiment.glob("rows*")):
            summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
            decisions = []
            for result in folder.glob("result-*.json"):
                decisions.extend(json.loads(result.read_text(encoding="utf-8"))["decisions"])
            if experiment.name == "hybrid":
                choices = {k:shortlist(v, "adaptive") for k,v in ranked.items()}
                decisions.extend(fastlane(data["banks"], pool, choices))
            raw = score(decisions, data["truth"], pool)
            guarded = score(guard_allocations(decisions, data["banks"], pool), data["truth"], pool)
            rows.append({"experiment": str(folder.relative_to(root)), "raw": raw, "guarded": guarded,
                         "batches": summary["batches"], "seconds": summary["wall_seconds"],
                         "usage": summary["usage"], "local_decisions": summary.get("local_decisions", 0),
                         "input_characters": summary["input_characters"]})
    totals = {key:sum(row["usage"]["totals"][key] for row in rows)
              for key in rows[0]["usage"]["totals"]}
    report = {"rows": rows, "reported_token_totals": totals,
              "attempts": sum(r["usage"]["attempts"] for r in rows),
              "unknown_attempts": sum(r["usage"]["unknown_attempts"] for r in rows),
              "cache_hits": sum(r["usage"]["cache_hits"] for r in rows),
              "distinct_labelled_cases": 40,
              "real_model_test": "Not run"}
    real_path = root / "real-results.json"
    if real_path.exists():
        real = json.loads(real_path.read_text(encoding="utf-8"))
        report["real_model_test"] = {label: {k:value[k] for k in ("error", "usage", "bank_count", "unique_candidates", "seconds")}
                                     for label, value in real.items()}
        for result in real.values():
            for key, value in result["usage"]["totals"].items():
                report["reported_token_totals"][key] += value
            report["attempts"] += result["usage"]["attempts"]
            report["unknown_attempts"] += result["usage"]["unknown_attempts"]
            report["cache_hits"] += result["usage"]["cache_hits"]
    save(root / "analysis.json", report)
    print(json.dumps({k:v for k,v in report.items() if k != "rows"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    analyze(parser.parse_args().root)
