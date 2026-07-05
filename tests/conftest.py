"""Test configuration.

pytest pythonpath is set via [tool.pytest.ini_options] in pyproject.toml.
This file is kept for future fixtures.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


def _make_mock_model() -> MagicMock:
    """Create a mock TextEmbedding instance with model.providers set."""
    mock_instance = MagicMock()
    mock_instance.model.providers = [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
    mock_vectors = [MagicMock(tolist=lambda: [0.1] * 384)]
    mock_instance.embed.return_value = mock_vectors
    return mock_instance


def pytest_configure(config: pytest.Config) -> None:
    """Inject mock fastembed/onnxruntime so tests run without CUDA libs.

    onnxruntime-gpu crashes at import time when CUDA libs are absent.
    The embedder tests mock TextEmbedding, so they don't need the real
    fastembed.  Other tests only need docs_shared to be importable
    (EMBEDDING_MODEL constant), which works with lazy imports.
    """
    if "onnxruntime" not in sys.modules:
        try:
            import onnxruntime  # noqa: F401
        except ImportError, OSError:
            sys.modules["onnxruntime"] = MagicMock()

    if "fastembed" not in sys.modules:
        mock_text_embedding = MagicMock(return_value=_make_mock_model())
        mock_fastembed = MagicMock(spec=["TextEmbedding"])
        mock_fastembed.TextEmbedding = mock_text_embedding
        sys.modules["fastembed"] = mock_fastembed
        for submodule in [
            "fastembed.image",
            "fastembed.image.image_embedding",
            "fastembed.image.onnx_embedding",
            "fastembed.common",
            "fastembed.common.onnx_model",
            "fastembed.text",
            "fastembed.text.text_embedding",
            "fastembed.text.onnx_embedding",
            "fastembed.common.types",
            "fastembed.embedder",
        ]:
            sys.modules[submodule] = MagicMock()
