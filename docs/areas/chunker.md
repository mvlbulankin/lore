# Chunker

**File:** `ingestion/chunker.py`

## Overview

Code-aware markdown chunker that preserves document structure, keeps code blocks atomic, and generates rich metadata per chunk.

## Pipeline

1. `_parse_blocks(text)` — markdown-it tokenization → typed blocks (`_HeadingBlock`, `_CodeBlock`, `_ProseBlock`, `_ListBlock`)
2. `_build_sections(blocks)` — group blocks under heading chains (H1>H2>H3), handle H4 labels
3. `_split_section(section)` — sub-split oversized sections by word count
4. `make_chunks()` — assemble `Chunk` objects with metadata

## Heading Chain

- H1, H2, H3 are tracked in a stack, producing chains like `"Title > Section > Subsection"`.
- H4 and deeper headings are NOT added to the chain. If an H4 immediately precedes a code fence, it becomes the fence's `label`. Otherwise it's treated as inline prose with `#### ` prefix.
- When a heading at level N is encountered, the stack is truncated to N-1 and the new heading is pushed.

## H4 Label Merging

An H4 heading immediately followed by a code fence is attached to that fence as `block.label`. The label is rendered as `**Label**` before the fence in the chunk content. If the H4 is NOT followed by a code fence, it becomes a prose block.

## Code Fence Atomicity

Code blocks (`_CodeBlock`) are NEVER split. If a code block exceeds `max_words`, it still occupies a single chunk. No overlap is carried across code block boundaries.

## Prose Splitting

Long prose blocks are split by sentences using regex `(?<=[.!?])\s+(?=[A-ZА-Я0-9`])`. Two overlap mechanisms exist:

1. **Within a single prose block** (`_split_prose_for_overlap`): when a prose block exceeds `max_words`, the overlap is computed by taking the last `overlap_words` words from the accumulated text, then re-splitting those words into sentences to respect boundaries.
2.  **Between accumulated blocks in a section** (`_split_section`): when the running chunk exceeds `max_words` and a new block would push it over, overlap is computed by walking backwards through prose blocks, re-splitting them into sentences, and collecting whole sentences until `overlap_words` is reached. Non-prose blocks (code, lists) terminate the backward walk.

Overlap is prose-only: it is never carried across code block boundaries or section boundaries.

## Block Types

| Block Type | Atomic? | Overlap? |
|-----------|---------|----------|
| `_CodeBlock` | Yes | No |
| `_ProseBlock` | No (sentence-split) | Yes |
| `_ListBlock` | Yes | No |

## Chunk Metadata

```python
@dataclass
class Chunk:
    framework: str
    source_path: str
    title: str
    heading: str          # "H1 > H2 > H3"
    chunk_index: int
    content: str           # heading chain prepended: "heading\n\nbody"
    is_last_chunk: bool
    has_code: bool         # True if chunk contains code blocks
    code_languages: list[str]  # ["python", "sql"]
    block_types: list[str]     # ["prose", "code", "list"]
    # Parent-child
    parent_id: str | None       # "framework/path/H1/H2"
    parent_heading: str | None  # heading chain of parent section
    parent_content: str | None  # full parent text (multi-chunk sections only)
```

## Parent-Child Chunking

After chunking, each chunk is assigned a parent section based on the heading chain up to `parent_level` (default: 2, i.e., H2).

- **`parent_id`** — unique identifier: `"framework/path/H1 > H2"`
- **`parent_heading`** — heading chain of the parent section
- **`parent_content`** — concatenation of all child chunks in the same parent section.
  Set only when a section is split into 2+ chunks. Single-chunk sections have
  `parent_content = None` to avoid duplication.

The `parent_level` parameter controls which heading level defines a parent boundary.
H2 is the default because Spark/Delta docs use H2 as the natural "section" boundary.

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_words` | 800 | Max words per chunk (code blocks may exceed) |
| `overlap_words` | 80 | Overlap between prose chunks |
| `parent_level` | 2 | Heading level defining parent section boundary (1=H1, 2=H2) |
