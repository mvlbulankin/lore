"""Code-aware markdown chunker.

Design goals:
- Heading chain (H1>H2>H3) preserved per chunk as metadata.
- H4 labels preceding code fences are treated as language labels for that
  fence, NOT added to the heading chain.
- Code fences are atomic: never split mid-block. If a fence exceeds the
  chunk word budget it is kept whole in a single chunk.
- Prose is split by sentences when a section exceeds max_words, with a
  configurable overlap carried only over prose (not across code blocks or
  section boundaries).
- The heading chain is prepended to chunk.content so that embedding and
  BM25 both see it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

import structlog
from markdown_it import MarkdownIt

log = structlog.get_logger()


@dataclass
class Chunk:
    framework: str
    source_path: str
    title: str
    heading: str
    chunk_index: int
    content: str
    is_last_chunk: bool
    has_code: bool = False
    code_languages: list[str] = field(default_factory=list)
    block_types: list[str] = field(default_factory=list)
    # Parent-child
    parent_id: str | None = None
    parent_heading: str | None = None
    parent_content: str | None = None


@dataclass
class _CodeBlock:
    language: str
    content: str
    label: str = ""


@dataclass
class _ProseBlock:
    text: str


@dataclass
class _ListBlock:
    items: list[str]


@dataclass
class _HeadingBlock:
    level: int
    text: str


@dataclass
class _Section:
    heading_chain: list[str]
    blocks: list[object]


def _split_into_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZА-Я0-9`])", text)
    return [p for p in parts if p.strip()]


def _count_words(text: str) -> int:
    return len(text.split())


def _parse_blocks(text: str) -> list[object]:
    md = MarkdownIt()
    tokens = md.parse(text)
    blocks: list[object] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        t = tok.type
        if t == "heading_open":
            level = int(tok.tag[1])
            j = i + 1
            heading_text = ""
            if j < len(tokens) and tokens[j].type == "inline":
                heading_text = tokens[j].content.strip()
                j += 1
            if j < len(tokens) and tokens[j].type == "heading_close":
                j += 1
            blocks.append(_HeadingBlock(level=level, text=heading_text))
            i = j
            continue
        if t == "fence":
            info = (tok.info or "").strip()
            lang = info.split()[0] if info else ""
            content = tok.content
            blocks.append(_CodeBlock(language=lang, content=content))
            i += 1
            continue
        if t == "code_block":
            blocks.append(_CodeBlock(language="", content=tok.content))
            i += 1
            continue
        if t == "paragraph_open":
            j = i + 1
            parts: list[str] = []
            if j < len(tokens) and tokens[j].type == "inline":
                parts.append(tokens[j].content)
                j += 1
            while j < len(tokens) and tokens[j].type == "inline":
                parts.append(tokens[j].content)
                j += 1
            if j < len(tokens) and tokens[j].type == "paragraph_close":
                j += 1
            text = "\n".join(parts).strip()
            if text:
                blocks.append(_ProseBlock(text=text))
            i = j
            continue
        if t == "bullet_list_open" or t == "ordered_list_open":
            j = i + 1
            items: list[str] = []
            current: list[str] | None = []
            depth = 1
            while j < len(tokens) and depth > 0:
                tt = tokens[j]
                if tt.type in ("bullet_list_open", "ordered_list_open"):
                    depth += 1
                elif tt.type in ("bullet_list_close", "ordered_list_close"):
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                if tt.type == "list_item_open":
                    current = []
                elif tt.type == "inline" and current is not None:
                    current.append(tt.content)
                elif tt.type == "list_item_close":
                    if current:
                        items.append(" ".join(current).strip())
                    current = None
                j += 1
            if items:
                blocks.append(_ListBlock(items=items))
            i = j
            continue
        i += 1
    return blocks


def _build_sections(
    blocks: list[object], heading_chain_max: int = 3
) -> tuple[str, list[_Section]]:
    title = ""
    heading_stack: list[str] = []
    sections: list[_Section] = []
    current_blocks: list[object] = []

    def _flush() -> None:
        nonlocal current_blocks
        if current_blocks:
            sections.append(
                _Section(
                    heading_chain=list(heading_stack),
                    blocks=list(current_blocks),
                )
            )
            current_blocks = []

    pending_label: str | None = None

    for block in blocks:
        if isinstance(block, _HeadingBlock):
            if pending_label is not None:
                current_blocks.append(_ProseBlock(text=f"{'#' * 4} {pending_label}"))
                pending_label = None
            if block.level <= heading_chain_max:
                _flush()
                if block.level <= len(heading_stack):
                    heading_stack = heading_stack[: block.level - 1]
                if not heading_stack and not title:
                    title = block.text
                heading_stack.append(block.text)
            else:
                pending_label = block.text
            continue

        if isinstance(block, _CodeBlock) and pending_label is not None:
            block.label = pending_label
            _flush()
            current_blocks.append(block)
            pending_label = None
            continue

        _flush()
        if pending_label is not None:
            current_blocks.append(_ProseBlock(text=f"{'#' * 4} {pending_label}"))
            pending_label = None
        current_blocks.append(block)

    if pending_label is not None:
        current_blocks.append(_ProseBlock(text=f"{'#' * 4} {pending_label}"))
    _flush()
    return title, sections


def _blocks_to_text(blocks: Sequence[object]) -> str:
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, _ProseBlock):
            parts.append(block.text)
        elif isinstance(block, _CodeBlock):
            fence_lang = block.language or ""
            label_line = f"**{block.label}**\n\n" if block.label else ""
            parts.append(f"{label_line}```{fence_lang}\n{block.content.strip()}\n```")
        elif isinstance(block, _ListBlock):
            for item in block.items:
                parts.append(f"- {item}")
    return "\n\n".join(parts)


def _collect_metadata(blocks: Sequence[object]) -> tuple[bool, list[str], list[str]]:
    has_code = False
    langs: list[str] = []
    types: list[str] = []
    for block in blocks:
        if isinstance(block, _CodeBlock):
            has_code = True
            if block.language:
                langs.append(block.language)
            types.append("code")
        elif isinstance(block, _ProseBlock):
            types.append("prose")
        elif isinstance(block, _ListBlock):
            types.append("list")
    return has_code, langs, types


def _split_prose_for_overlap(
    prose: _ProseBlock, max_words: int, overlap_words: int
) -> list[_ProseBlock]:
    text = prose.text
    if _count_words(text) <= max_words:
        return [prose]
    sentences = _split_into_sentences(text)
    if len(sentences) <= 1:
        word_count = _count_words(text)
        if word_count > max_words:
            words = text.split()
            log.warning(
                "forced_split_long_sentence",
                words=word_count,
                max_words=max_words,
            )
            forced: list[_ProseBlock] = []
            overlap_tail: list[str] = []
            for i in range(0, len(words), max_words):
                chunk_words = words[i : i + max_words]
                forced.append(_ProseBlock(text=" ".join(overlap_tail + chunk_words)))
                if overlap_words and i + max_words < len(words):
                    overlap_tail = (
                        chunk_words[-overlap_words:]
                        if len(chunk_words) >= overlap_words
                        else chunk_words
                    )
                else:
                    overlap_tail = []
            return forced
        return [prose]

    chunks: list[_ProseBlock] = []
    current: list[str] = []
    current_words = 0
    for sent in sentences:
        sent_words = _count_words(sent)
        if current_words + sent_words > max_words and current:
            chunks.append(_ProseBlock(text=" ".join(current)))
            # Walk backwards through complete sentences to build overlap.
            # This guarantees overlap contains whole sentences only.
            overlap: list[str] = []
            overlap_word_count = 0
            for prev_sent in reversed(current):
                sw = _count_words(prev_sent)
                if overlap_word_count + sw > overlap_words:
                    break
                overlap.insert(0, prev_sent)
                overlap_word_count += sw
            current = overlap
            current_words = overlap_word_count
        current.append(sent)
        current_words += sent_words
    if current:
        chunks.append(_ProseBlock(text=" ".join(current)))
    return chunks


def _split_section(
    section: _Section,
    max_words: int,
    overlap_words: int,
) -> list[tuple[list[str], list[object]]]:
    heading_chain = section.heading_chain
    if not section.blocks:
        return []

    chunks: list[tuple[list[str], list[object]]] = []
    current_blocks: list[object] = []
    current_words = 0
    overlap_tail: list[object] = []

    for block in section.blocks:
        if isinstance(block, _CodeBlock):
            if current_blocks:
                chunks.append((heading_chain, current_blocks))
                current_blocks = list(overlap_tail)
                current_words = sum(
                    _count_words(_blocks_to_text([b])) for b in current_blocks
                )
                overlap_tail = []
            block_words = _count_words(block.content)
            current_blocks.append(block)
            current_words += block_words
            if current_words >= max_words:
                chunks.append((heading_chain, current_blocks))
                current_blocks = []
                current_words = 0
                overlap_tail = []
            continue

        if isinstance(block, _ProseBlock):
            sub = _split_prose_for_overlap(block, max_words, overlap_words)
            for sub_block in sub:
                sub_words = _count_words(sub_block.text)
                if current_words + sub_words > max_words and current_blocks:
                    chunks.append((heading_chain, current_blocks))
                    if overlap_words:
                        # Walk backwards through prose blocks to build overlap
                        # from complete sentences.
                        overlap_blocks: list[_ProseBlock] = []
                        overlap_wc = 0
                        for blk in reversed(current_blocks):
                            if not isinstance(blk, _ProseBlock):
                                break
                            for sent in reversed(_split_into_sentences(blk.text)):
                                sw = _count_words(sent)
                                if overlap_wc + sw > overlap_words:
                                    break
                                overlap_blocks.insert(0, _ProseBlock(text=sent))
                                overlap_wc += sw
                        current_blocks = overlap_blocks
                        current_words = overlap_wc
                    else:
                        current_blocks = []
                        current_words = 0
                current_blocks.append(sub_block)
                current_words += sub_words
            continue

        if isinstance(block, _ListBlock):
            text = _blocks_to_text([block])
            words = _count_words(text)
            if current_words + words > max_words and current_blocks:
                chunks.append((heading_chain, current_blocks))
                current_blocks = []
                current_words = 0
            current_blocks.append(block)
            current_words += words
            continue

    if current_blocks:
        chunks.append((heading_chain, current_blocks))

    return chunks


def make_chunks(
    framework: str,
    path: str,
    raw_text: str,
    max_words: int = 800,
    overlap_words: int = 80,
    parent_level: int = 2,
    heading_chain_max: int = 3,
) -> list[Chunk]:
    blocks = _parse_blocks(raw_text)
    if not blocks:
        return []

    title, sections = _build_sections(blocks, heading_chain_max=heading_chain_max)
    if not title:
        title = path.replace("/", "_").replace(".md", "")

    pieces: list[tuple[list[str], list[object]]] = []
    for section in sections:
        pieces.extend(_split_section(section, max_words, overlap_words))

    if not pieces:
        return []

    chunks: list[Chunk] = []
    for idx, (chain, blocks_in_chunk) in enumerate(pieces):
        heading_str = " > ".join(chain)
        body = _blocks_to_text(blocks_in_chunk)
        if heading_str:
            content = f"{heading_str}\n\n{body}"
        else:
            content = body
        has_code, langs, types = _collect_metadata(blocks_in_chunk)
        chunks.append(
            Chunk(
                framework=framework,
                source_path=path,
                title=title,
                heading=heading_str,
                chunk_index=idx,
                content=content,
                is_last_chunk=False,
                has_code=has_code,
                code_languages=langs,
                block_types=types,
            )
        )

    if chunks:
        last = chunks[-1]
        chunks[-1] = Chunk(
            framework=last.framework,
            source_path=last.source_path,
            title=last.title,
            heading=last.heading,
            chunk_index=last.chunk_index,
            content=last.content,
            is_last_chunk=True,
            has_code=last.has_code,
            code_languages=last.code_languages,
            block_types=last.block_types,
        )

    # Phase 2: attach parent info
    # Group chunks by parent section (heading chain up to parent_level)
    parent_groups: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        pid = _parent_id(chunk.heading, parent_level)
        parent_groups.setdefault(pid, []).append(chunk)

    for chunk in chunks:
        pid = _parent_id(chunk.heading, parent_level)
        chunk.parent_id = f"{framework}/{path}/{pid}"
        chunk.parent_heading = pid

        # Build parent content from all chunks in same group
        parent_chunks = parent_groups[pid]
        if len(parent_chunks) > 1:
            chunk.parent_content = "\n\n".join(c.content for c in parent_chunks)
        # Single-chunk section → parent = child (no duplication needed)

    return chunks


def _parent_id(heading: str, parent_level: int) -> str:
    """Compute parent ID from heading chain.

    Splits ' > ' chain and takes first `parent_level` components.
    Falls back to the full heading if chain is shorter.
    """
    if not heading:
        return ""
    parts = heading.split(" > ")
    if len(parts) >= parent_level:
        return " > ".join(parts[:parent_level])
    return heading


__all__ = ["Chunk", "make_chunks"]
