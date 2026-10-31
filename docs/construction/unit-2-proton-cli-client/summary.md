# Code Summary — Unit 2: Proton CLI client

## Files

| Path | Description |
|------|-------------|
| `src/sieve_as_code/client.py` | `connect`, `ProtonClient`, `FilterRef`, `MailTarget`, `fingerprint_of`, `TESTED_MINIMUM` |
| `src/sieve_as_code/model.py` | Adds `ClientError` (with `exit_code`) |
| `tests/fake_proton.py` | In-memory `proton`: filters, order, folders, labels, account id, failure injection |
| `tests/conftest.py` | `fake_proton` and `work_account` fixtures |
| `tests/unit/test_client.py`, `test_fake_proton.py` | 78 tests |
| `pyproject.toml`, `uv.lock` | `pytest-cov` 7.1.0; coverage gate (90%) in pytest options; `pythonpath` for `tests` |

## Requirement → implementation

| Requirement | File | Status |
|-------------|------|--------|
| FR-ACCT.1 | `client.py:ProtonClient._run` (`--profile`) | Implemented |
| FR-ACCT.4 | `client.py:fingerprint_of`, `_check_marker`, `connect` | Implemented (marker and client side; snapshot side is Unit 5) |
| FR-APPLY.3 | `client.py:create_filter`, `update_filter` | Implemented |
| FR-PLAN.6 | `client.py` read methods, `connect` | Implemented |
| NFR-REL.2 | `client.py:connect`, `ProtonClient._run` | Implemented |
| NFR-REL.3 | `client.py:_check_version`, `_read` | Implemented |
| NFR-SAFE.2 (RVQ-Q25) | `client.py:ProtonClient._run` | Implemented |

No gaps.

## Business rule coverage

| BR | Implemented in | Tests (`tests/unit/test_client.py`) |
|----|----------------|--------------------------------------|
| BR-1 | `_run`, `_check_version` | `test_commands_carry_*`, `test_version_probe_has_no_profile`, `test_configured_binary_is_used` |
| BR-2 | `create_filter`, `update_filter` | `test_script_travels_on_stdin_only` (PBT), `test_failure_message_never_holds_the_script` |
| BR-3 | all methods | `test_no_call_ever_passes_dry_run` |
| BR-4 | read methods, `connect` | `test_reads_use_only_read_verbs` |
| BR-5 | `_run` | `test_each_method_makes_exactly_one_call`, `test_a_failed_write_is_not_retried` |
| BR-6 | `connect` | `test_connect_probes_version_then_account`, `test_wrong_account_stops_all_further_calls` |
| BR-7 | `_run` | `test_not_signed_in_names_the_login_command` |
| BR-8 | `_check_version` | `test_warning_iff_below_tested_minimum` (PBT), `test_version_boundaries`, `test_failing_version_probe_*`, `test_old_version_warning_*` |
| BR-9 | `fingerprint_of`, `_check_marker` | `test_fingerprint_is_twelve_hex_of_sha256` (PBT), `test_*marker*` |
| BR-10 | `_run` | `test_exit_codes_carry_*`, `test_stderr_first_line_*`, `test_arguments_are_not_in_*` |
| BR-11 | `_read`, `_text`, `_enabled`, `_filter*`, `_created_id` | `test_malformed_*` |
| BR-12 | `_spawn` | `test_missing_binary_*`, `test_timeout_names_the_seconds`, `test_unrunnable_binary_*` |
| BR-13 | `_rows`, `--limit 0` | `test_malformed_listings_*`, `test_list_filters_keeps_order_*` |
| BR-14 | `list_filters`, `_enabled` | `test_list_filters_keeps_order_and_maps_status` |
| BR-15 | `get_filter`, `_filter` | `test_get_filter_returns_the_script_verbatim`, `test_list_then_get_*` |
| BR-16 | `create_filter` | `test_create_returns_id_*`, `test_malformed_create_response_*` |
| BR-17 | `delete_filter` | `test_delete_always_confirms_*` |
| BR-18 | `reorder_filters` | `test_reorder_*` |
| BR-19 | `list_folders`, `list_labels`, `create_*`, `_target` | `test_target_path_*`, `test_label_and_folder_*`, `test_parent_is_passed_*` |
| BR-20 | `list_messages` | `test_messages_ask_for_every_folder_*` |
| BR-21 | `apply_retroactively` | `test_apply_retroactively_is_one_call` |

## Tests

- 127 tests in total, passing on Python 3.12, 3.13 and 3.14; line coverage 100%; ruff, black, mypy (strict) and vulture clean; `uv build` works.
- Build and test: `uv sync && make quality`.

## Implementation notes

- Coverage is now enforced by `make quality` (`--cov-fail-under=90`), as agreed at the code plan.
- `connect` and `_read` cover the `account get` response; `status`, `has_more` and `ids` follow the shapes confirmed live against `proton` 4.2.3/4.3.0, marked in `business-rules.md`.
- A probe that times out is a `ClientError`, not a warning: a hung binary is not an unreadable version (BR-8 applies to exit codes and output).
- Folder and label listings pass `--limit 0` like filter listings (BR-13); `proton`'s help confirms both flags.
- `tests/__init__.py` and `pythonpath = ["."]` let tests import `tests.fake_proton`.
