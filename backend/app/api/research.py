"""Research API: POST /research/ask routes to the right specialist agent.

Routing:
  - questions about qualitative 10-K disclosures -> SEC Filing Agent
  - questions needing computed numeric metrics  -> Financial Agent

Both routes persist an agent_runs row with tool_calls, citations, and status.
SEC Filing Agent answers go through the citation-integrity validator; a 422
is returned on mismatch. Financial Agent answers come from deterministic
Python over XBRL and are published with full fact provenance.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.citation_integrity import issues_summary, validate_citations
from app.agents.orchestrator import run as orchestrator_run
from app.agents.schemas import (
    CitationOut,
    FinancialCitationOut,
    FinancialFactOut,
    ResearchAskRequest,
    ResearchAskResponse,
)
from app.core.logging import get_logger
from app.core.tracing import TraceCapture
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
        with TraceCapture() as cap:
            result = orchestrator_run(ticker, req.question)
        if cap.trace_url:
            run.trace_url = cap.trace_url
    except LookupError as exc:
        run.status = "no_data"
        run.error = str(exc)
        run.finished_at = datetime.now(tz=timezone.utc)
        db.commit()
        log.warning("ask_no_data", run_id=str(run.id), ticker=ticker, error=str(exc))
        raise HTTPException(
            status_code=400,
            detail=(
                f"No data has been ingested for {ticker} yet. Run:\n"
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

    # ------------------------------------------------------------------
    # SEC Filing Agent route
    # ------------------------------------------------------------------
    if result.sec_state is not None:
        state = result.sec_state
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
            route="sec_filing",
            route_reason=result.route.reason,
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
            trace_url=run.trace_url,
        )

    # ------------------------------------------------------------------
    # Financial Agent route
    # ------------------------------------------------------------------
    assert result.fin_state is not None
    fin = result.fin_state
    run.tool_calls = [
        {
            "tool": "get_financial_metrics",
            "arguments": {"ticker": ticker},
            "metrics": [m["name"] for m in fin.metrics],
        }
    ]
    if fin.error:
        run.status = "error"
        run.answer = fin.answer_markdown
        run.error = fin.error
        run.finished_at = datetime.now(tz=timezone.utc)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Financial Agent error: {fin.error}")

    # Build financial citations only for metrics the agent actually cited.
    cited: list[FinancialCitationOut] = []
    for m in fin.metrics:
        if m["name"] not in fin.metric_markers:
            continue
        if m.get("error"):
            continue
        cited.append(
            FinancialCitationOut(
                marker=f"[metric: {m['name']}]",
                name=m["name"],
                value=m["value"],
                unit=m["unit"],
                period_label=m["period_label"],
                narrative=m["narrative"],
                inputs=[FinancialFactOut(**p) for p in m["inputs"]],
            )
        )

    run.status = "ok"
    run.answer = fin.answer_markdown
    run.finished_at = datetime.now(tz=timezone.utc)
    db.commit()

    return ResearchAskResponse(
        run_id=str(run.id),
        ticker=ticker,
        question=req.question,
        route="financial",
        route_reason=result.route.reason,
        answer_markdown=fin.answer_markdown or "",
        financial_citations=cited,
        deferred=False,
        trace_url=run.trace_url,
    )
