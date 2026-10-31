# Components

Flat package `src/sieve_as_code/`. One module per component; functions, not classes, except frozen dataclasses for data.

| Component | Module | Responsibility | Requirements |
|---|---|---|---|
| Model | `model.py` | `Filter`, `FilterOrder` dataclasses; shared error types | FR-DECL.1, FR-DECL.4 |
| Settings | `settings.py` | Resolve env vars and the account name to per-account paths and the `proton-cli` binary | FR-CLI.3, FR-ACCT.1, FR-ACCT.2, FR-ACCT.5 |
| Audit | `audit.py` | Append-only JSONL, names and counts only | FR-APPLY.6, FR-PLAN.4, NFR-SAFE.2, NFR-SAFE.3 |
| Proton client | `client.py` | Only module that runs `proton-cli`; session and version checks; passes `--profile`; filter, label, folder and message operations | FR-APPLY.3, FR-PLAN.6, NFR-REL.2, NFR-REL.3 |
| Declared | `declared.py` | Load, render and validate filter files and the order file | FR-DECL.1–3, FR-DECL.5, FR-DECL.6 |
| Live | `live.py` | `discover` | FR-DISC.1 |
| Importer | `importer.py` | `import_live` and `.sieve` import | FR-DISC.2, FR-DISC.3 |
| Plan | `plan.py` | Diff declared vs live; targets; extension flags | FR-PLAN.1–6, FR-DECL.4 |
| Backup | `backup.py` | Write, read and diff versioned checksummed snapshots | FR-BAK.1–3, FR-BAK.5 |
| Apply | `apply.py` | Execute a plan in order with failure accounting | FR-APPLY.1–6 |
| Restore | `restore.py` | Plan and apply a snapshot, verify by re-plan | FR-BAK.4 |
| Sieve evaluator | `sieve_eval.py` | Evaluate the supported Sieve subset against a message | FR-RETRO.2 |
| Retroactive | `retroactive.py` | Preview, gated run, snapshots, status, audit report | FR-RETRO.1–5 |
| CLI | `cli.py` | argparse dispatch, confirmations, exit codes | FR-CLI.1 |
| Public API | `__init__.py` | Re-exports the documented functions | FR-CLI.2 |
