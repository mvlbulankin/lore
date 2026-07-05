# Embedder

**File:** `docs_shared/embedder.py`

## Overview

`FastEmbedEmbedder` uses Qdrant's `fastembed` library for local, ONNX-based text embeddings. No external API or GPU required — model runs inside the container.

## Architecture

```
lore (container)
┌─────────────────────┐
│ FastEmbedEmbedder   │
│ (fastembed + ONNX)  │
│                     │
│ embed(texts)        │
│ embed_sync(texts)   │
│ embed_one(text)     │
└─────────────────────┘
```

## Class: `FastEmbedEmbedder`

```python
class FastEmbedEmbedder:
    def __init__(self, model_name: str = EMBEDDING_MODEL) -> None:
        ...
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...
    def embed_sync(self, texts: Sequence[str]) -> list[list[float]]:
        ...
    async def embed_one(self, text: str) -> list[float]:
        ...
    @property
    def dimension(self) -> int | None:
        ...
```

## Key Behaviors

- **Local inference** — uses `fastembed.TextEmbedding` with ONNX runtime, no network calls
- **Batching** — `embed_sync` iterates texts individually through the model (fastembed processes in batches internally)
- **Dimension auto-detection** — deduced from first embedding result, cached in `self._dimension`
- **Async wrapper** — `embed()` wraps `embed_sync()` via `asyncio.to_thread()`
- **Model download** — first instantiation downloads model weights from HuggingFace Hub to `HF_HOME` (default: `/data/hf_cache`)

## Factory: `Embedder()`

```python
from docs_shared.embedder import Embedder

# Creates FastEmbedEmbedder with default model (BAAI/bge-small-en-v1.5)
embedder = Embedder()

# Or with explicit model
embedder = Embedder(model_name="sentence-transformers/all-MiniLM-L6-v2")
```

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Model identifier (fastembed-compatible) |
| `EMBEDDING_DIM` | `384` | Vector dimension (for Qdrant collection creation) |
| `HF_HOME` | `/data/hf_cache` | HuggingFace cache directory (set in Dockerfile) |

## Model Migration

To change the embedding model:

1. Update `EMBEDDING_MODEL` in `.env` or `docs_shared/embedder.py`
2. Update `EMBEDDING_DIM` if dimension differs
3. Run `make ingest-clear` to rebuild with new model
