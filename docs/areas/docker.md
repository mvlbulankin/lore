# Docker

**Files:** `Dockerfile`, `docker-compose.yml`

## Image

Based on `python:3.14-slim` with `uv` copied from `ghcr.io/astral-sh/uv:latest`. Final image size is ~890MB (includes fastembed, ONNX runtime, scikit-learn).

### Build Layers

1. Base Python 3.14 slim + uv
2. System deps: `curl` (for healthcheck)
3. Lock file sync: `uv sync --frozen` (cached layer)
4. Application code: `docs_shared/`, `ingestion/`, `app/`
5. Environment: `PYTHONPATH=/app:/app/ingestion`, `PATH` includes `.venv/bin`, `HF_HOME=/data/hf_cache`

### Entrypoint

```bash
python -m uvicorn app.server:app --host 0.0.0.0 --port 8000
```

## Volume Mounts

| Mount | Direction | Purpose |
|-------|-----------|---------|
| `./data:/data` | read-write | Qdrant embedded storage + prepared documents + HF model cache |

The `data` directory on the host contains:
- `data/qdrant_storage/` — Qdrant embedded storage (vectors + sparse model)
- `data/docs/` — framework documentation (output of external extractors)
- `data/hf_cache/` — HuggingFace model cache (populated on first server start)

## No External Dependencies

The container is self-contained. Embeddings are computed locally via fastembed (ONNX).
No external API, no GPU, no `extra_hosts` needed.

## Port Mapping

Container exposes port 8000, mapped to host port 8000. Server binds to `0.0.0.0`.

## Healthcheck

Docker healthcheck curls `http://localhost:8000/health` every 10s with 5s timeout and 5 retry attempts.

## PYTHONPATH

Set to `/app:/app/ingestion` so that:
- `docs_shared` is importable as a top-level package
- `ingestion/` modules (chunker, ingest) are importable directly
- `app/` is the uvicorn working directory

## HF_HOME

Set to `/data/hf_cache` so that downloaded embedding models persist across container restarts.
First server start downloads the model from HuggingFace Hub (~40MB for `BAAI/bge-small-en-v1.5`).

## Security Notes

- Container runs as non-root user `lore`
- `/data` is chowned to `lore:lore`
- For host volumes with different UID, use Docker volume driver or `--user` flag
