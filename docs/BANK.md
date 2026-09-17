# Bank statement branch

Install the root `requirements.txt` into Python and run commands from the repository root.

```powershell
python -m reconciliation.bank_statement "statement.pdf" --year 2025
python -m reconciliation.bank_excel bank-output/master_statement.csv --company "Example Company Sdn. Bhd."
python -m unittest tests.unit.test_bank_statement
```

Default outputs:

- `bank-output/master_statement.csv`: full bank narration, raw party/details,
  parsed counterparty and role, amounts, balances, statement totals, source file
  hash/page, and transaction ID. This is the reference for matching.
- `bank-output/answer_statement.xlsx`: styled answer, generated from the
  master, with PAY TO populated and PARTICULAR blank for the supporting-document
  branch. Full narration stays in the master; source comments on DATE
  connect each answer row to the master and PDF.

Names remain as printed, including abbreviations. Incoming rows show the payer;
returned payments show the original recipient. No accounting classifications or
supporting-document verification are inferred. REMARK stays PENDING.

The extractor supports the observed single-account AmBank MYR digital layout.
It checks each running balance, opening/closing balances, and printed debit/credit
totals using Decimal. Excel export checks the PDF fingerprint and re-extracts the
source to verify the master rows, dates, text, IDs, account, currency and totals.
This catches later CSV changes but cannot independently detect a mistake repeated
by the same extractor. Visual and independent-reader checks are in `bank-audit.md`.
The year is supplied explicitly because the PDF date header
contains overlapping text. Formatting is loaded from `prompts/styles/bank_statement.xml` and documented in
`style.md`. Use `--style path/to/style.xml` to select another compatible style;
the original sample workbook is not required.
