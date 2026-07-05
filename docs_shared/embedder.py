from __future__ import annotations

import asyncio
import os
from functools import partial
from threading import Lock
from typing import Sequence

from fastembed import TextEmbedding

from docs_shared.exceptions import CudaNotAvailableError

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_PROVIDERS: tuple[str, ...] = ("CUDAExecutionProvider",)


class Embedder:
    """In-process ONNX embedding via fastembed (BAAI/bge-small-en-v1.5)."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        cache_dir: str | None = None,
        batch_size: int = 64,
        providers: Sequence[str] | None = None,
    ) -> None:

        if providers is None:
            env = os.environ.get("EMBEDDING_PROVIDERS", ",".join(DEFAULT_PROVIDERS))
            providers = tuple(p.strip() for p in env.split(",") if p.strip())

        if cache_dir is None:
            cache_dir = os.environ.get("FASTEMBED_CACHE_PATH")

        kwargs: dict = {
            "model_name": model_name,
            "batch_size": batch_size,
            "providers": list(providers),
        }
        if cache_dir:
            kwargs["cache_dir"] = cache_dir

        self._model = TextEmbedding(**kwargs)
        self._lock = Lock()
        self._validate_providers(providers)

    def _validate_providers(self, requested: Sequence[str]) -> None:
        # fastembed 0.8.0 stores the resolved provider list at
        # `self.model.providers` after the underlying onnxruntime session is
        # initialised. If a requested provider was rejected at init time
        # (e.g. CUDAExecutionProvider requested but no GPU / no libcudart),
        # fastembed drops it from this list.
        available = tuple(self._model.model.providers)
        missing = [p for p in requested if p not in available]
        if missing:
            raise CudaNotAvailableError(
                f"Requested ONNX provider(s) {missing!r} not available. "
                f"Resolved: {available!r}. "
                f"Check nvidia-container-toolkit (Phase 1) and host driver."
            )

    def embed_sync(self, texts: Sequence[str]) -> list[list[float]]:
        with self._lock:
            return [e.tolist() for e in self._model.embed(list(texts))]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self.embed_sync, texts))

    async def embed_one(self, text: str) -> list[float]:
        vecs = await self.embed([text])
        return vecs[0]
