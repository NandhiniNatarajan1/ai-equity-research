"""Verification + Report Agent — fan out to specialists, merge into one report.

Composition strategy:

    START -> fan_out (parallel invocations of specialist agents)
          -> compose_report (LLM structures everything into one report)
          -> verify (citation integrity, metric sanity) -> END

Specialists invoked (all for a single ticker):
  - SEC Filing Agent: Business overview question ("Describe the company's
    business and strategy")
  - Risk Agent: ranked themed risks over Item 1A
  - Financial Agent: deterministic metrics (growth, margins, FCF)
  - Competitor Agent: cross-peer comparison on business/strategy

The composer writes a structured report with these sections:
  1. Executive Summary
  2. Business Snapshot (with SEC Filing citations)
  3. Financial Highlights (with Financial metrics)
  4. Material Risks (with Risk citations)
  5. Competitive Position (with Competitor citations)
  6. Sources

No LLM arithmetic — numbers come from the Financial Agent's deterministic
calculators and are carried through verbatim.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
from dataclasses import dataclass, field
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents import competitor_agent, financial_agent, risk_agent, sec_filing_agent
from app.agents.schemas import AgentAnswer, AnswerCitation
from app.core.config import get_settings
from app.core.logging import get_logger
from app.financial_tools.history import HistorySeries, multi_year
from app.financial_tools.price_history import PriceSnapshot, fetch_price_snapshot
from app.financial_tools.xbrl_client import XbrlClient
from app.mcp_server.tools import _company_cik  # type: ignore[attr-defined]

log = get_logger("agent.report")


COMPOSER_SYSTEM = """\
You are the Verification + Report Agent. You produce a structured investment
research report by MERGING outputs from four specialist agents. You NEVER
invent facts; everything you say must come from the inputs provided.

Section layout (produce each section as markdown, in this order):

  ## Executive Summary
  2-4 sentences. The most important takeaways from the other sections.
  Reference specific metrics using [metric: name] markers that already appear
  in the Financial Highlights section (or omit markers if none fit).

  ## Business Snapshot
  Rewrite the SEC Filing agent's business-overview answer tightly. Preserve
  its [n] citation markers verbatim — the API carries them through.

  ## Financial Highlights
  Rewrite the Financial agent's narration tightly. Preserve its
  [metric: name] markers verbatim.

  ## Material Risks
  Rewrite the Risk agent's ranked themes tightly. Preserve its [n] markers
  (they are globally unique across the risk section).

  ## Competitive Position
  Rewrite the Competitor agent's comparison tightly. Preserve its
  TICKER [n] markers verbatim.

Rules:
- Do NOT add any new numbers, percentages, or citations beyond what each
  specialist supplied.
- If a section's specialist produced no output or errored, write a single
  line like "_No material competitive-position disclosures found in the
  retrieved passages._" and move on.
- Keep the final report under ~700 words.

Return a single JSON object:
{
  "report_markdown": "..."
}
Output only valid JSON.
"""


BUSINESS_OVERVIEW_QUESTION = (
    "Summarize the company's business, product lines, go-to-market, and strategy "
    "in 3-5 sentences, grounded in its most recent 10-K."
)

FINANCIAL_HIGHLIGHTS_QUESTION = (
    "Report the company's most recent fiscal year revenue growth, gross margin, "
    "operating margin, and free cash flow."
)

RISK_QUESTION = (
    "What are the most material risk factors disclosed in the company's most "
    "recent 10-K Item 1A?"
)

COMPETITOR_QUESTION = (
    "How does the company describe its competitive position and its products "
    "relative to peers in its most recent 10-K?"
)


@dataclass
class SpecialistOutputs:
    business: sec_filing_agent.AgentState | None = None
    financial: financial_agent.FinancialAgentState | None = None
    risk: risk_agent.RiskAgentState | None = None
    competitor: competitor_agent.CompetitorAgentState | None = None
    # Non-LLM additions (M4):
    price: PriceSnapshot | None = None
    history: dict[str, HistorySeries] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass
class ReportResult:
    ticker: str
    report_markdown: str
    specialists: SpecialistOutputs
    all_citations: list[AnswerCitation]
    financial_metrics: list[dict[str, Any]]  # name -> {value, unit, ...} as dict


def _llm() -> ChatAnthropic:
    s = get_settings()
    return ChatAnthropic(
        model=s.anthropic_model,
        api_key=s.anthropic_api_key.get_secret_value(),
        max_tokens=4096,
    )


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(b.get("text", "")) if isinstance(b, dict) and b.get("type") == "text" else ""
            for b in content
        )
    return str(content)


def _parse_json_block(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[start : i + 1])
        raise


def _fetch_history(ticker: str) -> dict[str, HistorySeries]:
    cik, _ = _company_cik(ticker)
    with XbrlClient() as xc:
        facts = xc.fetch(cik)
    return multi_year(facts, years=5)


def _fan_out(ticker: str, *, peers: list[str] | None = None) -> SpecialistOutputs:
    out = SpecialistOutputs()
    # Fan out in parallel; each specialist does its own LLM calls so this
    # overlaps network waits across providers. The two non-LLM tasks
    # (price snapshot, 5Y XBRL history) run alongside at zero LLM cost.
    with cf.ThreadPoolExecutor(max_workers=6, thread_name_prefix="report") as pool:
        futures: dict[str, cf.Future] = {
            "business": pool.submit(sec_filing_agent.run_agent, ticker, BUSINESS_OVERVIEW_QUESTION),
            "financial": pool.submit(financial_agent.run_agent, ticker, FINANCIAL_HIGHLIGHTS_QUESTION),
            "risk": pool.submit(risk_agent.run_agent, ticker, RISK_QUESTION),
            "competitor": pool.submit(
                competitor_agent.run_agent, ticker, COMPETITOR_QUESTION, peers=peers
            ),
            "price": pool.submit(fetch_price_snapshot, ticker),
            "history": pool.submit(_fetch_history, ticker),
        }
        for name, fut in futures.items():
            try:
                setattr(out, name, fut.result())
            except Exception as exc:
                log.exception("specialist_failed", specialist=name, ticker=ticker, error=str(exc))
                out.errors[name] = str(exc)
    return out


def _specialist_text_for_composer(outs: SpecialistOutputs) -> str:
    parts: list[str] = []

    # Business
    if outs.business and outs.business.answer:
        parts.append("### Business (SEC Filing Agent):")
        parts.append(outs.business.answer.answer_markdown)
        for c in outs.business.answer.citations:
            parts.append(f"  {c.marker}: {c.quoted_text[:200]}")
    else:
        parts.append(f"### Business: unavailable ({outs.errors.get('business', 'none')})")
    parts.append("")

    # Financial
    if outs.financial:
        parts.append("### Financials (Financial Agent):")
        parts.append(outs.financial.answer_markdown or "(no narration)")
        for m in outs.financial.metrics:
            parts.append(
                f"  [metric: {m['name']}] value={m['value']} {m['unit']} "
                f"period={m['period_label']} err={m.get('error') or 'none'}"
            )
    else:
        parts.append(f"### Financials: unavailable ({outs.errors.get('financial', 'none')})")
    parts.append("")

    # Risk
    if outs.risk and outs.risk.answer:
        parts.append("### Risks (Risk Agent):")
        parts.append(outs.risk.answer.answer_markdown)
        for c in outs.risk.answer.citations:
            parts.append(f"  {c.marker}: {c.quoted_text[:200]}")
    else:
        parts.append(f"### Risks: unavailable ({outs.errors.get('risk', 'none')})")
    parts.append("")

    # Competitor
    if outs.competitor and outs.competitor.answer:
        parts.append("### Competitors (Competitor Agent):")
        parts.append(outs.competitor.answer.answer_markdown)
        for c in outs.competitor.answer.citations:
            parts.append(f"  {c.marker}: {c.quoted_text[:200]}")
    else:
        parts.append(f"### Competitors: unavailable ({outs.errors.get('competitor', 'none')})")
    parts.append("")

    return "\n".join(parts)


def _collect_all_citations(outs: SpecialistOutputs) -> list[AnswerCitation]:
    """Flatten every verified textual citation from the specialists."""
    all_cits: list[AnswerCitation] = []
    for state in [outs.business, outs.risk, outs.competitor]:
        if state and state.answer:
            all_cits.extend(state.answer.citations)
    return all_cits


def _collect_metrics(outs: SpecialistOutputs) -> list[dict[str, Any]]:
    if outs.financial is None:
        return []
    cited_names = set(outs.financial.metric_markers)
    return [
        m for m in outs.financial.metrics
        if m["name"] in cited_names and not m.get("error")
    ]


def generate_report(ticker: str, *, peers: list[str] | None = None) -> ReportResult:
    ticker = ticker.upper()
    log.info("report_start", ticker=ticker, peers=peers)
    outs = _fan_out(ticker, peers=peers)

    specialist_blob = _specialist_text_for_composer(outs)
    msgs = [
        SystemMessage(content=COMPOSER_SYSTEM),
        HumanMessage(
            content=(
                f"Ticker: {ticker}\n\n"
                f"Specialist outputs:\n\n{specialist_blob}"
            )
        ),
    ]
    resp = _llm().invoke(msgs)
    raw = _extract_text(resp.content)
    try:
        obj = _parse_json_block(raw)
        report_md = str(obj.get("report_markdown", "")).strip()
    except Exception as exc:
        log.exception("report_parse_error", error=str(exc), raw=raw[:400])
        report_md = raw.strip()

    all_citations = _collect_all_citations(outs)
    metrics = _collect_metrics(outs)
    log.info(
        "report_done",
        ticker=ticker,
        n_citations=len(all_citations),
        n_metrics=len(metrics),
        errors=list(outs.errors),
    )
    return ReportResult(
        ticker=ticker,
        report_markdown=report_md,
        specialists=outs,
        all_citations=all_citations,
        financial_metrics=metrics,
    )
