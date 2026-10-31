# High-Level Design

## Architecture Overview

One in-process Python package. The only external boundary is the `proton-cli` subprocess, reached through `client.py`. Local files (filters, order, backups, audit log) are the only state.

```mermaid
graph TD
    User["Maintainer / Library caller"] --> CLI["cli.py"]
    User --> API["__init__.py (public API)"]
    CLI --> API
    subgraph Package["sieve_as_code"]
        API --> Plan["plan"]
        API --> Apply["apply / restore"]
        API --> Retro["retroactive"]
        API --> Imp["importer"]
        API --> Bak["backup"]
        Plan --> Live["live (discover)"]
        Plan --> Decl["declared"]
        Apply --> Plan
        Apply --> Bak
        Retro --> Eval["sieve_eval"]
        Retro --> Live
        Imp --> Live
        Imp --> Decl
        Bak --> Live
        Live --> Client["client"]
        Apply --> Client
        Retro --> Client
        Audit["audit"]
        Plan -.-> Audit
        Apply -.-> Audit
        Retro -.-> Audit
    end
    Client -->|"subprocess, stdin scripts"| Proton["proton-cli (external)"]
    Decl --> Files[("filters/*.yaml + order file")]
    Bak --> Snaps[("backups/*.json")]
    Audit --> Log[("audit.log JSONL")]
```

## Technology Decisions

| Decision | Choice | Rationale | Alternatives Considered |
|---|---|---|---|
| Language | Python ≥3.12 | RVQ-Q12 | — |
| Process boundary | One `client.py` | Single place to fake in tests and to absorb `proton-cli` output changes | Calls spread across modules |
| State | Local files are truth, live read each run | FR-PLAN.4; no baseline file to drift | Stored baseline |
| Results | Frozen dataclasses (`PlanResult`, `ApplyReport`, `RestoreReport`, `RetroPreview`) | Library callers need typed results (FR-CLI.2) | Dicts, printed text |
| Confirmation | Library takes `confirmed: bool`; CLI owns prompts and `--yes` | Library stays non-interactive | Prompts inside library |
| CLI parsing | `argparse` | stdlib first | click, typer |
| Config | Four env vars; account subdirectories by convention | RVQ-Q11, RVQ-Q18; fewer than 10 values | Config file listing accounts |

## Data Flows

### Plan and apply

```mermaid
flowchart TD
    A[plan / apply] --> B[load_declared]
    B --> C{validate_declared}
    C -->|invalid| X[Error naming file and field; audit invalid]
    C -->|valid| D[discover live via client]
    D --> E[plan: diff, targets, flags]
    E --> F{apply --yes?}
    F -->|no| G[Print plan, stop]
    F -->|yes| H[write backup]
    H --> I[execute writes in order]
    I --> J{failure?}
    J -->|yes| K[Stop; report succeeded / failed / not attempted]
    J -->|no| L[Audit writes; report success]
```

### Retroactive run

```mermaid
flowchart TD
    A[apply-retroactive NAME] --> B[evaluate filter over mailbox listing]
    B --> C{supported Sieve?}
    C -->|no| D[Report not previewable]
    C -->|yes| E[Show preview, Spam excluded]
    D --> F{typed name and reason match?}
    E --> F
    F -->|no| G[Refuse; audit refused]
    F -->|yes| H[Save preview snapshot; prune over 10 days]
    H --> I[client.apply_retroactively]
    I --> J[Audit write with name and reason]
```

## Cross-Cutting Concerns

| Concern | Strategy | Requirement |
|---|---|---|
| Errors | One base `SieveAsCodeError`; subclasses only where callers branch: validation, client, backup integrity, unsupported Sieve. CLI maps to exit codes: 0 ok, 1 failure or remaining diff, 2 usage or validation | NFR-OPS.1, FR-CLI.1 |
| Validation | Fail fast on the first error, naming file and field | FR-DECL.5 |
| Configuration | Env vars read once in `settings.py`; every path is built from the validated account name | FR-CLI.3, FR-ACCT.5 |
| Logging | Audit JSONL for writes and checks; names and counts only | NFR-SAFE.2 |
| Secrets | None held; the session lives in `proton-cli` | RVQ-Q11 |
| Idempotency / drift | Second `apply` is a no-op; `plan` is the drift check | NFR-REL.1, FR-PLAN.4 |
| Recovery | Pre-write backup (also before restore), verified restore, disable-not-delete | FR-BAK.*, FR-APPLY.5 |
| Wrong account | Fingerprint of the Proton account `id` checked against a marker before any Proton command; snapshots carry it | FR-ACCT.4 |
