from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    lm_studio_url: str
    lm_studio_api_key: str
    embedding_model: str
    embedding_dim: int
    qdrant_storage_path: str
    qdrant_collection: str
    rrf_k: int
    prepared_dir: str
    server_port: int
    chunk_max_words: int
    chunk_overlap_words: int
    parent_level: int

    @property
    def lm_studio_headers(self) -> dict:
        if self.lm_studio_api_key:
            return {"Authorization": f"Bearer {self.lm_studio_api_key}"}
        return {}

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            lm_studio_url=os.getenv("LM_STUDIO_URL", "http://host.docker.internal:1234/v1"),
            lm_studio_api_key=os.getenv("LM_STUDIO_API_KEY", ""),
            embedding_model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text-v1.5"),
            embedding_dim=int(os.getenv("EMBEDDING_DIM", "768")),
            qdrant_storage_path=os.getenv("QDRANT_STORAGE_PATH", "/data/qdrant_storage"),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "docs"),
            rrf_k=int(os.getenv("RRF_K", "60")),
            prepared_dir=os.getenv("PREPARED_DIR", "/data/prepared"),
            server_port=int(os.getenv("SERVER_PORT", "8000")),
            chunk_max_words=int(os.getenv("CHUNK_MAX_WORDS", "800")),
            chunk_overlap_words=int(os.getenv("CHUNK_OVERLAP_WORDS", "80")),
            parent_level=int(os.getenv("PARENT_LEVEL", "2")),
        )

settings = Settings.from_env()
