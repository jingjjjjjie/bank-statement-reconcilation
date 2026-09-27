# Matching images benchmark

`scripts/benchmark_matching_images.py` freezes the active project's sources,
rendered images, bank entries, prompts and Python runtime into an isolated output
folder. It regenerates extraction with `gpt-5.6-sol` through the existing Codex
subscription login. Production approvals and matching decisions are not imported
as approvals for the new pieces.

The extraction and assembly prompts explicitly normalize printed RM or MYR to
MYR. Unknown currencies stay empty; explicit other currencies are preserved.
Vision extraction continues to attach source images. Original Codex coding-agent
instructions remain enabled.

Run from the repository in the dashboard container:

```powershell
docker compose exec -T dashboard python -m scripts.benchmark_matching_images prepare --project /workspace/duplicated/projects/26673bea63406905 --output /workspace/review/matching-images-benchmark --workers 1
docker compose exec -T dashboard python -m scripts.benchmark_matching_images extract --project /workspace/duplicated/projects/26673bea63406905 --output /workspace/review/matching-images-benchmark --workers 1 --capacity-retries 12
```

Prepare refuses an existing output folder. Extraction resumes its saved results.
Capacity retries wait 30 seconds and stop after three failed runs with no progress
or the configured retry limit. Other failures return unresolved. Every Codex
attempt retains its audit record; attempts without reported usage remain unknown.
`extraction-summary.json`, `extraction-runs.jsonl`, and
`extraction/token-usage.jsonl` retain progress and usage. Completion counts require
all source units plus current assembly for documents with multiple units.

Once extraction is complete, `cases` freezes up to 50 bank entries stratified by
the previous currency errors, context-size errors, and other outcomes. `match`
uses the same facts and native text for both arms, attaching all corresponding
page images only in the images arm. Both retain production allocation validation
and context limits. Matching refuses incomplete extraction coverage.

Report operational success across all cases and compare tokens on paired cases
that both arms actually attempted. Context-limit blocks are not zero-cost model
successes. Agreement between arms or with old suggestions is not accuracy: neither
is independent ground truth. Source inspection is needed to assess disagreements.
Extraction costs are shared preprocessing and must be reported separately from
the two matching arms. Subscription usage must not be presented as an API bill.
