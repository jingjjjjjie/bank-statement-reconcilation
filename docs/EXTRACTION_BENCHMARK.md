# Extraction concurrency benchmark

`scripts/benchmark_extraction.py` runs fresh model extraction for every eligible
unit in a prepared review. It freezes Python workflow code, prompts, unit text and
images, and verifies source/image hashes before starting. It does not change the
normal review's state, model settings or results.

Run it in a separate container so dashboard restarts do not interrupt it:

```console
docker compose run --rm --no-deps dashboard python scripts/benchmark_extraction.py --work /workspace/duplicated/projects/PROJECT/review --output /workspace/duplicated/benchmarks/UNIQUE-RUN --workers 8 12 16 30
```

Replace `PROJECT` and `UNIQUE-RUN` with the intended review and a new output folder.
Keep normal model reviews stopped throughout the benchmark: separate containers
still share the same ChatGPT account and can compete for capacity.

The benchmark uses `gpt-5.6-sol`, default reasoning and a 240-second per-call timeout.
Worker levels run sequentially with identical input order. Each unit has its own
fresh response-cache namespace, and shared development-cache reuse is disabled
only inside the benchmark process. Provider-side prompt caching can still occur;
reported cached-input tokens are retained separately.

Timing covers model extraction and response validation. It reuses prepared local
text/images and excludes PDF rendering, duplicate screening, receipt assembly and
bank matching. A single sequential pass per level is an observed comparison,
not proof of a universal optimum: service load, cache state and model outputs vary.

Each worker folder saves `unit-results.jsonl`, `token-usage.jsonl`, raw model-call
artifacts, `progress.json` and `report.json`. `results.json` collects completed
levels. Token reports contain stage/model totals and unknown-usage counts. Unknown
usage is never estimated; totals with unknown attempts are partial. Cache hits
are zero new usage. Token counts through the subscription are not a dollar charge.

Timeouts and other failures remain unresolved and are not automatically retried.
A schema-valid response marked unreadable also remains unresolved; it is different
from a failed call. Successful validation is not an independent accuracy audit.
Keep interrupted runs for their token audit, but exclude them from speed comparisons.
