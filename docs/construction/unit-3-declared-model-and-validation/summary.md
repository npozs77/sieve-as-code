# Code Summary — Unit 3: Declared model and validation

## Files

| Path | Description |
|------|-------------|
| `src/sieve_as_code/declared.py` | `load_declared`, `validate_declared`, `render`, `normalize_whitespace`; private `_Scanner` for the script check |
| `tests/unit/test_declared.py` | 83 tests |

## Requirement → implementation

| Requirement | File | Status |
|-------------|------|--------|
| FR-DECL.1 | `declared.py:_load_filter`, `_dump` | Implemented |
| FR-DECL.2 | `declared.py:_load_order`, `render` | Implemented |
| FR-DECL.3 | `declared.py:_load_filter` (verbatim), `normalize_whitespace`, `render` | Implemented |
| FR-DECL.4 | `declared.py:_check_duplicates`, `render` (file-name collisions) | Implemented |
| FR-DECL.5 | `declared.py:validate_declared`, `load_declared`, `_check_filter`, `_check_order` | Implemented |
| FR-DECL.7 | `declared.py:_Scanner`, `_script_problem` | Implemented |

No gaps.

## Business rule coverage

| BR | Implemented in | Tests (`tests/unit/test_declared.py`) |
|----|----------------|----------------------------------------|
| BR-1, BR-2 | `load_declared` | `test_load_missing_directory_or_order_file_*`, `test_load_empty_account_*`, `test_load_reads_only_yaml_files_*` |
| BR-3, BR-4 | `_load_filter`, `_check_filter` | `test_load_rejects_bad_file_*`, `test_load_binary_file_*`, `test_validate_checks_in_memory_*` |
| BR-5 | `_load_filter` | `test_load_keeps_script_exactly_as_written` (PBT) |
| BR-6 | `_check_duplicates` | `test_duplicate_names_across_files_*`, `test_names_differing_in_case_*` |
| BR-7, BR-8 | `_load_order`, `_check_order` | `test_load_rejects_bad_order_file` |
| BR-9 | all checks | `test_first_failure_wins_*`, `test_broken_scripts_fail_without_echoing_the_script` (PBT), `test_render_writes_nothing` |
| BR-10 | `_filter_filename` | `test_rendered_file_name_stays_inside_the_directory` (PBT), `test_load_file_name_does_not_matter` |
| BR-11 | `render` | `test_render_refuses_colliding_file_names_*`, `test_render_accepts_distinct_names` |
| BR-12 | `normalize_whitespace` | `test_normalize_whitespace_*` (PBT, example) |
| BR-13, BR-14 | `render`, `_dump` | `test_render_exact_text`, `test_render_writes_nothing` |
| BR-15 | `render`, `load_declared` | `test_render_then_load_round_trips` (PBT) |
| BR-16, BR-17 | `_Scanner` | `test_script_problem_is_reported_*`, `test_each_gated_command_*`, `test_well_formed_scripts_pass` (PBT), `test_broken_scripts_*` (PBT) |
| BR-18 | `_Scanner` | `test_what_the_check_cannot_prove_wrong_passes` |

## Tests

- 210 tests in total, passing on Python 3.12, 3.13 and 3.14; line coverage 100%; ruff, black, mypy (strict) and vulture clean; `uv build` works.
- Build and test: `uv sync && make quality`.

## Implementation notes

- The live smoke case for a rejected script (NFR-TEST.2) is built with the live suite, not in this unit.
- `_Scanner` is a class because it holds scan state across eight methods (position, line, bracket stack, `require` set).
- `load_declared` does its own file-aware duplicate check (BR-6 names both files); `validate_declared` repeats it by name for in-memory callers.
