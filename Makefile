.PHONY: quality test integration live build

quality:
	uv run ruff check .
	uv run black --check .
	uv run mypy
	uv run vulture
	uv run pytest

test:
	uv run pytest

# Real Proton; needs SIEVE_AS_CODE_IT_ACCOUNTS=<profile>,<other profile>.
integration:
	uv run pytest tests/integration --no-cov

# Real Proton, one account of your choice; needs SIEVE_AS_CODE_LIVE_TEST=1 and
# SIEVE_AS_CODE_ACCOUNT=<profile>. Creates only filters named sieve-as-code-test-*.
live:
	uv run pytest tests/live --no-cov

build:
	uv build
