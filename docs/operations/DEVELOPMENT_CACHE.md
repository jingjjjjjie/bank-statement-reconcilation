# Retired development cache

Development mode, shared model caches, output snapshots, and remembered-decision replay are retired. Saved development flags cannot enable them. Existing archive files remain on disk and are not modified or automatically restored.

Each review still keeps its own model-response cache and resumable extraction checkpoints. Cache identity includes the prompt, schema, model, reasoning, and image bytes. Local cache hits consume no new model calls and record zero new token usage. Failed or incomplete attempts remain unresolved, with unknown usage reported explicitly.

Human approvals and history remain in the active review and final-review ledgers. See [token accounting](TOKEN_ACCOUNTING.md) and [process cancellation](PROCESS_CANCELLATION.md).
