"""Section-aware chunker.

Produces fixed-size (by tokens) chunks with small overlap, split on paragraph
boundaries so semantic retrieval returns coherent passages. Each chunk records
char_start / char_end back into the parent section's raw_text.

Defaults are tuned for 10-K prose:
  - target 800 tokens per chunk
  - overlap 100 tokens
  - never split a paragraph if it fits whole
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import tiktoken

_ENCODER = tiktoken.get_encoding("cl100k_base")


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    text: str
    token_count: int
    char_start: int
    char_end: int


def _count_tokens(text: str) -> int:
    return len(_ENCODER.encode(text))


def _split_paragraphs(text: str) -> list[tuple[int, int, str]]:
    """Return [(start, end, paragraph)] over the original text."""
    paragraphs: list[tuple[int, int, str]] = []
    cursor = 0
    for match in re.finditer(r"(?:[^\n]+(?:\n[^\n]+)*)", text):
        start = match.start()
        end = match.end()
        para = text[start:end].strip()
        if para:
            paragraphs.append((start, end, para))
        cursor = end
    _ = cursor
    return paragraphs


def chunk_section(
    text: str,
    *,
    target_tokens: int = 800,
    overlap_tokens: int = 100,
    min_tokens: int = 100,
) -> list[ChunkDraft]:
    """Chunk a single section's text into roughly `target_tokens`-sized pieces.

    Prefers paragraph boundaries. Enforces at most `target_tokens` per chunk by
    falling back to sentence/line splits for abnormally long paragraphs.
    """

    if not text.strip():
        return []

    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: list[ChunkDraft] = []
    cur_tokens: list[int] = []
    cur_segments: list[tuple[int, int, str]] = []
    cur_token_count = 0

    def flush() -> None:
        nonlocal cur_tokens, cur_segments, cur_token_count
        if not cur_segments:
            return
        start = cur_segments[0][0]
        end = cur_segments[-1][1]
        body = text[start:end].strip()
        if body:
            chunks.append(
                ChunkDraft(
                    chunk_index=len(chunks),
                    text=body,
                    token_count=cur_token_count,
                    char_start=start,
                    char_end=end,
                )
            )
        cur_tokens = []
        cur_segments = []
        cur_token_count = 0

    for start, end, para in paragraphs:
        para_tokens = _count_tokens(para)

        # Oversized single paragraph: force-split on sentence boundaries.
        if para_tokens > target_tokens:
            flush()
            for sub_start, sub_end, sub in _split_oversized(start, end, para, target_tokens):
                sub_token_count = _count_tokens(sub)
                chunks.append(
                    ChunkDraft(
                        chunk_index=len(chunks),
                        text=sub,
                        token_count=sub_token_count,
                        char_start=sub_start,
                        char_end=sub_end,
                    )
                )
            continue

        if cur_token_count + para_tokens > target_tokens and cur_token_count >= min_tokens:
            flush()
            # Simple overlap: carry over the last paragraph if it's small.
            if overlap_tokens > 0 and chunks:
                last = chunks[-1]
                if last.token_count <= overlap_tokens:
                    cur_segments.append((last.char_start, last.char_end, last.text))
                    cur_tokens.append(last.token_count)
                    cur_token_count = last.token_count

        cur_segments.append((start, end, para))
        cur_tokens.append(para_tokens)
        cur_token_count += para_tokens

    flush()
    return chunks


def _split_oversized(
    base_start: int, base_end: int, para: str, target_tokens: int
) -> list[tuple[int, int, str]]:
    """Fallback: slice a very long paragraph into pieces by sentence."""
    sentences = re.split(r"(?<=[\.\?!])\s+", para)
    out: list[tuple[int, int, str]] = []
    cursor_offset = 0  # offset relative to para start
    buf: list[str] = []
    buf_tokens = 0
    buf_start = 0
    for sent in sentences:
        tok = _count_tokens(sent)
        if buf and buf_tokens + tok > target_tokens:
            body = " ".join(buf).strip()
            if body:
                out.append((base_start + buf_start, base_start + cursor_offset, body))
            buf = []
            buf_tokens = 0
            buf_start = cursor_offset
        if not buf:
            buf_start = cursor_offset
        buf.append(sent)
        buf_tokens += tok
        # Advance offset over the sentence + a following space (if any).
        cursor_offset += len(sent) + 1
    if buf:
        body = " ".join(buf).strip()
        if body:
            out.append((base_start + buf_start, base_end, body))
    return out
