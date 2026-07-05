"""Tests for docs_shared.embedder Embedder (fastembed)."""

from __future__ import annotations

import os
import threading
from unittest.mock import MagicMock, patch

import pytest

from docs_shared.embedder import CudaNotAvailableError, Embedder, EMBEDDING_MODEL


def _mock_model(embed_n: int = 1, dim: int = 384, val: float = 0.1) -> MagicMock:
    """Create a mock TextEmbedding instance with embed."""
    mock_instance = MagicMock()
    mock_instance.model.providers = [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
    mock_vectors = []
    for _ in range(embed_n):
        mv = MagicMock()
        mv.tolist.return_value = [val] * dim
        mock_vectors.append(mv)
    mock_instance.embed.return_value = mock_vectors
    return mock_instance


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_embedder_initialization():
    """Embedder() constructs with default model."""
    with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
        mock_cls.return_value = _mock_model()
        embedder = Embedder()
        mock_cls.assert_called_once()
        assert embedder._lock is not None


def test_embedder_initialization_with_cache():
    """Embedder() accepts cache_dir."""
    with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
        mock_cls.return_value = _mock_model()
        Embedder(cache_dir="/tmp/cache")
        mock_cls.assert_called_once_with(
            model_name=EMBEDDING_MODEL,
            batch_size=64,
            cache_dir="/tmp/cache",
            providers=["CUDAExecutionProvider"],
        )


# ---------------------------------------------------------------------------
# embed_sync
# ---------------------------------------------------------------------------


def test_embed_sync_returns_correct_shape():
    """N texts -> N vectors, each length 384."""
    with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
        mock_model = _mock_model(embed_n=3)
        mock_cls.return_value = mock_model

        embedder = Embedder()
        result = embedder.embed_sync(["a", "b", "c"])

    assert len(result) == 3
    assert all(len(v) == 384 for v in result)
    mock_model.embed.assert_called_once_with(["a", "b", "c"])


def test_embed_sync_single():
    """Single text returns one vector."""
    with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
        mock_model = _mock_model(embed_n=1, val=0.2)
        mock_cls.return_value = mock_model

        embedder = Embedder()
        result = embedder.embed_sync(["hello"])

    assert len(result) == 1
    assert len(result[0]) == 384


def test_embed_sync_batch_single_call():
    """A batch of texts is sent to the model in one call, not per-item."""
    with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
        mock_model = _mock_model(embed_n=10)
        mock_cls.return_value = mock_model

        embedder = Embedder()
        texts = [f"text-{i}" for i in range(10)]
        result = embedder.embed_sync(texts)

    assert len(result) == 10
    mock_model.embed.assert_called_once_with(texts)


# ---------------------------------------------------------------------------
# embed_one
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_embed_one_returns_single_vector():
    """Single text -> single vector length 384."""
    with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
        mock_model = _mock_model(embed_n=1, val=0.3)
        mock_cls.return_value = mock_model

        embedder = Embedder()
        result = await embedder.embed_one("test")

    assert len(result) == 384


# ---------------------------------------------------------------------------
# embed (async batch)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_embed_async_does_not_block():
    """await embedder.embed(...) returns correctly from async context."""
    with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
        mock_model = _mock_model(embed_n=2)
        mock_cls.return_value = mock_model

        embedder = Embedder()
        result = await embedder.embed(["a", "b"])

    assert len(result) == 2


# ---------------------------------------------------------------------------
# Lock serializes concurrent calls
# ---------------------------------------------------------------------------


def test_lock_serializes_concurrent_calls():
    """Two threads calling embed_sync simultaneously both succeed."""
    with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
        mock_model = _mock_model(embed_n=1)
        call_count = 0

        def fake_embed(texts):
            nonlocal call_count
            call_count += 1
            return [MagicMock(tolist=lambda: [0.1] * 384) for _ in texts]

        mock_model.embed = fake_embed
        mock_cls.return_value = mock_model

        embedder = Embedder()
        errors: list[Exception] = []

        def worker():
            try:
                embedder.embed_sync(["text"])
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    assert len(errors) == 0, f"Concurrent calls failed: {errors}"
    assert call_count == 2


# ---------------------------------------------------------------------------
# Provider validation
# ---------------------------------------------------------------------------


def _mock_text_embedding_instance(providers: list[str]) -> MagicMock:
    """Create a mock TextEmbedding instance with model.providers set to given list."""
    mock_instance = MagicMock()
    mock_instance.model.providers = providers
    return mock_instance


def test_embedder_default_providers():
    """Without EMBEDDING_PROVIDERS env, default is CUDAExecutionProvider."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
            mock_cls.return_value = _mock_text_embedding_instance(
                [
                    "CUDAExecutionProvider",
                    "CPUExecutionProvider",
                ]
            )
            Embedder()
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["providers"] == ["CUDAExecutionProvider"]


def test_embedder_providers_from_env():
    """EMBEDDING_PROVIDERS env var is parsed and passed to TextEmbedding."""
    with patch.dict(
        os.environ,
        {"EMBEDDING_PROVIDERS": "CUDAExecutionProvider,CPUExecutionProvider"},
    ):
        with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
            mock_cls.return_value = _mock_text_embedding_instance(
                [
                    "CUDAExecutionProvider",
                    "CPUExecutionProvider",
                ]
            )
            Embedder()
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["providers"] == [
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ]


def test_embedder_validates_providers_hard_fail():
    """Requested provider not resolved -> CudaNotAvailableError."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
            # CUDA requested but not in resolved list (no GPU / no libcudart)
            mock_cls.return_value = _mock_text_embedding_instance(
                ["CPUExecutionProvider"]
            )

            with pytest.raises(CudaNotAvailableError) as exc_info:
                Embedder()
            assert "CUDAExecutionProvider" in str(exc_info.value)
            assert "CPUExecutionProvider" in str(exc_info.value)


def test_embedder_providers_explicit_override():
    """providers= kwarg overrides env var."""
    with patch.dict(os.environ, {"EMBEDDING_PROVIDERS": "CUDAExecutionProvider"}):
        with patch("docs_shared.embedder.TextEmbedding") as mock_cls:
            mock_cls.return_value = _mock_text_embedding_instance(
                ["CPUExecutionProvider"]
            )
            Embedder(providers=["CPUExecutionProvider"])
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["providers"] == ["CPUExecutionProvider"]
