"""Chunker unit tests."""

from __future__ import annotations

from app.ingestion.chunker import chunk_section
from app.ingestion.section_parser import parse_sections


def test_chunker_produces_at_least_one_chunk(mini_10k_html: bytes) -> None:
    sections = parse_sections(mini_10k_html)
    risk = next(s for s in sections if s.item_code == "1A")
    chunks = chunk_section(risk.raw_text, target_tokens=800, overlap_tokens=100)
    assert len(chunks) >= 1


def test_chunker_offsets_point_into_source(mini_10k_html: bytes) -> None:
    sections = parse_sections(mini_10k_html)
    biz = next(s for s in sections if s.item_code == "1")
    chunks = chunk_section(biz.raw_text, target_tokens=200, overlap_tokens=20)
    for c in chunks:
        slice_ = biz.raw_text[c.char_start : c.char_end]
        assert c.text.strip() in slice_ or slice_.strip().startswith(c.text[:40])
        assert c.char_end <= len(biz.raw_text)
        assert c.char_start < c.char_end


def test_chunker_respects_target_size_roughly() -> None:
    text = ("This is a sentence that is medium length. " * 400).strip()
    chunks = chunk_section(text, target_tokens=200, overlap_tokens=20, min_tokens=50)
    assert chunks, "expected at least one chunk for long input"
    # Allow modest overshoot for the fallback splitter.
    assert all(c.token_count <= 300 for c in chunks)


def test_chunker_assigns_sequential_indexes(mini_10k_html: bytes) -> None:
    sections = parse_sections(mini_10k_html)
    biz = next(s for s in sections if s.item_code == "1")
    chunks = chunk_section(biz.raw_text, target_tokens=150, overlap_tokens=20)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
