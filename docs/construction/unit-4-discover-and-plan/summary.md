# Code Summary — Unit 4: Discover and plan

## Files

| Path | Description |
|------|-------------|
| `src/sieve_as_code/live.py` | `discover`, `discover_targets` |
| `src/sieve_as_code/plan.py` | `plan`, `diff`, `PlanEntry`, `Reorder`, `MissingTarget`, `Flag`, `PlanResult` |
| `src/sieve_as_code/declared.py` | Added `script_facts`, `ScriptFacts`, `Mailbox`; `_Scanner` records `fileinto` mailboxes |
| `src/sieve_as_code/model.py` | Added `FilterSet`, `Rename` |
| `tests/unit/test_live.py` | 8 tests |
| `tests/unit/test_plan.py` | 34 tests |
| `tests/unit/test_declared.py` | `script_facts` cases added |
| `README.md` | Status line |

## Requirement → implementation

| Requirement | File | Status |
|-------------|------|--------|
| FR-DISC.1 | `live.py:discover`, `_number_duplicates` | Implemented |
| FR-PLAN.1, FR-PLAN.2 | `plan.py:_entries`, `_live_only`, `_reorder` | Implemented |
| FR-PLAN.3 | `plan.py:_facts`, `_missing_targets`; `declared.py:script_facts` | Implemented |
| FR-PLAN.4 | `plan.py:plan` | Implemented |
| FR-PLAN.5 | `plan.py:_flags` | Implemented |
| FR-PLAN.6 | `live.py`, `plan.py` (read-only client calls) | Implemented |
| US-2.1 (plan part) | `plan.py:diff` | Implemented; size flag is FR-DECL.6, on hold |

No gaps.

## Business rule coverage

| BR | Implemented in | Tests |
|----|----------------|-------|
| BR-1, BR-16 | `discover`, `discover_targets` | `test_live.py`: `test_discover_returns_*`, `test_discover_and_targets_make_read_only_calls_only` |
| BR-2 | `_number_duplicates` | `test_duplicate_live_names_*`, `test_numbering_skips_*`, `test_numbered_names_are_unique_*` (PBT), `test_plan_reports_renamed_*` |
| BR-3 | `_entries` | `test_names_match_case_sensitively` |
| BR-4 | `_entries` | `test_whitespace_only_differences_*` (PBT) |
| BR-5, BR-6, BR-7, BR-14 | `_entries`, `_live_only`, `diff` | `test_each_entry_kind_*`, `test_content_and_enabled_*`, `test_a_disabled_live_only_*` |
| BR-8, BR-9 | `_reorder` | `test_any_number_of_moves_*` (PBT), `test_created_filter_*`, `test_live_only_filters_do_not_cause_*` |
| BR-10 | `_missing_targets`, `discover_targets` | `test_missing_targets_*`, `test_built_in_*`, `test_existing_folders_*`, `test_targets_of_disabled_*`, `test_targets_hold_*` |
| BR-11 | `_facts` | `test_unreadable_target_*`, `test_plan_audits_unreadable_*` |
| BR-12 | `_flags` | `test_destructive_extension_*`, `test_flags_do_not_change_the_outcome` |
| BR-18 | `plan` | `test_plan_refuses_a_client_connected_to_another_account` |
| BR-19 | `diff` | `test_snapshot_mode_skips_target_and_flag_checks` |
| BR-13 | `plan`, `PlanResult.outcome` | `test_plan_audits_*`, `test_plan_does_not_audit_*`, `test_plan_raises_when_the_audit_*` |
| BR-15 | `diff` | `test_diff_of_a_state_with_itself_*` (PBT), `test_applying_a_plan_leaves_nothing_to_plan` (model-based PBT) |
| BR-17 | `declared.py:script_facts` | `test_declared.py`: `test_script_facts_*` |

## Tests

- 264 tests in total, passing on Python 3.12, 3.13 and 3.14; line coverage 100%; ruff, black, mypy (strict) and vulture clean; `uv build` works.
- Build and test: `uv sync && make quality`.

## Implementation notes

- Built-in mailbox table (BR-10) is a superset (`inbox, archive, spam, trash, drafts, draft, sent, starred, all mail`): Proton's docs give no list, so a built-in is never reported missing. Confirm exact names in the live smoke suite (NFR-TEST.2).
- BR-9's "new filters land last" is an assumption for the live smoke suite to confirm.
