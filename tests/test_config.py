"""Tests for docs_shared.config Settings validation."""

from __future__ import annotations

import pytest

from docs_shared.config import Settings


def test_settings_new_env_vars_have_defaults() -> None:
    """New env vars snippet_max_chars, ingest_batch_size etc have defaults."""
    s = Settings()
    assert s.snippet_max_chars == 500
    assert s.parent_content_max_chars == 2000
    assert s.ingest_batch_size == 256
    assert s.search_fetch_multiplier == 4
    assert s.search_fetch_min == 20


def test_settings_raises_on_overlap_gte_max() -> None:
    """chunk_overlap_words >= chunk_max_words raises."""
    with pytest.raises(ValueError, match="must be"):
        Settings(chunk_overlap_words=800, chunk_max_words=800)
