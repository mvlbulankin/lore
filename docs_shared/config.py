from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

from .embedder import EMBEDDING_MODEL


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Falls back to defaults; reads .env file automatically when present.
    """

    embedding_model: str = EMBEDDING_MODEL
    embedding_dim: int = Field(default=384, gt=0)
    qdrant_storage_path: str = "/data/qdrant_storage"
    qdrant_collection: str = "docs"
    prepared_dir: str = "/data/prepared"
    server_port: int = Field(default=8000, gt=0)
    chunk_max_words: int = Field(default=800, gt=0)
    chunk_overlap_words: int = 80
    parent_level: int = 2
    snippet_max_chars: int = Field(default=500, gt=0)
    parent_content_max_chars: int = Field(default=2000, gt=0)
    ingest_batch_size: int = Field(default=256, gt=0)
    search_fetch_multiplier: int = Field(default=4, gt=0)
    search_fetch_min: int = Field(default=20, gt=0)
    cors_origins: str = "*"

    @model_validator(mode="after")
    def _validate_chunks(self) -> Settings:
        if self.chunk_overlap_words >= self.chunk_max_words:
            raise ValueError(
                f"chunk_overlap_words={self.chunk_overlap_words} must be "
                f"less than chunk_max_words={self.chunk_max_words}"
            )
        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
