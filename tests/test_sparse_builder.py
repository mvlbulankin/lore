"""Tests for ingestion.sparse_builder."""

from __future__ import annotations

import tempfile
from pathlib import Path

from docs_shared.sparse_builder import SparseBuilder


def test_fit_build_returns_sparse_vectors():
    texts = [
        "hello world foo",
        "foo bar baz",
        "hello foo bar",
        "world baz hello",
    ]
    builder = SparseBuilder()
    vectors = builder.fit_build(texts)
    assert len(vectors) == 4
    for v in vectors:
        assert len(v.indices) > 0
        assert len(v.values) == len(v.indices)


def test_build_after_fit():
    texts = [
        "hello world foo",
        "foo bar baz",
        "hello foo bar",
        "world baz hello",
    ]
    builder = SparseBuilder()
    builder.fit_build(texts)
    new_vectors = builder.build(["hello again"])
    assert len(new_vectors) == 1


def test_encode_query():
    texts = [
        "the quick brown fox jumps",
        "the lazy dog sleeps here",
        "quick fox is fast animal",
        "lazy dog rests quietly",
    ]
    builder = SparseBuilder()
    builder.fit_build(texts)
    qvec = builder.encode_query("quick fox")
    assert len(qvec.indices) > 0


def test_save_and_load():
    texts = [
        "alpha beta gamma delta",
        "delta epsilon alpha",
        "gamma delta beta",
        "epsilon alpha gamma",
    ]
    builder = SparseBuilder()
    builder.fit_build(texts)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "model.pkl"
        builder.save(path)

        loaded = SparseBuilder.load(path)
        v1 = builder.encode_query("alpha gamma")
        v2 = loaded.encode_query("alpha gamma")
        assert v1.indices == v2.indices


def test_build_before_fit_raises():
    builder = SparseBuilder()
    try:
        builder.build(["test"])
        assert False, "Should raise RuntimeError"
    except RuntimeError:
        pass


def test_encode_query_before_fit_raises():
    builder = SparseBuilder()
    try:
        builder.encode_query("test")
        assert False, "Should raise RuntimeError"
    except RuntimeError:
        pass
