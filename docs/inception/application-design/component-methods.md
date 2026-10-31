# Component Methods

Public functions only. Signatures are design intent; Functional Design fixes them per unit. `★` = documented public API (FR-CLI.2).

| Module | Function | Purpose |
|---|---|---|
| model | `Filter(name, raw_sieve, enabled, live_id)` | Frozen dataclass |
| model | `FilterOrder(sequence)` | Frozen dataclass of names |
| settings | `resolve_account(name)`, `account_paths(account)`, `proton_cli()` | Read env vars; validate account name; build per-account paths (Unit 1 design) |
| audit | `record_write(audit_log, outcome, detail)`, `record_check(audit_log, outcome, detail)` | Append one line (Unit 1 design) |
| client | `connect(paths)` | Version, session and account-fingerprint checks (NFR-REL.2/3, FR-ACCT.4); returns `ProtonClient` (Unit 2 design) |
| client | `ProtonClient.list_filters()`, `get_filter(...)`, `create_filter(...)`, `update_filter(...)`, `delete_filter(...)`, `enable_filter(...)`, `disable_filter(...)`, `reorder_filters(...)` | Filter operations; scripts via stdin |
| client | `ProtonClient.list_labels()`, `list_folders()`, `create_label(...)`, `create_folder(...)` | Targets |
| client | `ProtonClient.list_messages()`, `apply_retroactively(live_id)` | Retroactive support |
| declared | `load_declared(paths)` ★ | Parse files into filters and order, validated |
| declared | `validate_declared(filters, order)` ★ | Raise on any FR-DECL.5/7 failure |
| declared | `render(filters, order, paths)` | File contents; caller writes |
| declared | `normalize_whitespace(script)` | Script as written to files |
| live | `discover()` ★ | Live filters and order |
| importer | `import_live(name, force)` ★, `import_sieve_files(paths)` ★ | Write declared files |
| plan | `plan(declared, live)` ★ | `PlanResult` with typed entries and flags |
| backup | `write_backup(...)` ★, `read_backup(ref)`, `diff_backups(a, b)` ★ | Snapshot handling |
| apply | `apply_plan(result, confirmed, allow_delete)` ★ | `ApplyReport` |
| restore | `restore(ref, confirmed)` ★ | `RestoreReport` |
| sieve_eval | `evaluate(script, message)` | Actions, or `UnsupportedSieve` |
| retroactive | `preview(name)` ★, `run(name, confirmed_name, reason)` ★, `status(snapshot)` ★, `audit_all()` ★ | FR-RETRO.* |
| cli | `main(argv)` | Entry point |
