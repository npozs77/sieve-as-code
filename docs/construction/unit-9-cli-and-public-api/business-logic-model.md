# Business Logic Model — Unit 9: CLI and public API

## Overview

`__init__.py` holds the keyword-only, account-resolving wrappers (BR-2, BR-3) and `__all__` (BR-1); `cli.py` parses argv, calls only those wrappers, renders results and maps outcomes to exit codes (BR-6). The internal modules are renamed with a leading underscore first (BR-17). `backup` gains retention pruning (BR-5). Class-free; no new dependency (`argparse`, `importlib.metadata`).

---

## Public API (BR-1 to BR-5)

| Function | Signature | Wraps |
|---|---|---|
| `discover` | `(*, account=None) -> FilterSet` | `_live.discover` |
| `plan` | `(*, account=None) -> PlanResult` | `_plan.plan` |
| `apply` | `(*, account=None, confirmed=False, allow_delete=False) -> ApplyReport` | `_apply.apply_plan` |
| `import_live` | `(name=None, *, account=None, force=False) -> ImportReport` | `_importer.import_live` |
| `import_sieve_files` | `(sources, *, account=None, force=False) -> ImportReport` | `_importer.import_sieve_files` |
| `backup` | `(*, account=None, keep_days=None, keep_last=None) -> Snapshot` | `_backup.write_backup`, `prune_backups` |
| `backup_diff` | `(a, b, *, account=None) -> PlanResult` | `_backup.diff_backups` |
| `restore` | `(ref=None, *, account=None, confirmed=False) -> RestoreReport` | `_restore.restore` |
| `retroactive_preview` | `(name, *, account=None) -> RetroPreview` | `_retroactive.preview` |
| `apply_retroactive` | `(name, *, confirmed_name, reason, account=None) -> RetroReport` | `_retroactive.run` |
| `retroactive_status` | `(ref=None, *, account=None) -> RetroStatus` | `_retroactive.status` |
| `retroactive_audit` | `(*, account=None) -> RetroAudit` | `_retroactive.audit_all` |
| `load_declared` | `(*, account=None) -> FilterSet` | `_declared.load_declared` |
| `validate_declared` | `(declared) -> None` | `_declared.validate_declared` |

`apply_retroactive` takes `confirmed_name` and `reason` keyword-only and without defaults: a caller cannot run by omission. Re-exported types: `Filter`, `FilterOrder`, `FilterSet`, `Rename`, `PlanResult`, `PlanEntry`, `Reorder`, `MissingTarget`, `Flag`, `ApplyReport`, `Action`, `FailedAction`, `RestoreReport`, `ImportReport`, `Snapshot`, `RetroPreview`, `Entry`, `RetroReport`, `RetroStatus`, `Unexpected`, `RetroAudit`, `AuditRow`; errors `SieveAsCodeError`, `ValidationError`, `ClientError`, `BackupError`; `__version__`.

```
_session(account) -> (AccountPaths, ProtonClient)      private; resolve, account_paths, connect (BR-2)
```

### Backup with retention (BR-5)

```
keep_days, keep_last
    │
    ▼
[1] validate arguments                       └─[<1 / not int] ValidationError
[2] paths, client = _session(account)
[3] snapshot = write_backup(paths, client)   └─[BackupError, ClientError] propagate
[4] limits = Retention(keep_days or env, keep_last or env)
[5] both None → return snapshot
[6] prune_backups(paths, limits)             └─[BackupError] snapshot with prune_error
    ▼
replace(snapshot, pruned=names)
```

---

## CLI (BR-6 to BR-15)

```
argv → argparse → handler(args) → wrapper(...) → render(result) → exit code
                      └─[SieveAsCodeError] "error: MESSAGE" on stderr → 1, or 2 for ValidationError
```

| Command | Arguments | Calls | Exit 0 when | Rules |
|---|---|---|---|---|
| `discover` | | `discover` | printed | BR-12 |
| `plan` | | `plan` | no drift (drift exits 1) | BR-7 |
| `apply` | `--yes`, `--allow-delete` | `apply` | report `ok` | BR-8 |
| `import` | `[NAME] [--force]` or `--sieve FILE...` | `import_live`, `import_sieve_files` | not refused | BR-13 |
| `backup` | `--keep-days N`, `--keep-last N` | `backup` | written, or unchanged | BR-5 |
| `backup-diff` | `A B` | `backup_diff` | printed | BR-7 |
| `restore` | `[BACKUP] --yes` | `restore` | report `ok` | BR-8 |
| `apply-retroactive` | `NAME` | `retroactive_preview`, `apply_retroactive` | nothing to do, or report `ok` | BR-9 |
| `retroactive-status` | `[SNAPSHOT]` | `retroactive_status` | printed | BR-7 |
| `retroactive-audit` | | `retroactive_audit` | printed | BR-7 |

Every subcommand also takes `--account NAME` (BR-14).

### Workflow: `apply-retroactive` (BR-9, BR-10)

```
NAME
  │
  ▼
[1] preview = retroactive_preview(NAME)       └─[error] error line, exit 1/2
[2] print banner, preview, warnings           (declared_differs, approximate, reason, spam_excluded)
[3] previewable and no entries → "nothing to do", exit 0
[4] prompt name, reason (stdin; EOF = "")
[5] report = apply_retroactive(NAME, confirmed_name=…, reason=…)
[6] refused → "not confirmed; nothing changed", exit 1
    failed / audit_error → message, exit 1
    started → snapshot path (if any), exit 0
```

The library re-previews inside step 5 (Unit 8 BR-17), so the run acts on the mailbox as it is then, not as step 2 printed it.

### Rendering (BR-10, BR-11)

One private `_render_*` function per result type returning text; handlers print it. `_banner(paths)` reads `paths.account_marker` after the wrapper returned.

---

## Data Structures

No new dataclasses. `Snapshot` gains `pruned: tuple[str, ...] = ()` and `prune_error: str | None = None` (BR-4). The CLI keeps argparse's `Namespace`.

---

## Error Handling

| Condition | Response | Severity |
|---|---|---|
| Invalid account name, declared file, `--keep-*` value, unknown or disabled filter | `ValidationError` → `error:` line, exit 2 | Error |
| `proton` failure, snapshot problem, audit write failure raised | `error:` line, exit 1 | Error |
| Unconfirmed `apply` / `restore` / retroactive run | Plan or preview printed, refusal line, exit 1 | Info |
| Failed or partial write | Report printed (succeeded, failed, not attempted), exit 1 | Error |
| `restore` with a remaining diff | Diff printed, exit 1 | Error |
| Usage error | argparse message, exit 2 | Error |
| Ctrl-C | `interrupted` on stderr, exit 130 | Info |
| Prune failure after `backup` | `warning: prune failed: …` on stderr, exit 0 | Warning |

---

## Examples and Edge Cases

- `sieve-as-code plan` with drift → prints entries with each script (a unified diff for a change), exit 1; clean → exit 0 (BR-7, BR-11).
- `sieve-as-code apply` → plan, `nothing written; re-run with --yes`, exit 1; with an empty plan → no refusal, exit 0 (Unit 6).
- `sieve-as-code backup --keep-last 0` → usage error, exit 2 before any Proton call (BR-5, BR-14).
- `SIEVE_AS_CODE_KEEP_LAST=5` and `--keep-days 30` → keep-last from the variable, keep-days from the flag (BR-5).
- `apply-retroactive Newsletters` piped from `/dev/null` → preview, empty answers, refused, audit `refused`, exit 1 (BR-9).
- `import Rules --sieve a.sieve` → usage error (BR-13).
- Account `../x` → `ValidationError`, exit 2, nothing built (FR-ACCT.5).

---

## Contracts with Other Units

### Consumes
Units 1–8 through the renamed internal modules: `resolve_account`, `account_paths`, `retention`, `connect`, `discover`, `plan`, `apply_plan`, `restore`, `import_live`, `import_sieve_files`, `write_backup`, `diff_backups`, `prune_backups`, `preview`, `run`, `status`, `audit_all`, `load_declared`, `validate_declared`, `render`.

### Provides
The documented surface (BR-1) and the `sieve-as-code` command. Operations will deploy and invoke these.

---

## Test Strategy

`tests/unit/test_api.py` drives the wrappers over the `fake_proton` fixture and `work_account`; `tests/unit/test_cli.py` calls `main([...])` with `capsys`, `monkeypatch` for stdin and env.

| BR/Property | Test Type | Assertion | Planned File |
|---|---|---|---|
| BR-1 | Unit | `__all__` equals the documented set; each name resolves; no other non-underscore module than `cli`; each public function has a docstring | `tests/unit/test_api.py` |
| BR-2 | Unit + PBT | via `inspect`: parameters after the subject are keyword-only; `account` resolves from env, argument, default; invalid account → `ValidationError`; offline functions make no `proton` call | `tests/unit/test_api.py` |
| BR-3 | Unit | `apply`, `restore`, `import_live` without confirmation write nothing; `apply_retroactive` without `confirmed_name` or `reason` → `TypeError` | `tests/unit/test_api.py` |
| BR-4 | Unit | results frozen; `Snapshot` defaults for the new fields; `load_declared` → `FilterSet`; `validate_declared` raises on bad input | `tests/unit/test_api.py` |
| BR-5 | Unit + PBT | argument over env per field; none → no prune; 0 or `"3"` → `ValidationError` before a call; prune failure → `prune_error`, snapshot kept; unchanged backup still prunes; `apply` snapshot never prunes | `tests/unit/test_api.py` |
| BR-6 | Unit | exit 0 / 1 / 2 / 130 per outcome; `error:` line on stderr, no traceback, no script text | `tests/unit/test_cli.py` |
| BR-7 | Unit | `plan` drift → 1, clean → 0; backup differences, pending → 0; restore remaining diff → 1 | `tests/unit/test_cli.py` |
| BR-8 | Unit | no `--yes` → plan printed, refusal, exit 1, fake unchanged; `--yes` writes; `--allow-delete` only on `apply` | `tests/unit/test_cli.py` |
| BR-9 | Unit | exact name and reason run; wrong case → refused; EOF → refused; no entries → no prompt; prompt names account and fingerprint; no `--yes` option | `tests/unit/test_cli.py` |
| BR-10 | Unit | first line `account: work (fingerprint …)`; no marker → name alone; mismatch error has no banner | `tests/unit/test_cli.py` |
| BR-11 | Unit | script text in `discover` and in the plans of `plan`, `apply`, `restore`, `backup-diff` (diff labels); never in the audit log | `tests/unit/test_cli.py` |
| BR-12, BR-13 | Unit | discover text equals import's file text; renames listed; import refused → `changed` names, exit 1; `--sieve` imports; `NAME` plus `--sieve` → 2 | `tests/unit/test_cli.py` |
| BR-14, BR-15 | Unit | `--account` on every subcommand; `--keep-days 0` → 2; no command → 2; `--help`, `--version` → 0; `main` never raises `SystemExit`; entry point in package metadata resolves to `cli:main` | `tests/unit/test_cli.py` |
| BR-16 | Unit | `__version__` equals `pyproject.toml` | `tests/unit/test_api.py` |
| BR-17 | Regression | the 571 existing tests pass after the rename | existing files |
| BR-18 | Live | create, update, enable/disable, reorder, backup, restore, `.sieve` import, invalid script (exit 1, nothing left behind); skipped unless enabled; guard refuses a name without the prefix | `tests/live/test_smoke.py` |
| BR-19 | Review | README and CHANGELOG match the code at summary time | n/a |

Lenses: **boundary** — `--keep-*` 0, 1; no command; empty plan; EOF at prompt; **parity** — `discover` text equals `import` output; CLI and library give equal results; **derived** — exit code from report `ok`, banner from the marker; **emergent** — `backup --keep-last 1` over several runs, `plan` → `apply --yes` → `plan` clean through `main`; **invariants** — no write without confirmation, no script text outside `discover`, `main` returns an int. Nothing waived.
