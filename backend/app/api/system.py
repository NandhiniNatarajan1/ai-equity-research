"""System endpoints: ticker status (ingestion / XBRL availability) + run history."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AgentRun, Chunk, Company, Filing, Section
from app.db.session import get_session

router = APIRouter(tags=["system"])


@router.get("/system/status")
def status(db: Session = Depends(get_session)) -> dict[str, Any]:
    """Per-ticker ingestion state and overall health."""
    companies = db.scalars(select(Company).order_by(Company.ticker)).all()

    out: list[dict[str, Any]] = []
    for c in companies:
        latest: Filing | None = db.scalar(
            select(Filing)
            .where(Filing.cik == c.cik)
            .order_by(Filing.filing_date.desc())
            .limit(1)
        )
        section_count = 0
        chunk_count = 0
        if latest is not None:
            section_count = db.scalar(
                select(func.count(Section.id)).where(Section.filing_id == latest.id)
            ) or 0
            chunk_count = db.scalar(
                select(func.count(Chunk.id))
                .join(Section, Section.id == Chunk.section_id)
                .where(Section.filing_id == latest.id)
            ) or 0
        out.append(
            {
                "ticker": c.ticker,
                "name": c.name,
                "cik": c.cik,
                "ingested": latest is not None,
                "latest_filing": (
                    {
                        "accession": latest.accession,
                        "form_type": latest.form_type,
                        "filing_date": latest.filing_date.isoformat(),
                        "primary_doc_url": latest.primary_doc_url,
                    }
                    if latest
                    else None
                ),
                "section_count": section_count,
                "chunk_count": chunk_count,
            }
        )

    return {
        "companies": out,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/runs")
def list_runs(
    limit: int = Query(default=25, ge=1, le=100),
    ticker: str | None = Query(default=None),
    db: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """Recent agent runs, newest first."""
    stmt = select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)
    if ticker:
        stmt = stmt.where(AgentRun.ticker == ticker.upper())
    runs = db.scalars(stmt).all()
    return [
        {
            "run_id": str(r.id),
            "ticker": r.ticker,
            "question": r.question,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "trace_url": r.trace_url,
            "error": r.error,
            "answer_preview": (r.answer or "")[:200],
            "n_tool_calls": len(r.tool_calls or []),
        }
        for r in runs
    ]
