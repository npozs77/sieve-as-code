# Requirements — sieve-as-code

**Version**: 1.0
**Date**: 2026-10-31
**Status**: Draft

Rationale for each decision lives in `requirement-verification-questions.md` (RVQ-Qn); requirements cite it.

---

## Intent Analysis

| Attribute | Value |
|---|---|
| Request Type | New open-source tool (greenfield) |
| Scope | Proton Mail Sieve filters as code for one or more accounts, one account per command: discover, plan, apply, import, backup, restore, retroactive run |
| Complexity | Moderate |
| Maturity Level | **MVP** |

---

## System Context

- **Project**: sieve-as-code
- **Purpose**: Terraform-style discover → plan → apply loop for each of a user's Proton accounts' Sieve filters, built on `proton-cli` only (`concept.md`).
- **Users**: Proton users with a non-trivial filter set who want it reviewable, reproducible and restorable; and Python programs importing the library.
- **Deployment**: Python package from PyPI; installs a CLI.
- **Runtime**: Python ≥3.12 (RVQ-Q12); `proton-cli` subprocess calls; no credentials held (RVQ-Q11).

---

## Functional Requirements

### FR-ACCT — Accounts

| ID | Requirement | Priority |
|---|---|---|
| FR-ACCT.1 | An account is a `proton-cli` profile name. Every command acts on exactly one account, chosen by `--account NAME` or `SIEVE_AS_CODE_ACCOUNT`, defaulting to `default`; the name is passed to `proton-cli` as `--profile` (RVQ-Q18). | Must |
| FR-ACCT.2 | Each account has its own filter files, order file, backups, retroactive snapshots and audit log, in separate directories; nothing is shared between accounts (RVQ-Q18). | Must |
| FR-ACCT.3 | Every plan, apply, restore and retroactive output, and every confirmation prompt, names the account and its fingerprint (FR-ACCT.4). | Must |
| FR-ACCT.4 | An account's fingerprint is the first 12 hex characters of the SHA-256 of the Proton account `id` that `proton-cli` reports for the profile; the email is never stored. The fingerprint is written on first use to `<FILTERS_DIR>/<account>/account.id`. Every command that talks to Proton compares the logged-in profile's fingerprint with that file and refuses on mismatch. Snapshots record the account name and fingerprint; `restore` and `backup-diff` refuse a snapshot with a different fingerprint (RVQ-Q20). | Must |
| FR-ACCT.5 | An account name containing a path separator, `..` or a leading `.` is rejected before any path is built. | Must |

### FR-DECL — Declarative source

| ID | Requirement | Priority |
|---|---|---|
| FR-DECL.1 | One YAML file per filter holding `name`, `raw_sieve` and optional `enabled`; any other key is a load error (RVQ-Q1). | Must |
| FR-DECL.2 | Filter order lives in one separate order file listing filter names (RVQ-Q1). | Must |
| FR-DECL.3 | A filter's content is its Sieve script, stored and pushed verbatim; whitespace is normalised only when writing files on import. | Must |
| FR-DECL.4 | Identity is `name`. Two declared filters with one name are a load error. A rename is a delete plus a create and is documented as such (RVQ-Q2, RVQ-Q17). | Must |
| FR-DECL.5 | All declared files are validated on load, before any plan or write: required fields, non-blank `raw_sieve`, no duplicate names, order file references only declared filters, every declared filter appears in the order file. Errors name the file and field. | Must |
| FR-DECL.6 | Validation rejects a filter whose script exceeds the Proton per-filter size limit, once that limit is measured with the live smoke suite (RVQ-Q17, NFR-TEST.2). Until then no limit is enforced and Proton's rejection is reported by FR-APPLY.4. | Could |

### FR-DISC — Discover and import

| ID | Requirement | Priority |
|---|---|---|
| FR-DISC.1 | `discover` reads all live filters (content, `enabled`, order) via `proton-cli`, read-only, and prints them in the declarative format. Two live filters sharing a name are an error, not collapsed. | Must |
| FR-DISC.2 | `import [NAME]` writes live filters into the declared files. Where local files already exist and differ from live, it prints the local-vs-live diff and refuses to overwrite without `--force`. Local-only filters are never deleted (RVQ-Q5). | Must |
| FR-DISC.3 | `import` also reads plain `.sieve` files as filters, using the file name as the filter name (RVQ-Q17). | Should |

### FR-PLAN — Plan

| ID | Requirement | Priority |
|---|---|---|
| FR-PLAN.1 | `plan` diffs declared against live state with no mutation. Entries: creates, content changes, `enabled` changes, enabled live-only filters, one reorder, and missing targets (RVQ-Q3). A live-only filter that is already disabled is listed as informational and is not drift (RVQ-Q21). | Must |
| FR-PLAN.2 | A reorder is exactly one diff entry (old vs new sequence), however many filters moved. Only filters present both declared and live are compared; live-only filters are ignored (RVQ-Q21). | Must |
| FR-PLAN.3 | `plan` lists each `fileinto` folder or label that an enabled declared filter targets and the account lacks, ahead of the filter entries; Proton's built-in mailboxes are never listed. A target `plan` cannot read literally fails the plan. | Must |
| FR-PLAN.4 | `plan` is the drift detector; there is no baseline file. Its outcome (`clean`, `drift`, `invalid`) is audit-logged. | Must |
| FR-PLAN.5 | `plan` flags filters using destructive Proton extensions (for example `vnd.proton.expire`) (RVQ-Q17). | Must |
| FR-PLAN.6 | `plan` and `discover` use read-only `proton-cli` calls only. | Must |

### FR-APPLY — Apply

| ID | Requirement | Priority |
|---|---|---|
| FR-APPLY.1 | `apply` shows the plan and refuses to write without `--yes`. | Must |
| FR-APPLY.2 | Order of writes: missing targets, then creates, content changes, `enabled` changes, live-only handling, then one reorder that names the declared filters in order; `proton-cli` leaves the rest, including live-only filters, after them in their existing order (RVQ-Q21). Only differing filters are written. | Must |
| FR-APPLY.3 | Scripts reach `proton-cli` via `--sieve -` on stdin only. `--dry-run` is never treated as proof a push will succeed. | Must |
| FR-APPLY.4 | On the first failure, `apply` stops and reports succeeded, failed (with reason) and not attempted. There is no automatic rollback. A failing audit write never replaces the report. | Must |
| FR-APPLY.5 | A live-only filter is disabled, not deleted, by default. Deleting requires an explicit override flag and a verified backup taken in the same run. `restore` is the exception: it deletes filters created after the backup, protected by its own pre-restore snapshot (FR-BAK.4) (RVQ-Q4, RVQ-Q17, RVQ-Q21). | Must |
| FR-APPLY.6 | Every write is audit-logged, including failures. | Must |

### FR-BAK — Backup and restore

| ID | Requirement | Priority |
|---|---|---|
| FR-BAK.1 | Before any write, `apply` and `restore` snapshot all live filters (content, `enabled`, order) to the backup directory. | Must |
| FR-BAK.2 | `backup` writes the same snapshot on demand and prints its path. | Must |
| FR-BAK.3 | A snapshot is JSON with a format version and a checksum. It is created with owner-only permissions and never overwrites an existing file. Reading verifies version and checksum and fails on mismatch (RVQ-Q6). | Must |
| FR-BAK.4 | `restore [BACKUP]` takes a path, a name, or defaults to the latest. Without `--yes` it prints the plan backup → live and refuses. With `--yes` it first writes a snapshot of the current live state and prints its path, aborting before any write if the snapshot cannot be written; then it applies the backup (deleting filters created after it), re-reads live state, and reports success only when the diff against the backup is empty; otherwise it prints the remaining diff and exits non-zero. Filters created after the backup are deleted by restore and shown in the plan (RVQ-Q21). | Must |
| FR-BAK.5 | `backup-diff A B` compares two snapshots and prints the plan-style difference (RVQ-Q6). | Should |

### FR-RETRO — Retroactive run

| ID | Requirement | Priority |
|---|---|---|
| FR-RETRO.1 | `apply-retroactive NAME` runs `filters apply` for one live filter. Before running it prints a read-only preview of the existing messages it would act on: count, and per message date, sender, subject, current location and action. Spam is excluded (RVQ-Q7). | Must |
| FR-RETRO.2 | The preview evaluates only `address`/`header` tests on from, to and subject, `fileinto`, flags and `expire`. A filter using anything else is reported as not previewable, never guessed. The typed confirmation still gates the run (RVQ-Q8). | Must |
| FR-RETRO.3 | The run requires the operator to type back the filter name and a reason. It cannot be cancelled once started. The filter name and reason are audit-logged. When the named filter's declared content differs from live, the preview warns that the run uses the live script; it does not block (RVQ-Q23). | Must |
| FR-RETRO.4 | A confirmed run saves its preview as a snapshot; snapshots older than 10 days are deleted when a new one is written. `retroactive-status [SNAPSHOT]` compares the current preview with a snapshot and reports done / pending / unexpected. | Must |
| FR-RETRO.5 | `retroactive-audit` reports, for each enabled filter, how many existing messages a run would change, with notes for approximate or not-previewable filters. Read-only; one audit check. | Should |

### FR-CLI — Interfaces

| ID | Requirement | Priority |
|---|---|---|
| FR-CLI.1 | The CLI `sieve-as-code` provides `discover`, `plan`, `apply`, `import`, `backup`, `backup-diff`, `restore`, `apply-retroactive`, `retroactive-status`, `retroactive-audit` (RVQ-Q13). | Must |
| FR-CLI.2 | The package `sieve_as_code` exposes a documented function for every CLI command (discover, plan, apply, import, backup, backup-diff, restore, and the three retroactive commands) plus load/validate; the CLI is a thin wrapper over them (RVQ-Q14). Anything not documented is internal. | Must |
| FR-CLI.3 | Configuration comes from environment variables: `SIEVE_AS_CODE_FILTERS_DIR` (default `$XDG_CONFIG_HOME/sieve-as-code`, else `~/.config/sieve-as-code`; root; per account `<root>/<account>/filters/*.yaml` and `<root>/<account>/order.yaml`), `SIEVE_AS_CODE_STATE_DIR` (default `$XDG_STATE_HOME/sieve-as-code`, else `~/.local/state/sieve-as-code`; root; per account `<root>/<account>/backups/`, `retroactive/`, `audit.log`), `SIEVE_AS_CODE_ACCOUNT` (default account) and `SIEVE_AS_CODE_PROTON_CLI` (binary, default `proton`) (RVQ-Q11, RVQ-Q18, RVQ-Q24). The repository ships a `.env.example` listing them; the tool has no `.env` loader (RVQ-Q22). | Must |

---

## Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-SAFE.1 | No write to Proton occurs without a preceding plan output and an explicit `--yes` (or the typed confirmation of FR-RETRO.3). |
| NFR-SAFE.2 | No filter content, sender or domain list is written to the audit log or logs. Terminal error messages carry only the first line of `proton`'s own diagnostic, capped at 200 characters (RVQ-Q25). Audit lines hold names, counts, action, outcome and timestamp only (RVQ-Q10). |
| NFR-SAFE.3 | The audit log is append-only JSONL: timestamp, kind (`write` or `check`), outcome, detail. |
| NFR-REL.1 | Re-running `apply` with no changes produces an empty plan and no writes. |
| NFR-REL.2 | An active `proton-cli` session is checked before any command that calls `proton-cli`; its absence fails loudly and never prompts interactively (`--no-input`). |
| NFR-REL.3 | `proton-cli` version: the tested range is `>=4.3.0` (the version verified at specification time), documented in the README and defined in code. Below it the tool warns on stderr (detected vs tested) and continues; newer versions run silently; an unreadable version also warns and continues. Unparseable output or a rejected command fails with a `proton-cli` error (RVQ-Q9). |
| NFR-OPS.1 | Errors name the file, field or command that failed and what to do next. |
| NFR-TEST.1 | pytest with Hypothesis for parsing, validation and plan logic; `proton-cli` is faked only at its single subprocess boundary; no live-account tests in CI. A manual smoke test against a free account is optional (RVQ-Q15, RVQ-Q18). |
| NFR-TEST.2 | An opt-in live smoke suite (`tests/live/`, skipped unless `SIEVE_AS_CODE_LIVE_TEST=1`, run against one named account) exercises create, update, enable/disable, reorder, backup, restore and `.sieve` import using only throwaway filters named with the reserved prefix `sieve-as-code-test-`. Each test deletes what it created in a `finally` block; the suite refuses to start if it cannot list filters and never touches a filter without the prefix (RVQ-Q19). |
| NFR-DEP.1 | Runtime dependencies: PyYAML only unless a gap is shown; pinned versions; versions, maintenance status and advisories checked before adding any. |

---

## Constraints

| ID | Constraint |
|---|---|
| CON-1 | `proton-cli` is the only backend; it is unofficial, unaudited and stores a session on disk (`concept.md`). |
| CON-2 | `filters apply` is asynchronous over the full mailbox with no progress, cancel or scope preview (`concept.md`). |
| CON-3 | Default-allow filtering only: act on positively identified patterns, or label without hiding (`concept.md`). |
| CON-4 | One account per command; single operator. No staging account is assumed; an optional free account may be used for manual smoke tests (RVQ-Q18). |
| CON-5 | Python ≥3.12, tested on 3.12–3.14 (RVQ-Q12). |

---

## Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Language | Python ≥3.12 | RVQ-Q12 |
| Packaging | `uv`, `pyproject.toml`, console script | RVQ-Q12 |
| Config format | YAML (PyYAML) | Reviewable diffs; multi-line Sieve as literal blocks |
| CLI | `argparse` (stdlib) | quality-simplicity: stdlib first |
| Testing | pytest, Hypothesis | RVQ-Q15 |
| Quality | ruff, black, mypy, vulture | python-conventions; unused-code gate |

---

## Out of Scope

- Any backend other than `proton-cli`; no provider abstraction.
- UI scraping, own SRP login, manual-paste upload.
- Mail features beyond filters (aliases, DNS, search, reading mail).
- A structured filter vocabulary; a filter's content is its Sieve script.
- Live-account tests in CI.
- Windows (Linux and macOS only; RVQ-Q24).

---

## Open Items

| Item | Status | Decision |
|---|---|---|
| Licence | Resolved | MIT |
| Package and CLI names | Resolved | RVQ-Q13 |
| Python and packaging | Resolved | RVQ-Q12 |
| Specs location | Resolved | `docs/` committed in this repo (RVQ-Q16) |
| Tested `proton-cli` version range | Resolved | `>=4.3.0`; raise the floor only if a later release breaks compatibility |
| Proton per-filter size limit value | Open | Measure with the live smoke suite (NFR-TEST.2); FR-DECL.6 stays on hold until then |

---

## Success Criteria

The requirements are satisfied when:

1. All "Must" items are implemented and pass tests.
2. `discover` output matches the live account; `plan` shows no diff when in sync and surfaces manufactured content and order diffs.
3. A second `apply` with no change writes nothing (NFR-REL.1).
4. `restore` from a backup returns live state to an empty diff (FR-BAK.4).
5. No write to Proton happens without `--yes` or the typed confirmation (NFR-SAFE.1).
6. Two accounts managed from one machine never read or write each other's files (FR-ACCT.2).
