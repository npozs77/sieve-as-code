# Business Logic Model — Unit 6: Apply and restore

## Overview

`apply.py` turns a plan of declared against live state into ordered Proton writes with stop-on-failure accounting; `restore.py` does the same for a snapshot and then proves the result. Both snapshot first, audit every write, and write only with explicit confirmation. `apply.py` owns the shared engine; `restore.py` reuses it. No new errors: failures are in the report, setup errors are `ValidationError`, `ClientError`, `BackupError`.

---

## Primary Workflows

### Workflow 1: Apply

```
AccountPaths, ProtonClient, confirmed, allow_delete
    │
    ▼
[1] account and fingerprint check                 (BR-1)
    │        └─[ValidationError] nothing read, written, audited
    ▼
[2] load declared, discover, targets, diff        (BR-2)
    │        └─[ValidationError / ClientError] propagate, no write
    ▼
[3] nothing to write?                             (BR-3)
    │        └─[yes] ok, empty report
    ▼
[4] not confirmed?                                (BR-4)
    │        └─[yes] audit `check` refused, report refused=True
    ▼
[5] write_backup, read_backup                     (BR-5)
    │        └─[error] raise, no write
    ▼
[6] build actions                                 (BR-6, BR-7, BR-9)
    ▼
[7] run engine (Workflow 3)                       (BR-10 to BR-12)
    ▼
ApplyReport                                       (BR-13)
```

### Workflow 2: Restore

```
ref, AccountPaths, ProtonClient, confirmed
    │
    ▼
[1] account and fingerprint check                 (BR-15 → BR-1)
    ▼
[2] read_backup(ref, ..., fingerprint)            (BR-15)
    │        └─[BackupError] propagate, nothing read live or written
    ▼
[3] discover, diff(snapshot.state, live, None)    (BR-16)
    ▼
[4] nothing to write?                             (BR-18) → ok, remaining None
    ▼
[5] not confirmed?                                (BR-19) → audit refused, refused=True
    ▼
[6] pre-restore write_backup, read_backup         (BR-20)
    │        └─[error] raise, no write
    ▼
[7] build actions: creates, content, enabled, deletes, reorder   (BR-17)
    ▼
[8] run engine (Workflow 3)
    │        └─[failure] report without remaining
    ▼
[9] discover again, diff against snapshot         (BR-21)
    │        └─[ClientError] failed "verify live"
    ▼
[10] audit `check` verified | drift               (BR-22)
    ▼
RestoreReport(remaining)
```

### Workflow 3: Run actions (engine, in `apply.py`)

```
list of (Action, step) in order; command "apply" | "restore"
    │
    ▼
for each: step()                                  (BR-6)
    │   ├─[ok]          succeeded += action
    │   └─[ClientError] failed = action, reason   (BR-10)
    ▼
audit `write` ok | failed                         (BR-11)
    │   └─[audit error] audit_error, stop         (BR-12)
    ▼
stop at first failure or audit error: rest → not_attempted
```

`step` is a closure over the client and a shared `ids` map (name → live id, filled from `discover` and from `create_filter` results, BR-7). Folder steps list folders at run time (BR-8).

---

## Data Structures

```
ActionKind = "folder" | "label" | "create" | "content" | "enabled"
           | "disable" | "delete" | "reorder" | "verify"

Action (frozen)        kind: ActionKind; name: str        — "order" for reorder, "live" for verify
FailedAction (frozen)  action: Action; reason: str        — reason from ClientError (NFR-SAFE.2)

ApplyReport (frozen)
  plan: PlanResult                     — what was planned (flags, informational, renames included)
  refused: bool = False                — writes planned, not confirmed (BR-4)
  snapshot: Snapshot | None = None     — pre-write snapshot (BR-5)
  succeeded: tuple[Action, ...] = ()
  failed: FailedAction | None = None
  not_attempted: tuple[Action, ...] = ()
  audit_error: str | None = None       — BR-12
  ok: property                         — BR-13

RestoreReport(ApplyReport)
  remaining: PlanResult | None = None  — diff against the backup after the run (BR-21)
  ok: property                         — BR-21
```

Functions: `apply_plan(paths, client, confirmed, allow_delete) -> ApplyReport`; `restore(ref, paths, client, confirmed) -> RestoreReport` (`ref: str | Path | None`); internal `run_actions` in `apply.py`. `disable` is the `live-only` action without `allow_delete`; `delete` with it or in restore; `enabled` covers enable and disable by value.

---

## Error Handling

| Condition | Response | Severity |
|-----------|----------|----------|
| Wrong account or unconnected client | `ValidationError` (BR-1) | Error |
| Declared files invalid, unreadable `fileinto` target | `ValidationError` propagates, no write (BR-2) | Error |
| `proton` read fails before writing | `ClientError` propagates, no write (BR-2) | Error |
| Not confirmed | Report `refused`, audit `refused` (BR-4, BR-19) | Info |
| Snapshot cannot be written or re-read | `BackupError` or `SieveAsCodeError` raised, no write (BR-5, BR-20) | Error |
| Snapshot to restore missing, altered, foreign | `BackupError` before any live read (BR-15) | Error |
| A write is rejected or `proton` fails | `failed` action, rest `not_attempted`, no rollback (BR-10) | Error |
| Parent folder not found when creating a nested folder | That action fails (BR-8, BR-10) | Error |
| Audit line cannot be written | `audit_error` in the report, run ends (BR-12) | Error |
| Re-read after restore fails | `failed` "verify live" (BR-21) | Error |
| Live state differs from the backup after restore | `remaining` set, `ok` false (BR-21) | Error |

---

## Examples and Edge Cases

- Second `apply` after success: clean plan, no snapshot, no writes (BR-3).
- Declared adds `b` (enabled) and moves it first: actions `create b`, `reorder` with ids of `b` (new) then the others (BR-6, BR-7).
- Plan with a failing second create: first create `succeeded`, second `failed`, remaining creates and the reorder `not_attempted`; the snapshot path is in the report.
- `apply` with a live-only filter: `disable`; with `allow_delete`: `delete`. A disabled live-only filter is untouched by `apply` (informational).
- Restore after a deleted filter, an edited script and a new live filter: `create`, `content`, `delete`, `reorder`; verification must be clean.
- Restore when a disabled filter was added after the backup: it is deleted too (BR-16).
- Restore of a snapshot taken with duplicate names recreates a missing one under its numbered name (Unit 5).
- A flagged filter (`vnd.proton.expire`) is written after confirmation; the flag is in `plan` (BR-14).
- A restore target `fileinto` folder deleted since the backup: Proton rejects the create; reported as `failed` (BR-10). Targets are not recreated by restore.
- Reorder is the last action, so a failed create leaves order untouched (BR-6).

---

## Contract with Other Units

### Consumes
- Unit 1: `AccountPaths` (`audit_log`, `account`), `record_write`, `record_check`, `SieveAsCodeError`, `ValidationError`.
- Unit 2: `ProtonClient` write methods, `list_folders`; `ClientError`.
- Unit 3: `load_declared`.
- Unit 4: `discover`, `discover_targets`, `diff`, `PlanResult`, `PlanEntry`, `Reorder`.
- Unit 5: `write_backup`, `read_backup`, `Snapshot`, `BackupError`.

### Provides
- Unit 9: `apply_plan` and `restore` with `ApplyReport`, `RestoreReport`, `Action`, `FailedAction` as public API (FR-CLI.2); the CLI prints the report's plan before asking for `--yes`, prints the snapshot path, and maps `ok` false to a non-zero exit.
- Unit 8 (retroactive) is independent of this unit.

---

## Test Strategy

Stateful fake: `tests/fake_proton.py` is extended (if it lacks it) so created, updated, deleted, enabled and reordered filters change what later `list`/`get` return; failures are injected per command at the subprocess boundary.

| BR/Property | Test Type | Assertion | Planned File |
|-------------|-----------|-----------|--------------|
| BR-1, BR-15 | Unit | other account or client without fingerprint → `ValidationError`, no call, no audit | `tests/unit/test_apply.py`, `test_restore.py` |
| BR-2 | Unit | invalid declared or unreadable target → error, no write command, no snapshot | `tests/unit/test_apply.py` |
| BR-3, BR-18 | Unit | clean plan → no snapshot file, no write command, no audit line, `ok` | both |
| BR-4, BR-19 | Unit | not confirmed → no write, no snapshot, one `check`/`refused` line, plan in report | both |
| BR-5, BR-20 | Unit | snapshot exists and verifies before the first write command; unwritable or corrupt snapshot → raised, zero writes; unchanged state reuses the latest snapshot | both |
| BR-6, BR-7 | Unit | order folder-parent, folder, label, create, content, enabled, live-only, reorder; scripts only on stdin; reorder ids include a just-created filter; unchanged filters get no write | `tests/unit/test_apply.py` |
| BR-8 | Unit | nested folder creates parent first and passes its id; missing parent → `failed` | `tests/unit/test_apply.py` |
| BR-9 | Unit | live-only → disable; `allow_delete` → delete; disabled live-only untouched | `tests/unit/test_apply.py` |
| BR-10 | Unit | failure at each position: earlier `succeeded`, one `failed` with reason (first line, ≤200), rest `not_attempted`, no further call | `tests/unit/test_apply.py` |
| BR-11 | Unit | one `write` line per action with kind, name, `exit_code` on failure; no script text or reason in the log | both |
| BR-12 | Unit | audit write failure → report returned, `audit_error` set, rest `not_attempted` | both |
| BR-13, idempotence | PBT | for any declared/live pair, `apply_plan(confirmed, allow_delete)` on the stateful fake then `diff` has no entry and no reorder | `tests/unit/test_apply.py` |
| BR-14 | Unit | flagged filter is written; report plan holds the flag | `tests/unit/test_apply.py` |
| BR-15 | Unit | `BackupError` for missing, tampered, foreign snapshot before any live call | `tests/unit/test_restore.py` |
| BR-16, BR-17 | Unit | edited, removed, added-enabled and added-disabled live filters and a moved filter → `create`, `content`, `delete`, `delete`, `reorder`; numbered duplicate recreated under its numbered name | `tests/unit/test_restore.py` |
| Roundtrip | PBT | `write_backup`, arbitrary live mutation, `restore(confirmed)` → live state equals the snapshot state (names, scripts, `enabled`, order) and the report is `ok` | `tests/unit/test_restore.py` |
| BR-21 | Unit | clean `remaining` → `ok`; injected rejection of a create → not `ok`, no verify; live changed by the fake mid-run → `remaining` has entries and `ok` false; verify read failure → `failed` "verify live" | `tests/unit/test_restore.py` |
| BR-22 | Unit | `check`/`verified` or `drift` line with counts; audit failure sets `audit_error` | `tests/unit/test_restore.py` |
| Public types | Unit | reports are frozen; `RestoreReport` is an `ApplyReport` | `tests/unit/test_apply.py` |

Lenses: **boundary** — empty declared, empty live, one filter, failure at first and last action, reorder-only plan; **parity** — apply then plan is clean, restore then diff-to-backup is empty; **derived** — action list is derived from the plan, ids from live state and create results; **emergent** — snapshot then apply then restore of that snapshot; failure then re-run completes the rest; **invariants** — no write without confirmation, no write before a verified snapshot, no deletion in `apply` without `allow_delete`. Nothing waived.
