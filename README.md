# ?? Bank Statement Reconciliation

A local app for checking bank transactions against receipts, invoices and supporting documents. Extract data, review it beside the originals, approve matches and export the results.

Built with Python, FastAPI and Vue 3. AI extraction and matching use Codex through your ChatGPT subscription login.

## ?? TODO

Currently hard-coded; open source soon!

- Remove project-specific assumptions.
- Make setup reusable across workspaces.
- Prepare a clean public release.

## ?? Quick start

Requires Docker with Docker Compose and a ChatGPT account with Codex access.

1. Copy `.env.example` to `.env`.
2. Set `UPLOADS_PATH` to your jobs folder. Use forward slashes for Windows paths.
3. Create a project folder with exactly one bank-statement PDF in `statement/` and supporting files in `documents/`:

```text
bank-statement-uploads/
  MyProject/
    statement/
      bank-statement.pdf
    documents/
      invoice.pdf
      receipts/
```

The default jobs folder is `../bank-statement-uploads`, beside this repository. Keep input files outside the repository.

```console
docker compose build
docker compose run --rm dashboard codex login
docker compose up -d
```

Choose ChatGPT login. Open [localhost:8765](http://localhost:8765), select **Bank Statement Reconciliation**, then **New project**. Choose `/uploads/MyProject` and proceed. Use **Resume** to reopen saved work.

## ?? Workflow

1. **Extract documents.** Run supporting files, compare results with the originals and correct or accept entries.
2. **Extract the bank statement.** Enter its year and check transactions and balances. Bank extraction currently targets AmBank statements.
3. **Generate matches.** On the bank page, select **Load for final matching**, then **Generate matches**.
4. **Review matching.** Inspect proposed evidence and amounts, then accept or reject. AI suggestions require your review.
5. **Export.** Review saved results and download workbooks or document ZIPs.

Exact duplicates are detected automatically; originals stay intact. Extraction progress and review decisions are saved. Source changes require rechecking affected evidence.

## Run and update

```console
# Rebuild after code changes
docker compose up -d --build dashboard

# View logs
docker compose logs --tail 50 dashboard

# Stop the app
docker compose down
```

The app is localhost-only by default. The `codex-home` volume retains your login; project review data persists through the repository mount. Do not delete these when updating.

## Development

Python owns extraction, validation and workflow state. The Vue frontend lives in `dashboard/frontend/`.

```console
docker compose exec dashboard python -m unittest discover -s tests/unit -t .
```

See [test instructions](tests/README.md) for browser checks and [architecture](docs/ARCHITECTURE.md) for the code layout.

## ?? Documentation

- [Documentation index](docs/README.md)
- [Workflow](docs/workflow/WORKFLOW.md)
- [Matching and review rules](docs/workflow/FINAL_COMPARISON.md)
- [PDF processing](docs/workflow/PDF_ROUTING.md)
- [Live dashboard updates](docs/workflow/LIVE_DISPLAY.md)
- [Token usage](docs/operations/TOKEN_ACCOUNTING.md)
