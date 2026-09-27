# Tests

Run from the repository root with the project requirements installed:

```console
python -m unittest discover -s tests/unit -t .
```

None of these tests call a live model.

## Layout

- `unit/<package>/test_<module>.py` mirrors the code: `unit/extraction/test_workflow.py` tests
  `reconciliation/extraction/workflow.py`; `unit/dashboard/` covers `dashboard/services`, `previews` and the API;
  `unit/scripts/` covers `scripts/`.
- `fixtures/` holds shared setUp code: fake model clients and a prepared review folder (`workflow.py`), and one module
  per area (`receipt_review.py`, `final_review.py`, ...). Reuse a fixture by subclassing it, or instantiate it and call
  `setUp()` inside another test. **Never import one test module from another**; move shared code into `fixtures/`.
- `browser/` holds Playwright checks against a real local server.

To add a test, put it in the file mirroring the module you changed. Name it for the behaviour
(`test_budget_stop_keeps_review_incomplete`), give it a one-line docstring, and prefer the existing fixtures over new
temporary folders.

`model/test_process_manager` and `model/test_codex_cancellation` also launch real local Python
processes and children to verify Stop, timeouts, launch races, and cancellation
audit records. Run them on Windows and Linux; neither makes live Codex calls.
See [process cancellation](../docs/operations/PROCESS_CANCELLATION.md) for the guarantees.

`browser/` contains optional Playwright checks. Install `dashboard/requirements-dev.txt` first, then run individual modules, for example:

```console
python -m unittest tests.browser.workspace.test_office_preview
```

Some browser checks run through `main()` rather than unittest; invoke those with `python -m tests.browser.workspace.test_source_browser`. The settings and keep/undo smoke test runs with `python -m tests.browser.shell.test_browser` against temporary fixtures.

## Final review and report

Build the frontend first. Windows browser tests use installed Chrome; Linux uses Playwright Chromium. These checks exercise temporary ledgers and synthetic originals without model calls:

```console
python -m unittest tests.unit.dashboard.matching.test_final_review tests.browser.final_review.test_matching_review tests.browser.final_review.test_final_report
```

The report checks cover approved/pending/rejected evidence, page selection, zoom, original/CSV downloads, modal keyboard focus, filter retention, mobile layout, changed originals and missing snapshots. Set `FINAL_REPORT_SCREENSHOTS` to an output directory to capture the synthetic desktop/mobile flow. See [the captured UI review](../docs/ui/FINAL_REPORT_UI_REVIEW.md). Private live-workspace audit screenshots remain excluded from Git.
