"""Tests for docs_shared.config Settings validation."""

from __future__ import annotations

import pytest

from docs_shared.config import Settings, KNOWN_MODEL_DIMS


def test_settings_uses_default_dim_for_known_model() -> None:
    """Default dim matches the default model."""
    s = Settings()
    expected = KNOWN_MODEL_DIMS[s.embedding_model]
    assert s.embedding_dim == expected


def test_settings_raises_on_mismatched_dim() -> None:
    """Setting embedding_dim that doesn't match known model dim raises."""
    model = list(KNOWN_MODEL_DIMS.keys())[0]
    wrong_dim = KNOWN_MODEL_DIMS[model] + 1
    with pytest.raises(ValueError, match="does not match"):
        Settings(embedding_model=model, embedding_dim=wrong_dim)


def test_settings_accepts_unknown_model_any_dim() -> None:
    """Unknown model name skips dim validation."""
    s = Settings(embedding_model="unknown/model", embedding_dim=1234)
    assert s.embedding_dim == 1234


def test_settings_new_env_vars_have_defaults() -> None:
    """New env vars snippet_max_chars, ingest_batch_size etc have defaults."""
    s = Settings()
    assert s.snippet_max_chars == 500
    assert s.parent_content_max_chars == 2000
    assert s.ingest_batch_size == 256
    assert s.search_fetch_multiplier == 4
    assert s.search_fetch_min == 20
