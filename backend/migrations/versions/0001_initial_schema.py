"""Initial schema: companies, filings, sections, chunks, chunk_embeddings, agent_runs, citations.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = get_settings().embedding_dim


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "companies",
        sa.Column("cik", sa.String(length=10), primary_key=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sic", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("ticker", name="uq_companies_ticker"),
    )
    op.create_index("ix_companies_ticker", "companies", ["ticker"])

    op.create_table(
        "filings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cik", sa.String(length=10), sa.ForeignKey("companies.cik", ondelete="CASCADE"), nullable=False),
        sa.Column("accession", sa.String(length=32), nullable=False),
        sa.Column("form_type", sa.String(length=16), nullable=False),
        sa.Column("filing_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_of_report", sa.DateTime(timezone=True), nullable=True),
        sa.Column("primary_doc_url", sa.Text(), nullable=False),
        sa.Column("filing_index_url", sa.Text(), nullable=False),
        sa.Column("raw_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("cik", "accession", name="uq_filings_cik_accession"),
    )
    op.create_index("ix_filings_cik", "filings", ["cik"])
    op.create_index("ix_filings_accession", "filings", ["accession"])

    op.create_table(
        "sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("filings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_code", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("filing_id", "item_code", name="uq_sections_filing_item"),
    )
    op.create_index("ix_sections_filing_id", "sections", ["filing_id"])

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.UniqueConstraint("section_id", "chunk_index", name="uq_chunks_section_index"),
    )
    op.create_index("ix_chunks_section_id", "chunks", ["section_id"])

    op.create_table(
        "chunk_embeddings",
        sa.Column(
            "chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        "CREATE INDEX ix_chunk_embeddings_hnsw "
        "ON chunk_embeddings USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_url", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_agent_runs_ticker", "agent_runs", ["ticker"])

    op.create_table(
        "citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quoted_text", sa.Text(), nullable=False),
        sa.Column("marker", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_citations_agent_run_id", "citations", ["agent_run_id"])
    op.create_index("ix_citations_chunk_id", "citations", ["chunk_id"])


def downgrade() -> None:
    op.drop_index("ix_citations_chunk_id", table_name="citations")
    op.drop_index("ix_citations_agent_run_id", table_name="citations")
    op.drop_table("citations")

    op.drop_index("ix_agent_runs_ticker", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.execute("DROP INDEX IF EXISTS ix_chunk_embeddings_hnsw")
    op.drop_table("chunk_embeddings")

    op.drop_index("ix_chunks_section_id", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("ix_sections_filing_id", table_name="sections")
    op.drop_table("sections")

    op.drop_index("ix_filings_accession", table_name="filings")
    op.drop_index("ix_filings_cik", table_name="filings")
    op.drop_table("filings")

    op.drop_index("ix_companies_ticker", table_name="companies")
    op.drop_table("companies")
