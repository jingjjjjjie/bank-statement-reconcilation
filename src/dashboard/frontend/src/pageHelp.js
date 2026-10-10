// Keep help actionable; editing screens also explain each control and when changes are saved.
export const pageHelp = {
  Projects: ['Projects', [
    'Resume a saved project or choose New project.',
    'Close keeps progress and frees the workspace for another browser. Resume reopens it.',
    'Reset starts a fresh run. Delete removes the workspace from this list. Both keep originals and archive previous results. Stop running jobs first.',
  ]],
  Source: ['Workspace', [
    'Choose a folder with statement/ and documents/, then Proceed. Resume reopens your last review.',
  ]],
  Bank: ['Bank statement', [
    'Enter the statement year, extract, then check the rows. Load for final matching before Generate matches.',
  ]],
  Documents: ['Documents', [
    'Run all documents, then review the extractions. Progress is saved when you stop.',
  ]],
  ExactReport: ['Exact duplicates', [
    'Identical files are grouped automatically. Originals stay unchanged; only one copy is processed.',
  ]],
  ExactReview: ['Review duplicates', [
    'Choose one file per group, then validate. Undo selection lets you choose again.',
  ]],
  ExtractionReview: ['Review extraction', [
    'Compare the entries on the left with the original on the right. An entry represents a separate receipt or payee, not each purchase line.',
    'Add entry — add a missing receipt or payee to this document. Fill in its details, then Accept to save.',
    'Merge all — combine every entry in this document into one draft. Use it when one receipt was split into several entries. Check the merged details, currency and total before accepting.',
    'Remove — click an entry to select it, then remove it from the draft. The original file is preserved. Accept saves the removal.',
    'Reset to original — replace your current edits, added entries and merges with the latest original extraction. This resets the whole document, not just the selected entry. Accept to save the restored result.',
    'Edit fields directly. Details contains extra information such as dates and references. Document total sums the displayed entries separately for each currency.',
    'Show document / Show — display the entry’s source page or sheet. Download retrieves the original file. Page / sheet and Zoom change only the preview.',
    'Accept — save the displayed entries and mark this document reviewed, then advance when another document follows. Accepting no entries keeps the document as supporting evidence only.',
    'Reject — exclude this document from supporting evidence and advance. It does not delete the original file.',
    'Undo — reverse a saved acceptance or rejection using the same button. After editing an accepted document, Save changes saves your corrections.',
    'Next and the document arrows navigate without accepting. Unsaved edits are protected by a confirmation before leaving.',
    'Options → Reload results loads saved results. Export reviews downloads saved review data. Accept all accepts ready extractions across the batch, includes your current draft, and reports skipped items that still need attention.',
  ]],
  Matching: ['Review matching', [
    'Check the original, select supporting documents, then Accept or Reject. Reset to suggestion restores the proposed selection.',
  ]],
  FinalReport: ['Export', [
    'Check saved results and export files. Change decisions in Review Matching.',
  ]],
  Settings: ['Settings', [
    'Choose processing options, then Save settings. Saving does not start a run.',
  ]],
};
