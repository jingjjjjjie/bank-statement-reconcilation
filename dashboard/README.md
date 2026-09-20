# Bank Statement Reconciliation dashboard

See [Application workflow](../docs/WORKFLOW.md) for detailed Mermaid diagrams and the current matching integration boundary.

Start the complete application in Docker:

```console
docker compose up -d --build dashboard
```

Open http://127.0.0.1:8765. FastAPI serves the Vue application and Python API from the same container and port. See [frontend maintenance](frontend/README.md) for the source structure and local build commands.

For work folders containing `documents/` and `statement/`, Proceed verifies exact duplicates automatically. Proceed copies every member into `output/duplicates/group-NNN/` beside the input folders; `/review` can display the saved counts. `output/duplicates/report.json` records hashes and original locations. Inputs remain intact, no human selection is required, and extraction uses one input per hash. Existing organized copies are copied back to their original locations when upgrading a legacy work-folder review; old recovery files and the legacy manifest are preserved.

The following retain/undo controls apply only to older standalone-folder reviews:

- Browse/search groups and compare image, PDF, spreadsheet or Word previews.
- Expand **Original location** to see where each copy came from.
- **Retain this file** leaves it in the manifest's `duplicated/group-NNN` and moves other copies into the active review data directory's `recovery/`. No permanent deletion occurs.
- **Undo selection** returns the archived copies. Choices persist across server restarts.
- **Validate review** checks all groups using the existing exact-duplicate checker. It shows exact-pass readiness for extraction but does not start Codex or consume subscription usage.

## Current screens

- **Documents** at `/documents` runs extraction and receipt assembly only. It never screens or compares documents for vision duplicates. Run resumes saved extraction; Stop cancels active calls while retaining completed results. The five list statuses are Queued, Processing, Needs review, Complete, and Needs attention. A document becomes Complete after its current extraction is explicitly accepted. The progress bar eases between measured updates and respects reduced-motion preferences.
- **Receipt review** opens `/extraction-review` from each document or the navigation. Original evidence and editable receipt pieces have their own page. The removed `/content-review` page redirects to Documents. Historical comparison results and decisions remain saved; new dashboard and CLI runs do not generate them.
- **Regenerate document** queues a fresh extraction of the selected document, including multi-page assembly, on the shared parallel worker. Its live indicator shows queued, regenerating, completed, or unresolved status while you browse other documents. Completed results reload automatically unless you have unsaved edits; regenerated results require fresh approval. Relevance flags allow informal Excel claims and KWSP reports, and reserve unrelated classification for clearly unrelated content.
- **Document status** is always available at http://127.0.0.1:8765/documents and in every sidebar, including before a review is created. It reads saved progress, refreshes automatically, and remembers search/status filters in this browser across navigation and reloads.
- **Settings** opens the separate page at http://127.0.0.1:8765/settings. It saves PDF mode, pictures on/off, Codex on/off, request limit, model and reasoning to `config/review_config.json`. The request-limit section explains exactly what counts, when the run pauses, how to resume and when changes apply. Model/effort options come from the installed Codex catalog. Saving does not start model calls. Changed extraction settings display a refresh instruction; disabled inputs remain unresolved during extraction.
- **Development buttons** on Settings fill defaults without saving until **Save settings**. **Remember current decisions** pins human exact/legacy-comparison choices in the shared development cache when enabled, with a legacy per-review fallback. **Apply remembered decisions** requires a name and explicit click, checks original paths/hashes and comparison evidence, skips missing/already-decided entries, and makes no model calls. These tools do not approve current receipt extractions or final pairings. See [development cache](../docs/DEVELOPMENT_CACHE.md).
- **Completion** opens http://127.0.0.1:8765/complete. It displays final recorded token totals only after exact/extraction gates and the bank master's matching flags pass. It does not read the separate final-review ledger, so it is not the final report.
- **Get Started** at `/source` selects one workspace containing `documents/` and `statement/`. Proceed copies exact SHA duplicate groups to `output/duplicates/`, preserving originals, then opens the document list directly.
- **Bank statement** opens http://127.0.0.1:8765/bank. It shows saved AmBank totals and transactions, supports searching narration and counterparties, and exports a styled bank-only Excel file from the validated master. Enter or verify the actual company name before export. Formatting comes from `prompts/styles/bank_statement.xml`; no sample workbook path is needed. The download is generated on request and does not overwrite saved files. Supporting-document matching is reviewed separately at `/matching`, using the authorized frozen cache; new-workspace import remains pending.

Preserve the active review data directory (`dashboard-data/` for managed projects, or `dashboard/.data` by default for legacy reviews): it holds recovery copies and decision history. Recovery is outside both scanned document folders, so archived copies do not interfere with the one-file-per-group check. Changed files, unexpected files and interrupted actions block further changes for that group.

Model and reasoning controls cover document extraction by file type. All extraction and receipt-assembly calls share one request allowance. Existing comparison settings are preserved for historical compatibility but are not shown or used by new dashboard runs.

Settings controls concurrent `codex exec` calls (1–8, default 4). Finished extractions and receipt assemblies are checkpointed; unfinished or failed calls remain unresolved for the next run.

The local server defaults to loopback; Compose binds it to `0.0.0.0` inside the container but publishes only host loopback. Optional flags: `--host`, `--port 8766`, `--manifest path`, `--data path`. Stop with Ctrl+C if started in a terminal.

## Code layout

- `app.py`: command-line options and Uvicorn startup.
- `frontend/src/`: Vue views, shared navigation, scoped page controllers, and styles.
- `routes.py`: FastAPI creation, local request protection, and compiled asset delivery.
- `api/`: typed workspace, review, and preview endpoints calling the existing workflow code.
- `review.py`: manifest access, recoverable keep/undo decisions, and workflow readiness.
- `content_review.py`: background extraction/assembly, cancellation and retained legacy comparison verdicts.
- `regeneration.py`: durable per-document regeneration queue.
- `matching_review.py`: frozen-snapshot checks, human allocations, confidence labels and CSV export.
- `office_preview.py` and `document_status.py`: document previews and review status.
- `../reconciliation/document_reader.py`: extraction entry point with separate PDF, image, Excel, Word, and embedded-image handlers.

Tests (from the repository root, using Python with the project dependencies installed):

Build the frontend first, or run tests inside the Docker image where it is already compiled. The HTTP and browser fixtures run the same ASGI application on isolated loopback ports. Production uses one Uvicorn worker because active review state and cancellable background jobs belong to that process; increasing the worker count requires shared job coordination first.

```console
python -m unittest discover -s tests/unit -t .
python -m unittest tests.unit.test_app tests.unit.test_content_review
```

## Final review, report and individual receipts

The **Final review** navigation opens `/matching`, using the authorized frozen 240-line cache. It includes a filtered transaction queue, candidate search, original PDF/image/Office previews, approve/deny/undo, and an unmatched-supporting tab. Both tabs share the same persisted `final-review/decisions.json` ledger beside the active manifest. Original cache results are suggestions only and are never overwritten. The cache must belong to the active workspace. No new model calls run from this page.

High / Low confidence and its reason are independent of Pending / Approved / Rejected decisions; unpaired suggestions show No match. Confidence reuses saved assessments and Python checks, without a new model call. The compact review screen shows selected support first. Other candidates, explanations, optional notes and history are disclosed on demand; monetary warnings remain visible. No reviewer name is required. New unnamed actions use the generic `Local user` audit label and retain timestamps and undo history.

Reviewers may select multiple distinct expenses or allocate part of one source to different payments. Python validates decimal amounts, currencies, fresh source hashes, stale tabs, excluded documents, remaining balances and unassembled page totals. Flagged/partial/context-only approvals need a note and explicit acknowledgement. Approvals, denials and undo retain history. Changed evidence loses Supporting status but retains its reservation until explicitly undone. Only fully allocated current approvals export as Supporting; partial/contextual approvals retain their review status and visible differences. CSV includes all bank lines and original source references.

The **Final report** navigation and Final review button open `/final-report`. This read-only page lists all bank rows from the same ledger, including pending/no-support rows, with search, support filters and CSV export. **View evidence** opens a modal: bank original on the left, approved supporting documents on the right, and saved totals, differences, flags and notes below. It supports document switching, page selection, zoom and original downloads. Escape/Close restores focus and preserves report filters. Mobile uses transaction cards and a full-screen stacked pane. Missing or changed evidence is explicit; pending/rejected suggestions are never shown as approved evidence. The report refreshes when revisited; it is not a locked archive. See [synthetic UI checks](../docs/FINAL_REPORT_UI_REVIEW.md).

Document Status now links to Final review for matching. The older receipt-matching API below remains for legacy state, but cannot accept new allocations after a final-review ledger is created. Existing legacy approvals must be migrated or undone first; they are never silently ignored or double counted.

Documents includes **Run all documents** (bounded by the configured parallel/request limits) and a per-document **Review results** link. The results page offers **Reload** and **Regenerate document**. Each extracted unit can contain multiple receipt or claim pieces. Review their locations, invoice numbers, descriptions, totals, and currencies against the original. Correct the pieces or leave missing fields blank, then explicitly accept the extraction; a reviewer name is not required.

### Legacy receipt-allocation API

The following describes retained API/state behavior, not controls in the current Step 2 results page. Select a bank transaction and one or several accepted pieces to calculate a pending match. Python uses decimal arithmetic and shows the bank amount, individual allocations, supporting total, and difference. A separate **Accept match** action records approval; a nonzero difference requires a reason and remains visible. Pieces may be partially allocated across transactions. Accepted allocations reserve their amounts until **Undo match**; competing proposals cannot spend those amounts again. Refreshing extraction, changing source bytes, or changing the bank master invalidates affected approvals/proposals. Undo stale accepted matches before reallocation.

Receipt extraction approvals, matches, and decision history are saved separately in `review/receipt-matches.json`; the original files and bank master are unchanged. Extraction CSV rows also include the raw `receipts` JSON. Old completed extraction units are not guessed into receipt records: refresh the extraction or manually review and enter their pieces. The final statement/unmatched-document export workflow remains separate; receipt match acceptance does not alter the existing bank-only export or completion gate.


## Multi-page receipt review

Multi-page receipt review includes a document assembly step after page extraction.
The model sees the page results and original PDF page images, and returns receipts with
source unit numbers and location labels. A receipt can span pages;
a page can contain several receipts. This step uses the existing document-stage model,
request limit, subscription login, and token accounting. Completed page results are reused.

The extraction editor lets the user correct pieces and their source references.
Check each piece against the original before accepting. There is no model-generated
`needs_review` flag or boundary checkbox. Incomplete assembly cannot be approved; changes to its source page results
invalidate approval. Bank allocations remain separate from receipt boundaries.
