.PHONY: quality test integration build

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

build:
	uv build
