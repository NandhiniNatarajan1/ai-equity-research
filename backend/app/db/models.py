"""SQLAlchemy ORM models.

Schema overview:
  companies ─< filings ─< sections ─< chunks ─ (1:1) ─ chunk_embeddings
  agent_runs ─< citations >─ chunks
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import get_settings

_EMBED_DIM = get_settings().embedding_dim


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Company(Base):
    __tablename__ = "companies"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sic: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    filings: Mapped[list[Filing]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (UniqueConstraint("cik", "accession", name="uq_filings_cik_accession"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(ForeignKey("companies.cik", ondelete="CASCADE"), index=True)
    accession: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    form_type: Mapped[str] = mapped_column(String(16), nullable=False)
    filing_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_of_report: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    primary_doc_url: Mapped[str] = mapped_column(Text, nullable=False)
    filing_index_url: Mapped[str] = mapped_column(Text, nullable=False)
    raw_bytes: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    company: Mapped[Company] = relationship(back_populates="filings")
    sections: Mapped[list[Section]] = relationship(
        back_populates="filing", cascade="all, delete-orphan", order_by="Section.order_index"
    )


class Section(Base):
    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("filing_id", "item_code", name="uq_sections_filing_item"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filings.id", ondelete="CASCADE"), index=True
    )
    item_code: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    filing: Mapped[Filing] = relationship(back_populates="sections")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="section", cascade="all, delete-orphan", order_by="Chunk.chunk_index"
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("section_id", "chunk_index", name="uq_chunks_section_index"),
        Index("ix_chunks_section_id", "section_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)

    section: Mapped[Section] = relationship(back_populates="chunks")
    embedding: Mapped[ChunkEmbedding | None] = relationship(
        back_populates="chunk", uselist=False, cascade="all, delete-orphan"
    )


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(_EMBED_DIM), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chunk: Mapped[Chunk] = relationship(back_populates="embedding")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_url: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    # Full record of MCP tool invocations: [{tool, input, output_chunk_ids:[...], ...}]
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text)

    citations: Mapped[list[Citation]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="RESTRICT"), index=True
    )
    quoted_text: Mapped[str] = mapped_column(Text, nullable=False)
    marker: Mapped[str] = mapped_column(String(32), nullable=False)

    run: Mapped[AgentRun] = relationship(back_populates="citations")
    chunk: Mapped[Chunk] = relationship()
