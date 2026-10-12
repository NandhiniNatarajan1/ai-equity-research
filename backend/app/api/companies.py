"""Company discovery + on-demand ingestion endpoints.

Lets the UI search any public ticker (not just the three seeded ones),
tell the user whether we have its 10-K already, and kick off ingestion
on demand.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.report_cache import invalidate as invalidate_report_cache
from app.companies.resolver import TickerResolver
from app.core.logging import get_logger
from app.db.models import Chunk, Company, Filing, Section
from app.db.session import get_session
from app.ingestion.pipeline import ingest_ticker

router = APIRouter(prefix="/companies", tags=["companies"])
log = get_logger("api.companies")


@router.get("/search")
def search(
    q: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(default=15, ge=1, le=50),
    db: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """Autocomplete search across every ticker in SEC's public company list.

    For each hit, annotate whether we already have its 10-K ingested so the
    UI can show "Loaded" vs "Load now" affordances.
    """
    hits = TickerResolver.shared().search(q, limit=limit)
    if not hits:
        return []
    tickers = [h.ticker for h in hits]
    rows = db.execute(
        select(Company.ticker, Filing.accession, Filing.filing_date)
        .join(Filing, Filing.cik == Company.cik, isouter=True)
        .where(Company.ticker.in_(tickers))
    ).all()
    latest: dict[str, dict[str, Any] | None] = {t: None for t in tickers}
    for ticker, accession, filing_date in rows:
        if accession is None:
            continue
        prev = latest.get(ticker)
        if prev is None or filing_date > prev["filing_date"]:
            latest[ticker] = {"accession": accession, "filing_date": filing_date}

    out: list[dict[str, Any]] = []
    for h in hits:
        info = latest.get(h.ticker)
        out.append(
            {
                "ticker": h.ticker,
                "cik": h.cik,
                "name": h.name,
                "loaded": info is not None,
                "latest_filing": None
                if info is None
                else {
                    "accession": info["accession"],
                    "filing_date": info["filing_date"].isoformat(),
                },
            }
        )
    return out


@router.get("/{ticker}")
def status(ticker: str, db: Session = Depends(get_session)) -> dict[str, Any]:
    """Resolve ticker + report current ingestion state."""
    ticker = ticker.upper()
    hit = TickerResolver.shared().resolve(ticker)
    if hit is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown ticker '{ticker}' — not found in SEC public company list.",
        )
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    section_count = 0
    chunk_count = 0
    latest: Filing | None = None
    if company is not None:
        latest = db.scalar(
            select(Filing)
            .where(Filing.cik == company.cik)
            .order_by(Filing.filing_date.desc())
            .limit(1)
        )
        if latest is not None:
            from sqlalchemy import func

            section_count = db.scalar(
                select(func.count(Section.id)).where(Section.filing_id == latest.id)
            ) or 0
            chunk_count = db.scalar(
                select(func.count(Chunk.id))
                .join(Section, Section.id == Chunk.section_id)
                .where(Section.filing_id == latest.id)
            ) or 0

    return {
        "ticker": hit.ticker,
        "name": hit.name,
        "cik": hit.cik,
        "loaded": latest is not None,
        "section_count": section_count,
        "chunk_count": chunk_count,
        "latest_filing": None
        if latest is None
        else {
            "accession": latest.accession,
            "form_type": latest.form_type,
            "filing_date": latest.filing_date.isoformat(),
            "primary_doc_url": latest.primary_doc_url,
        },
    }


@router.post("/{ticker}/ingest")
def ingest(ticker: str) -> dict[str, Any]:
    """Download + parse + embed the latest 10-K for `ticker` (synchronous)."""
    from app.core.config import get_settings

    if get_settings().demo_mode:
        raise HTTPException(
            status_code=403,
            detail=(
                "On-demand ingestion is disabled in demo mode. Clone the repo "
                "and run locally to try arbitrary tickers."
            ),
        )
    ticker = ticker.upper()
    if TickerResolver.shared().resolve(ticker) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown ticker '{ticker}' — not found in SEC public company list.",
        )
    try:
        result = ingest_ticker(ticker)
    except Exception as exc:
        log.exception("ingest_failed", ticker=ticker, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc

    # Any older cached report is now stale (new accession likely).
    try:
        invalidate_report_cache(ticker)
    except Exception:
        pass
    return {
        "ticker": ticker,
        "finished_at": datetime.now(tz=timezone.utc).isoformat(),
        **result,
    }
