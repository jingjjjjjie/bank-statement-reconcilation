# Development contract

Read this file before starting any task in this workspace. Apply these rules to every instruction and change made here. If a task conflicts with this contract, follow the higher-priority instruction and make the conflict clear.

- Keep work clean and concise. Write minimal, readable Python code. Give every function a short, clear docstring or comment explaining its purpose.
- Use Python for development.
- Follow sound Git practice: inspect the working tree before editing, keep changes scoped, run relevant checks, review the diff, and commit only intended files with a clear message. Preserve unrelated work and avoid rewriting shared history.
- Default workflow LLM reasoning and vision to `gpt-5.6-sol`, unless the user or a benchmark explicitly overrides it.
- For work folders containing `documents/` and `statement/`, copy exact-duplicate groups into that work folder's `output/duplicates/` directory without changing inputs; no human selection is required for exact byte matches. Legacy review state may remain under the repository's `duplicated/` directory. Preserve original supporting-document locations in the manifest.
- For application or workflow LLM reasoning or vision, use `codex exec` with the existing ChatGPT subscription login. Do not use API keys or a separate paid API connection unless the user explicitly changes this preference.
- Use Python for deterministic extraction, hashing, validation, and workflow state. Require structured model output, attach images for vision, and record incomplete or failed calls as unresolved.
- Track token usage for every workflow `codex exec` attempt from now on. Keep durable per-attempt records and totals by stage and model. Record cache hits as zero new usage and mark attempts without reported usage as unknown; never estimate missing tokens or present partial totals as complete.
- Never treat model output as admin approval to delete files.
- Before final-comparison work, read `docs/FINAL_COMPARISON.md` for the agreed two-page review/export workflow and open decisions. Implementation is deferred until both input branches are ready.
