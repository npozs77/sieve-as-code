# Business Logic Model — Unit 8: Retroactive run

## Overview

`sieve_eval.py` compiles the supported Sieve subset and evaluates it against one message. `retroactive.py` builds the read-only preview of what `filters apply` would change, gates and starts the run behind a typed confirmation, saves the preview as a snapshot, reports status against a snapshot, and audits all enabled filters. Spam is excluded; unsupported Sieve is reported, never guessed. The `messages list` row fields, fixed here, are in BR-3.

---

## Primary Workflows

### Workflow 1: Preview (shared by `preview`, `run`, `status`)

```
AccountPaths, ProtonClient, name
    │
    ▼
[1] account check                                   (BR-1)
[2] discover; resolve enabled filter                (BR-2)
    │        └─[unknown / disabled] ValidationError
    ▼
[3] compile_script; check fileinto targets and
    recipient keys against list_folders/labels      (BR-6, BR-9, BR-10, BR-11)
    │        └─[any failure] RetroPreview(previewable=False, reason)  → stop
    ▼
[4] list_messages(); list_messages(to=KEY) per key  (BR-3, BR-10)
    │        └─[ClientError] propagates
    ▼
[5] drop Spam; per message: location, evaluate,
    keep when an action changes it                  (BR-4, BR-5, BR-7, BR-8, BR-12–BR-14)
    ▼
[6] declared_differs via load_local                 (BR-15)
    ▼
RetroPreview
```

### Workflow 2: Run

```
name, confirmed_name, reason
    │
    ▼
[1] Workflow 1                                       (BR-17)
[2] previewable and no entries? → ok, started=False  (BR-17)
[3] confirmed_name == name and reason not blank?     (BR-18)
    │        └─[no] audit check `refused`; RetroReport(refused=True)
    ▼
[4] previewable: write snapshot, then prune later    (BR-19–BR-21)
    │        └─[BackupError] raised, nothing started
    ▼
[5] client.apply_retroactively(live_id)              (BR-22)
    │        └─[ClientError] report.failed
    ▼
[6] audit write `started` / `failed`                 (BR-23)
[7] prune snapshots older than 10 days; audit `prune`(BR-24)
    ▼
RetroReport
```

### Workflow 3: Status

`read snapshot (BR-26)` → `Workflow 1 for snapshot.filter` → `compare ids (BR-27)` → `RetroStatus`.

### Workflow 4: Audit all

`discover` → enabled filters → one `list_messages()` and shared recipient searches → Workflow 1 steps 3–5 per filter → counts and notes → one audit `check` (BR-28).

---

## Evaluator Subset (BR-6 to BR-13)

```
script    := { require | command }
command   := if-chain | "stop" | fileinto | flagcmd | expire
if-chain  := "if" test block { "elsif" test block } [ "else" block ]
test      := "true" | "false" | "not" test | ("allof"|"anyof") "(" test {"," test} ")"
           | ("address"|"header") [":is"|":contains"|":matches"] [addrpart]
             ("from"|"to"|"subject") (string | string-list)
addrpart  := ":all" | ":localpart" | ":domain"     (address on from; to: :all only)
fileinto  := "fileinto" string
flagcmd   := ("addflag"|"setflag"|"removeflag") (string | string-list)   \Seen, \Flagged only
expire    := "expire" "day" string-of-positive-integer
```

`:comparator` other than the default, `:copy`, `:regex` and every other command or test → `UnsupportedSieve(construct, line)`. Comments and text blocks are skipped as Unit 3 does.

---

## Data Structures

```
UnsupportedSieve(SieveAsCodeError)               (in model.py)
  construct: str; line: int

MailMessage (frozen)                             — parsed from a list_messages row (BR-3)
  id: str; subject: str; from_name: str; from_address: str
  time: int; unread: bool; labels: frozenset[str]
  to_keys: frozenset[str] = frozenset()          — recipient keys that matched (BR-10)

CompiledScript (frozen)
  program: tuple[...]                            — private parse tree
  mailboxes: tuple[str, ...]                     — every fileinto target
  recipient_keys: tuple[str, ...]                — distinct `to` keys, case-folded

Outcome (frozen)                                 — evaluate() result (BR-8)
  files: tuple[str, ...]; flags: frozenset[str]; expire_days: int | None

Entry (frozen)                                   — BR-14
  message_id: str; date: str; sender: str; subject: str
  location: str; actions: tuple[str, ...]

RetroPreview (frozen)
  filter: str; previewable: bool; reason: str | None
  approximate: bool; entries: tuple[Entry, ...]
  spam_excluded: int; declared_differs: bool

RetroReport (frozen)
  preview: RetroPreview; refused: bool = False; started: bool = False
  snapshot: Path | None = None; failed: str | None = None
  audit_error: str | None = None; prune_error: str | None = None
  ok: property                                   — BR-25

Unexpected (frozen): message_id: str; reason: Literal["new", "gone"]
RetroStatus (frozen)
  filter: str; snapshot: Path; done: int
  pending: tuple[Entry, ...]; unexpected: tuple[Unexpected, ...]
  script_changed: bool

AuditRow (frozen): name: str; changes: int | None; note: str | None
RetroAudit (frozen): rows: tuple[AuditRow, ...]
```

Functions: `compile_script(script) -> CompiledScript`, `evaluate(compiled, message) -> Outcome`; `preview(paths, client, name) -> RetroPreview`, `run(paths, client, name, confirmed_name, reason) -> RetroReport`, `status(paths, client, ref=None) -> RetroStatus`, `audit_all(paths, client) -> RetroAudit`. `compile_script` is separate from `evaluate` so a script is parsed once for thousands of messages. Snapshot writing reuses Unit 5's checksum and exclusive create. Class-free.

---

## Error Handling

| Condition | Response | Severity |
|-----------|----------|----------|
| Wrong account or unconnected client | `ValidationError` (BR-1) | Error |
| Unknown or disabled filter | `ValidationError` naming it (BR-2) | Error |
| Unsupported Sieve, unresolved target, too many recipient keys | Preview `previewable` false with reason; `audit_all` row note; `status` → `ValidationError` (BR-11, BR-26) | Info |
| `proton` read fails; row has wrong shape | `ClientError` propagates, nothing written (BR-3) | Error |
| Invalid local file during the drift check | `ValidationError` naming file and field (BR-15) | Error |
| Wrong name or blank reason | Report `refused`, audit `refused` (BR-18) | Info |
| Audit write fails on the refusal line | `SieveAsCodeError` raised (BR-18) | Error |
| Snapshot cannot be written | `BackupError`, run not started (BR-20) | Error |
| `apply_retroactively` fails | Report `failed`, audit `failed` (BR-22, BR-23) | Error |
| Audit write fails | Report kept with `audit_error` (BR-23) | Error |
| Old snapshot cannot be removed | Report `prune_error`, run unaffected (BR-24) | Warning |
| Snapshot unreadable, altered, foreign | `BackupError` (BR-26) | Error |

---

## Examples and Edge Cases

- `if address :domain "from" "news.example" { fileinto "Newsletters"; }` with 40 inbox messages from it, 5 already in `Newsletters` → 35 entries, `move: Newsletters` (BR-14).
- Message in Spam matching the filter → not listed, `spam_excluded` 1 (BR-4).
- `fileinto "Newsletters"; addflag "\\Seen";` on a read message already in `Newsletters` → not listed (BR-14).
- `expire "day" "30"` only → no message counts; the action shows on listed messages of other branches (BR-13).
- `header :contains "to" "team@"` → one recipient search; preview `approximate` (BR-10).
- `size :over 1M` → not previewable, reason `size at line 3`; typed confirmation still runs it, no snapshot (BR-11, BR-19).
- `fileinto "Nowhere"` with no such folder or label → not previewable naming `Nowhere` (BR-9).
- Typed name `newsletters` for `Newsletters` → refused (BR-18).
- Status right after a run: 35 pending while Proton works, then 0 pending / 35 done; a mail that arrived since and matches → `unexpected: new`; a deleted one → `gone` (BR-27).
- Filter edited after the run → `script_changed` true (BR-27).
- Declared differs from live → warning in the preview, run uses live (BR-15).

---

## Contract with Other Units

### Consumes
- Unit 1: `AccountPaths` (`retroactive_dir`, `audit_log`), `record_check`, `record_write`, errors.
- Unit 2: `ProtonClient.list_messages`, `list_folders`, `list_labels`, `apply_retroactively`.
- Unit 3: `load_local`, `normalize_whitespace`.
- Unit 4: `discover`.
- Unit 5: checksum and exclusive create, snapshot name pattern, `BackupError`.

### Provides
- Unit 9: `preview`, `run`, `status`, `audit_all` with their result types as public API (FR-CLI.2). The CLI prints the preview and `declared_differs` warning, prompts for the name and reason, passes them to `run`, and maps `refused`, `failed`, `audit_error` to a non-zero exit.

---

## Test Strategy

Uses the stateful fake `tests/fake_proton.py` (messages, folders, labels, `to` search, `filters apply` recorded) and `tmp_path` accounts.

| BR/Property | Test Type | Assertion | Planned File |
|-------------|-----------|-----------|--------------|
| BR-6, BR-7 | Unit | each supported construct; each rejected construct names construct and line, no script text | `tests/unit/test_sieve_eval.py` |
| BR-7 | PBT | `:contains`/`:is` agree with a casefold reference; `:matches` agrees with a reference matcher; `not` flips; `allof`/`anyof` equal `all`/`any` | `tests/unit/test_sieve_eval.py` |
| BR-6 | PBT | arbitrary text yields a `CompiledScript` or `UnsupportedSieve`, never another exception | `tests/unit/test_sieve_eval.py` |
| BR-8, BR-12, BR-13 | Unit | branches, `stop`, flag arithmetic, last `expire`, duplicate targets | `tests/unit/test_sieve_eval.py` |
| BR-1, BR-2 | Unit | other account, unknown, disabled → `ValidationError`, no call | `tests/unit/test_retroactive.py` |
| BR-3, BR-16 | Unit | only list/get verbs; malformed row → `ClientError`; no file or audit line from preview/status | `tests/unit/test_retroactive.py` |
| BR-4, BR-5 | Unit | Spam excluded and counted; Trash included; location per system id, custom folder, unknown; UTC date | `tests/unit/test_retroactive.py` |
| BR-9, BR-10, BR-11 | Unit | unresolved target, `to` search per key, approximate, 11 keys, `:matches` on `to` → not previewable | `tests/unit/test_retroactive.py` |
| BR-14 | PBT | an entry exists iff an action changes the message; previewing after applying the entries' actions to the fake yields no entry | `tests/unit/test_retroactive.py` |
| BR-15 | Unit | declared differs warns, equal does not, undeclared does not; invalid file raises | `tests/unit/test_retroactive.py` |
| BR-17, BR-18 | Unit | zero entries → no gate, no write; wrong case name, blank reason → refused, audit `refused`, no snapshot, no apply | `tests/unit/test_retroactive.py` |
| BR-19, BR-20, BR-21 | Unit | not previewable runs without snapshot; snapshot written before the call; keys, mode `0o600`, checksum, no sender/subject; write failure → no call | `tests/unit/test_retroactive.py` |
| BR-22, BR-23 | Unit | one apply call; `ClientError` → `failed` and audit `failed`; audit line has name and reason; audit failure keeps the report | `tests/unit/test_retroactive.py` |
| BR-24 | Unit | 11-day-old snapshot removed, 9-day-old and new kept; foreign files untouched; removal failure → `prune_error`; prune audit | `tests/unit/test_retroactive.py` |
| BR-26, BR-27 | Unit | done / pending / unexpected `new` and `gone`; `script_changed`; foreign account, altered file, none → `BackupError` | `tests/unit/test_retroactive.py` |
| BR-28 | Unit | counts per filter, notes, disabled skipped, one list call, one audit line | `tests/unit/test_retroactive.py` |
| BR-29 | Unit | audit file, snapshot and errors contain no sender, subject or script | `tests/unit/test_retroactive.py` |
| Public types | Unit | results frozen; `RetroReport.ok` per BR-25 | `tests/unit/test_retroactive.py` |

Lenses: **boundary** — empty mailbox, all Spam, one message, 10 and 11 recipient keys, snapshot of exactly 10 days; **parity** — preview after a simulated run is empty, `audit_all` count equals `preview` count; **derived** — location from labels, entries from message and outcome, status from three id sets; **emergent** — preview, run, status pending, simulated completion, status done; **invariants** — Spam never listed, no Proton write outside `run`, one apply call per confirmed run, no private text in audit or snapshot. Nothing waived.
