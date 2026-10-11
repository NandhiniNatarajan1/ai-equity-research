"""Research orchestrator.

Routes an incoming question to one of the specialist agents based on whether
it needs computed numeric financial metrics (Financial Agent) or qualitative
disclosure text from a 10-K (SEC Filing Agent).

For M2 this is a simple binary route. M3 would extend to parallel branches
plus a merging Verification + Report Agent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents import financial_agent, sec_filing_agent
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("orchestrator")

RouteName = Literal["sec_filing", "financial"]


ROUTER_SYSTEM = """\
You classify an equity-research question into one of two routes:

  - "sec_filing":  the question is about qualitative disclosures from a 10-K
                   (business description, risks, strategy, legal, competition,
                   MD&A commentary, etc.). The answer should quote filing text.
  - "financial":   the question needs computed numeric metrics (revenue
                   growth, margins, FCF, CAGR, YoY change, ratios). The answer
                   should state exact numbers from XBRL.

Return ONLY a JSON object: {"route": "sec_filing" | "financial", "reason": "..."}
"""


# Fast keyword prefilter — avoids spending an LLM call on obviously-numeric
# questions. Order matters only for determinism.
_NUMERIC_KEYWORDS = [
    "revenue growth",
    "yoy",
    "year over year",
    "year-over-year",
    "cagr",
    "margin",
    "fcf",
    "free cash flow",
    "operating income",
    "net income",
    "earnings",
    "ratio",
    "leverage",
    "capex",
    "ebitda",
    "cash flow",
]


@dataclass(frozen=True)
class RouteDecision:
    route: RouteName
    reason: str
    source: Literal["heuristic", "llm"]


def _heuristic_route(question: str) -> RouteDecision | None:
    q = question.lower()
    for kw in _NUMERIC_KEYWORDS:
        # Word-boundary match: "ratio" must not fire inside "concentration".
        if re.search(rf"\b{re.escape(kw)}\b", q):
            return RouteDecision(route="financial", reason=f"keyword:{kw}", source="heuristic")
    # Numeric-looking phrases: "percent", "%", "$123..."
    if re.search(r"\b(percent|%|\$\d)\b", q):
        return RouteDecision(route="financial", reason="numeric phrase", source="heuristic")
    return None


def _llm_route(question: str) -> RouteDecision:
    # Router picks 1 of 2 routes — mechanical, use the cheap model.
    s = get_settings()
    llm = ChatAnthropic(
        model=s.anthropic_fast_model,
        api_key=s.anthropic_api_key.get_secret_value(),
        max_tokens=256,
    )
    resp = llm.invoke(
        [SystemMessage(content=ROUTER_SYSTEM), HumanMessage(content=f"Question: {question}")]
    )
    content = resp.content if isinstance(resp.content, str) else "".join(
        str(b.get("text", "")) if isinstance(b, dict) and b.get("type") == "text" else ""
        for b in resp.content
    )
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].strip()
    try:
        obj = json.loads(content)
        route = str(obj.get("route", "sec_filing"))
        reason = str(obj.get("reason", ""))
        if route not in ("sec_filing", "financial"):
            route = "sec_filing"
        return RouteDecision(route=route, reason=reason, source="llm")  # type: ignore[arg-type]
    except Exception as exc:
        log.warning("router_parse_fail", error=str(exc), raw=content[:200])
        return RouteDecision(route="sec_filing", reason=f"fallback:{exc}", source="llm")


def classify(question: str) -> RouteDecision:
    """Decide which agent should handle a question."""
    heuristic = _heuristic_route(question)
    if heuristic is not None:
        return heuristic
    return _llm_route(question)


@dataclass
class OrchestratorResult:
    route: RouteDecision
    sec_state: sec_filing_agent.AgentState | None = None
    fin_state: financial_agent.FinancialAgentState | None = None


def run(ticker: str, question: str) -> OrchestratorResult:
    decision = classify(question)
    log.info("orchestrator_route", ticker=ticker, route=decision.route, source=decision.source)
    if decision.route == "financial":
        return OrchestratorResult(route=decision, fin_state=financial_agent.run_agent(ticker, question))
    return OrchestratorResult(route=decision, sec_state=sec_filing_agent.run_agent(ticker, question))
