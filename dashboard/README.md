# Bank Statement Reconciliation dashboard

From Development:

```console
.tools\python\python.exe dashboard/app.py
```

Open http://127.0.0.1:8765. The Python server, HTML, CSS and JavaScript all live in `dashboard/`.

- Browse/search groups and compare image, PDF, spreadsheet or Word previews.
- Expand **Original location** to see where each copy came from.
- **Retain this file** leaves it in `Development/duplicated/group-NNN` and moves the others into `dashboard/.data/recovery`. No permanent deletion occurs.
- **Undo selection** returns the archived copies. Choices persist across server restarts.
- **Validate review** checks all groups using the existing exact-duplicate checker. It shows readiness for pass two but does not start Codex or consume subscription usage.
- **Content review** opens http://127.0.0.1:8765/content-review after exact-copy cleanup. Prepare extracts the remaining documents locally; Run next review batch resumes bounded Codex extraction, screening, and original comparison. Candidate cards show both originals, page previews, matching evidence, differences, and limitations. An admin must enter a name and reason to keep both or approve one survivor. Approval does not delete or move source files; cleanup remains a separate manual step.
- **Settings** opens the separate page at http://127.0.0.1:8765/settings. It saves PDF mode, pictures on/off, Codex on/off, request limit, model and reasoning to `Development/review_config.json`. The request-limit section explains exactly what counts, when the run pauses, how to resume and when changes apply. Model/effort options come from the installed Codex catalog. Saving does not start model calls. Changed extraction settings display a refresh instruction; disabled inputs remain unresolved in pass two.
- **Development buttons** on Settings fill the documented defaults without saving until you click **Save settings**. **Remember current decisions** stores only human choices from the exact and content passes in the active review's `dashboard-data/development-decisions.json`. **Apply remembered decisions** requires your name and an explicit click. It reuses exact choices only for the same original path and hash, and content choices only for the same hash pair after a new completed comparison. It skips missing or already decided matches and makes no Codex calls. Replayed content decisions record your name and a development-replay reason. Keep `dashboard-data` when resetting a test run if you want to reuse the preset.
- **Completion** opens http://127.0.0.1:8765/complete. It displays cumulative recorded token usage after exact review, content review, and bank matching are complete.
- **Source folder** opens http://127.0.0.1:8765/source. Choose a supporting-documents folder and a bank-statement PDF separately with the in-page file browser or a full path. Checking a path is read-only. The page previews source-file and exact-duplicate counts before **Create or open review** moves exact copies under `Development/duplicated/projects/`; a changed source requires a fresh preview. **Extract bank statement** uses the selected PDF and supplied year for the active review; an existing master from another statement is never replaced.
- **Bank statement** opens http://127.0.0.1:8765/bank. It shows saved AmBank totals and transactions, supports searching narration and counterparties, and exports a styled bank-only Excel file from the validated master. Enter or verify the actual company name and sample workbook path before export; the sample contributes styles only. The download is generated on request and does not overwrite saved files. Supporting-document matching remains pending.

Do not delete `.data`: it holds recovery copies and the decision history. Recovery is outside both scanned document folders, so archived copies do not interfere with the one-file-per-group check. Changed files, unexpected files and interrupted actions block further changes for that group.

Model and reasoning controls are separate for PDF reading, JPG/images, Excel, Word, and document comparison. JPG/images use vision only for now. Comparison settings cover both summary screening and original-document comparisons, including mixed file types. All stages share one request allowance. Existing shared settings remain the fallback until stage selections are saved. Command-line `--model` or `--reasoning` overrides that field for every stage in that run. Changing a stage's model or effort after review work has started requires `prepare --refresh`; previous metadata is archived.

The server listens only on loopback. Optional flags: `--port 8766`, `--manifest path`, `--data path`. Stop with Ctrl+C if started in a terminal.

Tests:

```console
.tools\python\python.exe -m unittest dashboard.test_app
```
