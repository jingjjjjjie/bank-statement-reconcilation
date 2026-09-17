# Workbook styles

`bank_statement.xml` is the reusable bank export style, captured from the approved
sample without customer values, formulas, or source paths. The original workbook
is no longer required. Python reloads this file for every export.

- `columns`: A:K headings and column widths.
- Named `row` entries: heights and per-column references to shared styles.
- `styles/style`: fonts, fills, borders, alignment, protection and number formats
  using Excel's standard style elements. Edit the referenced style to change all
  cells using it, or copy it under a new name for a separate appearance.
- `print`: paper size (9 means A4), orientation, scaling and repeated header rows.
- The embedded `theme` preserves the sample's theme colours and fonts.

Keep the A:K field order and named row roles: they correspond to the bank report's
schema. Transaction values, evidence comments, blank accounting fields and pending
matching status remain controlled by the exporter, not the style. No code is
executed from the style file.

The dashboard uses this saved style automatically. The CLI can select another
compatible definition with `--style path/to/style.xml`. A missing or malformed
file fails export rather than silently switching formats. Appearance and bank
report conventions are documented in `docs/style.md`.
