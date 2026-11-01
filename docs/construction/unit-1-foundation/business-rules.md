# Business Rules — Unit 1: Foundation

| ID | Rule (condition → outcome) | Source |
|----|----------------------------|--------|
| BR-1 | Account is chosen by: explicit argument, else `SIEVE_AS_CODE_ACCOUNT`, else `default`. | FR-ACCT.1 |
| BR-2 | An environment variable that is unset, empty or whitespace-only counts as unset; any other value is used with surrounding whitespace stripped. | FR-CLI.3 |
| BR-3 | An account name that is empty, contains `/`, `\`, NUL or `..`, or starts with `.` → `ValidationError` before any path is built. Names such as `a.b`, `work-2`, `Ünï` are accepted. | FR-ACCT.5 |
| BR-4 | A root is chosen by: its variable (`SIEVE_AS_CODE_FILTERS_DIR` / `SIEVE_AS_CODE_STATE_DIR`), else `$XDG_CONFIG_HOME/sieve-as-code` / `$XDG_STATE_HOME/sieve-as-code` when that XDG variable is an absolute path, else `~/.config/sieve-as-code` / `~/.local/state/sieve-as-code`. A relative XDG value is ignored. No resolvable home directory when a default is needed → `ValidationError` naming the variable to set. | FR-CLI.3 |
| BR-5 | For a valid account, filter-side paths are `<FILTERS_DIR>/<account>/filters/`, `<FILTERS_DIR>/<account>/order.yaml`, `<FILTERS_DIR>/<account>/account.id`; state-side paths are `<STATE_DIR>/<account>/backups/`, `retroactive/`, `audit.log`. A leading `~` in a variable's value is expanded; paths are otherwise used as given. Resolving paths creates nothing. | FR-CLI.3, FR-ACCT.2 |
| BR-6 | Every path is built from a root and the validated account name only; two valid names that differ never yield one path or a path inside the other's directory. | FR-ACCT.2 |
| BR-7 | `SIEVE_AS_CODE_PROTON_CLI` gives the `proton-cli` binary, default `proton`; it is not checked for existence here. | FR-CLI.3 |
| BR-8 | `Filter.enabled` defaults to `True` and `live_id` to `None`; `Filter` and `FilterOrder` are immutable; `FilterOrder` holds names as a tuple, order preserved. | FR-DECL.1 |
| BR-9 | Each audit record is one JSON object on one line with exactly `ts` (UTC, ISO 8601, `Z`), `kind` (`write` or `check`), `outcome`, `detail`. `record_write` sets kind `write`, `record_check` sets `check`. | NFR-SAFE.3 |
| BR-10 | Audit `detail` is a flat mapping of string keys to `str`, `int`, `bool` or `None`; any other value type (list, mapping, bytes, float) → `ValueError` and nothing is written. `outcome` must be a non-blank string. | NFR-SAFE.2 |
| BR-11 | The audit log is only ever opened for append: existing lines are never read, changed or removed. A missing log is created with mode `0o600` and its missing directory with `0o700`. | NFR-SAFE.3 |
| BR-12 | An audit write that fails on I/O → `SieveAsCodeError` naming the log path; the audit module never swallows it (callers decide, FR-APPLY.4). | NFR-OPS.1 |
| BR-13 | Runtime dependencies are PyYAML only, as a compatible range (`>=6.0.3,<7`) whose exact version `uv.lock` fixes; dev tools pinned exactly; `requires-python >=3.12`; console script `sieve-as-code` points at `sieve_as_code.cli:main`. | NFR-DEP.1, CON-5 |
| BR-14 | `.env.example` lists exactly the four `SIEVE_AS_CODE_*` variables; `make quality` runs ruff, black, mypy, vulture and the tests. | FR-CLI.3, implementation-plan |
