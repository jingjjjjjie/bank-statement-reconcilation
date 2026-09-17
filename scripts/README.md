# Manual tools

Run these commands from the repository root. They are excluded from offline test discovery.

- `python -m scripts.check_codex_connection`: makes one live Codex request with a synthetic receipt and records token usage.
- `python -m scripts.benchmark_terra`: runs the explicitly configured Terra benchmark and records token usage.
- `python -m scripts.relocate_duplicates`: legacy, one-time migration of an existing duplicate review. It moves files; do not run it again for an already organized batch.
