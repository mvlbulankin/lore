from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock

from docs_shared.embedder import FastEmbedEmbedder


def _make_mock_model(dim: int = 384) -> MagicMock:
    mock_model = MagicMock()

    def embed_side_effect(texts):
        return iter([np.ones(dim) * 0.1])

    mock_model.embed.side_effect = embed_side_effect
    return mock_model


@pytest.fixture
def embedder(monkeypatch: pytest.MonkeyPatch) -> FastEmbedEmbedder:
    mock_model = _make_mock_model()
    monkeypatch.setattr("docs_shared.embedder.TextEmbedding", lambda **kwargs: mock_model)
    return FastEmbedEmbedder(model_name="test-model")


class TestEmbed:
    def test_basic_batch(self, embedder: FastEmbedEmbedder) -> None:
        vecs = embedder.embed_sync(["hello", "world"])
        assert len(vecs) == 2
        assert len(vecs[0]) == 384

    def test_empty_input(self, embedder: FastEmbedEmbedder) -> None:
        vecs = embedder.embed_sync([])
        assert vecs == []

    def test_single_text(self, embedder: FastEmbedEmbedder) -> None:
        vecs = embedder.embed_sync(["hello"])
        assert len(vecs) == 1
        assert len(vecs[0]) == 384


class TestEmbedOne:
    def test_embed_one(self, embedder: FastEmbedEmbedder) -> None:
        vec = embedder.embed_sync(["hello"])
        assert len(vec) == 1
        assert len(vec[0]) == 384


class TestAutoDimension:
    def test_detects_dimension(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_model = _make_mock_model(dim=128)
        monkeypatch.setattr("docs_shared.embedder.TextEmbedding", lambda **kwargs: mock_model)
        e = FastEmbedEmbedder(model_name="test-model")
        assert e.dimension is None
        e.embed_sync(["hello"])
        assert e.dimension == 128


class TestEmbedderFactory:
    def test_embedder_default_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from docs_shared.embedder import Embedder

        mock_model = _make_mock_model()
        monkeypatch.setattr("docs_shared.embedder.TextEmbedding", lambda **kwargs: mock_model)
        e = Embedder()
        assert e._dimension is None

    def test_embedder_custom_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from docs_shared.embedder import Embedder

        mock_model = _make_mock_model()
        monkeypatch.setattr("docs_shared.embedder.TextEmbedding", lambda **kwargs: mock_model)
        e = Embedder(model_name="custom/model")
        assert e._dimension is None
