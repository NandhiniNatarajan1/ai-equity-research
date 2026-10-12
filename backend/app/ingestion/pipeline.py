"""End-to-end ingestion pipeline: EDGAR fetch -> parse -> chunk -> embed -> upsert.

Idempotent: re-running for a ticker that already has its latest 10-K ingested
is a no-op. Re-running for a ticker that has a *newer* 10-K adds the new
filing's sections, chunks, and embeddings without touching older ones.
"""

from __future__ import annotations

from datetime import datetime
from itertools import batched

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.companies.resolver import TickerResolver
from app.core.logging import get_logger
from app.db.models import Chunk, ChunkEmbedding, Company, Filing, Section
from app.db.session import session_scope
from app.ingestion.chunker import chunk_section
from app.ingestion.edgar_client import EdgarClient, FilingRef
from app.ingestion.embedder import Embedder, build_embedder
from app.ingestion.section_parser import parse_sections

log = get_logger("ingestion.pipeline")

EMBED_BATCH_SIZE = 32


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _resolve_company(db: Session, ticker: str) -> Company:
    """Return the Company row for `ticker`, inserting it if we've never seen it.

    SEC's company_tickers.json is the source of truth for ticker -> CIK + name;
    we only persist the triple so later queries don't need to re-hit SEC.
    """
    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is not None:
        return company
    hit = TickerResolver.shared().resolve(ticker)
    if hit is None:
        raise LookupError(
            f"Unknown ticker '{ticker}' — not found in the SEC's public company list."
        )
    company = Company(cik=hit.cik, ticker=hit.ticker, name=hit.name, sic=None)
    db.add(company)
    db.flush()
    log.info("company_autocreated", ticker=hit.ticker, cik=hit.cik, name=hit.name)
    return company


def _filing_already_ingested(db: Session, cik: str, accession: str) -> Filing | None:
    return db.scalar(
        select(Filing).where(Filing.cik == cik, Filing.accession == accession)
    )


def ingest_ticker(
    ticker: str,
    *,
    edgar: EdgarClient | None = None,
    embedder: Embedder | None = None,
) -> dict[str, int | str]:
    """Fetch and ingest the latest 10-K for `ticker`. Returns a stats dict."""
    close_edgar = edgar is None
    edgar = edgar or EdgarClient()
    embedder = embedder or build_embedder()

    try:
        with session_scope() as db:
            company = _resolve_company(db, ticker)
            ref: FilingRef = edgar.latest_10k(company.cik)
            log.info(
                "ingest_start",
                ticker=ticker,
                cik=company.cik,
                accession=ref.accession,
                filing_date=ref.filing_date,
            )

            existing = _filing_already_ingested(db, company.cik, ref.accession)
            if existing is not None:
                log.info("ingest_skip_already_ingested", ticker=ticker, accession=ref.accession)
                return {
                    "ticker": ticker,
                    "accession": ref.accession,
                    "status": "already_ingested",
                    "sections": 0,
                    "chunks": 0,
                }

            raw = edgar.fetch_primary_document(ref)
            parsed = parse_sections(raw)
            if not parsed:
                raise RuntimeError(
                    f"No sections parsed from 10-K for {ticker} ({ref.accession})."
                )

            filing = Filing(
                cik=company.cik,
                accession=ref.accession,
                form_type=ref.form_type,
                filing_date=_parse_date(ref.filing_date),
                period_of_report=_parse_date(ref.report_date) if ref.report_date else None,
                primary_doc_url=ref.primary_doc_url,
                filing_index_url=ref.filing_index_url,
                raw_bytes=len(raw),
            )
            db.add(filing)
            db.flush()

            total_chunks = 0
            pending_chunks: list[Chunk] = []
            for section_data in parsed:
                section = Section(
                    filing_id=filing.id,
                    item_code=section_data.item_code,
                    title=section_data.title,
                    order_index=section_data.order_index,
                    raw_text=section_data.raw_text,
                    char_count=section_data.char_count,
                )
                db.add(section)
                db.flush()

                drafts = chunk_section(section_data.raw_text)
                for draft in drafts:
                    chunk = Chunk(
                        section_id=section.id,
                        chunk_index=draft.chunk_index,
                        text=draft.text,
                        token_count=draft.token_count,
                        char_start=draft.char_start,
                        char_end=draft.char_end,
                    )
                    db.add(chunk)
                    pending_chunks.append(chunk)
                total_chunks += len(drafts)

            db.flush()

            # Batch-embed and upsert embeddings.
            embedded = 0
            for batch in batched(pending_chunks, EMBED_BATCH_SIZE):
                vectors = embedder.embed([c.text for c in batch], mode="document")
                for chunk, vec in zip(batch, vectors, strict=True):
                    db.add(
                        ChunkEmbedding(
                            chunk_id=chunk.id,
                            embedding=vec,
                            model=embedder.model,
                            dim=embedder.dim,
                        )
                    )
                    embedded += 1
                log.info("embed_batch", ticker=ticker, embedded=embedded, total=total_chunks)

            return {
                "ticker": ticker,
                "accession": ref.accession,
                "status": "ingested",
                "sections": len(parsed),
                "chunks": total_chunks,
                "embedded": embedded,
            }
    finally:
        if close_edgar:
            edgar.close()
