"""Report cache keyed on (ticker, latest_filing_accession).

Reports take ~60 s to generate (fan-out over 4 specialist agents + composer).
Once ingested data for a ticker is unchanged, the report is deterministic
enough that regenerating on every page-load is pure waste. We cache the
rendered ReportResult JSON on disk and invalidate automatically when a new
10-K for the ticker is ingested (new accession -> new cache key).

The cache is file-backed under `./data/reports/` so it survives container
restarts and docker-compose up/down cycles. There is no TTL — invalidation
is content-addressed by the SEC accession number.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.agents.report_agent import ReportResult, generate_report
from app.core.logging import get_logger
from app.db.models import Company, Filing
from app.db.session import session_scope

log = get_logger("report.cache")

CACHE_DIR = Path("./data/reports")


def _cache_path(ticker: str, accession: str) -> Path:
    safe_acc = accession.replace("/", "_")
    return CACHE_DIR / f"{ticker.upper()}__{safe_acc}.json"


def _latest_accession(ticker: str) -> str | None:
    """Return the latest ingested filing's accession for `ticker`, or None."""
    with session_scope() as db:
        company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
        if company is None:
            return None
        filing = db.scalar(
            select(Filing)
            .where(Filing.cik == company.cik)
            .order_by(Filing.filing_date.desc())
            .limit(1)
        )
        return filing.accession if filing else None


def _result_to_cacheable(r: ReportResult) -> dict[str, Any]:
    """Serialize a ReportResult to a cache-friendly dict."""
    from dataclasses import asdict as _dc_asdict

    from app.agents.schemas import AgentAnswer

    def _answer_dict(a: AgentAnswer | None) -> dict[str, Any] | None:
        if a is None:
            return None
        return {
            "answer_markdown": a.answer_markdown,
            "citations": [c.model_dump() for c in a.citations],
            "deferred": a.deferred,
            "deferral_reason": a.deferral_reason,
        }

    specs = r.specialists
    return {
        "ticker": r.ticker,
        "report_markdown": r.report_markdown,
        "all_citations": [c.model_dump() for c in r.all_citations],
        "financial_metrics": r.financial_metrics,
        "specialist_errors": specs.errors,
        "specialists": {
            "business": _answer_dict(specs.business.answer if specs.business else None),
            "risk": _answer_dict(specs.risk.answer if specs.risk else None),
            "competitor": _answer_dict(specs.competitor.answer if specs.competitor else None),
            "financial": None
            if specs.financial is None
            else {
                "answer_markdown": specs.financial.answer_markdown,
                "metrics": specs.financial.metrics,
                "metric_markers": specs.financial.metric_markers,
                "error": specs.financial.error,
            },
        },
        "price": _dc_asdict(specs.price) if specs.price else None,
        "history": {
            k: {
                "name": v.name,
                "unit": v.unit,
                "points": [_dc_asdict(p) for p in v.points],
            }
            for k, v in specs.history.items()
        },
    }


def _result_from_cache(blob: dict[str, Any]) -> ReportResult:
    """Reconstitute a minimal ReportResult from cache (enough for the renderer)."""
    from app.agents import financial_agent, risk_agent, sec_filing_agent
    from app.agents.competitor_agent import CompetitorAgentState
    from app.agents.report_agent import SpecialistOutputs
    from app.agents.schemas import AgentAnswer, AnswerCitation
    from app.financial_tools.history import HistoryPoint, HistorySeries
    from app.financial_tools.price_history import PriceSnapshot

    def _mk_answer(d: dict[str, Any] | None) -> AgentAnswer | None:
        if d is None:
            return None
        return AgentAnswer(
            answer_markdown=d.get("answer_markdown", ""),
            citations=[AnswerCitation(**c) for c in d.get("citations", []) or []],
            deferred=bool(d.get("deferred", False)),
            deferral_reason=d.get("deferral_reason"),
        )

    specs = SpecialistOutputs(errors=blob.get("specialist_errors", {}) or {})
    if blob.get("price"):
        specs.price = PriceSnapshot(**blob["price"])
    if blob.get("history"):
        specs.history = {
            k: HistorySeries(
                name=v["name"],
                unit=v["unit"],
                points=[HistoryPoint(**p) for p in v.get("points", [])],
            )
            for k, v in blob["history"].items()
        }
    s = blob.get("specialists", {})
    if s.get("business"):
        state = sec_filing_agent.AgentState(ticker=blob["ticker"], question="")
        state.answer = _mk_answer(s["business"])
        specs.business = state
    if s.get("risk"):
        rstate = risk_agent.RiskAgentState(ticker=blob["ticker"], question="")
        rstate.answer = _mk_answer(s["risk"])
        specs.risk = rstate
    if s.get("competitor"):
        cstate = CompetitorAgentState(anchor_ticker=blob["ticker"], question="")
        cstate.answer = _mk_answer(s["competitor"])
        specs.competitor = cstate
    if s.get("financial"):
        fstate = financial_agent.FinancialAgentState(ticker=blob["ticker"], question="")
        fstate.answer_markdown = s["financial"].get("answer_markdown")
        fstate.metrics = s["financial"].get("metrics", [])
        fstate.metric_markers = s["financial"].get("metric_markers", [])
        fstate.error = s["financial"].get("error")
        specs.financial = fstate

    return ReportResult(
        ticker=blob["ticker"],
        report_markdown=blob.get("report_markdown", ""),
        specialists=specs,
        all_citations=[AnswerCitation(**c) for c in blob.get("all_citations", []) or []],
        financial_metrics=blob.get("financial_metrics", []),
    )


def get_or_generate(
    ticker: str,
    *,
    force_refresh: bool = False,
    peers: list[str] | None = None,
) -> tuple[ReportResult, dict[str, Any]]:
    """Return a report for `ticker`, from cache if possible.

    Caching is skipped when `peers` is a custom list — different peer
    selections produce materially different Competitive Position sections,
    so they must not share a cache slot. The default peer set still caches.

    Returns (result, meta) with cache diagnostics.
    """
    ticker = ticker.upper()
    accession = _latest_accession(ticker)
    if accession is None:
        raise LookupError(f"No ingested filing for {ticker}.")

    use_cache = peers is None
    path = _cache_path(ticker, accession)
    if use_cache and path.exists() and not force_refresh:
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            result = _result_from_cache(blob)
            meta = {
                "cached": True,
                "accession": accession,
                "generated_at": blob.get("_generated_at"),
                "cache_path": str(path),
                "peers": None,
            }
            log.info("report_cache_hit", ticker=ticker, accession=accession)
            return result, meta
        except Exception as exc:
            log.warning("report_cache_read_fail", ticker=ticker, error=str(exc))

    log.info("report_cache_miss", ticker=ticker, accession=accession, custom_peers=peers)
    result = generate_report(ticker, peers=peers)

    if use_cache:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            blob = _result_to_cacheable(result)
            blob["_generated_at"] = datetime.now(tz=timezone.utc).isoformat()
            blob["_accession"] = accession
            path.write_text(json.dumps(blob, default=str), encoding="utf-8")
            log.info("report_cache_write", ticker=ticker, path=str(path))
        except Exception as exc:
            log.warning("report_cache_write_fail", ticker=ticker, error=str(exc))

    meta = {
        "cached": False,
        "accession": accession,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "cache_path": str(path) if use_cache else None,
        "peers": peers,
    }
    return result, meta


def invalidate(ticker: str) -> int:
    """Remove all cached reports for `ticker`. Returns count deleted."""
    if not CACHE_DIR.exists():
        return 0
    prefix = f"{ticker.upper()}__"
    removed = 0
    for p in CACHE_DIR.glob(f"{prefix}*.json"):
        p.unlink()
        removed += 1
    log.info("report_cache_invalidate", ticker=ticker, removed=removed)
    return removed
