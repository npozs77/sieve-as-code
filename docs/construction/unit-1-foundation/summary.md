# Code Summary — Unit 1: Foundation

## Files

| Path | Description |
|------|-------------|
| `src/sieve_as_code/model.py` | `Filter`, `FilterOrder`, `SieveAsCodeError`, `ValidationError` |
| `src/sieve_as_code/settings.py` | Account validation, XDG/env root resolution, `AccountPaths`, `proton_cli` |
| `src/sieve_as_code/audit.py` | Append-only JSONL `record_write` / `record_check` |
| `src/sieve_as_code/__init__.py` | Empty until Unit 9 |
| `tests/unit/test_model.py`, `test_settings.py`, `test_audit.py` | 49 tests |
| `pyproject.toml`, `uv.lock` | Package, console script, tool config, pinned dev group |
| `Makefile` | `quality`, `test`, `build` |
| `.env.example` | The four `SIEVE_AS_CODE_*` variables with defaults |

## Requirement → implementation

| Requirement | File | Status |
|-------------|------|--------|
| FR-ACCT.1 | `settings.py:resolve_account` | Implemented |
| FR-ACCT.2 | `settings.py:account_paths` | Implemented |
| FR-ACCT.5 | `settings.py:_validate_account` | Implemented |
| FR-CLI.3 | `settings.py:_root`, `proton_cli`; `.env.example` | Implemented |
| NFR-SAFE.2, NFR-SAFE.3 | `audit.py:_append` | Implemented |
| NFR-DEP.1, CON-5 | `pyproject.toml`, `uv.lock` | Implemented |
| FR-DECL.1, FR-DECL.4 (types only) | `model.py` | Implemented; validation is Unit 3 |

No gaps. FR-ACCT.3 and FR-ACCT.4 belong to Units 9 and 2.

## Business rule coverage

| BR | Implemented in | Tests (`tests/unit/`) |
|----|----------------|-----------------------|
| BR-1 | `settings.py:49` | `test_settings`: `test_account_*` |
| BR-2 | `settings.py:27` | `test_blank_env_counts_as_unset`, `test_env_value_is_stripped` |
| BR-3 | `settings.py:33` | `test_*_account_names_*`, `test_account_name_validity_matches_rule` (PBT) |
| BR-4 | `settings.py:56` | `test_roots_default_*`, `test_absolute_xdg_*`, `test_variables_beat_xdg`, `test_relative_xdg_*`, `test_missing_home_*` |
| BR-5 | `settings.py:72` | `test_roots_default_*`, `test_tilde_*`, `test_resolving_paths_creates_nothing` |
| BR-6 | `settings.py:72` | `test_distinct_accounts_never_share_or_nest_paths` (PBT) |
| BR-7 | `settings.py:92` | `test_proton_cli_default_and_override` |
| BR-8 | `model.py:14-28` | `test_model` |
| BR-9 | `audit.py:14` | `test_record_has_exactly_four_keys_*` |
| BR-10 | `audit.py:14` | `test_scalar_detail_round_trips`, `test_non_scalar_*` (PBT), `test_blank_outcome_*` |
| BR-11 | `audit.py:14` | `test_appends_keep_earlier_lines_unchanged` (PBT), `test_missing_directory_*` |
| BR-12 | `audit.py:14` | `test_unwritable_log_*`, `test_append_works_after_a_failed_append` |
| BR-13 | `pyproject.toml` | `make quality`, `uv build` |
| BR-14 | `.env.example`, `Makefile` | `test_env_example_lists_exactly_the_four_variables`, `make quality` |

## Tests

- 49 tests pass on Python 3.12, 3.13 and 3.14; ruff, black, mypy (strict) and vulture are clean; `uv build` produces sdist and wheel.
- Build and test: `uv sync && make quality`.
- Coverage percentage not measured (no coverage plugin yet; the 90% target in the implementation plan is checked from Unit 4, where the 100% modules begin).

## Implementation notes

- BR-11 reworded: only the log's own directory is created `0o700` (`Path.mkdir` does not apply the mode to ancestors).
- BR-13 reworded: PyYAML is the range `>=6.0.3,<7` with the exact version in `uv.lock`; dev tools pinned exactly (user decision at the code plan).
- vulture: `ignore_decorators = ["@pytest.fixture"]` in `pyproject.toml`, reason commented there.
- The console script targets `sieve_as_code.cli:main`, which exists from Unit 9.
- `ruff`/`black` line length 88; ruff rules `E F I B UP SIM`.
