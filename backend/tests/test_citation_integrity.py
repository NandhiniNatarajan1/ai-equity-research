"""Unit tests for the citation-integrity validator (no network, no LLM).

Uses a disposable SQLite database — enough to exercise the SQLAlchemy models
for Chunk/Section/Filing. Vector columns and pgvector-specific types are not
touched by the validator, so SQLite is fine for these tests.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import Session

from app.agents.citation_integrity import validate_citations
from app.agents.schemas import AgentAnswer, AnswerCitation, ToolCallRecord
from app.agents.sec_filing_agent import AgentState
from app.db.models import Base, Chunk, Company, Filing, Section


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    # SQLite can't create the pgvector column; drop that table from metadata
    # for the test schema create. Validator never touches it.
    md = MetaData()
    for t in Base.metadata.sorted_tables:
        if t.name == "chunk_embeddings":
            continue
        t.to_metadata(md)
    md.create_all(engine)
    with Session(engine, future=True) as session:
        yield session


def _seed(db: Session) -> tuple[Chunk, Chunk]:
    company = Company(cik="0001045810", ticker="NVDA", name="NVIDIA CORP")
    db.add(company)
    filing = Filing(
        id=uuid.uuid4(),
        cik=company.cik,
        accession="0001045810-25-000147",
        form_type="10-K",
        filing_date=datetime(2025, 2, 26, tzinfo=timezone.utc),
        primary_doc_url="https://example.com/nvda.htm",
        filing_index_url="https://example.com/nvda-index.htm",
    )
    db.add(filing)
    section = Section(
        id=uuid.uuid4(),
        filing_id=filing.id,
        item_code="1A",
        title="Risk Factors",
        order_index=1,
        raw_text="Export controls restrict our ability to sell into China.",
        char_count=58,
    )
    db.add(section)
    retrieved_chunk = Chunk(
        id=uuid.uuid4(),
        section_id=section.id,
        chunk_index=0,
        text=(
            "Export controls imposed by the U.S. government restrict our "
            "ability to sell certain products into specific geographies, "
            "including the People's Republic of China."
        ),
        token_count=24,
        char_start=0,
        char_end=160,
    )
    not_retrieved_chunk = Chunk(
        id=uuid.uuid4(),
        section_id=section.id,
        chunk_index=1,
        text="Supply chain concentration in Taiwan foundries is a key risk.",
        token_count=12,
        char_start=161,
        char_end=222,
    )
    db.add_all([retrieved_chunk, not_retrieved_chunk])
    db.commit()
    return retrieved_chunk, not_retrieved_chunk


def _state_with(chunk_ids: list[str]) -> AgentState:
    return AgentState(
        ticker="NVDA",
        question="What are the risks?",
        tool_calls=[
            ToolCallRecord(
                tool="search_filings",
                arguments={"ticker": "NVDA", "query": "risks"},
                returned_chunk_ids=chunk_ids,
            )
        ],
    )


def test_valid_citation_passes(db: Session) -> None:
    retrieved, _ = _seed(db)
    state = _state_with([str(retrieved.id)])
    answer = AgentAnswer(
        answer_markdown="Export controls limit NVDA's sales into China [1].",
        citations=[
            AnswerCitation(
                marker="[1]",
                chunk_id=str(retrieved.id),
                quoted_text="restrict our ability to sell certain products into specific geographies",
            )
        ],
    )
    result = validate_citations(db, state, answer)
    assert result.ok, [i.message for i in result.issues]
    assert len(result.verified) == 1
    assert result.enriched[0].section_item_code == "1A"


def test_rejects_chunk_not_retrieved(db: Session) -> None:
    retrieved, not_retrieved = _seed(db)
    state = _state_with([str(retrieved.id)])
    answer = AgentAnswer(
        answer_markdown="Supply chain is a risk [1].",
        citations=[
            AnswerCitation(
                marker="[1]",
                chunk_id=str(not_retrieved.id),
                quoted_text="Supply chain concentration in Taiwan",
            )
        ],
    )
    result = validate_citations(db, state, answer)
    assert not result.ok
    assert result.issues[0].kind == "chunk_not_retrieved"


def test_rejects_quote_not_in_chunk(db: Session) -> None:
    retrieved, _ = _seed(db)
    state = _state_with([str(retrieved.id)])
    answer = AgentAnswer(
        answer_markdown="NVDA will double revenue next year [1].",
        citations=[
            AnswerCitation(
                marker="[1]",
                chunk_id=str(retrieved.id),
                quoted_text="we will double revenue next year",
            )
        ],
    )
    result = validate_citations(db, state, answer)
    assert not result.ok
    assert result.issues[0].kind == "quote_not_in_chunk"


def test_rejects_malformed_uuid(db: Session) -> None:
    _seed(db)
    state = _state_with([])
    answer = AgentAnswer(
        answer_markdown="x [1]",
        citations=[AnswerCitation(marker="[1]", chunk_id="not-a-uuid", quoted_text="x")],
    )
    result = validate_citations(db, state, answer)
    assert not result.ok
    assert result.issues[0].kind == "unknown_chunk"


def test_fuzzy_whitespace_match(db: Session) -> None:
    retrieved, _ = _seed(db)
    state = _state_with([str(retrieved.id)])
    answer = AgentAnswer(
        answer_markdown="Export controls hit sales [1].",
        citations=[
            AnswerCitation(
                marker="[1]",
                chunk_id=str(retrieved.id),
                # Extra whitespace and casing — must still match.
                quoted_text="  Export  CONTROLS imposed by the U.S. government  ",
            )
        ],
    )
    result = validate_citations(db, state, answer)
    assert result.ok, [i.message for i in result.issues]
