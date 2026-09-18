# Tests

Run from the repository root with the project requirements installed:

```console
python -m unittest discover -s tests/unit -t .
```

`unit/` contains offline extraction, workflow, and local HTTP tests. `helpers.py` provides mocked Codex processes; these tests do not need a live model connection.

`test_process_manager` and `test_codex_cancellation` also launch real local Python
processes and children to verify Stop, timeouts, launch races, and cancellation
audit records. Run them on Windows and Linux; neither makes live Codex calls.
See [process cancellation](../docs/PROCESS_CANCELLATION.md) for the guarantees.

`browser/` contains optional Playwright checks. Install `dashboard/requirements-dev.txt` first, then run individual modules, for example:

```console
python -m unittest tests.browser.test_office_preview
```

Some browser checks run through `main()` rather than unittest; invoke those with `python -m tests.browser.test_source_browser`. The settings and keep/undo smoke test runs with `python -m tests.browser.test_browser` against temporary fixtures.

## Final review and report

Build the frontend first. Windows browser tests use installed Chrome; Linux uses Playwright Chromium. These checks exercise temporary ledgers and synthetic originals without model calls:

```console
python -m unittest tests.unit.test_matching_review tests.browser.test_matching_review tests.browser.test_final_report
```

The report checks cover approved/pending/rejected evidence, page selection, zoom, original/CSV downloads, modal keyboard focus, filter retention, mobile layout, changed originals and missing snapshots. Set `FINAL_REPORT_SCREENSHOTS` to an output directory to capture the synthetic desktop/mobile flow. See [the captured UI review](../docs/FINAL_REPORT_UI_REVIEW.md). Private live-workspace audit screenshots remain excluded from Git.
