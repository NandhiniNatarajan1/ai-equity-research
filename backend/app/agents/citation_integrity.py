"""Citation-integrity validator.

Non-negotiable: the agent cannot invent citations. Every chunk_id the agent
cites must have been returned by one of its MCP tool calls during that run,
and the quoted span must appear in that chunk's text (fuzzy-matched on
normalized whitespace).

Returned structure makes it trivial for the API layer to decide whether to
accept the answer, reject it with 422, or (in a later milestone) feed the
mismatches back to the agent for a retry.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.schemas import AgentAnswer, AnswerCitation
from app.agents.sec_filing_agent import AgentState
from app.db.models import Chunk, Filing, Section

_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


def _fuzzy_contains(needle: str, haystack: str, threshold: float = 0.9) -> bool:
    needle_n = _normalize(needle)
    hay_n = _normalize(haystack)
    if not needle_n:
        return False
    if needle_n in hay_n:
        return True
    # Fallback: short quotes may differ by a few characters (ellipses, etc).
    ratio = SequenceMatcher(None, needle_n, hay_n).ratio()
    return ratio >= threshold


@dataclass(frozen=True)
class CitationIssue:
    citation: AnswerCitation
    kind: str  # "unknown_chunk" | "chunk_not_retrieved" | "quote_not_in_chunk"
    message: str


@dataclass
class ValidationResult:
    ok: bool
    issues: list[CitationIssue]
    verified: list[AnswerCitation]
    enriched: list[EnrichedCitation]


@dataclass(frozen=True)
class EnrichedCitation:
    """A verified citation + the filing/section metadata the UI needs."""

    citation: AnswerCitation
    section_item_code: str
    section_title: str
    filing_accession: str
    filing_date: str
    primary_doc_url: str


def validate_citations(
    db: Session,
    state: AgentState,
    answer: AgentAnswer,
) -> ValidationResult:
    retrieved_ids: set[str] = set()
    for tc in state.tool_calls:
        retrieved_ids.update(tc.returned_chunk_ids)

    issues: list[CitationIssue] = []
    verified: list[AnswerCitation] = []
    enriched: list[EnrichedCitation] = []

    for cit in answer.citations:
        try:
            chunk_uuid = UUID(cit.chunk_id)
        except ValueError:
            issues.append(
                CitationIssue(cit, "unknown_chunk", f"not a UUID: {cit.chunk_id!r}")
            )
            continue

        if cit.chunk_id not in retrieved_ids:
            issues.append(
                CitationIssue(
                    cit,
                    "chunk_not_retrieved",
                    "chunk_id was not returned by any MCP tool call this run",
                )
            )
            continue

        row = db.execute(
            select(Chunk, Section, Filing)
            .join(Section, Section.id == Chunk.section_id)
            .join(Filing, Filing.id == Section.filing_id)
            .where(Chunk.id == chunk_uuid)
        ).one_or_none()

        if row is None:
            issues.append(
                CitationIssue(cit, "unknown_chunk", "chunk no longer exists in DB")
            )
            continue

        chunk, section, filing = row
        if not _fuzzy_contains(cit.quoted_text, chunk.text):
            issues.append(
                CitationIssue(
                    cit,
                    "quote_not_in_chunk",
                    "quoted_text not found in the cited chunk (fuzzy match)",
                )
            )
            continue

        verified.append(cit)
        enriched.append(
            EnrichedCitation(
                citation=cit,
                section_item_code=section.item_code,
                section_title=section.title,
                filing_accession=filing.accession,
                filing_date=filing.filing_date.isoformat(),
                primary_doc_url=filing.primary_doc_url,
            )
        )

    return ValidationResult(ok=not issues, issues=issues, verified=verified, enriched=enriched)


def issues_summary(issues: Iterable[CitationIssue]) -> list[dict]:
    return [
        {
            "marker": i.citation.marker,
            "chunk_id": i.citation.chunk_id,
            "kind": i.kind,
            "message": i.message,
        }
        for i in issues
    ]
