# Workbook styles

`bank_statement.xml` is the reusable bank export style, captured from the approved
sample without customer values, formulas, or source paths. The original workbook
is no longer required. Python reloads this file for every export.

- `columns`: ordered field mappings, headings and column widths. XML order determines
  Excel column order; move an entire `column` entry to move that field.
- Named `row` entries: heights and per-field references to shared styles.
  Title and subtitle `anchor-style` settings keep merged headings at the left edge.
- `styles/style`: fonts, fills, borders, alignment, protection and number formats
  using Excel's standard style elements. Edit the referenced style to change all
  cells using it, or copy it under a new name for a separate appearance.
- `print`: paper size (9 means A4), orientation, scaling and repeated header rows.
- The embedded `theme` preserves the sample's theme colours and fonts.

## Reorder columns

For example, move this entry before `money_in` to show outgoings first:

```xml
<column heading="CR" width="14.0" field="money_out" />
```

Values, headers, widths, number formats, opening balances, footer totals and
source comments follow their field automatically. No Python changes are needed.
Keep each field exactly once: `date`, `ledger`, `sql`, `sales_type`, `voucher`,
`counterparty`, `particular`, `money_in`, `money_out`, `balance`, `status`.
Unknown, missing or duplicate fields and broken style references fail export.

Version 2 uses field names rather than fixed column letters/numbers. Older
version 1 definitions must be migrated; the bundled definition is already updated.
`reconciliation/workbook_style.py` loads and renders the definition.
`reconciliation/bank_excel.py` supplies typed bank values and evidence comments.
Accounting fields and particulars remain blank; matching status follows the bank
workflow. These rules cannot be overridden by a style. No code is executed from XML.

Column order and appearance are configurable. The report still has the same title,
header, opening balance, transaction and footer sections. Adding a new business
field requires a Python data-provider change and a corresponding style entry.

The dashboard uses this saved style automatically. The CLI can select another
compatible definition with `--style path/to/style.xml`. A missing or malformed
file fails export rather than silently switching formats. Appearance and bank
report conventions are documented in `docs/style.md`.
