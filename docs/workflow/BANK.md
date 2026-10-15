# Bank statement branch

Install the root `requirements.txt` into Python and run commands from the repository root.

```powershell
python -m reconciliation.bank.statement "statement.pdf" --bank maybank --year 2025
python -m reconciliation.bank.excel bank-output/master_statement.csv --company "Example Company Sdn. Bhd."
python -m unittest tests.unit.bank.test_statement
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
supporting-document verification are inferred. REMARK stays PENDING, or REVIEW PAY TO
when the party cannot be identified.

The extractor supports the observed single-account MYR digital layouts for AmBank,
Public Bank (RM Plus Current Account), Maybank (CCA SME First Account), Hong Leong
Bank, and CIMB, plus the observed UOB account-activity export. Scanned PDFs remain unsupported.
Support is for these layouts, not every product or historical format issued by a bank.

Choose the bank and year before extracting in the dashboard. The API requires
`bank`; CLI `--bank` accepts `ambank`, `public_bank`, `maybank`, `hong_leong`,
`cimb`, or `uob` and defaults to AmBank for existing scripts. Bank detection uses issuer
wording inside the PDF, never its filename. A wrong selection is rejected with the
detected bank's name. Unknown/ambiguous issuers, unexpected columns, missing pages,
conflicting accounts, invalid dates, and failed financial checks stop extraction
before a master is saved. Existing masters cannot be replaced by another bank,
source, or year. The new formats verify the supplied year against the printed
statement date; AmBank retains its explicitly supplied year because its date header
overlaps in the observed sample.

Each bank has a module under `src/reconciliation/bank/formats/`. New formats define
source metadata, columns, and conservative party rules there. UOB uses its own
row-boundary reader for vertically centered table cells; shared reading and
Decimal validation live in `formats/common.py` and `statement.py`. Full narration
is preserved. Only recognizable party fields populate PAY TO; ambiguous names and
batch references stay unidentified and produce REVIEW PAY TO in bank-only Excel.

Public Bank preserves zero-value debit/credit entries and continued dates/narration
across page boundaries. Maybank interprets signed amounts. CIMB reverses its printed
newest-first rows into chronological sequence while preserving source page numbers.
Hong Leong calculates missing intermediate balances and checks every available
printed balance. `balance_origin` distinguishes calculated balances in the master,
dashboard, and workbook comments. Printed transaction counts are checked where
available (Public Bank, Hong Leong, CIMB), along with opening/closing balances and
both printed transaction totals for every supported format.

UOB is an account-activity export, not a formal monthly statement. Its printed record
count, deposit/withdrawal totals, running balances, and selected date range are checked.
Opening balance is inferred from the first row, closing balance is the last listed
balance, and the header ledger balance is stored separately as `header_balance`.
Statement date drives reconciliation; the separate original transaction timestamp
is preserved as `transaction_datetime`. `statement_kind`, `opening_balance_origin`,
and `validation_note` preserve these distinctions through CSV and exports. The
filtered export's full-period completeness remains unverified and is visibly flagged
on the bank page; workbook headings and opening labels distinguish it as well.

Masters include `bank`; legacy masters without it remain AmBank. Excel headings use
the bank name. Export checks the PDF fingerprint and re-extracts the source to verify
rows, dates, narration, IDs, account, currency, balance provenance, and totals. This
catches CSV edits but is not independent verification of the same parser's logic.

Validation on the five supplied samples: Public Bank 480 rows, Maybank 33 rows,
Hong Leong 309 rows, CIMB 128 rows, and UOB 53 rows; all available balance/count/total checks passed.
Customer PDFs are not test fixtures or committed. Synthetic PDF regression tests
cover wrong bank/year, filename independence, damaged/missing rows, unsupported
headers/currency, repeated pages, zero amounts, calculated balance provenance,
preservation of saved masters, and UOB header/period balance separation. Browser
checks cover bank/year submission, visible errors, one help control/navigation,
and narrow screens.

Formatting is loaded from `resources/prompts/excel/bank_statement.xml` and documented
in [workbook style](BANK_WORKBOOK_STYLE.md). Use `--style path/to/style.xml` to select
another compatible style; the original sample workbook is not required.
