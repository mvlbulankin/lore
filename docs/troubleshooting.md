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

## Sparse Model Rebuild on Partial Ingest

Sparse model (TF-IDF) is always rebuilt fully on every `make ingest`, even with `--framework`. This ensures the sparse model and Qdrant stay consistent.

## Search Returns 0 Hits After `make ingest`

Qdrant is embedded (in-process) — no restart needed after `make ingest`. If results are empty:
1. Check `collection_count` in `/health`
2. Verify `sparse_model: true` in `/health`

## fastembed Model Not Loading

On first startup, fastembed downloads the ONNX model to `/data/fastembed_cache`. If it fails:
1. Check network connectivity (model is downloaded from HuggingFace)
2. Verify `/data` is writable by the container user
3. Check logs: `docker compose logs lore`

## `ModuleNotFoundError: No module named 'docs_shared'`

Container runs as `lore` user with `PYTHONPATH="/app:/app/ingestion"`. Verify:
- `Dockerfile` sets `ENV PYTHONPATH="/app:/app/ingestion"`
- Makefile ingest targets use `sh -c 'PYTHONPATH=/app ...'` — Python's implicit `sys.path[0]` adds the script's directory (`/app/ingestion`) at runtime

## Preparation: "directory not found"

Verify `data/source/{framework}/` exists. Check path with `make prepare-dry-run`.

## CUDA Provider Unavailable

The container starts but fails with `CudaNotAvailableError`. This means the
requested ONNX execution provider (default: `CUDAExecutionProvider`) is not
available inside the container.

1. **nvidia-container-toolkit not installed** — follow Phase 1 instructions in
   `docs/areas/docker.md` to install and configure the toolkit.
2. **Docker daemon not restarted** — after installing the toolkit, run
   `sudo systemctl restart docker`.
3. **GPU passthrough not working** — verify with:
   `docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi`
4. **WSL2 driver mismatch** — update Windows NVIDIA driver, run
   `wsl --update`, then re-enter the WSL distro.
5. **CPU fallback for development** — set
   `EMBEDDING_PROVIDERS=CPUExecutionProvider` in `.env`.
