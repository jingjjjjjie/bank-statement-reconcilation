# Bank statement reconciliation

Python performs extraction, hashing, validation, arithmetic and workflow state. FastAPI serves a Vue 3 frontend from one Docker service. Model reasoning and vision use `codex exec` with the existing ChatGPT subscription login; no API-key backend is used.

## Current workflow

1. **Get Started:** choose a work folder containing `documents/` and `statement/`. Proceed verifies the preview and copies exact SHA duplicate groups to `output/duplicates/`, preserving originals. It opens Documents directly; no duplicate selection is required.
2. **Documents:** run or resume extraction and receipt assembly. Open each document's **Review results**, correct pieces and explicitly accept them. Regenerate document queues a fresh extraction when needed. New dashboard and CLI runs do not run vision duplicate screening or comparison.
3. **Bank statement:** provide the statement year, extract the AmBank statement, validate balances, and optionally export the bank-only Excel workbook.
4. **Final review:** review saved pairing proposals, approve/reject/correct allocations, and inspect unmatched evidence. High/Low confidence is separate from human approval.
5. **Final report:** inspect the saved decisions and export CSV. View evidence opens the statement and approved supporting documents in a popup with page/zoom controls, original downloads, allocations, differences and notes.

**Matching limitation:** Final review and Final report currently use the authorized frozen `duplicated/benchmarks/full-statement-240` snapshot. It must match the active manifest and original bank master. Newly extracted workspaces are not automatically imported into matching. Completion also still reads bank-master matching flags rather than the separate final-review ledger. Do not interpret either page as proof that the entire new-workspace workflow is connected.

Documentation:

- [Workflow and Mermaid diagrams](docs/WORKFLOW.md)
- [Dashboard screens and maintenance](dashboard/README.md)
- [Final comparison rules and open decisions](docs/FINAL_COMPARISON.md)
- [Final report UI checks with synthetic evidence](docs/FINAL_REPORT_UI_REVIEW.md)
- [Earlier live UI audit](docs/UI_REVIEW.md) - historical observations, not current sign-off
- [PDF routing](docs/PDF_ROUTING.md), [bank extraction](docs/BANK.md), [development cache](docs/DEVELOPMENT_CACHE.md), [process cancellation](docs/PROCESS_CANCELLATION.md)

## Docker setup

Copy `.env.example` to `.env`. Set `UPLOADS_PATH` to the host folder containing jobs, and `DOCUMENTS_PATH` if a separate source mount is needed. Both default to the sibling `bank-statement-uploads/` directory.

```text
bank-statement-uploads/
  WorkName/
    statement/
      bank-statement.pdf
    documents/
      supporting files and subfolders
```

Keep exactly one bank-statement PDF directly in `statement/`. Supporting PDFs belong in `documents/`. Create the host folders first and ensure Docker can read and write them.

```console
docker compose build
docker compose run --rm dashboard codex login
docker compose up -d
```

Choose ChatGPT login. Open **http://127.0.0.1:8765**, browse to `/uploads/WorkName`, and click Proceed after checking the input preview. Selecting the folder does not change files; Proceed writes the duplicate report and activates the project.

Compose mounts the repository at `/workspace`, `UPLOADS_PATH` at `/uploads`, and `DOCUMENTS_PATH` at `/documents`. The `codex-home` volume retains login. Review state remains in the repository through the bind mount, while exact-copy outputs are inside the work folder. The mounts are read-write; ordinary work-folder processing preserves inputs. Legacy standalone-folder organization can move copies, so use working copies for that workflow.

Paths in `.env` may be relative to the repository or absolute host paths. Use forward slashes on Windows and quote values containing spaces, for example `UPLOADS_PATH="C:/Shared Files/uploads"`. Keep input folders outside Git and the Docker build context. Files added to an existing mount appear immediately; changing mount settings requires `docker compose up -d dashboard`.

### Builds, restarts and debugging

Docker builds Vue in a separate Node stage and installs it at `/opt/dashboard-frontend`, outside the repository bind mount. One Uvicorn worker serves the API and compiled frontend on port 8765. No separate Node server is needed.

```console
docker compose up -d --build dashboard
docker compose ps
docker compose logs --tail 50 dashboard
```

Rebuild after frontend or image changes. For a routine restart use `docker compose restart dashboard`; stop with `docker compose down`.

The default `development` image includes Python 3.12, Node/npm, Codex, Git, ripgrep, build tools, pytest, debugpy and Python Playwright. Enter it with `docker compose exec dashboard bash`. The `app` user works in `/workspace`; edits reach the host repository. Use `DOCKER_TARGET=runtime` in `.env` for the smaller image. The pinned Codex CLI version is in `.env.example`; change `CODEX_VERSION` deliberately when upgrading.

Browser binaries are optional. After creating a development container, install them if running browser checks there:

```console
docker compose exec --user root dashboard python -m playwright install-deps chromium
docker compose exec dashboard python -m playwright install chromium
```

Repeat browser installation after recreating the container. Existing host Chrome can instead run Windows browser tests.

## Settings and model usage

Settings saves `config/review_config.json`. Saving settings does not start model calls.

- **PDF processing:** Vision is the default. Text + checked vision fallback and Compare text and vision require development mode and pictures. Legacy saved text-only/sparse-page modes remain supported. See [PDF routing](docs/PDF_ROUTING.md) for the actual safeguards.
- **Pictures:** controls model image inputs, including Office images; dashboard previews remain available.
- **Codex:** switching off prevents subsequent calls; use Stop to cancel active calls.
- **Calls per run:** 1-1,000, default 1,000. The CLI uses the saved allowance unless `--max-calls` overrides it. A call is a new model invocation, including started failed/timed-out attempts. Local processing and cache hits do not consume the allowance. Rerun to resume with a fresh allowance.
- **Parallel requests:** 1-8, default 4. Calls share one allowance, and completed responses are checkpointed.
- **Model/reasoning:** defaults to `gpt-5.6-sol` and model-default reasoning. Supported choices come from the installed Codex catalog. All model calls use ChatGPT login and structured output; vision calls attach images.
- **Token usage:** per-attempt records live in project `review/token-usage.jsonl`, with stage/model totals and zero new usage for cache hits. Missing usage is unknown, never estimated. Settings and review reports expose recorded totals; Completion's final totals depend on its older completion gates.
- **Development mode:** optional local shared caches and explicit human-decision replay. See [development cache](docs/DEVELOPMENT_CACHE.md). It never makes human approval automatic.

Changed extraction settings require preparing/refreshing the affected review. Refresh archives metadata and decisions in `review/history/`, retaining assets and successful model caches. Prompt/schema/model/reasoning/image changes affect cache identity. Completed results are not silently recomputed on resume. Regenerating one document refreshes its extraction and assembly and requires fresh acceptance.

## Local Python and CLI

Install Python 3.12+ and `requirements.txt`. Build the frontend using Node 22.12+ before starting the local server:

```console
cd dashboard/frontend
npm ci
npm run build
cd ../..
python -m dashboard.app
```

For a prepared project's extraction workflow, substitute its real manifest and review paths:

```console
python -m reconciliation.vision_workflow prepare --manifest duplicated/projects/PROJECT/duplicate-manifest.json --work duplicated/projects/PROJECT/review
python -m reconciliation.vision_workflow run --work duplicated/projects/PROJECT/review --max-calls 1000
python -m reconciliation.vision_workflow check --work duplicated/projects/PROJECT/review
```

`prepare` performs local preparation. Add `--refresh` to intentionally archive/reprepare existing results. `run` extracts units and assembles multi-unit documents, then stops before vision duplicate comparisons. `--timeout` defaults to 240 seconds per call. `--model` and `--reasoning` override the configured selection. `prepare --config PATH` pins another configuration file.

`check` follows the saved workflow mode: extraction-only runs check source/config consistency, readable units and required assembly; legacy comparison states retain their comparison checks. Exit 0 means that gate passed, 2 means unresolved work, and 1 means error. Extraction readiness is not human receipt acceptance or final bank approval.

### Legacy duplicate tools

Standalone-folder `reconciliation.duplicate_workflow organize` verifies size, SHA-256 and bytes, records original locations, and **moves** groups into `duplicated/` beside the manifest. Legacy dashboard retain/undo controls use recoverable storage. These controls are separate from the automatic copy-only work-folder flow. Do not blindly rerun an interrupted organization or overwrite its manifest.

Historical screening/comparison code, prompts and decisions remain for compatibility and audit. `vision_workflow decide` can record a verdict on an existing comparison, but normal dashboard/CLI runs no longer create those comparisons. Model output never authorizes file deletion. Original locations remain in manifests and extraction inventory exports.

## Source map and checks

- `reconciliation/`: readers, model integration, workflow state and deterministic matching checks.
- `dashboard/`: FastAPI APIs, background workers and Vue frontend.
- `prompts/`: editable model instructions and deterministic workbook style.
- `tests/unit/`, `tests/browser/`: offline regression and synthetic browser fixtures.
- `scripts/`: benchmarks, matching experiments and the live connection check.
- `docs/`, `config/`, `docker/`: documentation, saved settings and image definition.

```console
python -m unittest discover -s tests/unit -t .
python -m unittest tests.browser.test_matching_review tests.browser.test_final_report
```

Browser checks additionally require `dashboard/requirements-dev.txt`, built frontend assets, and Chrome/Chromium. See [test instructions](tests/README.md). Tests use isolated fixtures without model calls. `python -m scripts.check_codex_connection` is a separate explicit live subscription check using one synthetic receipt.
