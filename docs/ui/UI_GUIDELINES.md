# Dashboard UI rules

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
  at a time to select documents, green for reviewed and an outline for the current
  document; arrows move between groups of ten.
- Extraction review offers Discard and Undo discard. Trash is
  an audited, reversible classification that excludes supporting evidence; it never
  deletes or moves original files. Trash squares have a distinct muted brown shade.

Shared help content: `dashboard/frontend/src/pageHelp.js`.
Shared help control: `dashboard/frontend/src/components/PageHelp.vue`.

- Step 2 displays all pieces together as editable rows. Keep payee, payer, amount, currency, date and document number visible; put type, other names, references and Amount at (with Show, which jumps the preview to that page or sheet rows) under Details. Fields from older extractions appear only when they hold a value. Selecting a row targets Remove; Merge all combines every entry in the current document into one editable draft; Split is not offered. Narrow screens wrap the fields and place save actions after the rows without overlap.

- Pieces represent separate receipts or payees, not purchase lines. Show editable payee, payer, amount, currency, date and document number together; keep type, other names, references and amount location in the piece disclosure. Add entry and Remove are explicit edits; existing identities are preserved.

- Review results uses one compact toolbar for entry count, Add entry and Remove. The highlighted row indicates selection; do not add separate heading or selection bars. Keep Accept / Undo accept, Discard / Undo discard and Next in the footer. Keep the title visible on narrow screens.

- Review results combines title, filename, document numbers, progress and actions in one horizontal bar; scroll the bar on narrow screens. Do not show entry search.

- Show review status as an accessible icon beside the filename. Acceptance belongs there, while warnings stay visible. Accept and Discard advance to the next document after a successful save; Undo stays on the current document; the last document stays open; Use exactly three footer buttons in order: Accept / Undo accept, Discard / Undo discard, Next. Labels toggle with the current status. Discard is red. After editing an accepted document, its button returns to Accept to save those changes. Next navigates independently, with unsaved-edit protection.

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
