# Business Logic Model — Unit 7: Import

## Overview

`importer.py` writes filters into the declared files, from live Proton state (`import_live`) or from plain `.sieve` files (`import_sieve_files`). It never touches Proton beyond the read-only `discover`, never deletes a local filter, and refuses to overwrite differing local files without `force`. All checks run before the first write. No new errors and no audit lines (BR-2). `declared.py` gains `load_local` and `free_filename` (Unit 3 BR-19, BR-20).

---

## Primary Workflows

### Workflow 1: Import live

```
AccountPaths, ProtonClient, name | None, force
    │
    ▼
[1] account check                               (BR-1)
    │        └─[ValidationError] nothing read
    ▼
[2] discover; select all or `name`              (BR-2, BR-3)
    │        └─[unknown name] ValidationError; [ClientError] propagates
    ▼
[3] Workflow 3: plan, refuse or write           (BR-5 to BR-14)
    ▼
ImportReport (renamed = live renames)
```

### Workflow 2: Import `.sieve` files

```
AccountPaths, sources, force
    │
    ▼
[1] per source: suffix, read, name from stem    (BR-4)
    │        └─[ValidationError] naming the file
    ▼
[2] incoming Filter(name, script, enabled)      (BR-4: enabled from local, else true)
    ▼
[3] Workflow 3
    ▼
ImportReport
```

### Workflow 3: Stage, compare, write (shared)

```
incoming filters, mode (all-live | single | files), force
    │
    ▼
[1] validate_declared(incoming)                 (BR-5)
    ▼
[2] load_local(paths)                           (BR-6)
    ▼
[3] classify: new | changed | untouched         (BR-7)
    preserved = local names not incoming        (BR-8, all-live mode: all local-only;
                                                 other modes: not applicable, empty)
    ▼
[4] new order, reordered                        (BR-9, BR-10)
    ▼
[5] changed or reordered, and not force?        (BR-11) → ImportReport(refused=True), no write
    ▼
[6] render; resolve file paths                  (BR-13, Unit 3 BR-10/20)
    ▼
[7] write filters, then order file              (BR-12, BR-14)
    │        └─[OSError] SieveAsCodeError, rerun completes
    ▼
ImportReport(written)
```

`preserved` is filled only by `import_live(name=None)`: the single and `.sieve` modes touch named filters only, so other local filters are not reported.

---

## Data Structures

```
ImportReport (frozen)
  refused: bool = False                 — BR-11
  new: tuple[str, ...] = ()             — filter names with no local filter
  changed: tuple[str, ...] = ()         — local filter differs (script, or enabled for live)
  reordered: bool = False               — an existing order entry would move (BR-10)
  preserved: tuple[str, ...] = ()       — local-only filters kept (BR-8)
  written: tuple[Path, ...] = ()        — files created or replaced, order file last
  renamed: tuple[Rename, ...] = ()      — live duplicate-name renames (BR-2)
  ok: property                          — not refused
```

Functions: `import_live(paths, client, name=None, force=False) -> ImportReport`; `import_sieve_files(paths, sources, force=False) -> ImportReport` (`sources: Sequence[Path]`). Private helpers: `_stage` (Workflow 3 steps 1–5), `_write_all` (step 7). Class-free, as the other units.

---

## Error Handling

| Condition | Response | Severity |
|-----------|----------|----------|
| Wrong account | `ValidationError` (BR-1) | Error |
| Unknown `name`; bad source suffix, unreadable or non-UTF-8 source; duplicate source name | `ValidationError` naming it (BR-3, BR-4) | Error |
| Incoming script structurally invalid | `ValidationError` naming filter and line (BR-5) | Error |
| Invalid local file | `ValidationError` naming file and field, even with `force` (BR-6) | Error |
| `proton` read fails | `ClientError` propagates, nothing written (BR-2) | Error |
| Differences without `force` | Report `refused`, nothing written (BR-11) | Info |
| Disk write fails | `SieveAsCodeError` with path; earlier files stay (BR-14) | Error |

---

## Examples and Edge Cases

- Fresh account, three live filters: directory and files created, order file last; `plan` is clean (BR-15).
- Second `import_live` straight after: nothing `changed`, no `new`, `written` empty (BR-12).
- A local filter edited since import, live unchanged: it is `changed`; without `force` the run is refused and nothing else is written either (BR-11).
- A local filter that Proton lacks: `preserved` and listed in the order after the live sequence (BR-8, BR-9). With a local order `[local, a, b]` and live `[a, b]` the new order `[a, b, local]` moves `local`, so `reordered` is true and `force` is needed (BR-10).
- Local `[a, b]`, live `[a, x, b]` (`x` new): `[a, x, b]` only inserts, no `force` (BR-10).
- Local filter stored as `my-rules.yaml` with `name: spam`: `import_live` writes updates there, not `spam.yaml` (BR-13).
- Live `a/b` new while local `a_b.yaml` holds another filter: written to `a_b (1).yaml` with `name: a/b` inside (BR-13).
- Live duplicates `Rule`, `Rule (1)`: imported as `Rule` and `Rule (1)`; `renamed` lists the second; `import_live(name="Rule (1)")` works (BR-2, BR-3).
- Disabled live filter: written with `enabled: false` (Unit 3 BR-13); as a `.sieve` import over an existing disabled filter it stays disabled (BR-4).
- `.sieve` file `Spam.SIEVE` → name `Spam`; `notes.txt` → `ValidationError` (BR-4).
- Empty live account, no local state: an order file with an empty sequence is written (BR-12).

---

## Contract with Other Units

### Consumes
- Unit 1: `AccountPaths`, `SieveAsCodeError`, `ValidationError`.
- Unit 2: `ProtonClient` (through `discover`).
- Unit 3: `render`, `free_filename` (new, BR-20), `normalize_whitespace`, `validate_declared`, `load_local` (new, BR-19), `Filter`, `FilterOrder`.
- Unit 4: `discover`.

### Provides
- Unit 9: `import_live` and `import_sieve_files` with `ImportReport` as public API (FR-CLI.2). The CLI prints `new`, `changed`, `reordered`, `preserved` and renames, suggests `--force` when `refused`, prints `written`, and maps `refused` to a non-zero exit.
- Unit 8 is independent of this unit.

---

## Test Strategy

Uses the stateful fake `tests/fake_proton.py` and `tmp_path` accounts.

| BR/Property | Test Type | Assertion | Planned File |
|-------------|-----------|-----------|--------------|
| BR-1 | Unit | other account → `ValidationError`, no call, no file | `tests/unit/test_importer.py` |
| BR-2 | Unit | only `list`/`get` commands issued; no audit file; renames reported | `tests/unit/test_importer.py` |
| BR-3 | Unit | one name imports only that filter; unknown name → error, no file; numbered name works | `tests/unit/test_importer.py` |
| BR-4 | Unit | stem naming, `.SIEVE` suffix, bad suffix, non-UTF-8, duplicate stems, `enabled` kept from local | `tests/unit/test_importer.py` |
| BR-5 | Unit | structurally invalid script → error naming filter and line, no file written, no script text in message | `tests/unit/test_importer.py` |
| BR-6 | Unit | missing directory and order file import cleanly; invalid local file → error even with `force` | `tests/unit/test_importer.py` |
| BR-7, BR-12 | Unit | identical local file keeps its bytes and mtime; second import writes nothing; empty account writes empty order | `tests/unit/test_importer.py` |
| BR-8, BR-9 | Unit | local-only file and order entry survive; order is live then local-only; filter missing from order file is appended | `tests/unit/test_importer.py` |
| BR-10, BR-11 | Unit | changed script, changed `enabled`, moved entry → refused with nothing written; pure insertion not refused; `force` writes | `tests/unit/test_importer.py` |
| BR-13 | Unit | filter in `my-rules.yaml` updated there; `a/b` vs existing `a_b.yaml` and `Foo` vs `foo` → `<name> (1).yaml`, name inside unchanged, existing file untouched | `tests/unit/test_importer.py` |
| BR-14 | Unit | order file written last; injected `OSError` → `SieveAsCodeError`, rerun completes; no temp files left | `tests/unit/test_importer.py` |
| BR-15 | PBT | for arbitrary live filters (names with `/`, case variants, duplicates, disabled), `import_live` then `load_declared` equals `discover` (normalised) and `diff` is clean | `tests/unit/test_importer.py` |
| Idempotence | PBT | second import after any import writes nothing and is not refused | `tests/unit/test_importer.py` |
| Preservation | PBT | arbitrary local-only filters present before are present and byte-equal after, with or without `force` | `tests/unit/test_importer.py` |
| BR-16 | Unit | report and errors contain no script text | `tests/unit/test_importer.py` |
| `load_local` (Unit 3 BR-19), `free_filename` (BR-20) | Unit | missing dir → empty; order None; duplicate names error; no order cross-check; `(n)` lowest free, case-folded; `render` numbers colliding names instead of raising | `tests/unit/test_declared.py` |
| Public types | Unit | `ImportReport` frozen; `ok` is `not refused` | `tests/unit/test_importer.py` |

Lenses: **boundary** — empty live, empty local, one filter, order file only; **parity** — import then plan clean, import twice equals once; **derived** — new order derived from live order and local order, file path from existing file or name; **emergent** — import, edit locally, import (refused), import `--force`, apply (clean); **invariants** — no deletion of local files, no write when refused, no Proton write. Nothing waived.
