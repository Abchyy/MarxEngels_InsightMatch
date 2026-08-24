.PHONY: setup lint typecheck test test-unit test-contract test-integration test-regression migrate verify-corpus build-index verify-index run-api run-web export-openapi freeze-contracts verify-contracts verify clean

setup:
	uv sync --all-groups
	pnpm install --frozen-lockfile=false

lint:
	uv run ruff check packages apps/api scripts tests
	pnpm lint

typecheck:
	uv run mypy packages/marx_engels
	pnpm typecheck

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit

test-contract:
	uv run pytest -m contract

test-integration:
	uv run pytest -m integration

test-regression:
	uv run python -m marx_engels.evaluation.cli regression

migrate:
	uv run python -m marx_engels.storage.cli migrate

verify-corpus:
	uv run python -m marx_engels.ingestion.cli verify-corpus

build-index:
	uv run python -m marx_engels.indexing.cli build-index

verify-index:
	uv run python -m marx_engels.indexing.cli verify-index

run-api:
	uv run uvicorn marx_engels.api.app:app --reload --host 127.0.0.1 --port 8000

run-web:
	pnpm dev

export-openapi:
	uv run python scripts/export_openapi.py --output contracts/openapi.v1.json
	pnpm generate:api

freeze-contracts:
	uv run python scripts/freeze_contracts.py --write

verify-contracts:
	uv run python scripts/freeze_contracts.py --check

verify: lint typecheck test export-openapi verify-contracts
	pnpm build

clean:
	uv run python scripts/clean_generated.py
