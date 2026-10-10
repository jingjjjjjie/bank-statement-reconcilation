<div align="center">

![Accounting Copilot: A little less paperwork.](docs/assets/readme-banner.svg)

### Bank Statement Reconciliation

Your receipts, statements and supporting documents. One place to make sense of them.

**[Get started](#get-started)** &nbsp;·&nbsp; **[How it works](#how-it-works)** &nbsp;·&nbsp; **[Documentation](docs/README.md)**

`Python` &nbsp; `FastAPI` &nbsp; `Vue 3` &nbsp; `Docker`

</div>

> 🌱 **Growing into something shareable.**  
> Currently hard-coded; open source soon! Bank extraction currently targets AmBank statements.

## Small steps. Clear records.

📄 **Read the paperwork.** Extract receipts, invoices and supporting files. Group exact duplicates automatically.

🔎 **Check the details.** Review entries beside the originals, then inspect suggested matches.

✅ **Make the call.** Accept or reject evidence. Your decisions are saved; originals stay intact.

📦 **Take it with you.** Export bank workbooks and supporting-document ZIPs.

<a id="how-it-works"></a>
## How it works

**Documents → Extraction → Your review → Matching → Export**

Run supporting documents, check their entries, then extract the bank statement. On the bank page, choose **Load for final matching**, then **Generate matches**. Review the proposed evidence before accepting it.

AI extraction and matching use Codex through your ChatGPT subscription login. Suggestions always need your review.

<a id="get-started"></a>
## 🚀 Get started

You need **Docker Compose** and **a ChatGPT account with Codex access**.

**01 · Add your files**

Copy `.env.example` to `.env`. Set `UPLOADS_PATH` to your jobs folder; use forward slashes on Windows.

```text
bank-statement-uploads/
  MyProject/
    statement/
      bank-statement.pdf    # One statement PDF
    documents/
      invoice.pdf
      receipts/
```

The default folder is `../bank-statement-uploads`, beside this repository. Keep inputs outside Git.

**02 · Start your workspace**

```console
docker compose build
docker compose run --rm dashboard codex login
docker compose up -d
```

Choose ChatGPT login. Open **[localhost:8765](http://localhost:8765)**, then **Bank Statement Reconciliation → New project**. Select `/uploads/MyProject`. Use **Resume** to pick up where you left off.

## 🌱 Up next

- [ ] Remove hard-coded project assumptions.
- [ ] Make setup reusable across workspaces.
- [ ] Prepare the open-source release.

<details>
<summary><strong>For developers</strong></summary>

```console
# Rebuild
docker compose up -d --build dashboard

# Test
docker compose exec dashboard python -m unittest discover -s tests/unit -t .

# Logs
docker compose logs --tail 50 dashboard

# Stop
docker compose down
```

The app binds to localhost by default. Keep the `codex-home` volume and project review data when updating.

[Architecture](docs/ARCHITECTURE.md) · [Tests](tests/README.md) · [Matching rules](docs/workflow/FINAL_COMPARISON.md) · [Token usage](docs/operations/TOKEN_ACCOUNTING.md)

</details>
