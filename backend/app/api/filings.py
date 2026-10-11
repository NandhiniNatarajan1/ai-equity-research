"""Filings & citations lookup endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Company, Filing, Section
from app.db.session import get_session

router = APIRouter(tags=["filings"])


@router.get("/filings/{ticker}")
def list_filings(ticker: str, db: Session = Depends(get_session)) -> list[dict]:
    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    filings = db.scalars(
        select(Filing).where(Filing.cik == company.cik).order_by(Filing.filing_date.desc())
    ).all()
    return [
        {
            "id": str(f.id),
            "accession": f.accession,
            "form_type": f.form_type,
            "filing_date": f.filing_date.isoformat(),
            "period_of_report": f.period_of_report.isoformat() if f.period_of_report else None,
            "primary_doc_url": f.primary_doc_url,
        }
        for f in filings
    ]


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: UUID, db: Session = Depends(get_session)) -> dict:
    """Return the text and provenance of a chunk, for citation popovers."""
    chunk = db.get(Chunk, chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    section: Section = chunk.section
    filing: Filing = section.filing
    return {
        "chunk_id": str(chunk.id),
        "text": chunk.text,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "section": {
            "item_code": section.item_code,
            "title": section.title,
        },
        "filing": {
            "accession": filing.accession,
            "form_type": filing.form_type,
            "filing_date": filing.filing_date.isoformat(),
            "primary_doc_url": filing.primary_doc_url,
        },
    }
