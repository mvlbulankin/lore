# Troubleshooting

## `lm_studio: false` in `/health`

1. Verify LM Studio is running and the local server is active
2. Check `LM_STUDIO_API_KEY` in `.env` — token must be valid
3. Check `LM_STUDIO_URL` — port must match LM Studio settings
4. Test manually: `curl -H "Authorization: Bearer <token>" http://localhost:1234/v1/models`

## ChromaDB Not Responding

1. `docker compose logs lore` — look for initialization errors
2. Check `collection_count` in `/health` — if > 0, ChromaDB is working
3. Verify write permissions on `data/chroma/`

## Embed Drift Warning

Log message `embedding_model_mismatch` means the embedding model changed but ChromaDB still has old vectors.

```bash
make ingest-clear
```

## Empty Search Results

1. Verify `data/prepared/{framework}/` contains `.md` files
2. Verify documents are indexed: `make ingest`
3. Check `bm25_loaded: true` in `/health`
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

## BM25 Rebuild on Partial Ingest

BM25 index is always rebuilt fully on every `make ingest`, even with `--framework`. This ensures BM25 and ChromaDB stay consistent.

## Search Returns 0 Hits After `make ingest`

`HybridRetriever` loads `bm25.pkl` at container startup. After `make ingest`, restart the container:

```bash
make down && make up
```

## `ModuleNotFoundError: No module named 'docs_shared'`

Container runs as root with `PYTHONPATH="/app:/app/ingestion"`. Verify:
- `Dockerfile` sets `ENV PYTHONPATH="/app:/app/ingestion"`
- Makefile ingest targets use `sh -c 'PYTHONPATH="/app:/app/ingestion" ...'`

## Preparation: "directory not found"

Verify `data/source/{framework}/` exists. Check path with `make prepare-dry-run`.
