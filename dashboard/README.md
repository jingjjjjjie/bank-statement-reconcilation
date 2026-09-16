# Local review dashboard

From Development:

```console
.tools\python\python.exe dashboard/app.py
```

Open http://127.0.0.1:8765. The Python server, HTML, CSS and JavaScript all live in `dashboard/`.

- Browse/search groups and compare image, PDF, spreadsheet or Word previews.
- Expand **Original location** to see where each copy came from.
- **Keep this copy** leaves it in `Development/duplicated/group-NNN` and moves the others into `dashboard/.data/recovery`. No permanent deletion occurs.
- **Undo choice** returns the archived copies. Choices persist across server restarts.
- **Validate & continue** checks all groups using the existing exact-duplicate checker. It shows readiness for pass two but does not start Codex or consume subscription usage.
- **Settings** opens the separate page at http://127.0.0.1:8765/settings. It saves PDF mode, pictures on/off, Codex on/off, request limit, model and reasoning to `Development/review_config.json`. The request-limit section explains exactly what counts, when the run pauses, how to resume and when changes apply. Model/effort options come from the installed Codex catalog. Saving does not start model calls. Changed extraction settings display a refresh instruction; disabled inputs remain unresolved in pass two.

Do not delete `.data`: it holds recovery copies and the decision history. Recovery is outside both scanned document folders, so archived copies do not interfere with the one-file-per-group check. Changed files, unexpected files and interrupted actions block further changes for that group.

Model and reasoning controls are separate for PDF reading, JPG/images, Excel, Word, and document comparison. JPG/images use vision only for now. Comparison settings cover both summary screening and original-document comparisons, including mixed file types. All stages share one request allowance. Existing shared settings remain the fallback until stage selections are saved. Command-line `--model` or `--reasoning` overrides that field for every stage in that run. Changing a stage's model or effort after review work has started requires `prepare --refresh`; previous metadata is archived.

The server listens only on loopback. Optional flags: `--port 8766`, `--manifest path`, `--data path`. Stop with Ctrl+C if started in a terminal.

Tests:

```console
.tools\python\python.exe -m unittest dashboard.test_app
```
