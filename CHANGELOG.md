# Changelog

Semver; provisional until 1.0.

## Unreleased

### Added
- `sieve-as-code` CLI: `discover`, `plan`, `apply`, `import`, `backup`, `backup-diff`, `restore`, `apply-retroactive`, `retroactive-status`, `retroactive-audit`; exit codes 0, 1, 2, 130.
- Python API in `sieve_as_code.__all__`: keyword-only, account-resolving functions for every command, plus `load_declared` and `validate_declared`.
- Per-account declared files, backups, retroactive snapshots and audit log; account fingerprint guard.
- Verified, owner-only snapshots; `apply` and `restore` snapshot first and stop on the first failure.
- `backup` retention: `SIEVE_AS_CODE_KEEP_DAYS`, `SIEVE_AS_CODE_KEEP_LAST`, `--keep-days`, `--keep-last`.
- Retroactive preview for a Sieve subset (including Proton's generated spam guard), typed confirmation, snapshot and status.
- Opt-in live smoke suite (`make live`) and two-account integration tests (`make integration`).

### Changed
- Internal modules are underscore-prefixed; import from `sieve_as_code`.
