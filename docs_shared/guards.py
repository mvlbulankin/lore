from __future__ import annotations
import structlog
from .config import settings

log = structlog.get_logger()

def warn_if_embedding_drift(collection_metadata: dict | None) -> None:
    """Check if the embedding model has changed since last ingest."""
    stored = (collection_metadata or {}).get("embedding_model")
    if stored and stored != settings.embedding_model:
        log.warning(
            "embedding_model_mismatch",
            stored=stored,
            configured=settings.embedding_model,
            hint="run: make ingest-clear",
        )
