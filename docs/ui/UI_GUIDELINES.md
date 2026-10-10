# Dashboard UI rules

- Home at /home contains Accounting and Finance with the Bank Statement Reconciliation card, followed by Others with a full Coming soon card. Do not add a separate department-selection page. The header shows Accounting Copilot with Home on the landing page, and Bank Statement Reconciliation on /projects and inside the app; never use the workspace folder name there. Home has no question-mark help icon. Keep its previous light-grey background and blue icon styling. Use one Back to Home button without an underline instead of Home/Projects text links. New project opens the workspace picker as a popup; Resume opens existing projects directly.

User preference, recorded 2026-09-18:

- Keep copy functional and concise. Remove decorative subtitles, repeated labels,
  and explanations that duplicate a title or control.
- Put page instructions in one small, tightly fitted circled question mark raised like a superscript beside the title, styled like a copyright symbol with a thin outline and no fill.
  Show help on hover, keyboard focus, or tap; support Escape to dismiss it.
- Keep field labels, values, progress, validation errors and review warnings visible.
- Keep the horizontal header navigation bar. This is the single navigation area;
  do not replace it with a dropdown or repeat its links elsewhere on the page.
  Workspace selection still uses Proceed / Resume workspace to activate the job.
- Put numbered circles and completion ticks directly beside their header links.
  Do not add a separate workflow status row beneath the header.
- Align header navigation to the right. Keep Settings as a separate gear icon at
  the far right, visible even when the navigation links scroll on narrow screens.
- Verify page help and navigation with Playwright, including narrow screens.
- Step 2 shows the current filename without a dropdown. Use ten numbered squares
  at a time to select documents, blue for reviewed and an outline for the current
  document; arrows move between groups of ten.
- Extraction review offers Discard and Undo discard. Trash is
  an audited, reversible classification that excludes supporting evidence; it never
  deletes or moves original files. Trash squares have a distinct muted brown shade.

Shared help content: `src/dashboard/frontend/src/pageHelp.js`.
Shared help control: `src/dashboard/frontend/src/components/PageHelp.vue`.

- Accounting Copilot uses the Career Copilot wordmark style: locally hosted Syne
  800, 17px desktop text, tight letter spacing and the same blue-to-teal gradient.
  Bank Reconciliation remains the application descriptor. Use DM Sans for the UI,
  white cards, cool grey surfaces and blue primary controls. Keep rainbow suggestions
  and meaningful green completion/balanced states. Keep the selected-page underline
  close to its label, and allow room around the wordmark so glyphs do not clip.
- Export and evidence dialogs use the same white/blue palette, including workbook
  and ZIP download controls. Low-confidence suggestions use pale blue; high-confidence
  rainbows remain. Green is reserved for status markers and balanced totals. Keep
  the UPVANTAGE logo background blended into the header and Bank Reconciliation
  moderately bold (600).
- Completed header navigation ticks use blue circles, matching the selected-page
  indicator. The UPVANTAGE logo is slightly larger (164x66 on desktop), with
  responsive sizing that keeps the wordmark and Settings separate.
- Document-folder download buttons use solid blue backgrounds and white text.
  Final report omits the divider beneath its heading and keeps a compact gap
  above transaction totals.
- Matching on desktop viewports up to 820px tall uses compact outer spacing and
  a scrollable review pane. Keep full selected cards reachable and confirmation
  actions fixed; do not reduce text size to fit a scaled display.
- Matching supports a draggable, keyboard-accessible panel split on desktop,
  saved locally as a display preference. Double-click or Home restores 50/50.
  Highlight the previewed candidate with a blue outline while preserving rainbows.
  Put compact 34px Confirm/Save, Reject and Next buttons, at most 140px wide and
  right-aligned, below the right evidence
  preview, after page/zoom controls. Confirmed and Rejected states offer Undo within
  their existing buttons; edits return confirmation to Save changes. Do not reserve
  a second footer row. Save feedback must not cover the controls.

- Step 2 displays all pieces together as editable rows. Keep payee, payer, amount, currency, date and document number visible; put type, other names, references and Amount at (with Show, which jumps the preview to that page or sheet rows) under Details. Fields from older extractions appear only when they hold a value. Selecting a row targets Remove; Merge all combines every entry in the current document into one editable draft; Split is not offered. Narrow screens wrap the fields and place save actions after the rows without overlap.

- Pieces represent separate receipts or payees, not purchase lines. Show editable payee, payer, amount, currency, date and document number together; keep type, other names, references and amount location in the piece disclosure. Add entry and Remove are explicit edits; existing identities are preserved.

- Review results uses one compact toolbar for entry count, Add entry and Remove. The highlighted row indicates selection; do not add separate heading or selection bars. Keep Accept / Accepted · Undo, Discard / Discarded · Undo and Next in the footer. Keep the title visible on narrow screens.

- Review results combines title, filename, document numbers, progress and actions in one horizontal bar; scroll the bar on narrow screens. Do not show entry search.

- Show review status as an accessible icon beside the filename. Acceptance belongs there, while warnings stay visible. Accept and Discard advance to the next document after a successful save; Undo stays on the current document; the last document stays open; Use exactly three footer buttons in order: Accept / Accepted · Undo, Discard / Discarded · Undo, Next. Labels toggle with the current status. Discard is red. After editing an accepted document, its button returns to Accept to save those changes. Next navigates independently, with unsaved-edit protection.

- The original preview has no heading bar. Keep Download original as a labelled icon alongside the page and zoom controls.

- Keep review action buttons visible and grey out unavailable actions. Footer buttons are compact, equal-width and right-aligned, including on narrow screens.

- Accept and Discard switch directly between the two statuses; Undo is optional. Accepting a discarded document preserves its saved entries.

- Extraction entries show Pay to, Pay from, Short description, Amount, a currency selector (MYR/USD/CNY, preserving other existing values), and Document no. Date remains in Details. Document total sums the displayed entries separately by currency and marks incomplete amounts.

- Review results omits the document-summary/page list and per-page relevance prose. Keep pending/error/review warnings visible; source details remain in Details and the original page selector.

- Review results labels forward actions Accept & next and Discard & next when another document follows. Failed saves preserve the current document and edits.

- Review results uses a compact header with secondary actions (Reload results, Export reviews, Accept all) in Options. Entry cards use readable 14px values, a clear selection marker, more width for the short description and a shorter document-number field. Keep document total, Add entry and Remove together in one compact toolbar; wrap fields on narrow screens.

- All documents shows original folder names and icons in an always-visible hierarchy without expand/collapse controls. Show exact-copy locations as grey rows labelled Exact duplicate, and approved duplicate documents as grey rows labelled Approved duplicate. Search matches folder names as well as filenames. File counts include copies; extraction progress continues to count unique documents.

- Final review selected cards keep Use as and Allocation collapsed under Edit allocation until opened. Show stays visible at the bottom-right of every candidate card. Supporting only saves an empty allocation, never zero. Changing role updates totals immediately but requires Confirm / Save; missing monetary facts cannot be assigned a money role.

- Final review allocation summaries use a green gradient for valid amounts that equal the bank payment; differences or invalid amounts remain red. Green indicates balanced amounts, not saved approval.

- Final review candidate actions use Show to open original evidence. Omit Use only this; selection changes through checkboxes and Remove.

- Review Extraction and Review Matching are the visible review-page names. Documents ticks after saved extraction completes; review ticks require current saved decisions. Reviewed matching transaction boxes are blue in both confidence filters.
- Export is the fifth navigation destination combining the final report and downloads. One Export button above the report opens the workbook choices and document ZIPs. Keep one page-help circle. The former /complete route redirects to /final-report.
- Disable Review Extraction until extraction results exist; disable Review Matching until document and bank extraction finish. Disabled navigation explains the prerequisite, and direct routes enforce the same readiness checks. Original-file downloads remain accessible from Export.

- Dashboard display reads use shared workspace snapshots and a single live event stream. Keep the current view visible while Updating... is shown in the header. Live updates must preserve unsaved drafts, and saved/confirmed states still require successful backend validation. Disconnects fall back to ordinary progress requests.

- Review Matching starts Available candidates collapsed; click or keyboard activation
  expands its search button and candidate list. Keep the toolbar flush with the top
  of the workspace, and offer 50% and 75% original-preview zoom.

- Candidate Search sits at the right of the Available candidates heading. It opens
  the disclosure and shows a wide search field with Reset directly below the heading.
  Matching save announcements are accessible but do not add a visible timestamp row
  beneath the buttons.

- Both review pages put three compact 34px actions below the right original preview,
  right-aligned and at most 140px wide. Reject/Rejected and Discard/Discarded use
  solid red with white text, including saved Undo states. Extraction Accepted and
  Discarded states offer Undo inside their existing buttons; no extra footer row.

- Unify both review footers as Accept, Reject, Next. Saved decisions read
  Accepted / Rejected with Undo in the same button; edited accepted drafts show
  Save changes. Use shared reviewActionLabels.js copy. Keep partial-support warnings
  in the allocation summary and explain different rejection effects in page help.
  These labels do not change validation, automatic advance or trash semantics.

- Original preview controls and review actions share one bottom toolbar on panels
  at least 700px wide; narrower panels wrap the actions into a second compact row.
  Put Download beside Show document on matching candidate cards only. Extraction
  entry cards use Show and Remove without Download. No
  download control belongs in the bottom toolbar. Bank download sits beside the
  source selector; extraction keeps a document-level fallback in its entry toolbar.
  Downloads preserve validated original bytes and source filenames.

- Extraction entry cards show Show and Remove only. Right-align the document total
  and Add entry / Reset / Merge all / Remove toolbar group, including wrapped rows.

- Omit Workspace from the application header. Back to Home retains access to project selection. Number visible workflow destinations Documents 1, Review Extraction 2, Bank statement 3, Review Matching 4 and Export 5.

- Export evidence uses a compact payment/document sidebar beside a full-height original preview. Keep Download evidence in the dialog header, document page/zoom controls below the preview, and saved differences/flags visible in the sidebar. Group entries sharing an original into one document choice; one original downloads directly, multiple unique originals download as a ZIP.
