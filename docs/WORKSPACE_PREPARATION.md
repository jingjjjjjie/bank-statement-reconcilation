# Workspace preparation and Excel previews

On the Workspace page, **Proceed** prepares files before opening Documents.
**Prepare files** runs the same preparation for the active workspace;
**Resume workspace** continues without running it again.

The progress bar reports three stages, with file counts and the current filename:

1. Verify and copy exact duplicates into the work folder's `output/duplicates/`.
2. Convert unique Excel workbooks to cached PDF print previews.
3. Prepare original PDF pages, images, Excel cell data, and Word content locally.

No model calls run in this flow. Document extraction remains an explicit action
on Documents, and bank extraction still requires its statement year. Existing
prepared extraction state and human decisions are retained. Preparation errors
stay visible; failed Excel conversions can be retried with **Prepare files**.
Per-file preview outcomes are recorded in the project's `preview-status.json`.

## Display-only Excel conversion

`dashboard.excel_pdf.convert_excel_to_pdf(source)` uses LibreOffice Calc in a
separate temporary profile, with macros disabled, a copied input, and a timeout.
It validates the output before atomically publishing the PDF. Originals are not
changed. PDFs are stored under `dashboard/.data/excel-pdf/`, or the directory
specified by `EXCEL_PREVIEW_CACHE`. The cache key includes the workbook bytes,
renderer version, and preview format version. Failed conversions are not cached.

Review results, Final review, and Final report share the converted print preview
through `dashboard.extraction_preview`. Original downloads still return XLSX.
The legacy structured Office endpoints remain available for other views.

**Converted PDFs are not extraction inputs, matching evidence records, or new
supporting documents.** Extraction continues reading the original Excel workbook,
including cell data and hidden sheets. Print previews follow workbook print areas,
page settings, and sheet visibility. They therefore need not show every cell.
LibreOffice preserves substantially more layout than the old HTML table but is
not guaranteed to match Microsoft Excel pixel for pixel.

Both Docker targets install LibreOffice Calc and Carlito, Caladea, and Noto CJK
fonts. For a native deployment, install LibreOffice and make `libreoffice` or
`soffice` available on PATH. Rebuild the Docker image for reproducible deployment.

Validation covers cache reuse and invalidation, original-file preservation,
real multi-sheet PDF conversion, print areas and number formatting, live progress
while preparation holds the decision lock, conversion failure/retry, mobile
layout, and unchanged extraction state when preparing an existing workspace.
