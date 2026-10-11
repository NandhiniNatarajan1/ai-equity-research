"""Financial Agent (deterministic math, LLM narration only).

Shape (one LangGraph node for M2):

    START -> run_financial_tools -> narrate_metrics -> END

The agent does NO arithmetic. It:
  1. Calls `get_financial_metrics` to pull computed values from the
     deterministic Python calculators (via MCP tools).
  2. Hands the structured results to Claude purely to narrate them in a
     readable short-paragraph form.

Every numeric claim in the narration is backed by a MetricResult whose
inputs carry XBRL concept + accession + filed date, so the API layer can
publish those as "financial citations" alongside the narration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.core.logging import get_logger
from app.mcp_server.tools import get_financial_metrics

log = get_logger("agent.financial")

NARRATOR_SYSTEM = """\
You are the Financial Agent for an investment research platform. You receive
a company ticker, a user question, and a set of pre-computed financial metrics
that come from deterministic Python calculators over SEC XBRL data.

Rules:
1. You MAY NOT invent, round, or recompute numbers. Use the values from
   `metrics` exactly as given.
2. For each metric you reference, cite it by its name using a marker like
   [metric: revenue_yoy_growth]. Use ONLY metric names that appear in the
   input you were given.
3. If a metric has `error`, acknowledge the limitation ("prior-year revenue
   data unavailable" etc.) rather than making up a value.
4. Keep the response tight: 2-5 sentences, in prose, no bullet lists.
5. Return a JSON object with this shape (nothing else):
   {
     "answer_markdown": "...",
     "metric_markers": ["revenue_yoy_growth", "gross_margin", ...]
   }
"""


@dataclass
class FinancialAgentState:
    ticker: str
    question: str
    metrics: list[dict[str, Any]] = field(default_factory=list)
    entity_name: str | None = None
    answer_markdown: str | None = None
    metric_markers: list[str] = field(default_factory=list)
    error: str | None = None


def _llm() -> ChatAnthropic:
    # Narrator is a mechanical step (read structured metrics, write a short
    # paragraph) — use the fast/cheap model.
    s = get_settings()
    return ChatAnthropic(
        model=s.anthropic_fast_model,
        api_key=s.anthropic_api_key.get_secret_value(),
        max_tokens=2048,
    )


def _extract_text(content: Any) -> str:
    """Extract text from Anthropic content (handles extended-thinking lists)."""
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


def run_financial_tools(state: FinancialAgentState) -> FinancialAgentState:
    try:
        payload = get_financial_metrics(state.ticker)
    except Exception as exc:
        state.error = f"financial_tools_failed: {exc}"
        log.exception("fin_tools_failed", ticker=state.ticker, error=str(exc))
        return state
    state.metrics = payload.get("metrics", [])
    state.entity_name = payload.get("entity_name")
    log.info(
        "fin_tools_done",
        ticker=state.ticker,
        n_metrics=len(state.metrics),
        n_ok=sum(1 for m in state.metrics if m.get("error") is None),
    )
    return state


def narrate_metrics(state: FinancialAgentState) -> FinancialAgentState:
    if state.error:
        state.answer_markdown = (
            f"Unable to compute financial metrics for {state.ticker}: {state.error}"
        )
        return state

    # Give the LLM only the fields it needs; drop verbose input facts here.
    compact = [
        {
            "name": m["name"],
            "value": m["value"],
            "unit": m["unit"],
            "period_label": m["period_label"],
            "narrative": m["narrative"],
            "error": m.get("error"),
        }
        for m in state.metrics
    ]
    msgs = [
        SystemMessage(content=NARRATOR_SYSTEM),
        HumanMessage(
            content=(
                f"Ticker: {state.ticker}\n"
                f"Entity: {state.entity_name}\n"
                f"User question: {state.question}\n\n"
                f"Computed metrics (JSON):\n{json.dumps(compact, indent=2)}"
            )
        ),
    ]
    resp = _llm().invoke(msgs)
    raw = _extract_text(resp.content)
    try:
        obj = _parse_json_block(raw)
        state.answer_markdown = str(obj.get("answer_markdown", "")).strip()
        markers = obj.get("metric_markers", []) or []
        valid = {m["name"] for m in state.metrics if m.get("error") is None}
        state.metric_markers = [m for m in markers if m in valid]
    except Exception as exc:
        log.exception("narrate_parse_error", error=str(exc), raw=raw[:400])
        state.answer_markdown = f"Could not narrate metrics ({exc})."
    log.info(
        "narrate_done",
        ticker=state.ticker,
        n_markers=len(state.metric_markers),
    )
    return state


_graph = None


def build_graph() -> Any:
    graph: StateGraph = StateGraph(FinancialAgentState)
    graph.add_node("run_financial_tools", run_financial_tools)
    graph.add_node("narrate_metrics", narrate_metrics)
    graph.add_edge(START, "run_financial_tools")
    graph.add_edge("run_financial_tools", "narrate_metrics")
    graph.add_edge("narrate_metrics", END)
    return graph.compile()


def run_agent(ticker: str, question: str) -> FinancialAgentState:
    global _graph
    if _graph is None:
        _graph = build_graph()
    initial = FinancialAgentState(ticker=ticker.upper(), question=question)
    final = _graph.invoke(initial)
    if isinstance(final, dict):
        return FinancialAgentState(**final)
    return final  # type: ignore[return-value]
