# Application workflow

Updated 18 September 2026, checked against application revision `d0c3018` (including document regeneration and final report). This describes the implemented Docker application, including its current matching limitation. Concurrent uncommitted feature work is outside this snapshot. The root README summarizes the current flow; historical comparison helpers remain separate.

## 1. Complete user journey

Solid arrows are implemented transitions or processing. Dotted arrows identify the intended connection that still needs an import implementation.

```mermaid
flowchart TD
    A["01 Get Started /source"] --> B["Choose workspace containing documents/ and statement/"]
    B --> C{"Both inputs valid?"}
    C -->|No| D["Show folder or statement error; correct selection"]
    D --> B
    C -->|Yes| E["Python hashes supporting files with SHA-256; show preview"]
    E --> F["User clicks Proceed"]
    F --> G{"Inputs still match preview?"}
    G -->|No| E
    G -->|Yes| H["Copy exact duplicate groups into output/duplicates/; write report.json"]
    H --> I["Preserve all originals; activate isolated project manifest"]
    I --> J["02 Documents /documents; skip duplicate-report screen"]
    J --> K["User clicks Run all documents"]
    K --> L["Prepare unique document inventory and page or sheet units"]
    L --> M["Codex extracts structured facts and receipt pieces"]
    M --> N{"Multiple units in a document?"}
    N -->|Yes| O["Assemble receipt boundaries across source pages"]
    N -->|No| P["Save extraction checkpoint and usage"]
    O --> P
    P --> Q["Extraction ends; no vision duplicate screening or comparison"]
    Q --> R["Each document has Review results"]
    R --> S["Step 2 result page: original evidence beside editable receipt pieces"]
    S --> RG["Optional: Regenerate document; persist queued request"]
    RG --> RW["Shared worker reruns extraction and assembly; checkpoint status"]
    RW --> S
    S --> T["Check totals, currency, references, locations, and receipt boundaries"]
    T --> U{"Accept this extraction?"}
    U -->|Edit further| T
    U -->|Accept and next| V["Validate evidence revision; persist human approval"]
    V --> W{"More unaccepted results?"}
    W -->|Yes| S
    W -->|No| X["Document results reviewed"]

    I --> BA["Bank statement /bank"]
    BA --> BB["User supplies statement year and requests extraction"]
    BB --> BC["Python extracts transactions and validates balances"]
    BC --> BD["Save bank-output/master_statement.csv"]
    BD --> BE["Browse transactions; optionally export bank-only workbook"]

    X -.-> IMP["New-workspace matching import still required"]
    BD -.-> IMP
    CACHE["Existing authorized frozen matching snapshot"] --> MATCH["Final review /matching"]
    IMP -.-> MATCH
    MATCH --> VALID{"Snapshot belongs to workspace and evidence is current?"}
    VALID -->|No| BLOCK["Show blocker; do not inherit unrelated approvals"]
    VALID -->|Yes| REVIEW["Review bank rows with High/Low confidence, candidates, originals, and balances"]
    REVIEW --> DECIDE["Human approves, denies, changes, or undoes allocations"]
    DECIDE --> LEDGER["Save revision-bound final-review/decisions.json and history"]
    LEDGER --> REVIEW
    LEDGER --> REPORT["Final report /final-report; saved decisions and support status"]
    REPORT --> POPUP["View evidence popup: statement and approved documents, allocations and notes"]
    POPUP --> REPORT
    REPORT --> EXPORT["Export all bank rows as CSV with support status and differences"]
```

**Current matching limitation:** `/matching` reads the authorized `duplicated/benchmarks/full-statement-240` snapshot. It does not automatically consume a newly extracted workspace or newly accepted receipt results. It checks the manifest and original bank-master hash and rejects mismatches. The dotted connection above is pending work, not an automatic step. See [FINAL_COMPARISON.md](FINAL_COMPARISON.md).

## 2. Extraction, failures, stop, and resume

```mermaid
flowchart TD
    START["Run or resume extraction"] --> CHECK["Verify exact-copy report, input inventory, and settings"]
    CHECK --> CACHE{"Successful response already cached?"}
    CACHE -->|Yes| REUSE["Reuse response; record zero new token usage"]
    CACHE -->|No| BUDGET{"Request allowance available and Codex enabled?"}
    BUDGET -->|No| PAUSE["Pause; retain completed checkpoints"]
    BUDGET -->|Yes| CALL["codex exec with ChatGPT login; structured schema; images for vision"]
    CALL --> RESULT{"Valid complete result?"}
    RESULT -->|No| FAIL["Keep unresolved; retain attempt details and reported usage"]
    RESULT -->|Yes| SAVE["Save completed extraction or receipt assembly"]
    REUSE --> SAVE
    SAVE --> MORE{"More extraction or assembly work?"}
    MORE -->|Yes| CACHE
    MORE -->|No| REVIEW["Ready for per-document result review"]
    FAIL --> PAUSE
    STOP["User clicks Stop"] --> CANCEL["Cancel active processes; verify worker finalization"]
    CANCEL --> PAUSE
    PAUSE -->|User runs again| CHECK
    USAGE["Durable token-usage.jsonl: stage, model, attempts, cache hits, unknown usage"]
    CALL --> USAGE
    REUSE --> USAGE
```

- Extraction and receipt assembly retain their existing structured-output validation and request limits.
- A stopped, failed, blocked, or unreadable item is not silently accepted.
- Missing usage remains **unknown**; partial totals are not complete totals.
- Progress percentages report completed units in the current stage. Animation smooths measured updates; it does not invent completed work.
- Multi-page receipt assembly is part of extraction. It is not the removed vision duplicate pass.

## 3. Step 2 statuses and review actions

```mermaid
flowchart LR
    QUEUED["Queued: no completed units"] --> PROCESS["Processing: extraction or assembly remains"]
    PROCESS --> REVIEW["Needs review: results available, not all currently accepted"]
    REVIEW -->|Human accepts current results| COMPLETE["Complete: current extracted results accepted"]
    QUEUED -->|Blocked input or extraction failure| ATTENTION["Needs attention"]
    PROCESS -->|Unreadable or blocked evidence| ATTENTION
    COMPLETE -->|Evidence or extraction revision changes| REVIEW
```

| Control | Behavior |
| --- | --- |
| Run all documents | Prepare if needed, then start or resume extraction and assembly. Does not run vision duplicate checks. |
| Stop | Request cancellation and retain completed work. Running remains true until worker/process shutdown is confirmed. |
| Search / status filter | Filter the list only; retain browser preferences. |
| Review results beside a document | Open `/extraction-review?unit=<document-id>:0`; assembled documents resolve to their whole-document result. |
| Original preview | View pages, sheets, zoom and source evidence beside the editable results. |
| Split / Remove / Add piece | Edit receipt extraction pieces; never delete the original file. |
| Regenerate document | Queue fresh extraction and assembly on the shared worker; retain unresolved failures and require fresh acceptance. Reload completed results unless unsaved edits need protection. |
| Accept & next | Validate the current evidence revision, save acceptance, then open the next available unaccepted result. |
| Complete document status | Means extraction results were accepted. It does not mean a bank payment has been matched. |

## 4. Runtime architecture

```mermaid
flowchart LR
    USER["Browser at localhost:8765"] --> VUE["Vue 3 and Vue Router; cached views and lazy routes"]
    VUE -->|Same-origin HTTP| API["FastAPI and one Uvicorn worker"]
    subgraph DOCKER["One dashboard Docker service"]
        ASSETS["Vite build in /opt/dashboard-frontend"] --> API
        API --> PY["Python extraction, hashes, validation, arithmetic, and state"]
        API --> BG["Background extraction worker; bounded concurrent requests"]
        BG --> CODEX["codex exec using subscription login"]
        PY --> STORE["Workspace files and per-project checkpoints"]
        BG --> STORE
    end
    INPUTS["Host uploads mounted at /uploads and /documents"] --> PY
    REPO["Repository bind-mounted at /workspace"] --> STORE
    LOGIN["Persistent codex-home Docker volume"] --> CODEX
```

Docker builds Vue with Node, then serves its compiled files through FastAPI. There is no separate frontend server to start. The one-worker requirement preserves ownership of the active workspace and its background jobs. Workflow access is serialized; inexpensive session metadata and static pages can still respond while a workflow request waits.

## 5. Per-document review request sequence

```mermaid
sequenceDiagram
    actor User
    participant List as Documents page
    participant View as Step 2 results page
    participant API as FastAPI
    participant State as Python evidence and saved state
    User->>List: Click Review results for one document
    List->>View: Navigate with document unit query
    View->>API: GET /api/receipts
    API->>State: Load results and check approval bindings
    State-->>View: Units, receipt pieces, and evidence revision
    View->>API: GET original preview for selected document
    API-->>View: Source preview and page labels
    User->>View: Inspect and correct pieces
    User->>View: Accept and next
    View->>API: POST /api/receipts/accept with revision and pieces
    API->>State: Check active workspace, no running batch, current evidence, and schema
    alt Revision changed or validation fails
        State-->>View: Error, keep editable results visible
    else Valid explicit acceptance
        State->>State: Persist approval and history
        State-->>View: Updated results
        View-->>User: Next available unaccepted document
    end
```

## 6. Final report and evidence popup

```mermaid
sequenceDiagram
    actor User
    participant Report as Final report
    participant API as FastAPI
    participant Ledger as Saved final review and originals
    User->>Report: Open Final report
    Report->>API: GET /api/matching
    API->>Ledger: Validate snapshot binding, read decisions and source hashes
    Ledger-->>Report: Bank rows, support status, notes and approved allocations
    User->>Report: Click View evidence
    Report->>API: GET /api/matching-preview for bank and approved item
    API->>Ledger: Resolve corpus ID and verify original bytes
    alt Original changed or unavailable
        API-->>Report: Explicit preview error
    else Current original
        API-->>Report: Page labels and preview type
        Report->>API: GET /api/matching-image or /api/matching-office
        API-->>Report: Original page image or safe Office preview
    end
    User->>Report: Close or Escape
    Report-->>User: Same filters and originating control focused
```

The report is read-only and makes no model calls. Pending/rejected suggestions do not appear as approved evidence. Approved partial/contextual evidence can be viewed, while its status remains No supporting under the current export policy. Missing snapshot data blocks the report and hides export. The report is refreshed on revisiting; it is not a frozen sign-off record.

## 7. Files, outputs, and implementation map

| Location / module | Purpose |
| --- | --- |
| `WorkName/documents/`, `WorkName/statement/` | Original supporting files and statement; preserved. |
| `WorkName/output/duplicates/` | Exact SHA duplicate copies and `report.json`, including original locations. |
| `duplicated/projects/<workspace-key>/duplicate-manifest.json` | Activated workspace manifest. |
| Project `review/index.json`, `review/state.json` | Prepared unique documents, saved extraction, assembly, and historical evidence. |
| Project `review/model-cache/`, `review/token-usage.jsonl` | Successful model cache and durable attempt usage. |
| Project `review/regeneration.json` | Queued per-document regeneration jobs, status and history. Interrupted work remains unresolved. |
| Project `review/receipt-matches.json` | Receipt extraction approvals and legacy receipt-allocation history. |
| Project `bank-output/master_statement.csv` | Deterministic bank master; differing existing masters are protected. |
| Project `final-review/decisions.json` | Human decisions bound to the frozen matching evidence. |
| `dashboard/frontend/src/router.js` | User-visible routes; retired `/content-review` redirects to `/documents`. |
| `dashboard/api/`, `dashboard/routes.py` | HTTP endpoints, local access protections, session token and workspace guards. |
| `reconciliation/source_selection.py`, `exact_report.py` | Input selection, SHA preview, exact-copy output. |
| `dashboard/content_review.py`, `reconciliation/vision_workflow.py` | Background extraction/assembly, cancellation, cache, and resume. Historical comparison helpers remain for compatibility. |
| `dashboard/regeneration.py` | Durable regeneration queue on the shared extraction worker. |
| `dashboard/frontend/src/views/FinalReport.vue`, `components/ReportEvidence.vue` | Read-only report, modal evidence navigation and original downloads. |
| `dashboard/document_status.py`, `receipt_review.py` | Five list statuses, current receipt results, and acceptance validation. |
| `dashboard/matching_review.py` | Frozen-snapshot evidence checks, allocation ledger, remaining balances, and CSV export. |

The Completion page currently checks extraction readiness and the bank master's matching flags. It is not automatically synchronized with the separate frozen-snapshot matching ledger; treat that as a current integration limitation, not evidence that a new workspace can finish end to end.
