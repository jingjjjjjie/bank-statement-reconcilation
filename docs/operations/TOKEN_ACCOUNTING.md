# Workspace token accounting

Settings shows accumulated usage for this application workspace, across all
projects, benchmarks, retries and workflow stages. It refreshes every ten seconds
while visible without resetting unsaved settings. Completion reports retain their
individual review totals.

Each managed call writes its local `token-usage.jsonl` and a durable workspace
ledger at `duplicated/accounting/usage.sqlite3`. This ledger is independent of
development mode and is not reset by preparing a review or clearing result caches.
It is accounting data, not a disposable response cache.

Historical logs are imported on reading Settings. Attempts are deduplicated by
their recorded attempt ID across project logs, benchmark copies and development
mirrors. A completed usage record is never replaced by an older started record.
New cache events also carry IDs; legacy development-mirror cache entries are
excluded to avoid counting copied cache events twice. Known totals remain in the
ledger if original logs are subsequently removed.

Cached input is already included in input tokens. Reasoning output is already
included in output tokens. The displayed total is input plus output, not the sum
of all four counters. Application result-cache hits consume zero new tokens.

Active attempts and attempts without reported usage remain unknown. Corrupt or
unreadable logs make totals incomplete. The UI labels incomplete totals as
partial. Historical calls made before logging existed cannot be reconstructed;
this is reported workspace workflow usage, not account billing or this assistant
conversation's usage. Commands bypassing the shared wrapper are outside coverage.

Keep the accounting directory when migrating the workspace. Workflow outputs
outside this workspace are not automatically included. Local source-document,
dependency, generated-asset and frozen-code directories are excluded from
historical discovery; normal project and benchmark output directories are scanned.
