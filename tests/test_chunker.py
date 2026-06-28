"""Tests for ingestion.chunker code-aware markdown chunker."""

from __future__ import annotations

import pytest

from ingestion.chunker import (
    Chunk,
    _build_sections,
    _parse_blocks,
    _split_section,
    make_chunks,
    _HeadingBlock,
    _CodeBlock,
    _ProseBlock,
)


# ---------------------------------------------------------------------------
# Heading chain
# ---------------------------------------------------------------------------


def test_h1_only_document():
    md = "# Title\n\nSome text here.\n"
    chunks = make_chunks("fw", "a.md", md)
    assert len(chunks) == 1
    assert chunks[0].heading == "Title"
    assert chunks[0].title == "Title"
    assert chunks[0].is_last_chunk is True


def test_h1_h2_h3_chain():
    md = """# H1

## H2

### H3

text
"""
    chunks = make_chunks("fw", "a.md", md)
    assert chunks[0].heading == "H1 > H2 > H3"


def test_h5_h6_ignored_from_chain():
    md = """# Title

## Sec

##### H5 label

more content here
##### H6 label

more content after
"""
    chunks = make_chunks("fw", "a.md", md)
    assert chunks[0].heading == "Title > Sec"
    all_content = "\n\n".join(c.content for c in chunks)
    assert "#### H5 label" in all_content
    assert "#### H6 label" in all_content


def test_h2_resets_h3():
    md = """# T

## A
text A
### A1
text A1
## B
text B
"""
    chunks = make_chunks("fw", "a.md", md)
    headings = [c.heading for c in chunks]
    assert "T > A" in headings
    assert "T > A > A1" in headings
    assert "T > B" in headings


def test_h1_resets_all():
    md = """# Doc1

## S1
text1
# Doc2

## S2
text2
"""
    chunks = make_chunks("fw", "a.md", md)
    assert chunks[0].heading == "Doc1 > S1"
    assert chunks[1].heading == "Doc2 > S2"


# ---------------------------------------------------------------------------
# Code blocks
# ---------------------------------------------------------------------------


def test_h4_before_code_block_is_label():
    md = """# Title

## Sec
#### SQL
```sql
SELECT 1;
```
#### Python
```python
print(1)
```
"""
    chunks = make_chunks("fw", "a.md", md)
    code_chunks = [c for c in chunks if c.has_code]
    assert len(code_chunks) == 2
    assert "SQL" in code_chunks[0].content
    assert "Python" in code_chunks[1].content
    for c in code_chunks:
        assert c.heading == "Title > Sec"
        assert "#### SQL" not in c.content
        assert "#### Python" not in c.content


def test_h4_standalone_becomes_prose():
    md = """# Title

## Sec
#### Notes
This is just a note.
"""
    chunks = make_chunks("fw", "a.md", md)
    assert len(chunks) == 1
    assert "Notes" in chunks[0].content


def test_code_block_never_split():
    md_lines = "\n".join(f"x = {i}" for i in range(700))
    md = f"""# Title

## Long

```python
{md_lines}
```
"""
    chunks = make_chunks("fw", "a.md", md, max_words=100, overlap_words=10)
    code_chunks = [c for c in chunks if c.has_code]
    assert len(code_chunks) == 1
    assert "x = 0" in code_chunks[0].content
    assert "x = 699" in code_chunks[0].content


def test_code_block_no_overlap():
    md_lines_a = "\n".join(f"a = {i}" for i in range(80))
    md_lines_b = "\n".join(f"b = {i}" for i in range(80))
    md = f"""# Title

```python
{md_lines_a}
```
```python
{md_lines_b}
```
"""
    chunks = make_chunks("fw", "a.md", md, max_words=20, overlap_words=5)
    code_chunks = [c for c in chunks if c.has_code]
    assert len(code_chunks) >= 2
    for c in code_chunks:
        assert "a =" not in c.content or "b =" not in c.content


def test_has_code_metadata():
    md = """# Title

```python
print(1)
```
"""
    chunks = make_chunks("fw", "a.md", md)
    assert chunks[0].has_code is True


def test_code_languages_metadata():
    md = """# Title

```sql
SELECT 1;
```
```python
print(1)
```
"""
    chunks = make_chunks("fw", "a.md", md)
    langs = []
    for c in chunks:
        langs.extend(c.code_languages)
    assert "sql" in langs
    assert "python" in langs


# ---------------------------------------------------------------------------
# Prose splitting
# ---------------------------------------------------------------------------


def test_large_prose_split_with_overlap():
    prose = " ".join(f"Sentence number {i}." for i in range(200))
    md = f"""# Doc

## Section
{prose}
"""
    chunks = make_chunks("fw", "a.md", md, max_words=80, overlap_words=20)
    assert len(chunks) >= 2
    assert chunks[0].heading == "Doc > Section"
    assert "Sentence number 0" in chunks[0].content
    assert chunks[1].heading == "Doc > Section"


def test_section_boundary_no_overlap():
    md = """# T

## A
text A
## B
text B
"""
    chunks = make_chunks("fw", "a.md", md)
    assert len(chunks) == 2
    assert chunks[0].content.endswith("text A")
    assert chunks[1].content.startswith("T > B")


# ---------------------------------------------------------------------------
# Metadata and structure
# ---------------------------------------------------------------------------


def test_heading_chain_in_content():
    md = """# Title

## Section也给
body
"""
    chunks = make_chunks("fw", "a.md", md)
    assert chunks[0].content.startswith("Title > Section")


def test_is_last_chunk_marks_final():
    md = """# T

## A
a body
## B
b body
"""
    chunks = make_chunks("fw", "a.md", md)
    assert chunks[-1].is_last_chunk is True
    for c in chunks[:-1]:
        assert c.is_last_chunk is False


def test_empty_document_returns_empty():
    chunks = make_chunks("fw", "a.md", "", max_words=800, overlap_words=80)
    assert chunks == []


def test_whitespace_only_returns_empty():
    chunks = make_chunks("fw", "a.md", "   \n\n  \n", max_words=800, overlap_words=80)
    assert chunks == []


def test_chunk_indices_are_sequential():
    md = """# T

## A
a body
## B
b body
## C
c body
"""
    chunks = make_chunks("fw", "a.md", md)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_title_fallback_to_path():
    md = "Just a paragraph with no heading.\n"
    chunks = make_chunks("fw", "docs/intro/file.md", md)
    assert chunks[0].title == "docs_intro_file"


def test_block_types_metadata():
    md = """# T

paragraph text

- item one
- item two
"""
    chunks = make_chunks("fw", "a.md", md)
    types = []
    for c in chunks:
        types.extend(c.block_types)
    assert "prose" in types or "list" in types


# ---------------------------------------------------------------------------
# Lists and tables
# ---------------------------------------------------------------------------


def test_list_atomic():
    md = """# T

## Sec
- item 1
- item 2
- item 3
"""
    chunks = make_chunks("fw", "a.md", md)
    assert "- item 1" in chunks[0].content
    assert "- item 3" in chunks[0].content


# ---------------------------------------------------------------------------
# Framework + path metadata
# ---------------------------------------------------------------------------


def test_framework_and_path_propagated():
    md = "# T\n\ntext\n"
    chunks = make_chunks("delta", "docs/foo.md", md)
    assert chunks[0].framework == "delta"
    assert chunks[0].source_path == "docs/foo.md"


# ---------------------------------------------------------------------------
# Chunk dataclass
# ---------------------------------------------------------------------------


def test_chunk_dataclass_fields():
    c = Chunk(
        framework="fw",
        source_path="a.md",
        title="T",
        heading="T > S",
        chunk_index=0,
        content="body",
        is_last_chunk=True,
    )
    assert c.has_code is False
    assert c.code_languages == []
    assert c.block_types == []


# ---------------------------------------------------------------------------
# Block parsing helpers
# ---------------------------------------------------------------------------


def test_parse_blocks_returns_headings_and_code():
    md = """# Title

```python
print(1)
```
"""
    blocks = _parse_blocks(md)
    headings = [b for b in blocks if isinstance(b, _HeadingBlock)]
    codes = [b for b in blocks if isinstance(b, _CodeBlock)]
    assert len(headings) == 1
    assert headings[0].level == 1
    assert headings[0].text == "Title"
    assert len(codes) == 1
    assert codes[0].language == "python"


def test_build_sections_attaches_h4_label_to_code():
    md = """# T

## S
#### Python
```python
print(1)
```
"""
    blocks = _parse_blocks(md)
    title, sections = _build_sections(blocks)
    code_blocks = [b for b in sections[0].blocks if isinstance(b, _CodeBlock)]
    assert code_blocks[0].label == "Python"