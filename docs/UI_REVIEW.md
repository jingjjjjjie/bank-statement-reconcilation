# UI review — 18 September 2026

This is the earlier live-workspace audit captured before document regeneration and the final report. Findings describe that capture, not the latest UI; they have not all been rechecked. The subsequent [final report audit](FINAL_REPORT_UI_REVIEW.md) uses synthetic evidence and does not resolve the real-workspace matching import limitation.

## Verdict

The simplified document list is clearer, but the live workflow is **not ready for an end-to-end sign-off**. The highest-priority issues are unavailable matching data and blank or slow result-loading states. This audit itself made no implementation changes; later work must be evaluated separately.

Scope: current Docker app at `localhost:8765`, desktop 1440 × 1000 and mobile 390 × 844, using local Chrome through Playwright with user permission. All screenshots were captured and inspected during this audit. No extraction calls, approvals, file changes, or exports were triggered. The active workspace has 115 queued documents and no completed extraction units, which limits what could be reviewed in the results editor.

Screenshot evidence is kept locally in `.tools/ui-audit-2026-09-18/` and excluded from Git because it can contain private workspace filenames. The image links below work in the local checkout; screenshots are not published with this report.

## Flow review

| Step | Screen and health | Evidence and finding |
| --- | --- | --- |
| 1 | Get Started — good | Both input folders and file counts are clearly identified. Proceed is visually prominent. Secondary path entry stays collapsed. |
| 2 | Documents — good hierarchy, confusing readiness | Three summary cards and the three-column list are easy to scan. All documents are Queued, but each has Review results and the page tells the user to open results. The zero-progress stage says Paused without explaining whether work has ever started. |
| 3 | Per-document results — blocked in this run | The desktop and mobile editor stayed blank during the capture window, including a 30-second wait in the initial attempt. The selector shows 0 / 0, yet Split, Remove, Add piece, and Accept & next remain visually available. No clear loading, empty-state explanation, or retry guidance fills the main panel. |
| 4 | Bank — incomplete state, needs recovery guidance | The captured screen says no prepared statement exists. It does not show an extraction action or source-selection action in this state. Network idle was not reached, so this is evidence of a problematic observed state, not proof that extraction controls never appear. |
| 5 | Final review — blocked | A settled error state exposes a missing `full-statement-240/index.json` filesystem path. The transaction area is empty while Export CSV is still visible. There is no user-facing explanation of how to make matching available. |
| 6 | Completion — partial | The screen correctly lists extraction and bank matching as pending and hides final token totals. It gives no direct action for each pending check. Shared navigation did not fully settle during capture. |
| 7 | Mobile document list — partial | No page-level horizontal overflow at 390 px. Navigation wraps to multiple rows; the actual document list begins below the initial viewport. The captured request was still loading, so populated mobile rows were not signed off in this run. |
| 8 | Mobile results — blocked | No horizontal overflow, but the result-review title is absent and a large blank preview dominates the screen. The empty editor still exposes acceptance controls. |

## Priority findings

### P1 — Explain and resolve missing matching data

**Evidence:** Step 5. The current workspace cannot load the frozen matching snapshot because its required index is absent. The code also requires the snapshot to belong to the active manifest and original bank master.

**Recommendation:** Show a specific readiness screen: “Matching results are not available for this workspace.” Explain the required import/preparation step, offer Back to Documents / Bank, and hide or disable export until data is usable. Implement the new-workspace matching import before describing the workflow as end to end. Do not copy another workspace's decisions into this one.

### P1 — Make pending and empty result states safe and understandable

**Evidence:** Steps 2–3 and 8. Results links are offered for queued documents; the opened editor remains blank with action controls visible.

**Recommendation:** Keep the original available, but show “Extraction has not produced results for this document yet” with Back to Documents. Disable edit/accept controls until a valid selected result is loaded. Show a visible loading status, bounded error feedback, and retry action for delayed or failed requests. Do not infer result readiness merely from the existence of a prepared document.

### P1 — Investigate slow data loading on the real workspace

**Evidence:** Initial Get Started and Documents captures populated successfully. Later receipt, bank, completion, and mobile captures did not reach network idle within their capture windows; results remained blank. The session endpoint still returned HTTP 200 in approximately 0.06 seconds. No browser JavaScript exceptions were recorded in these captures.

**Recommendation:** Measure request durations for `/api/receipts`, `/api/document-status`, `/api/workflow-checks`, and their file/hash work. Check contention around the serialized workflow context. Avoid repeatedly scanning unchanged evidence for display metadata where a correctly invalidated cache can be used. Add request-level loading/error states. The root cause was not established in this audit; network-idle timeout alone is not a performance benchmark.

### P2 — Make stage readiness and navigation consistent

**Evidence:** Steps 2, 4, and 6. “Paused” appears at zero completed units; Documents uses both “Document status” and “Review results”; Completion lists pending checks without a direct next action. Code inspection confirms Bank's “Document review” header points to the old exact-report route.

**Recommendation:** Use Not started / Running / Paused / Finished according to actual execution history. Label the journey consistently: Get Started → Documents → Review results → Bank → Final review. Give every blocked stage a direct next action, and point document links to `/documents`.

### P2 — Tighten mobile orientation and accessibility

**Evidence:** Steps 7–8. Mobile navigation occupies several rows, review-page context is hidden, and previous/next controls are compact. Muted helper text is visually small on desktop and mobile.

**Recommendation:** Preserve a short “Review results” heading on mobile, group secondary navigation, verify minimum target sizes, and measure text contrast. Test keyboard order, visible focus, labelled progress announcements, and screen-reader output on actual loaded and failed states. No full WCAG compliance claim is made from these screenshots.

## Screenshots in flow order

### 1. Get Started — accepted populated capture

![Get Started showing detected inputs](../.tools/ui-audit-2026-09-18/01-get-started.png)

### 2. Documents — accepted populated capture

![Documents with queued files and review links](../.tools/ui-audit-2026-09-18/02-documents.png)

### 3. Review results — blocker evidence, not a completed-results capture

![Blank results editor during delayed loading](../.tools/ui-audit-2026-09-18/03-review-results.png)

### 4. Bank — observed incomplete state

![Bank screen without an available preparation action in the captured state](../.tools/ui-audit-2026-09-18/04-bank.png)

### 5. Final review — accepted settled error capture

![Final review reports a missing matching snapshot](../.tools/ui-audit-2026-09-18/05-final-review.png)

### 6. Completion — visible pending checks; shared loading unresolved

![Completion with pending extraction and matching](../.tools/ui-audit-2026-09-18/06-completion.png)

### 7. Mobile Documents — loading blocker evidence

![Mobile document screen during loading](../.tools/ui-audit-2026-09-18/07-documents-mobile.png)

### 8. Mobile results — empty/loading blocker evidence

![Mobile results editor without loaded evidence](../.tools/ui-audit-2026-09-18/08-results-mobile.png)

## Limits and follow-up acceptance

- This pass did not validate populated live receipt editing, real extraction progress animation, successful bank extraction, allocation approval, or export; the current inputs and loading/matching blockers prevented a full journey. Earlier fixture tests are not used as audit evidence here.
- The audit began at committed revision `14659d1`. Other application edits appeared concurrently before handoff; they were not changed or included in this documentation commit. Findings describe the captured run and should be rechecked against the next completed build.
- No approvals or model calls were made solely to populate screenshots.
- Backend integration findings are distinguished from visual findings. See [the detailed workflow](WORKFLOW.md) for the frozen-snapshot matching boundary and the separate completion-check limitation.
- After fixes, repeat Step 2 with a queued file, an extracted single-page receipt, a multi-page assembled receipt, a stale approval, and a failed extraction. Check desktop/mobile and keyboard navigation.
- Repeat Bank and Final review using this workspace's own validated evidence. Confirm import readiness, approval/undo persistence, remaining amounts, and export availability before signing off the complete journey.
