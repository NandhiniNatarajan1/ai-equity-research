"""Retrieval tool implementations backed by Postgres + pgvector.

Both tools return a `RetrievalResult` whose entries carry the information needed
to construct a citation: chunk_id, filing accession, section item_code and title,
plus the text passage and its character offsets within the section.

Keeping these implementations as plain functions (no MCP decorators) means they
can be:
  - called directly from pytest for unit testing,
  - re-used inside the backend API if we want to short-circuit MCP for local dev,
  - exposed through the MCP server (see server.py).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk, ChunkEmbedding, Company, Filing, Section
from app.db.session import session_scope
from app.financial_tools import (
    XbrlClient,
    free_cash_flow,
    gross_margin,
    net_margin,
    operating_margin,
    revenue_cagr,
    revenue_yoy_growth,
)
from app.ingestion.embedder import build_embedder

_ITEM_PREFIX_RE = re.compile(r"^\s*(item\s+)?", re.IGNORECASE)


def _normalize_item_code(code: str) -> str:
    """Accept 'Item 1A', 'item 1a', '1A', ' 1a ' -> '1A'. Also allows 'FULL'."""
    return _ITEM_PREFIX_RE.sub("", code).strip().upper()


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    text: str
    score: float | None
    char_start: int
    char_end: int
    section_item_code: str
    section_title: str
    filing_accession: str
    filing_form_type: str
    filing_date: str
    primary_doc_url: str
    ticker: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_company_or_404(db: Session, ticker: str) -> Company:
    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        raise ValueError(f"Unknown ticker: {ticker}")
    return company


def _latest_filing(db: Session, cik: str, form_type: str = "10-K") -> Filing:
    filing = db.scalar(
        select(Filing)
        .where(Filing.cik == cik, Filing.form_type == form_type)
        .order_by(Filing.filing_date.desc())
    )
    if filing is None:
        raise LookupError(f"No {form_type} ingested for CIK {cik}.")
    return filing


def search_filings(
    ticker: str,
    query: str,
    *,
    k: int = 6,
    item_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Semantic search over the latest ingested 10-K for `ticker`.

    Returns the top-k chunks ordered by cosine distance ascending.
    Optionally restricts to specific 10-K Item codes (e.g. ["1", "1A"]).
    """
    embedder = build_embedder()
    [vec] = embedder.embed([query], mode="query")

    with session_scope() as db:
        company = _resolve_company_or_404(db, ticker)
        filing = _latest_filing(db, company.cik)

        stmt = (
            select(
                Chunk,
                Section,
                ChunkEmbedding.embedding.cosine_distance(vec).label("distance"),
            )
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
            .join(Section, Section.id == Chunk.section_id)
            .where(Section.filing_id == filing.id)
        )
        if item_codes:
            normalized = [_normalize_item_code(c) for c in item_codes if c]
            if normalized:
                # Always allow the FULL pseudo-section through — filings that
                # fell back to whole-document parsing (e.g. Intel) have no
                # per-Item sections and would otherwise be unreachable.
                normalized_set = set(normalized) | {"FULL"}
                stmt = stmt.where(Section.item_code.in_(list(normalized_set)))
        stmt = stmt.order_by("distance").limit(max(1, min(k, 25)))

        rows = db.execute(stmt).all()
        return [
            RetrievedChunk(
                chunk_id=str(chunk.id),
                text=chunk.text,
                score=float(distance),
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                section_item_code=section.item_code,
                section_title=section.title,
                filing_accession=filing.accession,
                filing_form_type=filing.form_type,
                filing_date=filing.filing_date.isoformat(),
                primary_doc_url=filing.primary_doc_url,
                ticker=company.ticker,
            ).as_dict()
            for chunk, section, distance in rows
        ]


def get_filing_section(
    ticker: str,
    item_code: str,
    *,
    max_chars: int = 20000,
) -> dict[str, Any]:
    """Return the full text of a specific 10-K section for `ticker`.

    Useful when the agent wants to confirm context around a retrieved chunk.
    Truncates to `max_chars` to protect the LLM context budget.
    """
    with session_scope() as db:
        company = _resolve_company_or_404(db, ticker)
        filing = _latest_filing(db, company.cik)
        normalized_code = _normalize_item_code(item_code)
        section = db.scalar(
            select(Section).where(
                Section.filing_id == filing.id,
                Section.item_code == normalized_code,
            )
        )
        if section is None:
            raise LookupError(
                f"No Item {item_code.upper()} in {ticker}'s latest 10-K ({filing.accession})."
            )
        text = section.raw_text
        truncated = len(text) > max_chars
        return {
            "ticker": company.ticker,
            "filing_accession": filing.accession,
            "filing_date": filing.filing_date.isoformat(),
            "primary_doc_url": filing.primary_doc_url,
            "item_code": section.item_code,
            "section_title": section.title,
            "char_count": section.char_count,
            "truncated": truncated,
            "text": text[:max_chars],
        }


# ---------------------------------------------------------------------------
# Financial tools (deterministic Python over SEC XBRL — Milestone 2).
# ---------------------------------------------------------------------------


_CALCULATORS = {
    "revenue_yoy_growth": revenue_yoy_growth,
    "revenue_cagr_3y": lambda f: revenue_cagr(f, years=3),
    "gross_margin": gross_margin,
    "operating_margin": operating_margin,
    "net_margin": net_margin,
    "free_cash_flow": free_cash_flow,
}


def _company_cik(ticker: str) -> tuple[str, str]:
    with session_scope() as db:
        company = _resolve_company_or_404(db, ticker)
        return company.cik, company.ticker


def get_financial_metrics(
    ticker: str,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Compute deterministic financial metrics for `ticker`'s latest fiscal year.

    `metrics` restricts to a subset; omit or empty for all. Supported:
      - revenue_yoy_growth
      - revenue_cagr_3y
      - gross_margin
      - operating_margin
      - net_margin
      - free_cash_flow

    Returns each metric with its computed value AND the exact XBRL fact
    inputs that produced it (concept, accession, filed date, form). The
    Financial Agent cites these facts in its answer — no LLM arithmetic.
    """
    cik, ticker_upper = _company_cik(ticker)
    wanted = [m for m in (metrics or list(_CALCULATORS)) if m in _CALCULATORS]
    if not wanted:
        raise ValueError(f"No valid metrics requested. Supported: {sorted(_CALCULATORS)}")

    with XbrlClient() as client:
        facts = client.fetch(cik)

    results = []
    for name in wanted:
        result = _CALCULATORS[name](facts)
        results.append(result.as_dict())

    return {
        "ticker": ticker_upper,
        "entity_name": facts.entity_name,
        "cik": cik,
        "metrics": results,
    }


def get_revenue_history(ticker: str, years: int = 5) -> dict[str, Any]:
    """Return raw annual revenue values for `ticker`, newest first.

    Includes full provenance so the agent can cite each year's revenue
    directly to the originating 10-K filing.
    """
    cik, ticker_upper = _company_cik(ticker)
    with XbrlClient() as client:
        facts = client.fetch(cik)
    series = facts.annual_series("revenue", limit=max(1, min(years, 15)))
    return {
        "ticker": ticker_upper,
        "entity_name": facts.entity_name,
        "cik": cik,
        "concept": series[0].concept if series else None,
        "unit": series[0].unit if series else "USD",
        "points": [
            {
                "fiscal_year": p.fiscal_year,
                "value": p.value,
                "end_date": p.end_date,
                "filed": p.filed,
                "accession": p.accession,
                "form": p.form,
            }
            for p in series
        ],
    }
