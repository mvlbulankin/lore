# Troubleshooting

## `lm_studio: false` in `/health`

1. Verify LM Studio is running and the local server is active
2. Check `LM_STUDIO_API_KEY` in `.env` — token must be valid
3. Check `LM_STUDIO_URL` — port must match LM Studio settings
4. Test manually: `curl -H "Authorization: Bearer <token>" http://localhost:1234/v1/models`

## Qdrant Storage Issues

1. `docker compose logs lore` — look for initialization errors
2. Check `collection_count` in `/health` — if > 0, Qdrant is working
3. Verify write permissions on `data/qdrant_storage/`
4. Qdrant embedded mode stores data in `QDRANT_STORAGE_PATH` — ensure it exists and is writable

## Embed Drift Warning

NOTE: Qdrant doesn't store custom metadata on collection config like ChromaDB did.
`verify_embedding_model()` is currently a no-op. If you change the embedding model, you must manually run:

```bash
make ingest-clear
```

## Empty Search Results

1. Verify `data/prepared/{framework}/` contains `.md` files
2. Verify documents are indexed: `make ingest`
3. Check `sparse_model: true` in `/health`
4. Check sources: `curl http://localhost:8000/sources`

## Preparation Finds No Source Files

Verify files are in `data/source/{framework}/` in the format the preparer expects:
- Spark: `data/source/spark/docs/*.md`
- Delta: `data/source/delta/docs/src/content/docs/*.mdx` + `data/source/delta/examples/python/*.py`

## After Chunking Update — Old Indexes Incompatible

New chunker versions may change metadata schema. After updating code:

```bash
make ingest-clear && make ingest
```

## Docker Cannot Reach LM Studio

`host.docker.internal` should resolve to the host machine IP. If it doesn't:

```bash
docker run --rm alpine nslookup host.docker.internal
```

Replace with the host machine IP in `LM_STUDIO_URL` if needed.

## Sparse Model Rebuild on Partial Ingest

Sparse model (TF-IDF) is always rebuilt fully on every `make ingest`, even with `--framework`. This ensures the sparse model and Qdrant stay consistent.

## Search Returns 0 Hits After `make ingest`

Qdrant is embedded (in-process) — no restart needed after `make ingest`. If results are empty:
1. Check that LM Studio is running (embeddings are needed at query time)
2. Check `collection_count` in `/health`
3. Verify `sparse_model: true` in `/health`

## `ModuleNotFoundError: No module named 'docs_shared'`

Container runs as root with `PYTHONPATH="/app:/app/ingestion"`. Verify:
- `Dockerfile` sets `ENV PYTHONPATH="/app:/app/ingestion"`
- Makefile ingest targets use `sh -c 'PYTHONPATH="/app:/app/ingestion" ...'`

## Preparation: "directory not found"

Verify `data/source/{framework}/` exists. Check path with `make prepare-dry-run`.
