# Business Logic Model — Unit 5: Backup

## Overview

`backup.py` writes the live filter state as a verified, owner-only snapshot, reads snapshots back with integrity and account checks, and diffs two snapshots. It adds `BackupError` to `model.py`. Nothing here writes to Proton; each backup is audited.

---

## Primary Workflows

### Workflow 1: Write a backup

```
AccountPaths, ProtonClient
    │
    ▼
[1] account and fingerprint check                 (BR-1)
    │        └─[ValidationError] nothing read or written
    ▼
[2] discover                                      (BR-2, BR-7)
    │        └─[ClientError] propagate, nothing written
    ▼
[3] latest snapshot equals live state?            (BR-14)
    │        └─[yes] audit `check` "unchanged", return it     (BR-15)
    ▼
[4] build document, compute checksum             (BR-3, BR-4)
    ▼
[5] mkdir 0o700, create <timestamp>.json 0o600 exclusively   (BR-5)
    │        └─[exists / I/O] BackupError
    ▼
[6] write and flush
    │        └─[I/O] remove partial file, BackupError      (BR-6)
    ▼
[7] audit `write` "backup"                      (BR-8)
    │        └─[audit I/O] SieveAsCodeError, snapshot kept
    ▼
Snapshot (path, state)
```

### Workflow 2: Read a backup

```
ref (None | existing file | name), AccountPaths, expected fingerprint
    │
    ▼
[1] resolve to a file                             (BR-9)
    │        └─[none / missing] BackupError
    ▼
[2] read, parse, format, keys, checksum, types, unique names   (BR-10)
    │        └─[any] BackupError naming file and check
    ▼
[3] fingerprint equals expected                   (BR-10, BR-13)
    │        └─[differs] BackupError naming both fingerprints
    ▼
Snapshot(path, created, account, fingerprint, state)           (BR-11)
```

### Workflow 3: Diff two backups

```
ref a, ref b, AccountPaths
    │
    ▼
[1] expected fingerprint from paths.account_marker             (BR-12)
    │        └─[missing / unreadable] BackupError
    ▼
[2] read_backup a, read_backup b                  (Workflow 2)
    ▼
[3] diff(b.state, a.state, None)                  (BR-12, Unit 4 BR-19)
    ▼
PlanResult: A → B
```

### Workflow 4: Prune

```
AccountPaths, Retention (keep_days, keep_last)
    │
    ▼
[1] list candidate files by name pattern          (BR-16)
    │        └─[nothing set / no directory] return ()
    ▼
[2] keep newest N, within D days, and the newest  (BR-17)
    ▼
[3] remove the rest                               (BR-18)
    │        └─[I/O] audit removed so far, BackupError
    ▼
[4] audit `write` "prune" if any removed          (BR-18)
    ▼
removed names
```

---

## Data Structures

```
Snapshot (frozen dataclass)
  path: Path           — file it was written to or read from
  created: str         — UTC ISO 8601 with Z
  account: str         — profile name when written (informational, BR-13)
  fingerprint: str     — 12 hex characters
  state: FilterSet     — filters in execution order, live_id None, renames
  unchanged: bool      — True when an existing snapshot was returned instead of a new file (BR-14)

Snapshot file (JSON, BR-3)
  { "format": 1, "created": str, "account": str, "fingerprint": str,
    "filters": [ { "name": str, "raw_sieve": str, "enabled": bool }, ... ],
    "renames": [ { "original": str, "name": str }, ... ],
    "checksum": str }

BackupError(SieveAsCodeError)  — snapshot unreadable, tampered, unsupported, of another
                                 account, missing, or not writable (CLI exit code 1)
```

Functions: `write_backup(paths, client) -> Snapshot`, `prune_backups(paths, keep: Retention) -> tuple[str, ...]` (`Retention` from Unit 1 BR-15), `read_backup(ref, paths, fingerprint) -> Snapshot`, `diff_backups(a, b, paths) -> PlanResult`; `ref` is `str | Path | None` (`None` only for `read_backup`).

---

## Error Handling

| Condition | Response | Severity |
|-----------|----------|----------|
| Wrong account or unconnected client | `ValidationError` (BR-1) | Error |
| `proton` read fails | `ClientError` propagates (BR-7) | Error |
| Backups directory or file cannot be created or written | `BackupError`, partial file removed (BR-5, BR-6) | Error |
| Latest snapshot unreadable or another account's | New backup taken (BR-14) | Info |
| A file cannot be removed while pruning | `BackupError` naming it, after auditing the removals so far (BR-18) | Error |
| Audit line cannot be written | `SieveAsCodeError`, snapshot kept (BR-8) | Error |
| Timestamp name already exists | `BackupError`, existing file untouched (BR-5) | Error |
| No backups, or named file missing | `BackupError` (BR-9) | Error |
| Unreadable, malformed, unknown `format`, bad checksum, bad field | `BackupError` naming file and check (BR-10) | Error |
| Fingerprint differs from the account's | `BackupError` naming both (BR-10, BR-13) | Error |
| Marker missing or unreadable in `diff_backups` | `BackupError` (BR-12) | Error |

---

## Edge Cases

- Empty live account: a valid snapshot with empty `filters`.
- Duplicate live names: stored numbered with `renames`; a restore (Unit 6) therefore recreates a deleted one under its numbered name.
- Whitespace edits to the file (indentation, key order) keep the checksum valid; changing any value does not.
- A→B→A: the third backup is written; only the latest snapshot is compared (BR-14).
- Pruning with only `keep_days` and every file older: the newest file stays (BR-17).
- Two backups in the same microsecond: the second fails (BR-5); the caller may retry.

---

## Contract with Other Units

### Consumes
- Unit 1: `AccountPaths.backups_dir`, `account_marker`, `Retention` and `retention()`; `SieveAsCodeError`, `ValidationError`.
- Unit 2: `ProtonClient` (`account`, `fingerprint`).
- Unit 4: `discover`, `diff` (snapshot mode), `PlanResult`.

### Provides
- Unit 6: `write_backup` (audited) for the pre-write and pre-restore snapshots (FR-BAK.1, FR-BAK.4); `read_backup(None | ref, paths, client.fingerprint)` for restore; `Snapshot.state` as the `diff` input for verification.
- Unit 9: `write_backup`, `diff_backups`, `prune_backups`, `BackupError` as public API (FR-CLI.2); the `backup` command prunes after each run with `retention()` limits or its flags.

---

## Test Strategy

| BR/Property | Test Type | Assertion | Planned File |
|-------------|-----------|-----------|--------------|
| BR-1 | Unit | other account, or client without fingerprint → `ValidationError`, no calls, no file | `tests/unit/test_backup.py` |
| BR-2, BR-3 | Unit | snapshot holds live filters in order with numbered duplicates and `renames`; no `live_id`; exact keys | `tests/unit/test_backup.py` |
| Roundtrip | PBT | for any `FilterSet`, `write_backup` then `read_backup` returns an equal `state` (live_id None) | `tests/unit/test_backup.py` |
| BR-4 | PBT | changing any single value of a written document without recomputing the checksum → `BackupError` | `tests/unit/test_backup.py` |
| BR-5 | Unit | file mode `0o600`, directory `0o700`; pre-existing file with the same name → `BackupError`, content unchanged | `tests/unit/test_backup.py` |
| BR-6 | Unit | write failure (injected at the file boundary) → no file left; removal failure named | `tests/unit/test_backup.py` |
| BR-7 | Unit | `ClientError` propagates, no file, no audit line | `tests/unit/test_backup.py` |
| BR-8 | Unit | one `write`/`backup` line with `file`, `filters`, `renamed` and no names or content; audit failure raises, snapshot kept | `tests/unit/test_backup.py` |
| BR-14 | Unit | second backup of unchanged state returns the same path, `unchanged` true, one file; changed script, `enabled`, order or a new duplicate name → new file; A→B→A writes a third; corrupt or foreign latest → new file | `tests/unit/test_backup.py` |
| BR-15 | Unit | skip appends one `check`/`unchanged` line; audit failure raises | `tests/unit/test_backup.py` |
| BR-16 | Unit | unmatched names, directories and invalid dates untouched; nothing set → nothing removed; missing directory → `()` | `tests/unit/test_backup.py` |
| BR-17 | Unit + PBT | `keep_last` only, `keep_days` only (23 h kept, 25 h removed), both (union), newest never removed; PBT: removed set equals an independent calculation | `tests/unit/test_backup.py` |
| BR-18 | Unit | one `write`/`prune` line with counts and no line when nothing removed; removal failure raises after auditing the earlier removals | `tests/unit/test_backup.py` |
| BR-9 | Unit | `None` → latest of several; existing file; name with and without `.json`; empty directory; missing name | `tests/unit/test_backup.py` |
| BR-10 | Unit | one case per check: unreadable, not JSON, not an object, missing/extra key, `format` 2, bad checksum, wrong field type, duplicate names, other fingerprint; messages carry no script text | `tests/unit/test_backup.py` |
| BR-11 | Unit | `diff(snapshot.state, snapshot.state, None)` is clean | `tests/unit/test_backup.py` |
| BR-12 | Unit | added filter → `create`, removed → `live-only`, changed script → `content`, moved → `reorder`; missing marker → `BackupError`; no client call | `tests/unit/test_backup.py` |
| Mirror | PBT | `diff_backups(a, b)` `create` names equal `diff_backups(b, a)` `live-only` names | `tests/unit/test_backup.py` |
| BR-13 | Unit | same fingerprint with another account name is accepted | `tests/unit/test_backup.py` |
| `BackupError` | Unit | subclass of `SieveAsCodeError` | `tests/unit/test_model.py` |

Lenses: **boundary** — empty set, one filter, `None`/name/path refs, empty directory, name collision; **parity** — write/read and `diff(a,b)`/`diff(b,a)` mirrors; **derived** — order comes from `filters`, so no order/filter mismatch can exist, duplicate names are rejected on read; **emergent** — write after discover numbering, latest after several writes, a backup diffed with itself is clean; **invariants** — roundtrip and tamper PBTs above. Nothing waived.
