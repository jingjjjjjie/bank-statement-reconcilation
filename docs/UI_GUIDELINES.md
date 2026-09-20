# Dashboard UI rules

User preference, recorded 2026-09-18:

- Keep copy functional and concise. Remove decorative subtitles, repeated labels,
  and explanations that duplicate a title or control.
- Put page instructions in one circled question-mark control beside the title.
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
- Extraction review offers Discard document and Restore document. Trash is
  an audited, reversible classification that excludes supporting evidence; it never
  deletes or moves original files. Trash squares have a distinct muted brown shade.

Shared help content: `dashboard/frontend/src/pageHelp.js`.
Shared help control: `dashboard/frontend/src/components/PageHelp.vue`.

- Step 2 displays all pieces together as editable rows. Keep payee, description, amount and currency visible; put secondary fields under Details. Selecting a row targets Remove; Split and Merge are not offered. Narrow screens wrap the fields and place save actions after the rows without overlap.

- Pieces represent separate receipts or payees, not purchase lines. Show editable payee, description, amount and currency together; keep source details, references and dates in the piece disclosure. Add entry and Remove are explicit edits; existing identities are preserved.

- Review results uses one compact toolbar for entry count, Add entry and Remove. The highlighted row indicates selection; do not add separate heading or selection bars. Keep Accept & next in the save footer. Keep the title visible on narrow screens.

- Review results combines title, filename, document numbers, progress and actions in one horizontal bar; scroll the bar on narrow screens. Do not show entry search.
