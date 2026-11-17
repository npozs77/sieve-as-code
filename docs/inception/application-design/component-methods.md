# Component Methods

Public functions only. Signatures are design intent; Functional Design fixes them per unit. `★` = documented public API (FR-CLI.2). A ★ row shows the internal function; its public counterpart in `sieve_as_code` is the account-resolving, keyword-only wrapper defined in Unit 9 (FR-CLI.2, RVQ-Q29), for example `plan(*, account=None)`.

| Module | Function | Purpose |
|---|---|---|
| model | `Filter(name, raw_sieve, enabled, live_id)` | Frozen dataclass |
| model | `FilterOrder(sequence)` | Frozen dataclass of names |
| model | `FilterSet(filters, order)` | Frozen dataclass; declared, live or snapshot state (Unit 4 design) |
| settings | `resolve_account(name)`, `account_paths(account)`, `proton_cli()`, `retention()` | Read env vars; validate account name; build per-account paths; retention limits (Unit 1 design) |
| audit | `record_write(audit_log, outcome, detail)`, `record_check(audit_log, outcome, detail)` | Append one line (Unit 1 design) |
| client | `connect(paths)` | Version, session and account-fingerprint checks (NFR-REL.2/3, FR-ACCT.4); returns `ProtonClient` (Unit 2 design) |
| client | `ProtonClient.list_filters()`, `get_filter(...)`, `create_filter(...)`, `update_filter(...)`, `delete_filter(...)`, `enable_filter(...)`, `disable_filter(...)`, `reorder_filters(...)` | Filter operations; scripts via stdin |
| client | `ProtonClient.list_labels()`, `list_folders()`, `create_label(...)`, `create_folder(...)` | Targets |
| client | `ProtonClient.list_messages()`, `apply_retroactively(live_id)` | Retroactive support |
| declared | `load_declared(paths)` ★, `load_local(paths)`, `free_filename(name, taken)` | Parse files into filters and order, validated |
| declared | `validate_declared(filters, order)` ★ | Raise on any FR-DECL.5/7 failure |
| declared | `render(filters, order, paths)` | File contents; caller writes |
| declared | `normalize_whitespace(script)` | Script as written to files |
| declared | `script_facts(script)` | Required extensions and `fileinto` mailboxes (Unit 4 design) |
| live | `discover(client)` ★, `discover_targets(client)` | `FilterSet` of live filters in order, duplicate names numbered and listed in `renames`; folder paths and label names as `Targets` (Unit 4 design) |
| importer | `import_live(paths, client, name, force)` ★, `import_sieve_files(paths, sources, force)` ★ | Write declared files; `ImportReport` with `new`, `changed`, `reordered`, `preserved`, `written`; refuses without `force` (Unit 7 design) |
| plan | `plan(paths, client)` ★, `diff(declared, live, targets)` | Audited `PlanResult` with typed entries, flags and renames; `diff` is pure, `targets=None` is snapshot mode (Unit 4 design) |
| backup | `write_backup(paths, client)` ★, `read_backup(ref, paths, fingerprint)`, `diff_backups(a, b, paths)` ★, `prune_backups(paths, keep)` ★ | Verified owner-only `Snapshot` (existing one when unchanged); `diff_backups` is A → B in snapshot mode; `prune_backups` only where retention is set; `BackupError` in `model` (Unit 5 design) |
| apply | `apply_plan(paths, client, confirmed, allow_delete)` ★, `run_actions(...)` | Snapshot first, ordered writes, stop-on-failure `ApplyReport`; `run_actions` is the engine `restore` shares (Unit 6 design) |
| restore | `restore(ref, paths, client, confirmed)` ★ | Pre-restore snapshot, writes, re-read; `RestoreReport` with `remaining` (Unit 6 design) |
| sieve_eval | `compile_script(script)`, `evaluate(compiled, message)` | `CompiledScript` or `UnsupportedSieve` (in `model`); `Outcome` of targets, flags, expire (Unit 8 design) |
| retroactive | `preview(paths, client, name)` ★, `run(paths, client, name, confirmed_name, reason)` ★, `status(paths, client, ref)` ★, `audit_all(paths, client)` ★ | Read-only `RetroPreview`; gated `RetroReport` with snapshot; `RetroStatus`; `RetroAudit` (Unit 8 design) |
| cli | `main(argv=None) -> int` | Entry point; argparse dispatch, renders results, maps outcomes to exit codes 0/1/2/130 (Unit 9 design) |
| public API | `discover`, `plan`, `apply`, `import_live`, `import_sieve_files`, `backup`, `backup_diff`, `restore`, `retroactive_preview`, `apply_retroactive`, `retroactive_status`, `retroactive_audit`, `load_declared`, `validate_declared` | Keyword-only wrappers in `__init__.py`; `backup` also prunes (Unit 9 design) |
