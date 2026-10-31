# Business Logic Model — Unit 1: Foundation

## Overview

Shared building blocks for every later unit: the filter data types and base error, per-account path resolution from environment variables, an append-only audit log, and the project scaffold. Its modules import nothing else from the package.

---

## Primary Workflows

### Workflow 1: Resolve an account's paths

```
explicit name | None
    │
    ▼
[1] resolve_account: pick name (BR-1, BR-2)
    │        └─[FAIL] invalid name (BR-3) → ValidationError
    ▼
[2] account_paths(name): re-validate name (BR-3), pick both roots (BR-2, BR-4)
    │        └─[FAIL] no home directory for a default → ValidationError naming the variable
    ▼
[3] build AccountPaths (BR-5, BR-6); touch no filesystem
    │
    ▼
AccountPaths
```

`proton_cli()` is independent: read the variable, apply BR-2, default per BR-7.

### Workflow 2: Append an audit record

```
audit_log path, outcome, detail
    │
    ▼
[1] validate outcome and detail (BR-10)     └─[FAIL] ValueError, nothing written
    │
    ▼
[2] build record: ts, kind, outcome, detail (BR-9)
    │
    ▼
[3] create parent dirs / file if missing (BR-11)
    │
    ▼
[4] append one line (BR-11)                  └─[FAIL] SieveAsCodeError naming the path (BR-12)
```

### Workflow 3: Project scaffold

`pyproject.toml`, `uv.lock`, `.env.example`, `Makefile` and tool config satisfy BR-13 and BR-14. Verified by `make quality` and `uv build`, not by unit tests. The console script targets `cli.py`, which Unit 9 creates.

---

## Rules

Stated once in `business-rules.md` (BR-1–BR-14); cited here by ID.

---

## Data Structures

```
Filter (frozen dataclass, model.py)
  name: str
  raw_sieve: str
  enabled: bool = True
  live_id: str | None = None       — Proton id; None for declared-only filters

FilterOrder (frozen dataclass, model.py)
  sequence: tuple[str, ...]        — filter names, in order

SieveAsCodeError(Exception)        — base for every package error
ValidationError(SieveAsCodeError)  — bad declared input, account name or configuration (CLI exit 2)

AccountPaths (frozen dataclass, settings.py)
  account: str
  filters_dir: Path
  order_file: Path
  account_marker: Path
  backups_dir: Path
  retroactive_dir: Path
  audit_log: Path

Audit record (one JSON line)
  {"ts": str, "kind": "write" | "check", "outcome": str, "detail": {str: str | int | bool | None}}
```

Function signatures (these replace the Settings/Audit rows of `component-methods.md`):

```
resolve_account(name: str | None = None) -> str
account_paths(account: str) -> AccountPaths
proton_cli() -> str
record_write(audit_log: Path, outcome: str, detail: Mapping[str, Scalar]) -> None
record_check(audit_log: Path, outcome: str, detail: Mapping[str, Scalar]) -> None
```

Only `SieveAsCodeError` and `ValidationError` exist now; later units add `ClientError`, `BackupIntegrityError` and `UnsupportedSieve` with their first user (unused-code gate).

---

## Error Handling

| Condition | Response | Severity |
|-----------|----------|----------|
| Invalid account name (BR-3) | `ValidationError`: names the rejected value and the rule | Error |
| Default root needed but no home directory (BR-4) | `ValidationError`: names the variable to set | Error |
| Audit detail/outcome invalid (BR-10) | `ValueError` (programming error in a caller) | Error |
| Audit I/O failure (BR-12) | `SieveAsCodeError` naming the log path and the OS reason | Error |

---

## Examples and Edge Cases

| Input | Result |
|-------|--------|
| no argument, no env | account `default` |
| argument `work`, env `home` | `work` |
| env `"  "` | treated as unset → `default` |
| `a.b`, `work-2` | accepted |
| `.hidden`, `a..b`, `..`, `a/b`, `a\b`, `""` | `ValidationError` |
| `work` and `work-2` | disjoint directories (neither is inside the other) |
| `~/sieve` as root | `~` expanded |
| no variables, no XDG | `~/.config/sieve-as-code/<account>/…` and `~/.local/state/sieve-as-code/<account>/…` |
| `XDG_CONFIG_HOME=/x` | filters under `/x/sieve-as-code/<account>/` |
| `XDG_CONFIG_HOME=rel/path` | ignored → `~/.config/sieve-as-code` |
| `SIEVE_AS_CODE_FILTERS_DIR=/y` and `XDG_CONFIG_HOME=/x` | `/y/<account>/` (variable wins) |
| two appends | two lines; the first byte-identical before and after the second |

Known limit: on a case-insensitive filesystem `Work` and `work` share a directory; not guarded (the names are `proton-cli` profile names the operator chose).

---

## Contract with Other Units

### Provides to Unit 2 — Proton CLI client
- `proton_cli()` binary, `AccountPaths.account` (for `--profile`) and `account_marker` (fingerprint file).

### Provides to Units 3, 5, 7, 8
- Unit 3/7: `Filter`, `FilterOrder`, `ValidationError`, `filters_dir`, `order_file`.
- Unit 5: `backups_dir`; Unit 8: `retroactive_dir`.

### Provides to Units 4, 6, 8
- `record_write` / `record_check` on `audit_log`; callers put names and counts in `detail`, never content (NFR-SAFE.2).

---

## Test Strategy

| BR/Property | Test Type | Assertion | Planned File |
|-------------|-----------|-----------|--------------|
| BR-1 | Unit | argument beats env beats `default` | `tests/unit/test_settings.py` |
| BR-2 | Unit | empty and whitespace-only values are unset; value stripped | `tests/unit/test_settings.py` |
| BR-3 | PBT | any name containing `/`, `\`, NUL, `..` or a leading `.` is rejected; any other non-empty generated name is accepted | `tests/unit/test_settings.py` |
| BR-3 | Unit | boundaries: `""`, `"."`, `".."`, `".a"`, `"a."`, `"a.b"`, `"a..b"` | `tests/unit/test_settings.py` |
| BR-4 | Unit | each root: variable beats XDG beats home default; relative XDG ignored; no home → error naming that variable (mirror for both roots) | `tests/unit/test_settings.py` |
| BR-5 | Unit | exact layout; `~` expanded; nothing created on disk | `tests/unit/test_settings.py` |
| BR-6 | PBT | for any two distinct valid names, no path of one equals or lies inside a directory of the other | `tests/unit/test_settings.py` |
| BR-7 | Unit | default `proton`; override; blank → default | `tests/unit/test_settings.py` |
| BR-8 | Unit | defaults, immutability (assignment raises), tuple order | `tests/unit/test_model.py` |
| BR-9 | Unit | record has exactly the four keys; `ts` matches UTC `Z` format; kind per function | `tests/unit/test_audit.py` |
| BR-10 | PBT | scalar-only detail round-trips through `json.loads`; any list/dict/float value raises and leaves the file untouched | `tests/unit/test_audit.py` |
| BR-10 | Unit | blank outcome raises | `tests/unit/test_audit.py` |
| BR-11 | PBT | after N appends the file has N lines and earlier lines are unchanged | `tests/unit/test_audit.py` |
| BR-11 | Unit | missing dirs created; file mode `0o600`, dir `0o700` | `tests/unit/test_audit.py` |
| BR-12 | Unit | unwritable path → `SieveAsCodeError` naming the path | `tests/unit/test_audit.py` |
| BR-13, BR-14 | Build check | `make quality` and `uv build` pass; `.env.example` keys equal the four variables (one unit test reads the file) | `tests/unit/test_settings.py` |

Test-design lenses (per rule group):

| Group | Boundary | Parity | Derived | Emergent | Invariants |
|-------|----------|--------|---------|----------|------------|
| Account (BR-1–3) | ✔ name edges | ✔ `filters` side and `state` side tested alike | ✔ blank env = unset | ✔ argument × env precedence | ✔ BR-3 PBT |
| Paths (BR-4–6) | ✔ absolute vs relative XDG | ✔ both roots, same precedence tests | ✔ `~` expansion | ✔ two accounts, one root (BR-6) | ✔ BR-6 PBT |
| Audit (BR-9–12) | ✔ empty detail, empty-string values | ✔ `record_write` ↔ `record_check` | ✔ file/dir creation | ✔ append after failed append | ✔ BR-10/11 PBT |
| Model (BR-8) | waived: plain data | waived: no mirror pair | ✔ defaults | waived | waived |

Coverage: MVP — every BR tested, PBT for invariants, error cases above.
