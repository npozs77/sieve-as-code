# Units of Work — sieve-as-code

9 units, ordered by dependency. Each is independently designable, buildable and testable. Paths are under `src/sieve_as_code/`; tests under `tests/unit/`.

---

## Unit 1 — Foundation

**Capability**: FR-CLI.3, FR-ACCT.1, FR-ACCT.2, FR-ACCT.5, NFR-SAFE.2, NFR-SAFE.3, NFR-DEP.1, CON-5
**Components**: Model, Settings, Audit
**Delivers**:
- `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore` entries, ruff/black/mypy/vulture config
- `model.py`, `settings.py`, `audit.py`
- Unit tests for each

**Input**: environment variables, account name · **Output**: dataclasses, per-account resolved paths, audit lines

---

## Unit 2 — Proton CLI client

**Capability**: FR-APPLY.3, FR-PLAN.6, NFR-REL.2, NFR-REL.3, FR-ACCT.1, FR-ACCT.4
**Components**: Proton client
**Delivers**:
- `client.py` — the only `proton-cli` caller; stdin scripts; session, version and account-fingerprint checks
- Test double for the subprocess boundary in `tests/`
- Unit tests, including output-shape errors

**Input**: filter/label/folder/message operations · **Output**: parsed dicts or `ClientError`
**Note**: encodes the tested range `>=4.3.0` (NFR-REL.3).

---

## Unit 3 — Declared model and validation

**Capability**: FR-DECL.1–6
**Components**: Declared
**Delivers**:
- `declared.py` — load, render, validate (incl. size limit)
- Property-based tests for round-trip and validation

**Input**: filter files and order file · **Output**: filters and order, or `ValidationError`
**Note**: the size check (FR-DECL.6) is on hold until the limit is measured; no limit is enforced until then.

---

## Unit 4 — Discover and plan

**Capability**: FR-DISC.1, FR-PLAN.1–6
**Components**: Live, Plan
**Delivers**:
- `live.py`, `plan.py`
- Property-based tests for diff and one-entry reorder

**Input**: declared + live state · **Output**: `PlanResult` with flags

---

## Unit 5 — Backup

**Capability**: FR-BAK.2, FR-BAK.3, FR-BAK.5, FR-ACCT.4
**Components**: Backup
**Delivers**:
- `backup.py` — versioned, checksummed, exclusive-create snapshots; read verification; diff
- Tests for tamper detection and no-overwrite

**Input**: live state or snapshots · **Output**: snapshot file or diff

---

## Unit 6 — Apply and restore

**Capability**: FR-APPLY.1–6, FR-BAK.1, FR-BAK.4
**Components**: Apply, Restore
**Delivers**:
- `apply.py`, `restore.py`
- Tests for write order, stop-on-failure accounting, disable-by-default, restore verification

**Input**: `PlanResult` or snapshot · **Output**: `ApplyReport`, `RestoreReport`

---

## Unit 7 — Import

**Capability**: FR-DISC.2, FR-DISC.3
**Components**: Importer
**Delivers**:
- `importer.py`
- Tests for `--force` refusal, local-only preservation, `.sieve` files

**Input**: live filters or `.sieve` paths · **Output**: declared files written

---

## Unit 8 — Retroactive run

**Capability**: FR-RETRO.1–5
**Components**: Sieve evaluator, Retroactive
**Delivers**:
- `sieve_eval.py`, `retroactive.py`
- Property-based tests for the evaluator subset; tests for typed gate, snapshot retention, status

**Input**: filter name, mailbox listing · **Output**: preview, run, status, audit report

---

## Unit 9 — CLI and public API

**Capability**: FR-CLI.1, FR-CLI.2, FR-ACCT.3, NFR-TEST.2
**Components**: CLI, Public API
**Delivers**:
- `cli.py`, `__init__.py`, console-script entry
- README (tested `proton-cli` range, rename note, API list), CHANGELOG
- CLI tests: confirmations, exit codes
- `tests/live/` opt-in smoke suite with throwaway-filter cleanup (NFR-TEST.2)

**Input**: argv · **Output**: exit code, rendered results

---

## Build Order Summary

```
Phase 0: Foundation      Unit 1
Phase 1: Boundaries      Unit 2 + Unit 3 (parallel, both need Unit 1)
Phase 2: Core            Unit 4 → Unit 5
Phase 3: Writes          Unit 6 + Unit 7 + Unit 8 (parallel after Units 4–5)
Phase 4: Delivery        Unit 9
```

---

## Structural Scaffolding

**Artifact type(s)**: cli, library (from `project-profile.yaml`)

| Structural necessity | Owned by | Notes |
|----------------------|----------|-------|
| Entry point / command dispatcher | Unit 9 | |
| Argument parsing, `--help`, `--version` | Unit 9 | |
| Config / state path resolution | Unit 1 | env-var overrides, FR-CLI.3 |
| Installation and invocation | Units 1, 9 | `pyproject.toml` console script in Unit 1; verified in Unit 9 |
| Error → exit-code translation | Unit 9 | |
| Confirmation guard on writes | Units 6, 8, 9 | `confirmed` flags in library; prompts in CLI |
| Unattended failure signalling | Unit 9 | non-zero exit and audit line on failure |
| Public API surface definition | Unit 9 | FR-CLI.2 |
| Versioning / compatibility policy | Unit 9 | semver in README; only documented functions are public |
| Packaging / distribution entry points | Unit 1 | PyPI build; publishing is Operations |

---

## Code Organisation

```
sieve-as-code/
├── src/sieve_as_code/   # Units 1–9, one module per component
├── tests/
│   └── unit/            # Per-unit tests, subprocess fake in conftest
├── docs/
├── pyproject.toml
└── README.md
```
