# Code Summary — Unit 9: CLI and public API

## Files

| Path | Description |
|------|-------------|
| `src/sieve_as_code/__init__.py` | 14 public wrappers, `_session`, `_paths`, `_limit`, `__all__`, `__version__` |
| `src/sieve_as_code/cli.py` | `main`, argparse parser, one `_handler` per command, `_*_lines` renderers, `_identity`, `_show`, `_ask` |
| `src/sieve_as_code/_*.py` (13) | Renamed from `apply.py` … `sieve_eval.py` (`git mv`); imports updated; no behaviour change |
| `src/sieve_as_code/_backup.py` | `Snapshot` gains `pruned`, `prune_error` |
| `tests/unit/test_api.py` | 22 test functions (parametrised) |
| `tests/unit/test_cli.py` | 32 test functions (parametrised) |
| `tests/live/{__init__,conftest,test_smoke}.py` | Opt-in smoke suite, 6 tests |
| `tests/unit/*`, `tests/conftest.py`, `tests/integration/*` | Import paths only |
| `Makefile` | `live` target |
| `README.md`, `CHANGELOG.md` | Usage, API list, tested range, exit codes; changelog |
| `docs/inception/application-design/component-methods.md` | cli and public API rows |

## Requirement → implementation

| Requirement | File | Status |
|-------------|------|--------|
| FR-CLI.1 | `cli.py:main`, `_add_commands` | Implemented |
| FR-CLI.2 | `__init__.py` (`__all__`, wrappers), renamed modules | Implemented |
| FR-ACCT.3 | `cli.py:_identity`, `_show`, `_apply_retroactive` | Implemented |
| FR-BAK.6 (flags, call after each run) | `__init__.py:backup`, `cli.py:_backup` | Implemented |
| NFR-OPS.1 | `cli.py:main` error lines | Implemented |
| NFR-TEST.2 | `tests/live/` | Implemented; not run in CI by design, see notes |
| NFR-SAFE.1 | `cli.py:_apply`, `_restore`, `_apply_retroactive` | Implemented |
| US-5.1, US-6.2 | `__init__.py`, `cli.py` | Implemented |

No gaps.

## Business rule coverage

| BR | Implemented in | Tests |
|----|----------------|-------|
| BR-1 | `__init__.py:__all__` | `test_all_lists_exactly_the_documented_names_and_each_resolves`, `test_internal_surfaces_are_not_exported`, `test_only_cli_is_a_public_module` |
| BR-2 | `_session`, `_paths`, every wrapper | `test_only_the_subject_is_positional_and_account_is_keyword`, `test_account_comes_from_argument_then_environment`, `test_invalid_account_name_is_rejected_before_any_call`, `test_offline_functions_make_no_proton_call` |
| BR-3 | wrapper defaults | `test_confirmations_default_to_false`, `test_apply_without_confirmation_writes_nothing`, `test_apply_retroactive_requires_confirmation_arguments` |
| BR-4 | `_backup.py:Snapshot`, `load_declared`, `validate_declared` | `test_results_are_frozen_and_snapshot_gains_defaulted_fields`, `test_validate_declared_raises_on_duplicate_names`, `test_every_command_wrapper_returns_its_result_type` |
| BR-5 | `backup`, `_limit`; `cli.py:_backup`, `_whole_number` | `test_backup_prunes_by_argument_over_environment`, `test_backup_takes_each_limit_*`, `test_backup_without_limits_never_prunes`, `test_unchanged_backup_still_prunes`, `test_bad_retention_*`, `test_prune_failure_keeps_the_snapshot`, `test_apply_snapshot_never_prunes`, `test_backup_reports_unchanged_and_prunes`, `test_backup_prune_failure_warns_*` |
| BR-6 | `cli.py:main` | `test_plain_errors_name_the_problem_and_exit_one`, `test_validation_errors_exit_two`, `test_interrupt_exits_130_*`, `test_apply_failure_names_*` |
| BR-7 | `_plan`, `_backup_diff`, `_retroactive_*`, `_restore_lines` | `test_plan_with_drift_exits_zero_*`, `test_backup_diff_with_differences_exits_zero`, `test_retroactive_status_and_audit_*`, `test_restore_that_leaves_a_diff_prints_it`, `test_renderers_show_every_part_of_a_result` |
| BR-8 | `_apply`, `_restore`, `_apply_lines` | `test_apply_without_yes_*`, `test_apply_with_yes_*`, `test_allow_delete_exists_on_apply_only`, `test_restore_without_yes_*` |
| BR-9 | `_apply_retroactive`, `_ask`, `_retro_lines` | `test_apply_retroactive_runs_after_*`, `test_apply_retroactive_refuses_*`, `test_apply_retroactive_treats_end_of_input_*`, `test_apply_retroactive_with_nothing_to_do_*`, `test_apply_retroactive_of_an_unpreviewable_filter_*`, `test_apply_retroactive_has_no_yes_option`, `test_apply_retroactive_reports_a_failed_start` |
| BR-10 | `_identity`, `_show` | `test_output_starts_with_the_account_and_its_fingerprint`, `test_account_line_has_no_fingerprint_*` |
| BR-11 | `_*_lines` | `test_plan_with_drift_*`, `test_apply_without_yes_*`, `test_discover_prints_scripts_*` |
| BR-12 | `_discover` | `test_discover_prints_scripts_in_import_format_and_writes_nothing` |
| BR-13 | `_import` | `test_import_refuses_differences_without_force`, `test_import_sieve_files_and_conflicting_arguments` |
| BR-14 | `_add_commands`, `_whole_number` | `test_every_command_accepts_account`, `test_keep_flags_reject_*`, `test_usage_errors_help_and_version_return_codes` |
| BR-15 | `main`, `pyproject.toml` | `test_main_returns_codes_and_never_raises_system_exit`, `test_console_script_points_at_main` |
| BR-16 | `__version__` | `test_version_matches_pyproject` |
| BR-17 | `git mv`, imports | all earlier tests, unchanged apart from import paths |
| BR-18 | `tests/live/conftest.py:live`, `clean_account`, `remove_scratch` | `tests/live/test_smoke.py` (6 tests), checked to skip when not enabled |
| BR-19 | `README.md`, `CHANGELOG.md` | review |

## Tests

- 649 unit tests passing on Python 3.12, 3.13 and 3.14; line coverage 100%; ruff, black, mypy (strict) and vulture clean; `uv build` works. `tests/live` collects and skips (6 skipped) without `SIEVE_AS_CODE_LIVE_TEST=1`.
- Build and test: `uv sync && make quality`; live suite: `SIEVE_AS_CODE_LIVE_TEST=1 SIEVE_AS_CODE_ACCOUNT=<profile> make live`.

## Implementation notes

- `backup` reads `retention()` before connecting, so an invalid variable fails before any Proton call (BR-5).
- The live suite has not been run against a real account in this session; its Proton-side assumptions (for example that Proton rejects `frobnicate;`) are checked the first time it is run.
- `import --sieve` on a new account prints `account: NAME` without a fingerprint (BR-10).
