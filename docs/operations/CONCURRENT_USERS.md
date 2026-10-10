# Concurrent browsers and project protection

Each browser profile has an opaque, HttpOnly, SameSite cookie and its own pending
workspace selection, active review, save token and live updates. Tabs in the same
profile share that session. These sessions are not named login accounts or access
permissions: anyone allowed to reach the dashboard can browse the project list.

Different sessions can work on different projects. A canonical supporting folder
can be owned by only one session at a time. A second session sees **Project in use**
and cannot open it, change its evidence or stop its jobs. Both direct activation
and existing-project Resume check the server lease before any setup writes.

Use **Close project** on Projects to release it immediately. Switching projects
releases the previous lease only after the new project opens successfully. Failed
opens preserve the original project and release the failed reservation. Existing
unsaved-edit and revision checks remain in place.

A connected browser renews its lease through requests and the live stream. After
five minutes without contact, an idle project becomes available. Running workers
or child processes whose exit is unverified retain the lease. An expired browser's
old save identity is rejected, so it cannot overwrite a new editor's work.

Only one Codex extraction batch runs across all projects on this dashboard process.
Other projects show a waiting message and disable Extract documents until it ends.
Regeneration is subject to the same gate; blocked requests do not create queue entries.
The admitted batch keeps its configured parallel calls. Stop retains the gate until
its worker and child processes have actually exited. Matching is not serialized by
this extraction gate.

Run one dashboard process/instance (`workers=1`). Sessions, leases and extraction
admission are process-local; multiple independent servers sharing the same project
files require a shared lock store. Restarting the server clears browser sessions;
users reopen their projects, while saved reviews and decisions remain on disk.
Ordinary startup no longer assigns a remembered project to the first visitor.
An explicit `--manifest` still seeds the first session for embedded/local use.

Checks: `tests.unit.dashboard.test_sessions`,
`tests.unit.dashboard.extraction.test_extraction_slot`, and
`tests.browser.shell.test_sessions`. They use synthetic workspaces and fake model
workers without live Codex calls.
