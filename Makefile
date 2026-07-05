.PHONY: install lock up down rebuild shell prepare prepare-spark prepare-delta prepare-dry-run ingest ingest-clear logs test clean

install:
	uv sync

lock:
	uv lock

up:
	docker compose up -d

rebuild:
	docker compose up -d --build

shell:
	docker compose exec lore bash

down:
	docker compose down

prepare:
	uv run python -m preparers.cli --execute

prepare-spark:
	uv run python -m preparers.cli --framework spark --execute

prepare-delta:
	uv run python -m preparers.cli --framework delta --execute

prepare-dry-run:
	uv run python -m preparers.cli

ingest:
	docker compose run --rm lore sh -c 'PYTHONPATH=/app python /app/ingestion/ingest.py'

ingest-clear:
	docker compose run --rm lore sh -c 'PYTHONPATH=/app python /app/ingestion/ingest.py --clear'

logs:
	docker compose logs -f lore

test:
	uv run pytest --cov=app --cov=docs_shared --cov=ingestion --cov=preparers --cov-report=term-missing

ruff:
	uv run ruff check --fix

clean:
	docker compose down -v
	rm -rf data/qdrant_storage/*
	rm -rf data/prepared/delta data/prepared/spark data/prepared/test
	rm -rf data/hf_cache
	rm -f data/bm25.pkl
	rm -rf .venv