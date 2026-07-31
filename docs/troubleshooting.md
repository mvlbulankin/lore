# Troubleshooting

## Qdrant Storage Issues

1. `docker compose logs lore` — look for initialization errors
2. Check `collection_count` in `/health` — if > 0, Qdrant is working
3. Verify write permissions on `data/qdrant_storage/`
4. Qdrant embedded mode stores data in `QDRANT_STORAGE_PATH` — ensure it exists and is writable

## Embed Drift Warning

`verify_embedding_model()` reads `.model_info.json` from `QDRANT_STORAGE_PATH/` and compares with current settings.
If mismatch, server logs a warning on startup. Fix with:

```bash
make down
make ingest-clear
make up
```

## Empty Search Results

1. Verify `data/docs/{framework}/` contains `.md` files
2. Verify documents are indexed: `make down && make ingest && make up`
3. Check `sparse_model: true` in `/health`
4. Check sources: `curl http://localhost:8000/sources`

## Extractor Produces No Output

Verify the extractor runs successfully from the workspace root:
- Spark: `cd pyspark-docs-extractor && uv run python main.py`
- Delta: `cd delta-docs-extractor && uv run python main.py`

## After Chunking Update — Old Indexes Incompatible

New chunker versions may change metadata schema. After updating code:

```bash
make down
make ingest-clear
make up
```

## Sparse Model Rebuild on Partial Ingest

Sparse model (TF-IDF) is always rebuilt fully on every `make ingest`, even with `--framework`. This ensures the sparse model and Qdrant stay consistent.

## Search Returns 0 Hits After `make ingest`

Qdrant is embedded (in-process) — the server and ingest cannot run simultaneously. If results are empty:
1. Ensure server is running: `make up`
2. Check `collection_count` in `/health`
3. Verify `sparse_model: true` in `/health`

## Qdrant Lock Error: "Storage folder is already accessed by another instance"

This happens when `make ingest` runs while the server container is up. Both try to lock the same Qdrant storage directory.

```bash
make down              # stop server (releases lock)
make ingest-clear      # run ingest
make up                # start server
```

## Model Download Slow on First Start

On first container start, fastembed downloads the embedding model from HuggingFace Hub (~40MB).
Subsequent starts use the cached model at `data/hf_cache/`.

1. Check logs: `docker compose logs lore | grep -i "fetching\|download"`
2. Set `HF_TOKEN` env var for higher rate limits (optional)
3. Pre-download: run `make shell` and import `fastembed` to trigger download

## `ModuleNotFoundError: No module named 'docs_shared'`

Container runs as `lore` user with `PYTHONPATH="/app:/app/ingestion"`. Verify:
- `Dockerfile` sets `ENV PYTHONPATH="/app:/app/ingestion"`
- Makefile ingest targets use `sh -c 'PYTHONPATH=/app ...'` — Python's implicit `sys.path[0]` adds the script's directory (`/app/ingestion`) at runtime

## Extraction: "directory not found"

Verify `{framework}-docs-extractor/` exists in the workspace parent directory.
