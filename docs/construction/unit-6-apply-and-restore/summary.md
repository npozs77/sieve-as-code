# Code Summary — Unit 6: Apply and restore

## Files

| Path | Description |
|------|-------------|
| `src/sieve_as_code/apply.py` | `Action`, `FailedAction`, `ApplyReport`, `apply_plan`, engine `build_steps`, `run_actions`, `check_client` |
| `src/sieve_as_code/restore.py` | `RestoreReport`, `restore` |
| `tests/unit/test_apply.py` | 21 tests |
| `tests/unit/test_restore.py` | 19 tests |
| `README.md` | Status line |

## Requirement → implementation

| Requirement | File | Status |
|-------------|------|--------|
| FR-APPLY.1, NFR-SAFE.1 | `apply.py:run_actions` (refusal) | Implemented; the `--yes` flag and plan printing are Unit 9 |
| FR-APPLY.2 | `apply.py:build_steps`, `_entry_step`, `_create_target`, `_reorder` | Implemented |
| FR-APPLY.3 | Unit 2 `ProtonClient` (stdin only); steps pass scripts as arguments to it | Implemented |
| FR-APPLY.4 | `apply.py:run_actions` | Implemented |
| FR-APPLY.5 | `apply.py:_entry_step`; `restore.py:_with_deletes` | Implemented; the override flag is Unit 9 |
| FR-APPLY.6 | `apply.py:_audit`, `run_actions` | Implemented |
| FR-BAK.1 | `apply.py:_snapshot` | Implemented |
| FR-BAK.4 | `restore.py:restore`, `_verify`, `_with_deletes` | Implemented; CLI printing is Unit 9 |
| US-2.2, US-2.4, US-3.2 | `apply_plan`, `restore` | Implemented |

No gaps.

## Business rule coverage

| BR | Implemented in | Tests |
|----|----------------|-------|
| BR-1, BR-15 | `check_client` | `test_other_account_or_unconnected_client_is_rejected` (both files) |
| BR-2 | `apply_plan` | `test_invalid_declared_files_fail_before_any_write` |
| BR-3, BR-18 | `apply_plan`, `restore` (no steps) | `test_clean_plan_writes_nothing_*`, `test_nothing_to_restore_writes_nothing` |
| BR-4, BR-19 | `run_actions` | `test_unconfirmed_apply_is_refused_*`, `test_unconfirmed_restore_is_refused_*` |
| BR-5, BR-20 | `_snapshot` | `test_snapshot_is_taken_*`, `test_an_equal_latest_snapshot_is_reused`, `test_unwritable_*`, `test_pre_restore_snapshot_*` |
| BR-6, BR-7 | `build_steps`, `_entry_step`, `_reorder`, `_create_filter` | `test_writes_follow_the_documented_order_*` |
| BR-8 | `_create_target` | `test_nested_folder_*`, `test_missing_parent_folder_*` |
| BR-9 | `_entry_step` | `test_live_only_filter_is_disabled_unless_delete_is_allowed` |
| BR-10 | `run_actions` | `test_first_failure_stops_*`, `test_failure_lists_the_rest_*` |
| BR-11 | `_audit` | `test_every_write_is_audited_*`, `test_verified_restore_is_audited_*` |
| BR-12 | `run_actions`, `_audit` | `test_audit_failure_ends_the_run_*` |
| BR-13 | `ApplyReport.ok` | `test_applying_then_planning_again_is_clean` (PBT) |
| BR-14 | `apply_plan` (flags not consulted) | `test_flagged_filter_is_written_and_reported` |
| BR-16, BR-17 | `restore._with_deletes`, `build_steps` | `test_restore_returns_live_state_*`, `test_disabled_filter_created_after_*`, `test_duplicate_name_*`, `test_restore_returns_any_state_to_any_backup` (PBT) |
| BR-21 | `restore._verify`, `RestoreReport.ok` | `test_failed_write_stops_restore_*`, `test_verify_read_failure_*`, `test_remaining_difference_*`, `test_restore_report_is_not_ok_*` |
| BR-22 | `restore._verify` | `test_verified_restore_is_audited_*`, `test_audit_failure_after_verification_*` |

## Tests

- 396 tests in total, passing on Python 3.12, 3.13 and 3.14; line coverage 100%; ruff, black, mypy (strict) and vulture clean; `uv build` works.
- Build and test: `uv sync && make quality`.

## Implementation notes

- BR-11 dropped the `filters` count from the reorder's audit line (amended in the rules): the reorder's size is in the plan.
- After `apply_plan`, declared filters are in declared relative order, but a live-only filter may sit before them (Unit 4 BR-8: live-only filters are ignored by the reorder).
- Tests inject the audit failure at `record_write`/`record_check` in the modules under test and the post-run live changes at the `subprocess.run` boundary.
- Defect (RVQ-Q33, found on a real account in Unit 9 acceptance): the restore report carried the plain diff, so a filter created after the backup and disabled showed as `info` under `outcome: clean` although `restore --yes` deletes it. `restore` now reports the plan that runs (`_with_deletes`, `informational` empty). Test: `test_unconfirmed_restore_is_refused_with_the_plan`. Approved with Gate 6.
