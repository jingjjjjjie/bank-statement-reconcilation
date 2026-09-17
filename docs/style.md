# Bank reconciliation workbook style

Runtime definition: `prompts/styles/bank_statement.xml`. This file captures the
approved sample's December formatting and theme without its customer data or
formulas. Exports load this definition directly; no sample workbook is required.
Edit it using the instructions in `prompts/styles/README.md`.

## Layout

- Monthly sheet names use `DEC'25` format.
- Row 1: company and assessment-year heading, merged across `A1:K1`.
- Row 2: bank, account number, and month, merged across `A2:K2`.
- Row 3: blank spacer.
- Row 4: column headings in the order below.
- Row 5: opening balance in J; other cells generally blank.
- Row 6 onward: transactions in date order.
- Footer: DR/CR subtotals, `AS PER SQL`, then `VARIANCE`.

## Columns

Widths are Excel column-width units, rounded to two decimals.

| Column | Heading | Width |
| --- | --- | ---: |
| A | DATE | 12.00 |
| B | LEDGER | 40.57 |
| C | SQL | 7.86 |
| D | SALES TYPE | 16.14 |
| E | PV/OR | 12.14 |
| F | PAY TO | 53.57 |
| G | PARTICULAR | 110.71 |
| H | DR | 14.00 |
| I | CR | 14.00 |
| J | TOTAL | 18.57 |
| K | REMARK | 18.14 |

## Typography and appearance

- Font: Aptos Narrow.
- Title rows: 16 pt, bold, left aligned, vertically centered; 21 pt row height.
- Column headings: 11 pt, bold, solid shaded fill.
- Header fill: Excel theme color index 2 with tint `-0.249977111117893`.
  Preserve the source workbook theme when copying this fill.
- Headers B, D, E, G, H, I, J, K are centered; A and F are left aligned;
  C uses default alignment.
- Ordinary transaction cells: primarily 11 pt, regular, vertically centered.
- REMARK entries: bold red (`#FF0000`), including the sample's `OK` entries.
- Body rows are primarily unfilled with no explicit cell borders.
- Default row height: 15 pt. Some PARTICULAR cells wrap and contain line breaks;
  wrapping is not applied consistently throughout the source.
- Gridlines use Excel's default setting. No freeze panes are configured.

## Values and number formats

- DATE contains Excel dates, but source formatting is inconsistent: December
  transactions commonly use `mm-dd-yy`; some other cells use `d/m/yyyy` or a
  hard-coded month/year format. Use real dates and a consistent `dd/mm/yyyy`
  format in the generated workbook.
- DR, CR, TOTAL use accounting-style formatting: thousands separators, two
  decimal places, and a dash for zero. Preserve the captured number format in the style definition.
- DR increases the balance; CR decreases it. This reverses the AmBank PDF's
  CREDIT/DEBIT labels when mapping into the workbook.
- TOTAL is a running balance. The sample formula is `=J5+H6-I6`, continuing
  down the column; J5 references the previous month's closing balance.
- The sample uses `SUBTOTAL(9,...)` for transaction totals.
- Some SQL cells use `=LEFT(B6,7)` to derive an account code from LEDGER.
- PAY TO is usually uppercase. PARTICULAR often uses colon-separated references,
  supplier names, descriptions, and periods; multiple supporting items may use
  separate lines within the same cell.

## Rules for the AmBank output

- Reuse formatting only; never copy the other customer's values or formulas.
- Use the actual company, bank, account, currency, and statement month.
- Omit the assessment year until supplied; the statement year does not establish it.
- Keep LEDGER blank. Leave SQL, SALES TYPE, and PV/OR pending supporting evidence.
- Keep two deliverables: a verbose `master_statement.csv` for comparison and
  a styled Excel answer generated from that master.
- The master preserves full narration, raw party/details fields, transaction type,
  amounts, balances, source path/hash/page, row ID, and reconciliation status.
- Fill PAY TO from the statement's named counterparty, uppercase for display:
  recipient for outgoing funds, payer for incoming funds. Returned payments name
  the original recipient; record that role in the master and the cell comment.
- Preserve abbreviated names as printed; do not expand them by guessing.
- Leave transaction PARTICULAR cells blank in the bank-branch Excel answer;
  the supporting-document branch supplies those descriptions later.
- Preserve full narration and reference line breaks in the master CSV.
  Attach source page, row ID and narration comments to DATE, not PARTICULAR.
- Use `PENDING` in REMARK until supporting-document matching is complete;
  balanced arithmetic alone does not justify `OK`.
- For this extraction preview, write validated numeric running balances and totals
  so values display immediately without requiring Excel formula recalculation.
- Leave `AS PER SQL` and `VARIANCE` empty until SQL figures are available.
- Use 30 pt transaction row heights in the bank-branch answer.
- Attach PDF page references as cell comments, preserving the A:K layout.

## Print settings observed

- A4 paper, portrait orientation.
- No explicit print area, repeated title rows, or fit-to-page settings in December.
- For the generated wide report, use A4 landscape, fit to one page wide with
  unrestricted page height, repeat row 4, and print only the populated A:K area.
