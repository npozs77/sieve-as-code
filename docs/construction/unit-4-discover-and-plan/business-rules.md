# Business Rules — Unit 4: Discover and plan

| ID | Rule (condition → outcome) | Source |
|----|----------------------------|--------|
| BR-1 | `discover` calls `list_filters` and then `get_filter` for each listed filter, and returns the filters in live execution order with `live_id` set, plus the order as their names. It makes no other call and writes nothing. | FR-DISC.1, FR-PLAN.6 |
| BR-2 | Two live filters with the same name → `ClientError` naming the name; nothing is collapsed or returned. | FR-DISC.1 |
| BR-3 | Filters are matched declared↔live by `name`, exact and case-sensitive. | FR-DECL.4 |
| BR-4 | Script equality is `normalize_whitespace(declared) == normalize_whitespace(live)`; any other difference is a content change. | FR-PLAN.1, NFR-REL.1 |
| BR-5 | A declared name absent live → `create` entry (carries the declared `enabled`). | FR-PLAN.1 |
| BR-6 | A name on both sides with different scripts (BR-4) → `content` entry; with different `enabled` → `enabled` entry carrying the declared value. A filter may have both. | FR-PLAN.1 |
| BR-7 | A live-only filter that is enabled → `live-only` entry (apply disables it). A live-only filter that is disabled → informational name, not an entry and not drift. | FR-PLAN.1 |
| BR-8 | Let *common* be the names on both sides. If the declared sequence restricted to *common* differs from the live sequence restricted to *common*, the plan holds exactly one `reorder` entry (old vs new sequence), however many filters moved. Live-only filters are ignored. | FR-PLAN.2 |
| BR-9 | Created filters join the reorder comparison: the old sequence is the live *common* order followed by the created names in declared order (Proton appends new filters last — to be confirmed by the live smoke suite, NFR-TEST.2); the new sequence is the declared sequence restricted to *common* plus created. Different → the one `reorder` entry. This keeps a second `apply` empty. | FR-PLAN.2, NFR-REL.1 |
| BR-10 | For each enabled declared filter, each `fileinto` mailbox is a target. A target is missing when it is not a Proton built-in mailbox (fixed table, case-insensitive) and equals no existing folder or label name or path (exact). Each missing target is listed once, with the filters using it, in order of first use, ahead of the filter entries. Disabled filters' targets are ignored. | FR-PLAN.3 |
| BR-11 | An enabled declared filter whose `fileinto` mailbox is not a plain quoted string (contains `${`, a `text:` block, or a non-string argument) → `ValidationError` naming the filter and line; no script text. The plan's outcome is `invalid`. | FR-PLAN.3 |
| BR-12 | An enabled declared filter that has a `create`, `content` or `enabled` entry and requires a destructive extension (table: `vnd.proton.expire`) → one flag naming the filter and extension. Flags never change the outcome. | FR-PLAN.5 |
| BR-13 | Outcome: `invalid` if loading, validating or BR-11 fails; else `drift` if there is any missing target, entry or reorder; else `clean`. Flags and informational names do not count. `plan` appends one check audit line with the outcome and counts (entries, missing targets, flags) — never names or content. Failures reading Proton (`ClientError`) propagate unaudited. | FR-PLAN.4, NFR-SAFE.2 |
| BR-14 | Entry order: missing targets, then `create`, `content`, `enabled` entries in declared sequence order, then `live-only` entries in live order, then the `reorder`. | FR-APPLY.2 |
| BR-15 | `diff` is pure: same inputs → same result, no I/O. Equal declared and live (BR-3, BR-4) → `clean`, empty. | NFR-REL.1, FR-PLAN.6 |
| BR-16 | `plan` and `discover` use only `list_filters`, `get_filter`, `list_folders`, `list_labels`; no mutation, no `--dry-run`. | FR-PLAN.6 |
| BR-17 | `script_facts(script)` (in `declared.py`) returns the lower-cased `require` extensions and each `fileinto` mailbox with its line: the last argument before `;`, taken as a name when it is a quoted string without `${` (escapes `\\` and `\"` resolved), else unreadable. It never judges grammar (BR-18 of Unit 3). | FR-PLAN.3, FR-PLAN.5 |
