# Business Logic Model — Unit 4: Discover and plan

## Overview

`live.py` reads the account's filters and mailboxes from Proton; `plan.py` diffs them against the declared files and audits the outcome. Both are read-only.

---

## Primary Workflows

### Workflow 1: Discover

```
ProtonClient
    │
    ▼
[1] list_filters                                  (BR-1, BR-16)
    ▼
[2] get_filter per listed filter                  (BR-1)
    ▼
[3] number duplicate names, record renames        (BR-2)
    ▼
FilterSet(filters in live order, FilterOrder, renames)
```

`discover_targets(client)` → `list_folders` + `list_labels` → `frozenset` of each target's `name` and `path` (BR-10, BR-16).

### Workflow 2: Plan

```
AccountPaths, ProtonClient
    │
    ▼
[1] load_declared                                 (Unit 3)
    │        └─[ValidationError] audit "invalid", re-raise   (BR-13)
    ▼
[2] discover, discover_targets                    (BR-1, BR-10)
    │        └─[ClientError] propagate, no audit             (BR-13)
    ▼
[3] diff(declared, live, targets)                 (BR-3 to BR-12, BR-14, BR-15, BR-17)
    │        └─[unreadable target] audit "invalid", ValidationError   (BR-11)
    ▼
[4] record_check(outcome, counts)                 (BR-13)
    ▼
PlanResult
```

### Workflow 3: Diff (pure)

```
declared, live, targets
    │
    ▼
[1] script_facts per enabled declared filter; missing targets   (BR-10, BR-11, BR-17)
[2] per declared filter in sequence order:
      absent live → create                        (BR-5)
      script differs → content; enabled differs → enabled   (BR-4, BR-6)
[3] live-only: enabled → entry; disabled → informational    (BR-7)
[4] reorder over common (+ created)               (BR-8, BR-9)
[5] flags                                         (BR-12)
    ▼
PlanResult
```

`diff` does no I/O, so `restore` (Unit 6) can diff a snapshot the same way.

---

## Rules

Stated once in `business-rules.md`; cited here by ID.

---

## Data Structures

```
Rename(original: str, name: str)                                 — model.py
FilterSet(filters: tuple[Filter, ...], order: FilterOrder, renames: tuple[Rename, ...] = ())   — model.py (shared)

discover(client: ProtonClient) -> FilterSet                       ★ live.py
discover_targets(client: ProtonClient) -> frozenset[str]          live.py
plan(paths: AccountPaths, client: ProtonClient) -> PlanResult     ★ plan.py
diff(declared: FilterSet, live: FilterSet, targets: frozenset[str] | None) -> PlanResult   plan.py   # None = snapshot mode (BR-19)
script_facts(script: str) -> ScriptFacts                          declared.py (new)

ScriptFacts(required: frozenset[str], mailboxes: tuple[Mailbox, ...])
Mailbox(line: int, name: str | None)         # None = unreadable (BR-11)

PlanEntry(kind: "create" | "content" | "enabled" | "live-only",
          name: str, live_id: str | None, enabled: bool | None)
Reorder(old: tuple[str, ...], new: tuple[str, ...])
MissingTarget(name: str, used_by: tuple[str, ...])
Flag(name: str, extension: str)
PlanResult(missing_targets: tuple[MissingTarget, ...], entries: tuple[PlanEntry, ...],
           reorder: Reorder | None, flags: tuple[Flag, ...],
           informational: tuple[str, ...], renamed: tuple[Rename, ...],
           outcome: "clean" | "drift")
```

`diff` reads each declared filter's facts via `script_facts`; `plan` maps any `ValidationError` to the `invalid` audit line. `enabled` on a `create` entry is the declared value; on an `enabled` entry the new value; `live_id` is set for every kind except `create`. `outcome` never holds `invalid` (that is the raised error).

---

## Error Handling

| Step | Condition | Response |
|------|-----------|----------|
| Discover 1–2 | Listing incomplete, bad output, rejected command | `ClientError` from Unit 2, unchanged |
| Plan 0 | Client and paths name different accounts (BR-18) | `ValidationError`; no audit |
| Plan 1 | Declared files invalid | `ValidationError` from Unit 3; audit `invalid` |
| Plan 3 | Unreadable `fileinto` target (BR-11) | `ValidationError` with filter and line; audit `invalid` |
| Plan 5 | Audit write fails | `SieveAsCodeError` from Unit 1; no result returned |

---

## Examples and Edge Cases

| Input | Result |
|-------|--------|
| declared = live, scripts differ only in tabs / trailing spaces | `clean` (BR-4) |
| declared `[a,b,c]`, live `[c,a,b]` | one `reorder` entry old `[c,a,b]` new `[a,b,c]` (BR-8) |
| declared `[a,x,b]`, live `[a,b]`, `x` new | `create x`; live-after-create `[a,b,x]` ≠ `[a,x,b]` → `reorder` (BR-9) |
| declared `[a,b,x]`, live `[a,b]`, `x` new | `create x`, no reorder |
| live has extra enabled `z` between `a` and `b` | `live-only z`; no reorder when `a`,`b` keep relative order |
| live has extra disabled `z` | informational; `clean` if nothing else (BR-7) |
| `fileinto "Archive"` | built-in, never listed (BR-10) |
| `fileinto "Receipts"`, no such folder or label | `MissingTarget("Receipts", ("f",))` |
| `fileinto "${folder}";` in an enabled filter | `invalid` (BR-11) |
| same in a disabled filter | ignored |
| `require ["vnd.proton.expire"]` on an unchanged filter | no flag (BR-12) |
| two live filters named `x` | `x`, `x (1)`; one rename reported; `clean` if nothing else (BR-2) |
| live `x`, `x`, `x (1)` | `x`, `x (2)`, `x (1)` (BR-2) |
| zero declared and zero live | `clean` |

---

## Contract with Other Units

### Consumes
- Unit 1: `AccountPaths`, `Filter`, `FilterOrder`, `record_check`, `SieveAsCodeError`.
- Unit 2: `ProtonClient.list_filters`, `get_filter`, `list_folders`, `list_labels`; `ClientError`.
- Unit 3: `load_declared`, `normalize_whitespace`.

### Provides
- Unit 5, 7, 8: `discover` → `FilterSet` with numbered names and `renames`; each reports the renames.
- Unit 6: `plan`, `diff`, `PlanResult`; `restore` diffs a snapshot's `FilterSet` against live with `diff`. Missing targets carry the name only — Unit 6 decides whether `apply` creates a folder or a label.
- Unit 9: `discover`, `plan`; prints `FilterSet` with `render`.

Additions to earlier units (no rule changes there): `FilterSet` in `model.py`; `script_facts` in `declared.py` reusing its scanner.

---

## Test Strategy

| BR/Property | Test Type | Assertion | Planned File |
|-------------|-----------|-----------|--------------|
| BR-1, BR-16 | Unit | fake `proton`: filters returned in live order with ids; only list/get calls made | `tests/unit/test_live.py` |
| BR-2 | Unit + PBT | duplicates numbered and reported; taken numbers skipped; PBT: names unique, first keeps its name, ids and order unchanged | `tests/unit/test_live.py` |
| BR-10 (`discover_targets`) | Unit | folders and labels, name and path both present | `tests/unit/test_live.py` |
| BR-3 to BR-7 | Unit | one case per entry kind; informational for disabled live-only | `tests/unit/test_plan.py` |
| BR-4 | PBT | adding tabs or trailing whitespace to a script never creates a `content` entry | `tests/unit/test_plan.py` |
| BR-8 | PBT | for any permutation of common names, exactly one `reorder`, none when order equal | `tests/unit/test_plan.py` |
| BR-9 | Unit | created filter mid-sequence → reorder; at end → none | `tests/unit/test_plan.py` |
| NFR-REL.1 / BR-15 | PBT | model-based: apply a `PlanResult` to the live `FilterSet` in memory (creates appended, edits, live-only disabled, reorder), then `diff` → `clean` | `tests/unit/test_plan.py` |
| BR-15 | PBT | `diff(x, x)` is `clean` and empty | `tests/unit/test_plan.py` |
| BR-10 | Unit | built-ins (any case) never listed; existing folder/label not listed; once per name with users; disabled filter ignored | `tests/unit/test_plan.py` |
| BR-11, BR-17 | Unit | variable / `text:` / non-string mailbox → error with line, no script text; escapes resolved | `tests/unit/test_plan.py`, `test_declared.py` |
| BR-12 | Unit | flag only with a write entry; outcome unchanged by flags | `tests/unit/test_plan.py` |
| BR-13 | Unit | audit line per outcome holds counts only; `invalid` audited; `ClientError` not audited | `tests/unit/test_plan.py` |
| BR-14 | Unit | entry order groups | `tests/unit/test_plan.py` |
| BR-18 | Unit | other account's paths → `ValidationError`, no audit | `tests/unit/test_plan.py` |
| BR-19 | Unit | snapshot mode: unreadable target and expire do not raise or flag | `tests/unit/test_plan.py` |
| BR-2, BR-13 | Unit | renames reported by `plan`, counted in the audit line, not drift | `tests/unit/test_plan.py` |
| Error: audit failure | Unit | `SieveAsCodeError` raised | `tests/unit/test_plan.py` |

Test-design lenses:

| Group | Boundary | Parity | Derived | Emergent | Invariants |
|-------|----------|--------|---------|----------|------------|
| Discover (BR-1, 2, 16) | ✔ zero filters, one filter | waived: `get` supplies name and enabled; `list` supplies ids and order only | ✔ order = names in list order | waived: no composition | ✔ read-only calls only |
| Entries (BR-3–7, 14) | ✔ both empty, case-different names | ✔ content vs enabled on one filter | ✔ live-only = live − declared | ✔ content × enabled × reorder together | ✔ NFR-REL.1 model-based PBT |
| Reorder (BR-8, 9) | ✔ one common filter, creates at ends | ✔ declared vs live restricted | ✔ restriction to common | ✔ create × live-only × reorder | ✔ one entry PBT |
| Targets and flags (BR-10–12, 17) | ✔ empty script, built-in case | ✔ enabled vs disabled filter | ✔ missing = used − known | ✔ missing target × unreadable target: error wins (`test_an_unreadable_target_wins_*`) | ✔ flags never change outcome |

Coverage: MVP — every BR tested, PBT for invariants, error cases above; the 90% line target applies.
