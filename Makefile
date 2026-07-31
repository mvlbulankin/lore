SHELL := /bin/bash
PYTHON := python
WORKSPACE := $(shell cd .. && pwd)
DATA_DIR := data/docs

.PHONY: all prepare-delta prepare-spark ingest ingest-clear logs test ruff clean

all: prepare-delta prepare-spark ingest-clear

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

prepare-delta:
	@echo "==> Running delta-docs-extractor"
	$(MAKE) -C $(WORKSPACE)/delta-docs-extractor run
	@mkdir -p $(DATA_DIR)/delta
	@cp -r $(WORKSPACE)/delta-docs-extractor/output/delta/* $(DATA_DIR)/delta/

prepare-spark:
	@echo "==> Running spark-docs-extractor"
	$(MAKE) -C $(WORKSPACE)/spark-docs-extractor run
	@mkdir -p $(DATA_DIR)/spark
	@cp -r $(WORKSPACE)/spark-docs-extractor/output/spark/* $(DATA_DIR)/spark/

ingest:
	docker compose run --rm lore sh -c 'PYTHONPATH=/app python /app/ingestion/ingest.py'

ingest-clear:
	docker compose run --rm lore sh -c 'PYTHONPATH=/app python /app/ingestion/ingest.py --clear'

logs:
	docker compose logs -f lore

test:
	uv run pytest --cov=app --cov=docs_shared --cov=ingestion --cov-report=term-missing

ruff:
	uv run ruff check --fix

clean:
	docker compose down -v
	rm -rf $(DATA_DIR)/*
	$(MAKE) -C $(WORKSPACE)/delta-docs-extractor clean
	$(MAKE) -C $(WORKSPACE)/spark-docs-extractor clean
	rm -rf data/qdrant_storage/*
	rm -rf data/hf_cache
	rm -f data/bm25.pkl
	rm -rf .venv
