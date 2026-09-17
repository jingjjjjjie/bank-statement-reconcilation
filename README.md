# Supporting-document review

The agreed final comparison workflow is recorded in [FINAL_COMPARISON.md](FINAL_COMPARISON.md). Implement it after both extraction branches are ready.

Python 3.12 or later. Pass one uses the standard library. Pass two uses the packages in `requirements.txt` and an installed Codex CLI logged in through ChatGPT.

The existing supporting files have already been organized. Do not run organize again for this batch.

## Project layout

- `reconciliation/`: extraction, duplicate review, model integration, and workflow state.
- `dashboard/`: Python server; HTML, JavaScript, and CSS live in `dashboard/static/`.
- `tests/unit/`: offline regression tests; `tests/browser/`: optional browser checks.
- `scripts/`: manual migration, benchmark, and live Codex connection tools.
- `docs/`: bank-extraction and workbook-format documentation.

Run commands from the repository root. For example:

```console
python -m dashboard.app
python -m unittest discover -s tests/unit -t .
```

Configuration and existing review data stay at their current workspace paths. `AGENTS.md` and `FINAL_COMPARISON.md` remain at the root for the development contract.

## Interactive dashboard

```console
python dashboard/app.py
```

Open **http://127.0.0.1:8765** to compare copies, choose which one to keep, undo choices, and validate pass one. Other copies move to recoverable storage under `dashboard/.data/recovery`, outside the active duplicate groups. Webpage and server code live in `dashboard/`. See [dashboard instructions](dashboard/README.md). The Settings page has development buttons for testing defaults and for remembering and explicitly reapplying human duplicate decisions. Saving settings and using those buttons make no Codex calls.

### Review settings

The separate [Settings page](http://127.0.0.1:8765/settings), linked from the dashboard, saves to `review_config.json`:

- **PDF processing:** extractor only (default), text with vision fallback for sparse/scanned pages, or text plus vision on every page.
- **Picture processing:** enables pictures, embedded Office images and PDF page images for review. Dashboard previews are unaffected.
- **Codex on/off:** enables model reasoning through `codex exec`. Off stops new calls; an already-running call may finish.
- **Calls per run:** 1–500, default 20.
- **Parallel Codex requests:** 1–8 at once, default 4. The next run uses the saved setting. Workers share the same calls-per-run allowance; completed responses are checkpointed as they finish, and in-flight calls finish before a budget pause is reported.
- **Request-limit explanation:** one call means one new model invocation, not one file. Started failed/timed-out attempts count; cached results and local extraction do not. At the limit, work is saved and the run pauses before another new request. Rerunning resumes with a fresh allowance. A changed limit applies to the next run. This is not a token, time or daily subscription limit.
- **Token tracking:** each new `codex exec` attempt is recorded in `review/token-usage.jsonl`, with Codex-reported input, cached input, output and reasoning output tokens when available. The settings page and pass-two report show running totals. The dashboard Completion page shows the final total after exact review, content review, and bank matching have all passed. Cache hits use no new tokens; interrupted or failed attempts without reported usage remain marked unknown. Tracking starts with this version and covers this workflow, not other ChatGPT activity.
- **Model and reasoning:** all review stages default to `gpt-5.6-sol`, with the model's default reasoning effort. Models and supported effort levels remain selectable from the local Codex catalog. Explicitly choosing Codex default / model default leaves selection to the CLI. An unknown model, unsupported effort, or picture input with a text-only model is rejected.

PDF extraction is local. When Codex is on it may reason over the extracted text; PDF images are sent only when the selected mode and picture switch allow it. Text-only processing does not inspect handwriting, signatures or visual differences. Fewer than 20 alphanumeric extracted characters marks a page as sparse; this is a fallback heuristic, not proof of readability. Disabled or unreadable inputs remain unresolved.

Saving does not launch a review. Changing extraction settings requires:

```console
python -m reconciliation.vision_workflow prepare --refresh
```

Refresh archives previous metadata/decisions in `review/history/` and retains old assets and model caches. Exact-duplicate choices are unaffected. Model/reasoning changes cannot silently reuse review results from another selection. The model and reasoning used are recorded in state and included in response-cache keys. Reasoning is passed using `model_reasoning_effort` as documented in the [official Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference); available levels come from local model capability metadata.

CLI overrides: `--model MODEL --reasoning LEVEL --max-calls N` on `run`. A custom `--config path.json` on `prepare` pins that configuration path for the prepared review. Turning Codex off is checked before each next call.

Check the admin's cleanup from this workspace:

```console
python -m reconciliation.duplicate_workflow check
```

A workspace-local Python runtime is also available:

```console
python -m reconciliation.duplicate_workflow check
```

The supporting folder defaults to the path in `duplicate-manifest.json`.
The checker reads files without modifying them. Exit codes: 0 = exact-duplicate pass complete, 2 = admin cleanup pending, 1 = execution error. Exit 0 permits LLM/vision review; it does not certify that the full duplicate review is complete.

The admin leaves one original-content file in every group under **Development/duplicated**, beside these Python scripts. This review folder is outside the Dropbox supporting folder. Both locations are scanned by the checkers. Missing folders, empty groups, multiple files, changed content, unexpected groups, and remaining exact duplicates block progression. Original claim locations are retained in the manifest and `duplicated/original-locations.csv`.

For a new batch, use a manifest in its own workspace subfolder; its `duplicated` folder is created beside that manifest:

```console
python -m reconciliation.duplicate_workflow organize --root "path/to/supporting" --manifest "new-batch.json"
python -m reconciliation.duplicate_workflow check --manifest "new-batch.json"
```

Organization verifies size, SHA-256 and actual bytes, records original locations, then moves all copies into one subfolder per group. It does not delete files. If interrupted, inspect the saved manifest and current locations before recovery; do not overwrite the manifest or blindly rerun organization.

Decisions and discussion: `issues.md`.

## Two-pass duplicate review

1. **Exact content:** the existing Python script verifies size, SHA-256 and bytes. Admin leaves one unchanged file per duplicate group; the checker validates this pass.
2. **LLM/text and vision:** review the remaining unique documents for equivalent content across scans, images, PDFs and spreadsheets. Compare document references, parties, dates, currency, amounts, line items, signatures and annotations. Read structured text where available and inspect page images where needed. Similar names or amounts alone are insufficient.

Pass two is implemented in `reconciliation/vision_workflow.py`. Its report distinguishes the same document, revised/conflicting versions, partial overlap, related supporting documents, distinct documents and uncertain cases. Each candidate includes file/page references, matching evidence, differences, confidence and an admin verdict. Confidence is a review aid, not a calibrated probability. The scanner walks nested folders without a depth limit. `review/supporting-inventory.csv` lists every original file separately, including exact copies moved during pass one; `original_path` records its initial location, `source_path` identifies the reviewed copy, and `exact_duplicate_with` lists same-byte originals. Accepted formats are PDF, PNG, JPG/JPEG, TIFF, WebP, BMP and Excel `.xlsx`. Other formats remain listed as `not_accepted` and receive no content review. For accepted files, `receipt_status` is `receipt`, `not_receipt`, or `unsure` based on visible evidence; an invoice alone is `not_receipt`. This classification does not remove accepted supporting documents from duplicate comparison. The CSV also includes available invoice numbers, companies, short descriptions, combined totals, other extracted fields, review status, and possible or confirmed matches. Empty extraction fields mean unavailable or pending information. `raw_text` preserves all locally extracted text; image evidence remains in its source file and prepared preview. The CSV is refreshed at every checkpoint and is a readable export of the validated JSON review state. Refresh an earlier prepared review to add the new classification and CSV columns. `reconciliation/comparison_policy.py` routes a pair straight to original-document comparison only when its combined total and currency match, together with the same invoice number or matching company and meaningful particulars. A matching date adds evidence but cannot replace company or particulars. Grand totals replace component amounts; otherwise invoice totals or line items are summed once. Pairs outside the fast route receive normal model screening, so the local rule never excludes a pair or confirms a duplicate.

Only admin-confirmed equivalent whole documents qualify for duplicate cleanup. An invoice and its payment receipt are complementary evidence. A shared page does not make two entire PDF bundles interchangeable. Do not move or delete pass-two candidates automatically. Unreadable or unreviewed documents remain unresolved. Proceed to the next reconciliation step only when both passes and their admin decisions are complete.

The dashboard's **Content review** page is unlocked by pass-one validation. It prepares the remaining documents, runs bounded model batches, shows each candidate's original documents and evidence, and records an admin verdict with a name and reason. Source cleanup is never automatic.

## Run pass two

The local runtime and dependencies are already installed in this workspace. For another Python installation:

```console
python -m pip install -r requirements.txt
codex login
```

Choose ChatGPT login. All model reasoning and vision use `codex exec`; there is no API-key backend. The wrapper verifies ChatGPT login and uses read-only, ephemeral sessions with structured JSON output and attached images. It ignores user CLI configuration to avoid custom providers; authentication is retained. `--model` can explicitly select a model available to the account. These options follow the [official non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

Prepare once (local extraction only; allowed while the admin cleans exact duplicates):

```console
python -m reconciliation.vision_workflow prepare
```

The current batch is prepared under `review/`. Preparation retains one model input per exact hash and all original file locations. PDFs include every page's native text and optional rendered images according to saved settings. Enabled pictures include all frames. Spreadsheets include hidden sheets, cell coordinates, formulas and cached values. DOCX includes XML text parts and optional embedded images. Office page layout is not reconstructed; unsupported embedded objects and unreadable files block completion. Images are previewed up to 2400 pixels; unclear details must remain unresolved.

After pass-one cleanup succeeds:

```console
python -m reconciliation.vision_workflow run --max-calls 20
```

Rerun the same command to resume. It reads every unit, screens every unique document pair through model-extracted summaries in batches, then compares original text/images for candidates. No filename or amount-only filter excludes pairs. Summary screening can still miss matches: this is model-assisted review, not a mathematical guarantee. Very large comparisons remain uncertain for admin inspection rather than being silently truncated.

`--max-calls` bounds new calls per invocation (default 20); `--timeout` bounds each call (default 240 seconds). Cached responses are keyed by prompt, schema, model selector and image contents. The current corpus has 136 unique documents, so full coverage involves 9,180 pair screens, batched into fewer model calls, plus page reads and candidate comparisons. A limited run does not complete the review.

Read `review/report.md`; `report.json` contains full coverage and evidence. Extraction finishes before pair screening starts. A progress unit is one page, image frame or spreadsheet sheet/chunk, so there can be more units than files. `review/state.json` resumes completed units and comparisons; `review/model-cache` holds prompts, validated responses and CLI logs and remains available after `prepare --refresh` for development tests. Identical prompt, schema, model, reasoning and image bytes reuse a successful response without a new Codex call. Changing any of those inputs requires a new call. Failed, timed-out, unreadable or skipped work cannot pass the final gate. Keep generated review files private with the source documents.

Record an admin decision using the full pair ID from the report:

```console
python -m reconciliation.vision_workflow decide --pair "LEFT_HASH:RIGHT_HASH" --verdict keep_both --reviewer "Admin" --reason "Complementary evidence"
```

Choices are `keep_both`, `keep_left`, and `keep_right`. The last two are permitted only for `same_document` findings and record which original must survive. They do not move or delete files. The admin removes unwanted copies using the report paths. Pending cleanup, missing survivors and contradictory choices block completion. Decisions and changes to decisions are recorded with reviewer, reason and timestamp.

Run the combined completion check:

```console
python -m reconciliation.vision_workflow check
```

Only exit 0 means both passes are complete. Exit 2 means outstanding review/cleanup; exit 1 means error. This combined check recognizes explicitly approved pass-two removals from original pass-one groups. The old pass-one-only checker does not know those later approvals.

Changing source contents or adding documents requires a new `--work` folder and fresh review. Deleting redundant exact copies during pass one does not invalidate prepared inputs. Review output must stay outside the source folder. Source files are never automatically deleted by either script.

## Validation

```console
python -m unittest tests.unit.test_duplicate_workflow tests.unit.test_vision_workflow
python -m scripts.check_codex_connection
```

The first command uses temporary fixtures. The second explicitly tests one synthetic receipt through the live subscription connection; it does not use customer documents.
