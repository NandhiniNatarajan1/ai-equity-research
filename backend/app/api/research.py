"""Research API: POST /research/ask runs the SEC Filing Agent and returns a cited answer.

Guarantees:
  - Every citation in the response is backed by a chunk returned by an MCP tool
    call during this run (recorded in agent_runs.tool_calls).
  - Every quoted_text is fuzzy-matched against the cited chunk's text.
  - If citation integrity fails, we respond 422 with the issues; the agent run
    is still persisted (status="citation_failed") for debugging.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.citation_integrity import issues_summary, validate_citations
from app.agents.schemas import (
    CitationOut,
    ResearchAskRequest,
    ResearchAskResponse,
)
from app.agents.sec_filing_agent import run_agent
from app.core.logging import get_logger
from app.db.models import AgentRun, Citation
from app.db.session import get_session

router = APIRouter(prefix="/research", tags=["research"])
log = get_logger("api.research")


@router.post("/ask", response_model=ResearchAskResponse)
def ask(req: ResearchAskRequest, db: Session = Depends(get_session)) -> ResearchAskResponse:
    ticker = req.ticker.upper()
    log.info("ask_start", ticker=ticker, question=req.question)

    run = AgentRun(ticker=ticker, question=req.question, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        state = run_agent(ticker, req.question)
    except LookupError as exc:
        # No data for this ticker yet — a user precondition, not a server bug.
        run.status = "no_data"
        run.error = str(exc)
        run.finished_at = datetime.now(tz=timezone.utc)
        db.commit()
        log.warning("ask_no_data", run_id=str(run.id), ticker=ticker, error=str(exc))
        raise HTTPException(
            status_code=400,
            detail=(
                f"No 10-K has been ingested for {ticker} yet. Run the ingestion CLI:\n"
                f"  docker compose exec api python -m app.ingestion.cli {ticker}"
            ),
        ) from exc
    except Exception as exc:
        run.status = "error"
        run.error = str(exc)
        run.finished_at = datetime.now(tz=timezone.utc)
        db.commit()
        log.exception("ask_agent_error", run_id=str(run.id), error=str(exc))
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}") from exc

    run.tool_calls = [tc.model_dump() for tc in state.tool_calls]
    answer = state.answer
    if answer is None:
        run.status = "error"
        run.error = "agent produced no answer"
        run.finished_at = datetime.now(tz=timezone.utc)
        db.commit()
        raise HTTPException(status_code=500, detail="Agent produced no answer")

    validation = validate_citations(db, state, answer)
    if not validation.ok and not answer.deferred:
        run.status = "citation_failed"
        run.answer = answer.answer_markdown
        run.error = f"citation_integrity_failed: {len(validation.issues)} issues"
        run.finished_at = datetime.now(tz=timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Citation integrity check failed",
                "run_id": str(run.id),
                "issues": issues_summary(validation.issues),
            },
        )

    # Persist verified citations.
    for enriched in validation.enriched:
        db.add(
            Citation(
                agent_run_id=run.id,
                chunk_id=enriched.citation.chunk_id,  # type: ignore[arg-type]
                quoted_text=enriched.citation.quoted_text,
                marker=enriched.citation.marker,
            )
        )

    run.status = "ok"
    run.answer = answer.answer_markdown
    run.finished_at = datetime.now(tz=timezone.utc)
    db.commit()

    return ResearchAskResponse(
        run_id=str(run.id),
        ticker=ticker,
        question=req.question,
        answer_markdown=answer.answer_markdown,
        citations=[
            CitationOut(
                marker=e.citation.marker,
                chunk_id=e.citation.chunk_id,
                quoted_text=e.citation.quoted_text,
                section_item_code=e.section_item_code,
                section_title=e.section_title,
                filing_accession=e.filing_accession,
                filing_date=e.filing_date,
                primary_doc_url=e.primary_doc_url,
            )
            for e in validation.enriched
        ],
        deferred=answer.deferred,
        deferral_reason=answer.deferral_reason,
    )
