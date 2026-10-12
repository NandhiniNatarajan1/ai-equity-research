"""Risk Agent — deep structured analysis of a company's Item 1A Risk Factors.

Shape (one LangGraph flow):

    START -> fetch_risk_passages -> structure_risks -> END

Differs from the general SEC Filing Agent in that it:
  - Always targets Item 1A (with the FULL fallback for Intel-style filings).
  - Pulls more passages per theme (k=10) so the structured output can
    enumerate top risks.
  - Produces a ranked list of ThemedRisk entries, each with:
      * theme (short label)
      * summary (1-2 sentences)
      * severity ("high" | "medium" | "low") — the LLM's judgement
      * citations (chunk_id + quoted_text) — citation-integrity validated

The output is still shaped as an AgentAnswer so the API's existing citation
validator and persistence path handle it unchanged. The `answer_markdown`
is a numbered markdown list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.agents.schemas import AgentAnswer, AnswerCitation, ToolCallRecord
from app.core.config import get_settings
from app.core.logging import get_logger
from app.mcp_server.tools import search_filings

log = get_logger("agent.risk")


# Themes commonly disclosed by hardware / semiconductor issuers. 5 broad
# themes give decent coverage; adding more just inflates input tokens.
# Callers who need deeper coverage can run the agent with the full question
# flow instead.
RISK_THEMES: list[tuple[str, str]] = [
    ("Supply chain / foundry concentration", "foundry concentration Taiwan TSMC single-source wafer manufacturing capacity"),
    ("Customer concentration", "customer concentration dependence on a limited number of customers major OEMs cloud service providers"),
    ("Export controls / geopolitical", "U.S. export controls restrictions China license requirements semiconductor technology"),
    ("Competition / product transition", "intense competition larger competitors custom silicon product transition new process nodes execution risk"),
    ("Macro / cyclicality / legal", "cyclical semiconductor demand macroeconomic downturn inventory correction intellectual property litigation"),
]

RISK_SYSTEM = """\
You synthesize a structured risk analysis for an investment research report,
grounded ONLY in the retrieved passages provided to you.

Rules:
1. Produce 3-5 ranked risk themes, highest severity first. Each theme must be
   backed by at least ONE citation into the retrieved passages.
2. Every citation must use a chunk_id that appears in the retrieved passages.
3. Quote the passage verbatim (<= 240 characters) in each citation's
   "quoted_text" so a reviewer can locate the exact phrase.
4. severity is one of "high" | "medium" | "low" — your judgement based on
   how prominently the 10-K discusses the risk and whether it discloses a
   concrete adverse impact (dollar amount, specific jurisdiction, loss of
   access, etc.).
5. Do NOT invent risks that are not present in the retrieved passages. If a
   theme has no evidence, omit it (do not pad to 7).

Return a single JSON object:
{
  "risks": [
    {
      "theme": "<short label>",
      "summary": "<1-2 sentence summary of the risk and its disclosed impact>",
      "severity": "high" | "medium" | "low",
      "citations": [
        {"marker": "[1]", "chunk_id": "<uuid>", "quoted_text": "..."}
      ]
    }
  ]
}
Markers in each theme's citations are LOCAL to that theme ([1], [2], ...).
Output only valid JSON. No commentary before or after.
"""


@dataclass
class RiskAgentState:
    ticker: str
    question: str
    retrieved: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    answer: AgentAnswer | None = None


def _llm() -> ChatAnthropic:
    # Risk ranking only needs coarse high/medium/low severity labels and
    # structured JSON — Haiku handles both cleanly and costs ~3x less than
    # Sonnet. 4096 tokens matches other composers; 3072 was clipping the
    # structured JSON mid-string for 5-theme outputs with multiple citations.
    s = get_settings()
    return ChatAnthropic(
        model=s.anthropic_fast_model,
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


def fetch_risk_passages(state: RiskAgentState) -> RiskAgentState:
    """Scan each known risk theme to ensure broad coverage; dedup by chunk_id."""
    seen: dict[str, dict[str, Any]] = {}
    for _, query in RISK_THEMES:
        # 5 themes × k=2 ≈ 10 chunks after dedup. Enough to ground a ranked
        # risk list; smaller k keeps input tokens down.
        results = search_filings(state.ticker, query, k=2, item_codes=["1A"])
        chunk_ids = [r["chunk_id"] for r in results]
        state.tool_calls.append(
            ToolCallRecord(
                tool="search_filings",
                arguments={"ticker": state.ticker, "query": query, "item_codes": ["1A"]},
                returned_chunk_ids=chunk_ids,
            )
        )
        for r in results:
            seen.setdefault(r["chunk_id"], r)
    state.retrieved = list(seen.values())
    log.info("risk_fetch_done", ticker=state.ticker, n_chunks=len(state.retrieved))
    return state


def _format_passages_for_llm(retrieved: list[dict[str, Any]]) -> str:
    lines = []
    for i, r in enumerate(retrieved, start=1):
        lines.append(
            f"Passage {i}  |  chunk_id={r['chunk_id']}  "
            f"|  Item {r['section_item_code']} — {r['section_title']}"
        )
        lines.append(r["text"])
        lines.append("")
    return "\n".join(lines)


def structure_risks(state: RiskAgentState) -> RiskAgentState:
    if not state.retrieved:
        state.answer = AgentAnswer(
            answer_markdown="No Item 1A passages were retrieved.",
            citations=[],
            deferred=True,
            deferral_reason="empty_retrieval",
        )
        return state

    passages = _format_passages_for_llm(state.retrieved)
    msgs = [
        SystemMessage(content=RISK_SYSTEM),
        HumanMessage(
            content=(
                f"Ticker: {state.ticker}\n"
                f"User question: {state.question}\n\n"
                f"Retrieved Item 1A passages:\n\n{passages}"
            )
        ),
    ]
    resp = _llm().invoke(msgs)
    raw = _extract_text(resp.content)
    try:
        obj = _parse_json_block(raw)
        risks = obj.get("risks", []) or []
    except Exception as exc:
        log.exception("risk_parse_error", error=str(exc), raw=raw[:400])
        state.answer = AgentAnswer(
            answer_markdown=f"Could not parse structured risks ({exc}).",
            citations=[],
            deferred=True,
            deferral_reason=f"parse_error: {exc}",
        )
        return state

    # Convert into a flat markdown narrative + global list of citations.
    # Each theme's local [n] markers get rewritten to globally-unique [N].
    md_parts: list[str] = []
    all_citations: list[AnswerCitation] = []
    global_idx = 0
    for risk in risks:
        theme = str(risk.get("theme", "")).strip()
        summary = str(risk.get("summary", "")).strip()
        severity = str(risk.get("severity", "")).strip().lower()
        if not theme or not summary:
            continue
        local_cits = risk.get("citations", []) or []
        global_markers: list[str] = []
        for c in local_cits:
            global_idx += 1
            marker = f"[{global_idx}]"
            try:
                all_citations.append(
                    AnswerCitation(
                        marker=marker,
                        chunk_id=str(c.get("chunk_id")),
                        quoted_text=str(c.get("quoted_text", "")),
                    )
                )
                global_markers.append(marker)
            except Exception as exc:
                log.warning("risk_bad_citation", error=str(exc), citation=c)
        sev_badge = {"high": "**HIGH**", "medium": "medium", "low": "low"}.get(severity, severity)
        marker_str = " ".join(global_markers)
        md_parts.append(f"- **{theme}** ({sev_badge}): {summary} {marker_str}".strip())

    md = "\n".join(md_parts) if md_parts else "No structured risks parsed."
    state.answer = AgentAnswer(
        answer_markdown=md,
        citations=all_citations,
        deferred=False,
        deferral_reason=None,
    )
    log.info(
        "risk_compose_done",
        ticker=state.ticker,
        n_risks=len(risks),
        n_citations=len(all_citations),
    )
    return state


_graph = None


def build_graph() -> Any:
    graph: StateGraph = StateGraph(RiskAgentState)
    graph.add_node("fetch_risk_passages", fetch_risk_passages)
    graph.add_node("structure_risks", structure_risks)
    graph.add_edge(START, "fetch_risk_passages")
    graph.add_edge("fetch_risk_passages", "structure_risks")
    graph.add_edge("structure_risks", END)
    return graph.compile()


def run_agent(ticker: str, question: str) -> RiskAgentState:
    global _graph
    if _graph is None:
        _graph = build_graph()
    initial = RiskAgentState(ticker=ticker.upper(), question=question)
    final = _graph.invoke(initial)
    if isinstance(final, dict):
        return RiskAgentState(
            ticker=final.get("ticker", ticker.upper()),
            question=final.get("question", question),
            retrieved=final.get("retrieved", []),
            tool_calls=final.get("tool_calls", []),
            answer=final.get("answer"),
        )
    return final  # type: ignore[return-value]
