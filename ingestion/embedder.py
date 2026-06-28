from __future__ import annotations

from docs_shared.config import settings
from docs_shared import http_client

def embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        r = http_client.post(
            f"{settings.lm_studio_url}/embeddings",
            json={"model": settings.embedding_model, "input": batch},
            headers=settings.lm_studio_headers,
        )
        r.raise_for_status()
        data = r.json()["data"]
        out.extend(d["embedding"] for d in data)
    return out
