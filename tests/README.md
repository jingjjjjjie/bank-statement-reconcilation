# Tests

Run from the repository root with the project requirements installed:

```console
python -m unittest discover -s tests/unit -t .
```

`unit/` contains offline extraction, workflow, and local HTTP tests. `helpers.py` provides mocked Codex processes; these tests do not need a live model connection.

`browser/` contains optional Playwright checks. Install `dashboard/requirements-dev.txt` first, then run individual modules, for example:

```console
python -m unittest tests.browser.test_office_preview
```

Some browser checks run through `main()` rather than unittest; invoke those with `python -m tests.browser.test_source_browser`. The settings and keep/undo smoke test runs with `python -m tests.browser.test_browser` against temporary fixtures.
