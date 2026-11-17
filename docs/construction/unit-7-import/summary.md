# Code Summary — Unit 7: Import

## Files

| Path | Description |
|------|-------------|
| `src/sieve_as_code/importer.py` | `ImportReport`, `import_live`, `import_sieve_files`; private `_import`, `_new_order`, `_files_to_write`, `_write_files` |
| `src/sieve_as_code/declared.py` | Unit 3 addendum: `load_local`, `free_filename`; `render` numbers colliding file names |
| `tests/unit/test_importer.py` | 31 test functions (2 property-based) |
| `tests/unit/test_declared.py` | Collision test now checks numbering; tests for `load_local`, `free_filename` |
| `README.md` | Status line |

## Requirement → implementation

| Requirement | File | Status |
|-------------|------|--------|
| FR-DISC.2 | `importer.py:import_live`, `_import` | Implemented; `--force` flag and diff printing are Unit 9 |
| FR-DISC.3 | `importer.py:import_sieve_files` | Implemented; `import` argument handling is Unit 9 |
| FR-DECL.3 | `importer.py:_filter_text` via `render` | Implemented |
| FR-DECL.4 | `declared.py:free_filename`, `render` | Implemented (Unit 3 BR-20 replaces the BR-11 error) |
| US-1.1, US-1.3 | `import_live`, `import_sieve_files` | Implemented |

No gaps.

## Business rule coverage

| BR | Implemented in | Tests |
|----|----------------|-------|
| BR-1 | `import_live` | `test_other_account_is_rejected` |
| BR-2 | `import_live` | `test_import_only_reads_proton_and_writes_no_audit_line`, `test_live_read_failure_*` |
| BR-3 | `import_live` | `test_single_name_imports_only_that_filter`, `test_unknown_name_*` |
| BR-4 | `import_sieve_files` | `test_sieve_files_are_named_by_stem_*`, `test_non_sieve_suffix_*`, `test_unreadable_and_non_utf8_*`, `test_two_sources_*`, `test_sieve_import_keeps_*` |
| BR-5 | `_import` (`validate_declared`), `_filter_text` | `test_invalid_live_script_*`, `test_sieve_script_is_validated_*`, `test_imported_scripts_are_written_normalised` |
| BR-6 | `_import` (`load_local`) | `test_missing_directory_*`, `test_invalid_local_file_blocks_*` |
| BR-7 | `_differs` | `test_equal_local_file_keeps_its_bytes_*` |
| BR-8 | `_new_order` | `test_local_only_filter_is_preserved_*`, `test_local_only_filters_survive_byte_for_byte` (PBT) |
| BR-9 | `_new_order` | `test_filter_missing_from_order_file_*`, `test_sieve_import_keeps_*` |
| BR-10 | `_new_order` | `test_pure_insertion_*`, `test_local_only_filter_in_the_middle_*` |
| BR-11 | `_import` | `test_changed_script_enabled_or_moved_entry_*`, `test_sieve_import_with_a_different_script_*` |
| BR-12 | `_import` | `test_import_all_writes_files_and_order_last`, `test_empty_account_*`, `test_equal_local_file_*` |
| BR-13 | `_files_to_write` | `test_filter_is_written_to_the_file_that_holds_it`, `test_clashing_file_name_*` |
| BR-14 | `_write_files` | `test_write_failure_names_the_path_*`, `test_unwritable_directory_*` |
| BR-15 | `import_live` | `test_import_then_load_equals_live_and_plan_is_clean` (PBT) |
| BR-16 | all error paths | `test_invalid_live_script_*`, `test_unreadable_and_non_utf8_*` |

## Tests

- 437 tests in total, passing on Python 3.12, 3.13 and 3.14; line coverage 100%; ruff, black, mypy (strict) and vulture clean; `uv build` works.
- Build and test: `uv sync && make quality`.

## Implementation notes

- BR-9 and BR-10 were clarified in the rules: dangling order entries are dropped, and a missing order file is never a reorder.
- Unit 3 BR-11 (collision error) is replaced by BR-20; the Unit 3 logic model is updated.
