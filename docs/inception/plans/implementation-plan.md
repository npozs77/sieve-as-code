# Implementation Plan

Project-wide workflow facts. Unit 1 owns setup; Operations owns publishing.

## Build and Compile

| Decision | Value |
|---|---|
| Build tool | `uv build` (hatchling backend) |
| Build command | `make build` |
| Output artifact | sdist and wheel in `dist/` |
| Prerequisites | Python ≥3.12, `uv` |

## Testing Strategy

| Decision | Value |
|---|---|
| Framework | pytest |
| Test command | `make test` |
| Coverage target | 90% lines on `src/`; 100% on plan, apply, backup, restore, retroactive gate |
| Test types | Unit; property-based (Hypothesis) for parsing, validation, diff, evaluator |
| Live smoke suite | `tests/live/`, off by default (`SIEVE_AS_CODE_LIVE_TEST=1`); throwaway filters only, reserved prefix, cleanup in `finally` (NFR-TEST.2) |
| Organisation | `tests/unit/`; `proton-cli` fake in `tests/conftest.py`; no live-account tests in CI (NFR-TEST.1) |

## CI/CD Pipeline

| Decision | Value |
|---|---|
| CI tool | GitHub Actions, `.github/workflows/ci.yaml` (generated in Operations) |
| Triggers | Push to `main`, pull request, tag |
| Stages | Lint → typecheck → unused-code → test (3.12, 3.13, 3.14) → build |
| Quality gates | All stages green |
| Branch strategy | Feature branches + PR; never commit to `main` |

## Packaging and Distribution

| Decision | Value |
|---|---|
| Format | PyPI wheel + sdist, console script `sieve-as-code` |
| Registry | PyPI (package name free as of 2026-10-31) |
| Versioning | Semantic versioning; only documented functions are public API |
| Install | `uv tool install sieve-as-code` or `pip install sieve-as-code` |

## Release Process

| Decision | Value |
|---|---|
| Trigger | Manual tag push |
| Changelog | Manual `CHANGELOG.md` |
| Approval | Maintainer publishes |
| Pre-release checks | `make quality`; README tested-`proton-cli` range current |
| Rollback | Yank the PyPI release; tag a fixed version |

## Development Workflow

| Decision | Value |
|---|---|
| Linter / formatter | ruff / black |
| Type check | mypy |
| Unused code | vulture; exceptions in config with a reason |
| Quality command | `make quality` |
| Dependencies | PyYAML, pinned; dev tools pinned |
| Git ignores | `.venv/`, `__pycache__/`, `.env`, `.tmp/` |
