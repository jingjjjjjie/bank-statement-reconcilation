# Accounting Copilot UI verification

Verified 2026-10-10 against the saved Career Copilot reference and the running
dashboard at http://127.0.0.1:8765.

## Result

The desktop wordmark matches the reference's computed font family (Syne), size
(17px), weight (800), letter spacing (-0.34px), text clipping and exact OKLCH
blue-to-teal gradient. Accounting Copilot is longer wording; narrow screens use
14px or 13px text to keep Settings visible. Padding and line height protect glyph
edges. Navigation links retain a 44px hit target with a closer blue underline.

The UPVANTAGE logo, locally hosted fonts, blue controls, white cards and cool grey
evidence surfaces are installed. Rainbow suggestions, reduced-motion support,
green completion markers, balanced totals, warnings and trash colours are preserved.
No extraction prompt, approval semantics or matching ledger changes are included.

## Checks

- Windows Vite production build: passed (`npm.cmd run build --prefix dashboard/frontend`).
- Live Playwright sweep: passed all 28 combinations of seven routes (Workspace,
  Documents, Review Extraction, Bank statement, Review Matching, Export and
  Settings) at widths 1440, 1024, 390 and 320.
- Each route retained one navigation area and one help control. Help opened,
  stayed within the viewport and closed with Escape. No horizontal page overflow
  or brand/Settings overlap was detected.
- Extraction entries and original image loaded; Options opened; preview zoom
  switched to 150% and back. The live sweep made no mutating requests and reported
  no browser console errors.
- `tests.browser.shell.test_accounting_theme`: passed. Uses isolated fixture data
  to check typography, logo, responsive navigation, help, rainbow gradients and
  reduced motion; it makes no model calls.
- `tests.browser.final_review.test_final_report`: passed (three tests).
- Matching review/report/theme run: six of seven tests passed. The candidate-save
  test rejects an additional background `/api/matching` refresh. The same failure
  was reproduced using the pre-theme frontend build with the current backend.
- Existing page-help/navigation suite: three failures around Settings fixture
  loading, reproduced with the pre-theme frontend build. The live seven-route
  help/navigation sweep and new isolated theme test passed.
- Existing extraction regeneration and Accept-next tests fail on older UI
  expectations (`#supporting-evidence` and `Accept` versus `Accept & next`).
  Both failures were also reproduced with the pre-theme frontend. These are
  recorded as unresolved suite failures, not passing checks. Results describe
  the test revisions exercised; concurrent workflow/test edits are outside this
  UI change.
- `git diff --check`: passed.

## Visual review and artifacts

Reviewed desktop and mobile extraction screenshots and the matching fixture
screenshots. The title style matches the reference; the wider wording and smaller
mobile size are intentional. The approved static preview screenshots were refreshed.

Local inspection artifacts are under `duplicated/inspection/accounting-copilot/`:
`checks.json`, `title-comparison.json`, route screenshots, matching fixture
screenshots and cropped reference/application wordmarks. They are ignored local
artifacts because live screenshots contain customer evidence. The committed static
preview under `docs/ui/previews/reconassist/` contains sample data only.
