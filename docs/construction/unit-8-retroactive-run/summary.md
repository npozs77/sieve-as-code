# Code Summary — Unit 8: Retroactive run

## Files

| Path | Description |
|------|-------------|
| `src/sieve_as_code/sieve_eval.py` | `MailMessage`, `Outcome`, `CompiledScript`, `compile_script`, `evaluate`; private tokenizer and `_Parser` |
| `src/sieve_as_code/retroactive.py` | `preview`, `run`, `status`, `audit_all` with `RetroPreview`, `Entry`, `RetroReport`, `RetroStatus`, `Unexpected`, `RetroAudit`, `AuditRow`; private `_build`, `_entry`, `_prepare`, `_save_snapshot`, `_read_snapshot`, `_prune` |
| `src/sieve_as_code/model.py` | `UnsupportedSieve` |
| `src/sieve_as_code/backup.py` | `checksum`, `create_exclusive`, `SNAPSHOT_NAME`, `SNAPSHOT_TIME`, `snapshot_candidates` made importable (Unit 5 behaviour unchanged) |
| `src/sieve_as_code/apply.py` | `check_client` message made neutral (reads use it too) |
| `tests/unit/test_sieve_eval.py` | 21 test functions (4 property-based) |
| `tests/unit/test_retroactive.py` | 45 test functions (1 property-based) |
| `tests/fake_proton.py` | `messages list` honours `--to` through `recipients` |
| `README.md` | Status line |

## Requirement → implementation

| Requirement | File | Status |
|-------------|------|--------|
| FR-RETRO.1 | `retroactive.py:preview`, `_build`, `_entry` | Implemented; printing is Unit 9 |
| FR-RETRO.2 | `sieve_eval.py:compile_script`, `retroactive.py:_prepare` | Implemented |
| FR-RETRO.3 | `retroactive.py:run`, `_audit_run`, `_declared_differs` | Implemented; the prompts are Unit 9 |
| FR-RETRO.4 | `retroactive.py:_save_snapshot`, `_prune`, `status` | Implemented |
| FR-RETRO.5 | `retroactive.py:audit_all` | Implemented |
| US-4.1 to US-4.4 | `preview`, `run`, `status`, `audit_all` | Implemented |

No gaps.

## Business rule coverage

| BR | Implemented in | Tests |
|----|----------------|-------|
| BR-1 | `check_client` in every public function | `test_other_account_or_unconnected_client_is_refused_untouched` |
| BR-2 | `_live_filter`, `audit_all` | `test_unknown_and_disabled_filters_are_refused`, `test_duplicate_live_names_*`, `test_audit_all_counts_*` |
| BR-3 | `_message`, `_read_mail`, `_Mail.recipients` | `test_preview_reads_only_*`, `test_a_malformed_message_row_*`, `test_a_row_missing_a_field_*`, `test_a_failing_listing_propagates` |
| BR-4 | `_build` | `test_spam_is_excluded_and_counted_trash_is_not` |
| BR-5 | `_location`, `_date` | `test_location_comes_from_the_labels`, `test_entries_carry_the_preview_fields_*`, `test_an_impossible_timestamp_*` |
| BR-6 | `compile_script`, `_Parser` | `test_anything_else_is_unsupported`, `test_deep_nesting_*`, `test_any_text_compiles_or_is_unsupported` (PBT) |
| BR-7 | `_matcher`, `_wildcard`, `_address_part`, `_field_test` | `test_tests_match_as_the_subset_defines`, `test_is_and_contains_*` (PBT), `test_matches_agrees_*` (PBT), `test_wildcards_can_be_escaped`, `test_an_address_without_at_sign_*` |
| BR-8 | `evaluate`, `_if` | `test_branches_stop_and_comments`, `test_stop_ends_*`, `test_duplicate_targets_*`, `test_not_allof_and_anyof_*` (PBT) |
| BR-9 | `_resolve`, `_prepare` | `test_system_folders_custom_folders_and_labels_*`, `test_unsupported_filters_are_not_previewable_*` |
| BR-10 | `_field_test`, `_Mail.recipients` | `test_recipient_tests_search_once_per_key_*`, `test_eleven_recipient_keys_*`, `test_more_than_ten_recipient_keys_*` |
| BR-11 | `_prepare`, `_build` | `test_unsupported_filters_are_not_previewable_never_guessed` |
| BR-12 | `_flags`, `_entry` | `test_flag_commands_build_the_final_set`, `test_flags_and_expire_actions` |
| BR-13 | `_expire`, `_entry` | `test_expire_keeps_the_last_value`, `test_expire_alone_never_counts_a_message` |
| BR-14 | `_entry`, `_build` | `test_an_entry_exists_exactly_when_an_action_changes_the_message` (PBT), `test_nothing_changes_*`, `test_a_label_already_present_*` |
| BR-15 | `_declared_differs` | `test_declared_differs_warns_without_blocking`, `test_an_invalid_local_file_is_an_error` |
| BR-16 | `preview`, `status`, `audit_all` | `test_preview_reads_only_and_leaves_no_trace` |
| BR-17 | `run` | `test_nothing_to_do_needs_no_confirmation_and_writes_nothing` |
| BR-18 | `run` | `test_a_wrong_name_or_blank_reason_is_refused`, `test_a_failing_audit_on_refusal_is_raised` |
| BR-19 | `run` | `test_a_not_previewable_run_proceeds_without_a_snapshot` |
| BR-20 | `run`, `_save_snapshot` | `test_an_unwritable_snapshot_stops_before_anything_starts` |
| BR-21 | `_save_snapshot` | `test_a_confirmed_run_snapshots_then_applies_once_and_audits` |
| BR-22 | `run` | `test_a_confirmed_run_*`, `test_a_failing_apply_keeps_the_snapshot_and_is_audited` |
| BR-23 | `_audit_run` | `test_a_confirmed_run_*`, `test_a_failing_audit_never_replaces_the_report` |
| BR-24 | `_prune` | `test_snapshots_over_ten_days_old_are_pruned_and_audited`, `test_nothing_is_pruned_*`, `test_a_failed_removal_*`, `test_a_failing_prune_audit_is_reported` |
| BR-25 | `RetroReport.ok` | `test_a_wrong_name_*`, `test_a_failing_apply_*`, `test_a_failing_audit_never_replaces_the_report`, `test_results_are_frozen` |
| BR-26 | `_snapshot_path`, `_read_snapshot`, `status` | `test_status_takes_a_name_a_path_or_the_latest`, `test_status_without_snapshots_*`, `test_status_refuses_*`, `test_status_needs_an_enabled_previewable_filter` |
| BR-27 | `status` | `test_status_reports_done_pending_and_unexpected`, `test_status_after_completion_and_after_a_script_change` |
| BR-28 | `audit_all`, `_row` | `test_audit_all_counts_each_enabled_filter_over_one_listing`, `test_audit_all_with_no_enabled_filter_*` |
| BR-29 | all audit, snapshot and error paths | `test_no_private_text_reaches_the_audit_log_or_errors`, `test_a_confirmed_run_*` |

## Tests

- 571 tests in total, passing on Python 3.12, 3.13 and 3.14; line coverage 100%; ruff, black, mypy (strict) and vulture clean; `uv build` works.
- Build and test: `uv sync && make quality`.

## Implementation notes

- BR-18 gained one clause: a failing audit write on the refusal line raises.
- The `messages list` fields were checked against the installed `proton-cli` 4.3.0 (names and types only): `id`, `subject`, `from_name`, `from_address`, `time`, `unread`, `labels`; system label ids 0, 3, 4, 6, 7 match the folder listings.
