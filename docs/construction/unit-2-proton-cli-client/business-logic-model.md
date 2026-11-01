# Business Logic Model — Unit 2: Proton CLI client

## Overview

`client.py` is the only module that starts `proton`. `connect` proves the session, version and account once; the returned `ProtonClient` then offers one method per Proton operation, each a single process call with parsed, typed results. Rules are in `business-rules.md` (BR-1–21).

---

## Primary Workflows

### Workflow 1: Connect

```
AccountPaths
    │
    ▼
[1] version probe: `proton --version`            (BR-8)
    │        └─[bad/old/unreadable] stderr warning, continue
    │        └─[binary missing] ClientError                     (BR-12)
    ▼
[2] `account get` as the profile                  (BR-1, BR-7)
    │        └─[exit 2] ClientError: sign in
    │        └─[other failure / bad shape] ClientError          (BR-10, BR-11)
    ▼
[3] fingerprint from `id`; marker read or created (BR-9)
    │        └─[mismatch / unreadable marker] ClientError
    ▼
ProtonClient(binary, account, fingerprint)
```

### Workflow 2: Run one operation (every method)

```
method arguments
    │
    ▼
[1] build argv (BR-1), script to stdin if any (BR-2)
    │
    ▼
[2] one subprocess.run, UTF-8, timeout            (BR-5, BR-12)
    │        └─[not found / timeout] ClientError
    ▼
[3] exit code ≠ 0 → ClientError with hint         (BR-10)
    │
    ▼
[4] parse stdout JSON, check keys and types       (BR-11, BR-13)
    │        └─[bad] ClientError
    ▼
typed result (or None for writes)
```

---

## Rules

Stated once in `business-rules.md`; cited here by ID.

---

## Data Structures

```
ProtonClient (frozen dataclass, client.py)
  binary: str
  account: str            — passed as --profile
  fingerprint: str        — 12 hex chars, set by connect

FilterRef (frozen dataclass)   live_id: str, name: str, enabled: bool
MailTarget (frozen dataclass)  id: str, name: str, path: str

ClientError(SieveAsCodeError)  (model.py)
  exit_code: int | None    — None for not-found, timeout, shape and fingerprint errors
```

Methods (all on `ProtonClient`; `connect` and `TESTED_MINIMUM` are module level):

```
connect(paths: AccountPaths) -> ProtonClient
list_filters() -> list[FilterRef]
get_filter(live_id: str) -> Filter
create_filter(name: str, raw_sieve: str, enabled: bool = True) -> str
update_filter(live_id: str, raw_sieve: str) -> None
delete_filter(live_id: str) -> None
enable_filter(live_id: str) -> None
disable_filter(live_id: str) -> None
reorder_filters(live_ids: Sequence[str]) -> None
list_folders() -> list[MailTarget]
list_labels() -> list[MailTarget]
create_label(name: str) -> None
create_folder(name: str, parent_id: str | None = None) -> None
list_messages(to: str | None = None) -> list[dict[str, Any]]
apply_retroactively(live_id: str) -> None
```

A class (not free functions) because the binary, profile and fingerprint are state shared by 15 methods; it replaces the free `check_*` / `list_*` rows of `component-methods.md`.

---

## Error Handling

| Condition | Response | Severity |
|-----------|----------|----------|
| Binary missing / timeout (BR-12) | `ClientError`, `exit_code` None | Error |
| Not signed in (BR-7) | `ClientError` with the login command | Error |
| Wrong account (BR-9) | `ClientError`, no `proton` call after it | Error |
| Non-zero exit (BR-10) | `ClientError` with `exit_code`, hint, first stderr line | Error |
| Unexpected output (BR-11, BR-13) | `ClientError`, stdout not echoed | Error |
| Old, unreadable or failing version probe (BR-8) | stderr warning, continue | Warning |
| `reorder_filters([])` (BR-18) | `ValueError` | Error |

Not audit-logged here: callers log. Session and version failures therefore leave no audit line (known, accepted at MVP in the inception review).

---

## Examples and Edge Cases

| Input | Result |
|-------|--------|
| `--version` → `proton version 4.3.0` | silent |
| `proton version 4.10.0` | silent (numeric, not text, comparison) |
| `proton version 4.2.9` | warning, continue |
| `--version` → `dev` | warning (unreadable), continue |
| marker absent | created, client returned |
| marker holds another fingerprint | `ClientError`; marker unchanged |
| `filters list` JSON with `has_more: true` | `ClientError` |
| script `"keep;\n# ünï 'q' \"d\""` | stdin carries it byte-identical; argv holds only `-` |
| `filters create` exit 1 | message holds the first stderr line (≤ 200 characters), never the script; callers log `exit_code` only |

---

## Contract with Other Units

### Consumes from Unit 1 — Foundation
- `AccountPaths.account` and `account_marker`, `proton_cli()`, `SieveAsCodeError`, `Filter`.

### Provides to Units 4, 5, 7, 8
- Unit 4/7: `connect`, `list_filters`, `get_filter`, `list_folders`, `list_labels`, `FilterRef`, `MailTarget`.
- Unit 5: `fingerprint` for snapshots, the reads above.
- Unit 6: `create_filter`, `update_filter`, `delete_filter`, `enable_filter`, `disable_filter`, `reorder_filters`, `create_label`, `create_folder`.
- Unit 8: `list_messages`, `apply_retroactively`, `get_filter`.
- All: the `fake_proton` fixture in `tests/conftest.py`, an in-memory `proton` that records calls and models filters, order, folders, labels and the account id.

---

## Test Strategy

The subprocess boundary is faked once, in `tests/conftest.py` (`fake_proton`, patching `subprocess.run`); no internal code is mocked.

| BR/Property | Test Type | Assertion | Planned File |
|-------------|-----------|-----------|--------------|
| BR-1 | Unit | argv prefix for a read and a write; version probe has no profile | `tests/unit/test_client.py` |
| BR-2 | PBT | for any script text: stdin equals it exactly, argv contains `-` after `--sieve` and not the script; same for `update_filter` (parity) | `tests/unit/test_client.py` |
| BR-2, BR-10 | Unit | a failing create: the message holds the first stderr line capped at 200 characters, never stdin; a longer line is cut | `tests/unit/test_client.py` |
| BR-3 | Unit | no recorded call over a full method sweep contains `--dry-run` | `tests/unit/test_client.py` |
| BR-4 | Unit | every read method and `connect` records only verbs `list`, `get`, `--version` | `tests/unit/test_client.py` |
| BR-5 | Unit | each method makes exactly one call; a failure is not repeated | `tests/unit/test_client.py` |
| BR-6 | Unit | `connect` call order; on a fingerprint mismatch no further call is made | `tests/unit/test_client.py` |
| BR-7 | Unit | exit 2 → error naming `account login` and the profile | `tests/unit/test_client.py` |
| BR-8 | PBT | for any `(maj, min, patch)`: warning iff below `(4, 3, 0)` | `tests/unit/test_client.py` |
| BR-8 | Unit | boundaries 4.2.9 / 4.3.0 / 4.3.1 / 4.10.0 / 5.0.0; `dev`, empty, exit 1, → warning and continue | `tests/unit/test_client.py` |
| BR-9 | PBT | fingerprint of any id is 12 lowercase hex and equals SHA-256[:12] | `tests/unit/test_client.py` |
| BR-9 | Unit | marker created `0o600`/`0o700` on first use; match passes; mismatch refuses; marker unchanged after mismatch; second `connect` passes | `tests/unit/test_client.py` |
| BR-10 | Unit | each exit code 1–7 and an unlisted one yields its hint and `exit_code` | `tests/unit/test_client.py` |
| BR-11, BR-13 | Unit | per parser (filters list/get/create, folders, labels, messages, account): non-JSON, list instead of object, missing key, wrong type, `has_more` → `ClientError`, stdout absent from message | `tests/unit/test_client.py` |
| BR-12 | Unit | missing binary names the variable; timeout names the seconds | `tests/unit/test_client.py` |
| BR-14, BR-15 | Unit | `status` 0 → disabled, 1 → enabled; order preserved; sieve verbatim | `tests/unit/test_client.py` |
| BR-16 | Unit | create returns `ids[0]`; `--disabled` only when `enabled=False`; empty ids → error | `tests/unit/test_client.py` |
| BR-17 | Unit | delete argv ends with `--yes` | `tests/unit/test_client.py` |
| BR-18 | Unit | reorder is one call with ids in order; empty → `ValueError` | `tests/unit/test_client.py` |
| BR-19 | Unit | `path` falls back to `name`; `--parent` only with a parent id; label and folder creates mirror each other | `tests/unit/test_client.py` |
| BR-20, BR-21 | Unit | `--to` only when given; apply is one call | `tests/unit/test_client.py` |
| Fake | Unit | the fake's reorder keeps unnamed filters after the named ones, in prior order; create/delete/enable/disable change what `list` returns | `tests/unit/test_fake_proton.py` |

Test-design lenses (per rule group):

| Group | Boundary | Parity | Derived | Emergent | Invariants |
|-------|----------|--------|---------|----------|------------|
| Process (BR-1–5, 12) | ✔ timeouts | ✔ read/write argv prefix | ✔ `--no-input` always | ✔ no retry × exit 5 | ✔ BR-3/4 sweep |
| Connect (BR-6–9) | ✔ version edges | ✔ first use vs later use | ✔ fingerprint from id only | ✔ mismatch stops all calls | ✔ BR-8/9 PBT |
| Errors (BR-10, 11, 13) | ✔ cap of 200 characters | ✔ every parser gets the same malformed set | ✔ hint per code | waived: no composition | ✔ stdout never echoed |
| Filters (BR-14–18) | ✔ empty reorder, empty listing | ✔ enable↔disable, create↔update script handling | ✔ `enabled` from `status` | ✔ list then get reproduces a `Filter` | ✔ BR-2 PBT |
| Targets, messages (BR-19–21) | ✔ no parent | ✔ label↔folder | ✔ `path` fallback | waived | waived |

Coverage: MVP — every BR tested, PBT for invariants, error cases above; the 90% line target applies (implementation plan).
