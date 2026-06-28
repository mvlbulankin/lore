from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    lm_studio_url: str
    lm_studio_api_key: str
    embedding_model: str
    chroma_persist_dir: str
    chroma_collection: str
    rrf_k: int
    prepared_dir: str
    bm25_path: str
    server_port: int
    chunk_max_words: int
    chunk_overlap_words: int

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
            chroma_persist_dir=os.getenv("CHROMA_PERSIST_DIR", "/data/chroma"),
            chroma_collection=os.getenv("CHROMA_COLLECTION", "docs"),
            rrf_k=int(os.getenv("RRF_K", "60")),
            prepared_dir=os.getenv("PREPARED_DIR", "/data/prepared"),
            bm25_path=os.getenv("BM25_PATH", "/data/bm25.pkl"),
            server_port=int(os.getenv("SERVER_PORT", "8000")),
            chunk_max_words=int(os.getenv("CHUNK_MAX_WORDS", "800")),
            chunk_overlap_words=int(os.getenv("CHUNK_OVERLAP_WORDS", "80")),
        )

settings = Settings.from_env()
