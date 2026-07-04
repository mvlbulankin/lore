"""Build sparse vectors (TF-IDF) for Qdrant keyword search."""

from __future__ import annotations

import pickle
from pathlib import Path

from qdrant_client.models import SparseVector
from sklearn.feature_extraction.text import TfidfVectorizer


class SparseBuilder:
    """TF-IDF -> Qdrant sparse vectors.

    Uses sublinear_tf=True for BM25-like term frequency saturation.
    """

    def __init__(
        self,
        max_features: int = 50_000,
        min_df: int = 2,
        max_df: float = 0.95,
    ):
        self._vectorizer = TfidfVectorizer(
            max_features=max_features,
            sublinear_tf=True,
            stop_words="english",
            min_df=min_df,
            max_df=max_df,
        )
        self._fitted = False

    def fit_build(self, texts: list[str]) -> list[SparseVector]:
        """Fit vectorizer on corpus and build sparse vectors."""
        tfidf_matrix = self._vectorizer.fit_transform(texts)
        self._fitted = True
        return self._matrix_to_sparse(tfidf_matrix)

    def build(self, texts: list[str]) -> list[SparseVector]:
        """Transform texts using fitted vectorizer."""
        if not self._fitted:
            raise RuntimeError("Call fit_build() first")
        return self._matrix_to_sparse(self._vectorizer.transform(texts))

    def encode_query(self, query: str) -> SparseVector:
        """Encode a single query to sparse vector."""
        if not self._fitted:
            raise RuntimeError("Vectorizer not fitted. Load from disk first.")
        tfidf = self._vectorizer.transform([query])
        row = tfidf[0]
        return SparseVector(indices=row.indices.tolist(), values=row.data.tolist())

    def save(self, path: str | Path) -> None:
        """Persist fitted vectorizer to disk."""
        with open(path, "wb") as f:
            pickle.dump(self._vectorizer, f)

    @classmethod
    def load(cls, path: str | Path) -> "SparseBuilder":
        """Load fitted vectorizer from disk."""
        instance = cls.__new__(cls)
        with open(path, "rb") as f:
            instance._vectorizer = pickle.load(f)
        instance._fitted = True
        return instance

    def _matrix_to_sparse(self, matrix) -> list[SparseVector]:
        vectors: list[SparseVector] = []
        for row in matrix:
            vectors.append(SparseVector(
                indices=row.indices.tolist(),
                values=row.data.tolist(),
            ))
        return vectors


__all__ = ["SparseBuilder"]
