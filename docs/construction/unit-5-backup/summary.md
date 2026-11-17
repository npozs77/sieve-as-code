# Code Summary — Unit 5: Backup

## Files

| Path | Description |
|------|-------------|
| `src/sieve_as_code/backup.py` | `Snapshot`, `write_backup`, `read_backup`, `diff_backups`, `prune_backups` |
| `src/sieve_as_code/model.py` | Added `BackupError` |
| `src/sieve_as_code/settings.py` | Added `Retention`, `retention()` (Unit 1 BR-15) |
| `.env.example`, `README.md` | `SIEVE_AS_CODE_KEEP_DAYS`, `SIEVE_AS_CODE_KEEP_LAST`; status line |
| `tests/unit/test_backup.py` | 70 tests |
| `tests/unit/test_settings.py` | `retention()` and six-variable `.env.example` tests |
| `tests/unit/test_model.py` | `BackupError` subclass test |

## Requirement → implementation

| Requirement | File | Status |
|-------------|------|--------|
| FR-BAK.2 | `backup.py:write_backup`, `_unchanged` | Implemented |
| FR-BAK.6 | `backup.py:prune_backups`, `_candidates`; `settings.py:retention` | Implemented; the `backup` command and flags are Unit 9 |
| FR-BAK.3 | `backup.py:_document`, `_checksum`, `_create`, `read_backup`, `_state` | Implemented |
| FR-BAK.5 | `backup.py:diff_backups` | Implemented |
| FR-ACCT.4 | `backup.py:write_backup` (account check), `read_backup` (fingerprint) | Implemented |
| FR-BAK.1, FR-BAK.4 | Consumed by Unit 6 (`write_backup`, `read_backup`, `Snapshot.state`) | Unit 6 |
| US-3.1, US-3.3 | `write_backup`, `prune_backups`, `diff_backups` | Implemented |

No gaps.

## Business rule coverage

| BR | Implemented in | Tests |
|----|----------------|-------|
| BR-1 | `write_backup` | `test_wrong_account_or_unconnected_client_is_refused` |
| BR-2, BR-3 | `write_backup`, `_document` | `test_snapshot_holds_live_filters_*`, `test_an_empty_account_*`, `test_a_written_snapshot_reads_back_equal` (PBT) |
| BR-4 | `_checksum`, `read_backup` | `test_changing_a_script_without_resigning_*` (PBT), `test_changing_any_value_*`, `test_whitespace_only_edits_*` |
| BR-5 | `_create` | `test_file_and_directory_are_owner_only_*`, `test_an_existing_file_is_never_overwritten`, `test_a_backups_path_that_is_a_file_*`, `test_a_directory_that_cannot_be_written_*` |
| BR-6 | `_create` | `test_a_failed_write_leaves_no_file`, `test_a_partial_file_that_cannot_be_removed_*` |
| BR-7 | `write_backup` | `test_a_proton_failure_writes_nothing` |
| BR-8 | `write_backup` | `test_a_backup_appends_one_audit_line_*`, `test_an_audit_failure_raises_*` |
| BR-9 | `_resolve` | `test_refs_resolve_*`, `test_a_missing_backup_is_an_error` |
| BR-10 | `read_backup`, `_state`, `_rows`, `_text_field` | `test_an_unreadable_file_*`, `test_a_file_that_is_not_a_snapshot_*`, `test_each_failed_check_*` |
| BR-11 | `read_backup`, `Snapshot` | `test_a_snapshot_diffed_with_itself_is_clean` |
| BR-12 | `diff_backups` | `test_diff_backups_*`, `test_added_in_one_direction_*` (PBT) |
| BR-14, BR-15 | `write_backup`, `_unchanged` | `test_an_unchanged_state_*`, `test_any_change_of_state_*`, `test_only_the_latest_snapshot_is_compared`, `test_unchanged_duplicate_names_*`, `test_an_unreadable_or_foreign_latest_*`, `test_an_audit_failure_on_a_skip_raises` |
| BR-16 to BR-18 | `prune_backups`, `_candidates` | `test_nothing_is_pruned_*`, `test_other_files_*`, `test_keep_*`, `test_either_limit_*`, `test_the_newest_snapshot_*`, `test_pruning_*` (PBT), `test_a_removal_failure_*` |
| BR-13 | `read_backup` | `test_the_account_name_in_a_snapshot_is_informational`, `test_diff_backups_refuses_*` |

## Tests

- 356 tests in total, passing on Python 3.12, 3.13 and 3.14; line coverage 100%; ruff, black, mypy (strict) and vulture clean; `uv build` works.
- Build and test: `uv sync && make quality`.

## Implementation notes

- BR-10 checks `format` before the key set (spec order amended during code generation): a newer format may change the keys.
- Unit 1 BR-15 (`retention()`) was added as an addendum; BR-14 there now counts six variables.
- `write_backup` returns `Snapshot.state` with `live_id` cleared (BR-11); the clock is replaced at `datetime` in the name-collision test.
