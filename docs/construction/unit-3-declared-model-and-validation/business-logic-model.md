# Business Logic Model — Unit 3: Declared model and validation

## Overview

`declared.py` turns an account's filter files and order file into `Filter` objects and a `FilterOrder`, checks them, and renders them back to file text. It touches no Proton state and writes no files.

---

## Primary Workflows

### Workflow 1: Load

```
AccountPaths
    │
    ▼
[1] filters dir and order file exist             (BR-1)
    │        └─[missing] ValidationError
    ▼
[2] for each *.yaml, sorted                      (BR-2)
    parse → mapping → keys → field types         (BR-3, BR-4, BR-5)
    script structure check                       (BR-16, BR-17, BR-18)
    │        └─[bad] ValidationError naming file and field
    ▼
[3] duplicate names across files                 (BR-6)
    ▼
[4] parse order file                             (BR-7)
    ▼
[5] validate_declared(filters, order)            (BR-6, BR-8)
    ▼
(list[Filter], FilterOrder)
```

### Workflow 2: Validate (in memory)

```
filters, order → field and script checks (BR-4, BR-16, BR-17) → duplicate names (BR-6) → sequence shape and entries (BR-8) → None
```

Used by `load_declared` and by importers that build filters in memory; BR-4 field and BR-16–17 script checks also run here so in-memory filters meet the same bar.

### Workflow 3: Render

```
filters, order, AccountPaths
    │
    ▼
[1] file name per filter                         (BR-10)
    ▼
[2] collision check, NFC + casefold              (BR-11)
    │        └─[collision] ValidationError, nothing rendered
    ▼
[3] normalise script, build YAML text            (BR-12, BR-13)
    ▼
dict[Path, str]                                  (BR-14)
```

---

## Rules

Stated once in `business-rules.md`; cited here by ID.

---

## Data Structures

```
Filter, FilterOrder, ValidationError    — model.py (Unit 1), unchanged

load_declared(paths: AccountPaths) -> tuple[list[Filter], FilterOrder]
validate_declared(filters: Sequence[Filter], order: FilterOrder) -> None
render(filters: Sequence[Filter], order: FilterOrder, paths: AccountPaths) -> dict[Path, str]
normalize_whitespace(script: str) -> str
```

Loaded filters have `live_id=None`. Order file:

```yaml
sequence:
  - first-filter
  - second-filter
```

Filter file:

```yaml
name: first-filter
raw_sieve: |-
  require ["fileinto"];
  if header :contains "subject" "x" { fileinto "X"; }
enabled: false   # omitted when true
```

---

## Error Handling

| Step | Condition | Response |
|------|-----------|----------|
| Load 1 | Directory or order file missing (BR-1) | `ValidationError` with path |
| Load 2 | Unreadable, invalid YAML, not a mapping, unknown key, missing or mistyped field (BR-3, BR-4) | `ValidationError` with file and field |
| Load 2 | Unbalanced or unterminated script, extension used without `require` (BR-16, BR-17) | `ValidationError` with file, line and extension, no script text |
| Load 3 / validate | Duplicate name (BR-6) | `ValidationError` with name (and files) |
| Load 4 / validate | Bad `sequence` shape, duplicate, undeclared or missing entry (BR-7, BR-8) | `ValidationError` with order file and name |
| Render 2 | File-name collision (BR-11) | `ValidationError` with both filter names |

---

## Examples and Edge Cases

| Input | Result |
|-------|--------|
| `name: "a/b"` | file `a_b.yaml`; loads under name `a/b` |
| filters `a/b` and `a_b` | render refuses (BR-11) |
| filters `Foo` and `foo` | load and validate accept (two names); render refuses |
| filter named `.hidden` | file `_hidden.yaml` |
| file `weird-name.yaml` with `name: other` | loads as `other` (BR-10) |
| `enabled: "yes"` (quoted) | error, not a boolean |
| `raw_sieve: "  \n"` | error, blank |
| script with tabs and trailing spaces | load returns it unchanged; render writes it normalised |
| zero filters, `sequence: []` | valid |
| `if true { keep;` | error, unbalanced `{` at line 1 |
| `fileinto "X";` with no `require` | error, `fileinto` needs `require` |
| `# } not code` / `"}"` / `text:` block holding `}` | no error |
| `require ["vnd.proton.expire"]; foo;` | passes (BR-18) |

---

## Contract with Other Units

### Consumes from Unit 1
- `AccountPaths` (`filters_dir`, `order_file`), `Filter`, `FilterOrder`, `ValidationError`.

### Provides to Units 4, 7, 9
- Unit 4: `load_declared`, `validate_declared`, `normalize_whitespace` (Unit 4 decides how to compare declared against live scripts).
- Unit 7: `render`, `normalize_whitespace`; the importer writes the returned files and decides overwrite policy.
- Unit 4 discover output and Unit 9: `render` for printing the declarative format.

---

## Test Strategy

| BR/Property | Test Type | Assertion | Planned File |
|-------------|-----------|-----------|--------------|
| BR-1, BR-2 | Unit | missing dir / order file; non-yaml files and subdirectories ignored; empty valid | `tests/unit/test_declared.py` |
| BR-3, BR-4 | Unit | each bad file shape, unknown key, missing/mistyped/blank field → error naming file and field | `tests/unit/test_declared.py` |
| BR-5 | PBT | for any non-blank script written as a literal block, load returns it byte-identical (already-normalised input) | `tests/unit/test_declared.py` |
| BR-16, BR-17 | Unit | each error case with its line number; braces in strings, comments and `text:` blocks ignored; each table entry needs its `require` | `tests/unit/test_declared.py` |
| BR-16, BR-17 | PBT | generated well-formed scripts pass; deleting one brace, one closing quote, or the `require` line fails | `tests/unit/test_declared.py` |
| BR-18 | Unit | unknown command, unknown extension, missing `;` pass | `tests/unit/test_declared.py` |
| BR-6 | Unit | duplicate across two files names both; case-different names accepted | `tests/unit/test_declared.py` |
| BR-7, BR-8 | Unit | bad shape, extra key, duplicate / undeclared / missing entry | `tests/unit/test_declared.py` |
| BR-9 | PBT | error messages never contain the script text; load leaves the directory unchanged | `tests/unit/test_declared.py` |
| BR-10 | PBT | for any name, file name has no `/`, `\`, NUL, does not start with `.`, ends `.yaml` | `tests/unit/test_declared.py` |
| BR-11 | Unit | `Foo`/`foo`, `a/b`/`a_b`, `.x`/`_x`, NFC vs NFD `é` collide; distinct names do not | `tests/unit/test_declared.py` |
| BR-12 | PBT | `normalize_whitespace` is idempotent; no tab or trailing space remains | `tests/unit/test_declared.py` |
| BR-13, BR-14 | Unit | exact text for enabled, disabled, multi-line, non-ASCII; paths; nothing written | `tests/unit/test_declared.py` |
| BR-15 | PBT | render → write → load round trip gives equal names, flags, sequence, normalised scripts | `tests/unit/test_declared.py` |

Test-design lenses:

| Group | Boundary | Parity | Derived | Emergent | Invariants |
|-------|----------|--------|---------|----------|------------|
| Load (BR-1–5, 16–18) | ✔ empty dir, blank script, brace at end of file | ✔ validate vs load field and script checks | ✔ default `enabled` | waived: no composition | ✔ BR-5 PBT |
| Sets (BR-6–9) | ✔ one filter, empty sequence | ✔ duplicates in names vs sequence | ✔ missing = declared − sequence | ✔ duplicate × undeclared: first error wins | ✔ BR-9 PBT |
| Render (BR-10–15) | ✔ leading `.`, NFC/NFD | ✔ enabled vs disabled output | ✔ file name from name only | ✔ collision stops all output | ✔ BR-10, 12, 15 PBT |

Coverage: MVP — every BR tested, PBT for invariants, error cases above; the 90% line target applies.
