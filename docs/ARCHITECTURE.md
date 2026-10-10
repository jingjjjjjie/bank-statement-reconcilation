# Architecture and how to change things

For people and coding agents editing this repository. Read the [contract](../AGENTS.md) first; this page explains
where code lives and how to make common changes without breaking the rest.

## The workflow in one picture

```text
 Get Started            Documents                  Bank statement        Final review / report
 intake/                extraction/                bank/                 matching/
 pick work folder  -->  read files into units -->  parse AmBank PDF -->  retrieve + rank pieces per
 set aside exact        model extracts pieces       validate balances     bank line; human approves
 duplicates             human accepts/edits         export Excel          allocations; export CSV
        \_______________________ core/ (paths, settings, prompts, money, revisions) _____________/
                         model/ (ModelClient interface, codex exec backend, processes, token usage)
```

The dashboard (`src/dashboard/`) is a thin web layer: `api/` validates HTTP input and calls one function in
`dashboard/services/`, which uses `src/reconciliation/`. The Vue frontend lives in `src/dashboard/frontend/src/`.

## Where things live

```text
src/reconciliation/
  core/          paths, settings (resources/review_config.json), prompt loading, money parsing, revision hashes
  model/         client.py (the ModelClient interface), codex.py (codex exec backend), processes, token usage
  intake/        workspace.py (work-folder selection), duplicates.py + exact_report.py (exact copies)
  extraction/
    workflow.py  entry point and CLI: prepare, run, gate (completion checks), report
    sources/     reader.py (file -> units, READERS table), pdf_routing.py (text vs vision per PDF page)
    pipeline/    stages.py (model stages), job_runner.py (parallel jobs), pdf_groups.py, assembly.py
    results/     pieces.py (piece facts), schemas.py (model output), records.py (saved JSON shapes), report, inventory
  bank/          statement.py (AmBank PDF -> master CSV), excel.py + workbook_style.py (styled export)
  matching/      candidate retrieval, ranking, and pure allocation/confidence rules in review_rules.py
src/dashboard/
  app.py, routes.py, api/        web layer
  services/review.py             active project session and workflow readiness
  services/extraction/           Documents + Review results pages
  services/matching/             Final review page
  previews/                      render originals for the browser
  frontend/src/
    features/                    page, controller and CSS grouped by workflow feature
      projects/                  Home, projects and workspace selection
      extraction/                document list, extraction editor and receipt actions
      bank/                      statement extraction
      matching/                  evidence matching
      export/                    report and export dialogs
      duplicates/, settings/     supporting screens
    components/                  shared navigation, help and progress
    styles/                      base, layout, fonts and theme; index.css sets cascade order
resources/prompts/  editable model instructions and schemas (read fresh on every request)
tests/          unit/ mirrors the code, browser/ is grouped by page, fixtures/ holds shared setup
scripts/        extraction/ and matching/ benchmarks, codex/ maintenance
docs/           current guides; archive/ contains historical audits and experiments
```

## Local development

Run `python -m pip install -e .` before invoking Python modules or tests on the host.
Docker sets `PYTHONPATH=/workspace/src:/workspace`; import names remain `dashboard` and `reconciliation`.
Shared settings live in `resources/review_config.json`. Existing saved reviews that name the former
`config/review_config.json` resolve to the new location without rewriting evidence.

## Frontend ownership

Keep page-specific code beside its view in `features/<feature>/`. Shared browser utilities
stay in `src/`; only reusable UI belongs in `components/`. Route URLs do not change when files move.

`styles/index.css` defines the global cascade: base rules, feature layouts, then the shared theme.
Put new shared colours and controls in `theme.css`; do not add another override stylesheet.
Portal and export styles remain loaded with their features.

## Dependency rules

Imports point one way: `core` <- `model` <- step packages (`intake`, `extraction`, `bank`, `matching`) <-
`dashboard/services` <- `dashboard/api`. A lower layer never imports a higher one, and step packages do not reach
into the dashboard. Tests import code and `tests/fixtures/`, never another test module.

## Plug-in points

| To replace or add | Implement | Register it in |
| --- | --- | --- |
| Model backend | `ask(prompt, schema, images) -> dict` (optionally `fork`, `acceptance`, `invalidate`) | pass it to `extraction.workflow.run(..., reviewer)`; see `model/client.py` |
| File type | `reader(path, config, units)` calling `units.add(label, text, image, ...)` | `READERS` at the bottom of `extraction/sources/reader.py` |
| Extraction stage | class with `jobs()`, `apply(result)`, `refill` | the `stages` list in `extraction.workflow.run`; see `extraction/pipeline/stages.py` |
| Report format | `render(index, state, problems, usage) -> str` | `extraction/results/report.py` |

## Recipes

**Change what the model is told.** Edit files in `prompts/` (see [prompts/README.md](../resources/prompts/README.md)).
Document kinds are the `## Kind` headings in `prompts/extraction/document_kinds.md`; they also become the allowed
`piece_type` values. No code change or restart is needed; changed prompts get a new cache key.

**Add a supported file type.** Write a reader in `extraction/sources/reader.py`, add its suffix to `READERS`, and
add a test in `tests/unit/extraction/test_reader.py`. `SUPPORTED_SUFFIXES` updates automatically.

**Tune a limit or threshold.** Fixed rules are named `UPPER_CASE` constants with a `#:` comment at the top of the
module that uses them (for example `MAX_IMAGE_SIDE` in `sources/reader.py`, `NAME_CANDIDATES` in
`matching/retrieval.py`). Change the value there; do not repeat the number elsewhere.

**Add a user setting.** Add the default to `DEFAULTS` and a check to `validate()` in `core/settings.py`, show it
in `src/dashboard/frontend/src/features/settings/Settings.js` and `views/Settings.vue`, and cover it in
`tests/unit/core/test_settings.py`. Settings that change extracted evidence belong in `content_settings()`.

**Add a dashboard action.** Put the logic in a `dashboard/services/...` function, add a thin endpoint in
`dashboard/api/` that validates input and calls it, then call it from the page controller. Follow
[UI guidelines](ui/UI_GUIDELINES.md).

**Swap the model backend.** Implement the `ModelClient` protocol and pass your client where `CodexReviewer` is
created (`dashboard/services/extraction/extraction_runs.py`,
`dashboard/services/matching/piece_match_jobs.py`, `extraction.workflow.main`). Per the contract,
workflow calls use `codex exec` with the ChatGPT login unless the owner decides otherwise.

## Conventions

- **Docstrings:** every module, class and public function has one (PEP 257). Start with a one-line summary of what
  it does; add Google-style `Args:` / `Returns:` / `Raises:` only when the inputs or failures are not obvious.
- **Saved data shapes** are documented once as `TypedDict`s in `extraction/results/records.py`, not repeated in
  docstrings. Model output shapes are JSON Schemas in `prompts/` and `extraction/results/schemas.py`.
- **Constants** at module top; **user-tunable values** in `resources/review_config.json` via Settings; secrets and
  host paths in `.env`.
- **Style:** Ruff formats and lints (`ruff check . && ruff format .`, settings in `pyproject.toml`).
- **Tests:** put a test in the file mirroring the module you changed; name it for the behaviour; reuse
  `tests/fixtures/`. Run `python -m unittest discover -s tests/unit -t .` (about 20 seconds, no model calls).
- **Compatibility:** saved review files outlive code. When removing a field or feature, keep reading old data
  (see how `removal_plan` still honours saved duplicate decisions).
