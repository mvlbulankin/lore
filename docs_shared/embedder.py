from __future__ import annotations

import asyncio
from typing import Sequence

import structlog
from fastembed import TextEmbedding

log = structlog.get_logger()

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"


class FastEmbedEmbedder:
    def __init__(self, model_name: str = EMBEDDING_MODEL) -> None:
        self._model = TextEmbedding(model_name=model_name)
        self._dimension: int | None = None

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed_sync, texts)

    def embed_sync(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float]] = []
        for text in texts:
            vec = list(self._model.embed([text]))[0]
            results.append(vec.tolist())
        if self._dimension is None and results:
            self._dimension = len(results[0])
        return results

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    @property
    def dimension(self) -> int | None:
        return self._dimension


def Embedder(
    model_name: str = EMBEDDING_MODEL,
) -> FastEmbedEmbedder:
    return FastEmbedEmbedder(model_name=model_name)
