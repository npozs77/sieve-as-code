.PHONY: quality test build

quality:
	uv run ruff check .
	uv run black --check .
	uv run mypy
	uv run vulture
	uv run pytest

test:
	uv run pytest

build:
	uv build
