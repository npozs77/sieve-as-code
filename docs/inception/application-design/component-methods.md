# Component Methods

Public functions only. Signatures are design intent; Functional Design fixes them per unit. `★` = documented public API (FR-CLI.2).

| Module | Function | Purpose |
|---|---|---|
| model | `Filter(name, raw_sieve, enabled, live_id)` | Frozen dataclass |
| model | `FilterOrder(sequence)` | Frozen dataclass of names |
| settings | `resolve_account(name)`, `filters_dir(account)`, `state_dir(account)`, `proton_cli()` | Read env vars; validate account name |
| audit | `record_write(action, detail)`, `record_check(outcome, detail)` | Append one line |
| client | `check_session()`, `check_version()`, `check_account(account)` | Preconditions (NFR-REL.2/3, FR-ACCT.4); writes the fingerprint marker on first use |
| client | `list_filters()`, `get_filter(ref)`, `create_filter(...)`, `update_filter(...)`, `delete_filter(...)`, `enable_filter(...)`, `disable_filter(...)`, `reorder_filters(...)` | Filter operations; scripts via stdin |
| client | `list_labels()`, `list_folders()`, `create_label(...)`, `create_folder(...)` | Targets |
| client | `list_messages()`, `apply_retroactively(live_id)` | Retroactive support |
| declared | `load_declared()` ★ | Parse files into filters and order |
| declared | `validate_declared(filters, order)` ★ | Raise on any FR-DECL.5/6 failure |
| declared | `render(filters, order)` | File contents; caller writes |
| live | `discover()` ★ | Live filters and order |
| importer | `import_live(name, force)` ★, `import_sieve_files(paths)` ★ | Write declared files |
| plan | `plan(declared, live)` ★ | `PlanResult` with typed entries and flags |
| backup | `write_backup(...)` ★, `read_backup(ref)`, `diff_backups(a, b)` ★ | Snapshot handling |
| apply | `apply_plan(result, confirmed, allow_delete)` ★ | `ApplyReport` |
| restore | `restore(ref, confirmed)` ★ | `RestoreReport` |
| sieve_eval | `evaluate(script, message)` | Actions, or `UnsupportedSieve` |
| retroactive | `preview(name)` ★, `run(name, confirmed_name, reason)` ★, `status(snapshot)` ★, `audit_all()` ★ | FR-RETRO.* |
| cli | `main(argv)` | Entry point |
