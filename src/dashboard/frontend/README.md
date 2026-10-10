# Dashboard frontend

Vue 3 and Vue Router provide a shared layout and navigation without full page reloads. Vite compiles the application; FastAPI serves the result. Docker performs the build automatically for both image targets.

Navigation retains cached screens within the active review. Proceed on the same workspace preserves its session and unsaved edits; activating a different workspace requires confirmation when edits are pending and resets the cached views. Controllers refresh after changes to the data they display, rather than after unrelated actions. The final report checks the saved ledger on return while keeping existing rows and filters visible. Evidence page, zoom, and scroll preferences are retained within that review; saved decisions remain server-owned.

## Small source structure

- `src/App.vue` and `components/`: shared layout, navigation, progress, and notifications.
- `src/router.js`: known routes, lazy view imports, and browser history.
- `src/features/`: each feature owns its Vue pages, controllers and page styles. Extraction actions live in `features/extraction/receipts.js`; export dialogs live in `features/export/`.
- `src/components/`: shared navigation, help and progress controls.
- `src/page.js`: lifecycle, polling, request cancellation and unsaved-edit protection.
- `src/api.js`: sessions and API requests. Evidence and approvals remain on the server.
- `src/office.js`: shared original-document rendering.
- `src/styles/index.css`: shared cascade entry point; `theme.css` owns the application theme.

Use Vue bindings for new UI. Existing controllers receive a `page` object instead of using global state or document-wide selectors. Keep selectors scoped through `page.$` or `page.root`. Register polling with `page.pollVisible`, observers with `page.observe`, and unsaved edits with `page.dirty` so leaving or evicting a view cleans up correctly. Do not introduce a second API or business-rule implementation in JavaScript.

Views stay mounted in a bounded `KeepAlive` cache while navigating, retaining inputs, selected evidence, and internal scroll positions. Polling pauses on inactive pages and hidden browser tabs. Switching workspaces clears cached views. API writes carry the workspace session ID, and the server rejects writes from stale tabs. Unsaved settings and extraction edits are protected on reload and workspace changes. These display caches never replace fresh evidence or revision checks before a decision.

## Build and run

The normal workflow, from the repository root:

```console
docker compose up -d --build dashboard
```

For local development with Node 22.12+ and Python requirements installed:

```console
cd src/dashboard/frontend
npm ci
npm run build
cd ../..
python -m dashboard.app
```

The build produces content-hashed assets under `dist/`. Commit source files and `package-lock.json`; generated output and `node_modules/` are ignored. Rebuild after frontend edits. The Docker build installs the compiled output at `/opt/dashboard-frontend`, outside the repository bind mount. `DASHBOARD_FRONTEND` can select another build directory for deployment or tests.

## Checks

```console
python -m unittest discover -s tests/unit -t .
python -m unittest discover -s tests/browser -t .
```

Browser checks require `src/dashboard/requirements-dev.txt` and installed Chrome on Windows or Playwright Chromium on Linux. They use temporary fixtures and make no model calls. Navigation checks assert that page switches retain actual DOM instances, preserve unsaved edits, support browser history, and suspend hidden-page polling.

Final report refreshes ledger data when activated, closes its popup when deactivated, and preserves filters during popup dismissal. Keep confidence, human decisions and Supporting / No supporting status distinct. No frontend code may approve evidence or recompute server allocation rules.

The active workspace shows Resume workspace. It returns to the last visited page in the current browser session without calling preview or start again. A fresh page load defaults to Documents; changing workspaces resets the return page.
