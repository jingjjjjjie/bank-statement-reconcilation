# Bank Statement Reconciliation dashboard

Start the complete application in Docker:

```console
docker compose up -d --build dashboard
```

Open http://127.0.0.1:8765. FastAPI serves the Vue application and Python API from the same container and port. See [frontend maintenance](frontend/README.md) for the source structure and local build commands.

For work folders containing `documents/` and `statement/`, Proceed verifies exact duplicates automatically. The report at `/review` shows counts and copies every member into `output/duplicates/group-NNN/` beside the input folders. `output/duplicates/report.json` records hashes and original locations. Inputs remain intact, no human selection is required, and content review uses one input per hash. Existing organized copies are copied back to their original locations when upgrading a legacy work-folder review; old recovery files and the legacy manifest are preserved.

The following retain/undo controls apply only to older standalone-folder reviews:

- Browse/search groups and compare image, PDF, spreadsheet or Word previews.
- Expand **Original location** to see where each copy came from.
- **Retain this file** leaves it in `Development/duplicated/group-NNN` and moves the others into `dashboard/.data/recovery`. No permanent deletion occurs.
- **Undo selection** returns the archived copies. Choices persist across server restarts.
- **Validate review** checks all groups using the existing exact-duplicate checker. It shows readiness for pass two but does not start Codex or consume subscription usage.
- **Content review** opens http://127.0.0.1:8765/content-review after exact-copy cleanup. Prepare extracts the remaining documents locally; Run next review batch resumes bounded Codex extraction, screening, and original comparison. A loading overlay names the active stage, including after a page reload. **Stop review** stops active Codex calls and saves completed results; unfinished calls remain pending and Run next review batch resumes them. Interrupted calls may have already used tokens. Candidate cards show both originals, page previews, matching evidence, differences, and limitations. An admin must enter a name and reason to keep both or approve one survivor. The verdict is saved immediately in `review/state.json`; **Remember current decisions** then copies human choices into the development preset. Approval does not delete or move source files; cleanup remains a separate manual step.
- The pair total is every possible document pair (N Ã— (N âˆ’ 1) Ã· 2), not a Codex-call count. Screens include up to 12 right-hand documents per request. Completed unit results and pair results are checkpointed in `review/state.json`; identical successful model requests are cached under `review/model-cache/`. A changed input, schema, model, or reasoning setting may require a new call. The first exhaustive run can still be costly.
- **Document status** is always available at http://127.0.0.1:8765/documents and in every sidebar, including before a review is created. It reads saved progress, refreshes automatically, and remembers search/status filters in this browser across navigation and reloads.
- **Settings** opens the separate page at http://127.0.0.1:8765/settings. It saves PDF mode, pictures on/off, Codex on/off, request limit, model and reasoning to `config/review_config.json`. The request-limit section explains exactly what counts, when the run pauses, how to resume and when changes apply. Model/effort options come from the installed Codex catalog. Saving does not start model calls. Changed extraction settings display a refresh instruction; disabled inputs remain unresolved in pass two.
- **Development buttons** on Settings fill the documented defaults without saving until you click **Save settings**. **Remember current decisions** stores only human choices from the exact and content passes in the active review's `dashboard-data/development-decisions.json`. **Apply remembered decisions** requires your name and an explicit click. It reuses exact choices only for the same original path and hash, and content choices only for the same hash pair after a new completed comparison. It skips missing or already decided matches and makes no Codex calls. Replayed content decisions record your name and a development-replay reason. Keep `dashboard-data` when resetting a test run if you want to reuse the preset.
- **Completion** opens http://127.0.0.1:8765/complete. It displays cumulative recorded token usage after exact review, content review, and bank matching are complete.
- **Source folder** opens http://127.0.0.1:8765/source. Choose a supporting-documents folder and a bank-statement PDF separately with the in-page file browser or a full path. Checking a path is read-only. The page previews source-file and exact-duplicate counts before **Create or open review** moves exact copies under `Development/duplicated/projects/`; a changed source requires a fresh preview. **Extract bank statement** uses the selected PDF and supplied year for the active review; an existing master from another statement is never replaced.
- **Bank statement** opens http://127.0.0.1:8765/bank. It shows saved AmBank totals and transactions, supports searching narration and counterparties, and exports a styled bank-only Excel file from the validated master. Enter or verify the actual company name before export. Formatting comes from `prompts/styles/bank_statement.xml`; no sample workbook path is needed. The download is generated on request and does not overwrite saved files. Supporting-document matching remains pending.

Do not delete `.data`: it holds recovery copies and the decision history. Recovery is outside both scanned document folders, so archived copies do not interfere with the one-file-per-group check. Changed files, unexpected files and interrupted actions block further changes for that group.

Model and reasoning controls are separate for PDF reading, JPG/images, Excel, Word, and document comparison. JPG/images use vision only for now. Comparison settings cover both summary screening and original-document comparisons, including mixed file types. All stages share one request allowance. Existing shared settings remain the fallback until stage selections are saved. Command-line `--model` or `--reasoning` overrides that field for every stage in that run. Changing a stage's model or effort after review work has started requires `prepare --refresh`; previous metadata is archived.

The Settings page also controls how many `codex exec` calls run together (1â€“8, default 4). All workers share the per-run request limit. Finished unit reads, screens, and original comparisons appear in saved review progress as they complete; unfinished or failed calls remain unresolved for the next run.

The server listens only on loopback. Optional flags: `--port 8766`, `--manifest path`, `--data path`. Stop with Ctrl+C if started in a terminal.

## Code layout

- `app.py`: command-line options and Uvicorn startup.
- `frontend/src/`: Vue views, shared navigation, scoped page controllers, and styles.
- `routes.py`: FastAPI creation, local request protection, and compiled asset delivery.
- `api/`: typed workspace, review, and preview endpoints calling the existing workflow code.
- `review.py`: manifest access, recoverable keep/undo decisions, and workflow readiness.
- `content_review.py`: background content-review jobs and human verdicts.
- `office_preview.py` and `document_status.py`: document previews and review status.
- `../reconciliation/document_reader.py`: extraction entry point with separate PDF, image, Excel, Word, and embedded-image handlers.

Tests (from the repository root, using Python with the project dependencies installed):

Build the frontend first, or run tests inside the Docker image where it is already compiled. The HTTP and browser fixtures run the same ASGI application on isolated loopback ports. Production uses one Uvicorn worker because active review state and cancellable background jobs belong to that process; increasing the worker count requires shared job coordination first.

```console
python -m unittest discover -s tests/unit -t .
python -m unittest tests.unit.test_app tests.unit.test_content_review
```

## Individual receipts and bank allocations

The **Final review** navigation opens `/matching`, using the authorized frozen 240-line cache. It includes a filtered transaction queue, candidate search, original PDF/image/Office previews, approve/deny/undo, and an unmatched-supporting tab. Both tabs share the same persisted `final-review/decisions.json` ledger beside the active manifest. Original cache results are suggestions only and are never overwritten. The cache must belong to the active workspace. No new model calls run from this page.

The compact review screen shows selected support first. Other candidates, explanations, optional notes and history are disclosed on demand; monetary warnings remain visible. No reviewer name is required. New unnamed actions use the generic `Local user` audit label and retain timestamps and undo history.

Reviewers may select multiple distinct expenses or allocate part of one source to different payments. Python validates decimal amounts, currencies, fresh source hashes, stale tabs, excluded documents, remaining balances and unassembled page totals. Flagged/partial/context-only approvals need a note and explicit acknowledgement. Approvals, denials and undo retain history. Changed evidence loses Supporting status but retains its reservation until explicitly undone. Only fully allocated current approvals export as Supporting; partial/contextual approvals retain their review status and visible differences. CSV includes all bank lines and original source references.

Document Status now links to Final review for matching. The older receipt-matching API below remains for legacy state, but cannot accept new allocations after a final-review ledger is created. Existing legacy approvals must be migrated or undone first; they are never silently ignored or double counted.

Document Status includes **Run all documents** (bounded by the configured parallel/request limits) and **Load latest receipt results**. Each extracted unit can contain multiple receipt or claim pieces. Review their locations, invoice numbers, descriptions, totals, and currencies against the original. Correct the pieces or leave missing fields blank, then accept the extraction with a reviewer name.

Select a bank transaction and one or several accepted pieces to calculate a pending match. Python uses decimal arithmetic and shows the bank amount, individual allocations, supporting total, and difference. A separate **Accept match** action records approval; a nonzero difference requires a reason and remains visible. Pieces may be partially allocated across transactions. Accepted allocations reserve their amounts until **Undo match**; competing proposals cannot spend those amounts again. Refreshing extraction, changing source bytes, or changing the bank master invalidates affected approvals/proposals. Undo stale accepted matches before reallocation.

Receipt extraction approvals, matches, and decision history are saved separately in `review/receipt-matches.json`; the original files and bank master are unchanged. Extraction CSV rows also include the raw `receipts` JSON. Old completed extraction units are not guessed into receipt records: refresh the extraction or manually review and enter their pieces. The final statement/unmatched-document export workflow remains separate; receipt match acceptance does not alter the existing bank-only export or completion gate.


Multi-page receipt review now includes a document assembly step after page extraction.
The model sees the page results and original PDF page images, and returns receipts with
source unit numbers, location labels, and boundary-review flags. A receipt can span pages;
a page can contain several receipts. This step uses the existing document-stage model,
request limit, subscription login, and token accounting. Completed page results are reused.

The extraction editor offers merge and split controls. Both clear the printed total for
verification rather than summing repeated page totals. Resolve boundary flags before
accepting. Incomplete assembly cannot be approved; changes to its source page results
invalidate approval. Bank allocations remain separate from receipt boundaries.
