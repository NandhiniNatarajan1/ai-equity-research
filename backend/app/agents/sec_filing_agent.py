"""SEC Filing Agent (LangGraph).

Milestone 1 shape:

    START -> plan_retrieval -> run_retrieval -> compose_answer -> END

- `plan_retrieval` asks Claude to propose up to 3 search queries + optional
  section filters, given the user's question. Deterministic Python, no citing.
- `run_retrieval` invokes the same functions the MCP server exposes
  (`search_filings` / `get_filing_section`). Every returned chunk is recorded
  in `state.tool_calls` so the citation-integrity validator in the API layer
  can intersect claimed citations with retrieved ones.
- `compose_answer` asks Claude to write a cited answer, constrained to the
  retrieved passages. It must either (a) answer with citations into those
  passages, or (b) defer if the question requires computed financial math.

This structure is intentionally designed so additional agents (Financial,
Risk, Competitor, Report) can be added as parallel nodes in a future graph
that reuses `run_retrieval` as a shared sub-component.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.agents.schemas import AgentAnswer, AnswerCitation, ToolCallRecord
from app.core.config import get_settings
from app.core.logging import get_logger
from app.mcp_server.tools import get_filing_section, search_filings

log = get_logger("agent.sec_filing")

RETRIEVAL_PLANNER_SYSTEM = """\
You plan retrieval over a single company's most recent 10-K filing.

Return a JSON object with a single key "queries": a list of 1-3 objects, each
with:
  - "query":       a focused search string (12-25 words), rephrasing a sub-aspect
                   of the user's question in terms you would expect to find in
                   10-K prose.
  - "item_codes":  optional list of 10-K Item codes to restrict to, written as
                   BARE codes without the word "Item" (e.g. "1A", "7", "7A").
                   Use when the question is clearly scoped to a specific section:
                     "1"   -> company overview, products, strategy
                     "1A"  -> risk factors
                     "7"   -> MD&A (management's discussion)
                     "8"   -> financial statements and notes
                   Leave empty (omit or []) if the question could span multiple
                   sections — some filings parse as a single pseudo-section
                   named "FULL" and only an empty filter will reach them.

Output only valid JSON. No commentary.
"""

ANSWER_SYSTEM = """\
You are the SEC Filing Agent for an investment research platform. You answer
questions about a company's most recent 10-K using ONLY the retrieved passages
provided to you.

Rules:
1. Every factual claim you make MUST cite one of the retrieved passages using a
   marker of the form [1], [2], [3] matching the "marker" field of the citations
   you emit. Do not include claims that are not covered by a passage.
2. Quote the passage verbatim (<= 240 characters) in each citation's
   "quoted_text" so a reviewer can locate it. Trim leading/trailing whitespace.
3. If the question asks you to COMPUTE a financial ratio (margin, growth rate,
   leverage, FCF, etc.), do NOT compute it. Instead return deferred=true and
   set deferral_reason explaining that the Financial Agent (Milestone 2) will
   handle it. You MAY still cite what the 10-K says qualitatively.
4. If the retrieved passages are insufficient to answer, say so briefly and
   defer; do not speculate.
5. Keep the answer tight. 2-6 sentences for most questions, more only if the
   question explicitly asks for a comprehensive summary.

Return a JSON object matching this exact shape:
{
  "answer_markdown": "...",
  "citations": [
    {"marker": "[1]", "chunk_id": "<uuid>", "quoted_text": "..."},
    ...
  ],
  "deferred": false,
  "deferral_reason": null
}
Output only valid JSON. No commentary before or after.
"""


@dataclass
class AgentState:
    ticker: str
    question: str
    plan: dict[str, Any] = field(default_factory=dict)
    retrieved: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    answer: AgentAnswer | None = None
    # When true, use the cheap model for the composer step too. Set by the
    # Competitor Agent for its per-peer runs — the final cross-peer narrative
    # is still composed by Sonnet, so the per-peer summaries don't need it.
    fast_composer: bool = False


def _llm(model: str | None = None, *, max_tokens: int = 4096) -> ChatAnthropic:
    s = get_settings()
    # NOTE: claude-sonnet-5-5 does not accept a non-default temperature;
    # we deliberately omit it rather than hardcoding a value.
    return ChatAnthropic(
        model=model or s.anthropic_model,
        api_key=s.anthropic_api_key.get_secret_value(),
        # Composer needs headroom for multi-citation JSON (quoted spans + markdown).
        # 2048 was clipping mid-string on 5-citation answers.
        max_tokens=max_tokens,
    )


def _fast_llm(max_tokens: int = 1024) -> ChatAnthropic:
    """Cheaper/faster model for mechanical steps (planner, router)."""
    return _llm(model=get_settings().anthropic_fast_model, max_tokens=max_tokens)


def _extract_text(content: Any) -> str:
    """Normalize Anthropic response content to a plain string.

    `claude-sonnet-5-5` returns a list of content blocks (thinking + text + ...)
    when extended thinking is on. We keep only the text blocks.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _parse_json_block(text: str) -> dict[str, Any]:
    """Tolerant JSON extraction: handles bare JSON, fenced blocks, or JSON embedded
    in surrounding prose. Falls back to extracting the first balanced {...} span.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to locate the first balanced JSON object in the text.
        start = text.find("{")
        if start == -1:
            raise
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


def plan_retrieval(state: AgentState) -> AgentState:
    # Planner is a mechanical step (produce 3 queries) — use the cheaper model.
    llm = _fast_llm(max_tokens=1024)
    msgs = [
        SystemMessage(content=RETRIEVAL_PLANNER_SYSTEM),
        HumanMessage(
            content=f"Ticker: {state.ticker}\nQuestion: {state.question}\n"
        ),
    ]
    resp = llm.invoke(msgs)
    plan = _parse_json_block(_extract_text(resp.content))
    queries = plan.get("queries") or []
    if not isinstance(queries, list) or not queries:
        queries = [{"query": state.question, "item_codes": []}]
    state.plan = {"queries": queries[:3]}
    log.info("plan_retrieval", ticker=state.ticker, n_queries=len(state.plan["queries"]))
    return state


def run_retrieval(state: AgentState) -> AgentState:
    seen: dict[str, dict[str, Any]] = {}
    for q in state.plan.get("queries", []):
        query = str(q.get("query") or state.question)
        item_codes = q.get("item_codes") or None
        # k=4 keeps composer input around ~3-4k tokens of passages instead of
        # ~6k with k=6; 3 queries still give good recall after dedup.
        results = search_filings(
            state.ticker, query, k=4, item_codes=item_codes if item_codes else None
        )
        chunk_ids = [r["chunk_id"] for r in results]
        state.tool_calls.append(
            ToolCallRecord(
                tool="search_filings",
                arguments={"ticker": state.ticker, "query": query, "item_codes": item_codes},
                returned_chunk_ids=chunk_ids,
            )
        )
        for r in results:
            seen.setdefault(r["chunk_id"], r)

    state.retrieved = list(seen.values())
    log.info(
        "run_retrieval",
        ticker=state.ticker,
        n_queries=len(state.plan.get("queries", [])),
        n_unique_chunks=len(state.retrieved),
    )
    return state


def _format_passages_for_llm(retrieved: list[dict[str, Any]]) -> str:
    """Serialize retrieved chunks for the answer prompt."""
    lines = []
    for i, r in enumerate(retrieved, start=1):
        header = (
            f"Passage {i}  |  chunk_id={r['chunk_id']}  "
            f"|  Item {r['section_item_code']} — {r['section_title']}  "
            f"|  {r['filing_form_type']} {r['filing_date']}"
        )
        lines.append(header)
        lines.append(r["text"])
        lines.append("")
    return "\n".join(lines)


def compose_answer(state: AgentState) -> AgentState:
    # Use Haiku for peer-level composer runs (Competitor Agent sets fast_composer).
    # The final cross-peer narrative is still Sonnet. 4096 tokens matches the
    # Sonnet composer and is still much cheaper per call than Sonnet; 2048 and
    # 3072 were both clipping mid-string on multi-citation JSON output.
    llm = _fast_llm(max_tokens=4096) if state.fast_composer else _llm()
    passages = _format_passages_for_llm(state.retrieved)
    if not state.retrieved:
        state.answer = AgentAnswer(
            answer_markdown=(
                "No passages were retrieved from the ingested 10-K. "
                "Try rephrasing the question or ingesting a newer filing."
            ),
            citations=[],
            deferred=True,
            deferral_reason="empty_retrieval",
        )
        return state

    msgs = [
        SystemMessage(content=ANSWER_SYSTEM),
        HumanMessage(
            content=(
                f"Company ticker: {state.ticker}\n"
                f"Question: {state.question}\n\n"
                f"Retrieved passages (use ONLY these):\n\n{passages}"
            )
        ),
    ]
    resp = llm.invoke(msgs)
    raw = _extract_text(resp.content)
    try:
        obj = _parse_json_block(raw)
        answer = AgentAnswer(
            answer_markdown=str(obj.get("answer_markdown", "")).strip(),
            citations=[AnswerCitation(**c) for c in obj.get("citations", []) or []],
            deferred=bool(obj.get("deferred", False)),
            deferral_reason=obj.get("deferral_reason"),
        )
    except Exception as exc:
        log.exception("compose_answer_parse_error", error=str(exc), raw=raw[:500])
        answer = AgentAnswer(
            answer_markdown="The agent response could not be parsed as JSON.",
            citations=[],
            deferred=True,
            deferral_reason=f"parse_error: {exc}",
        )
    state.answer = answer
    log.info(
        "compose_answer",
        ticker=state.ticker,
        n_citations=len(answer.citations),
        deferred=answer.deferred,
    )
    return state


def build_graph() -> Any:
    graph: StateGraph = StateGraph(AgentState)
    graph.add_node("plan_retrieval", plan_retrieval)
    graph.add_node("run_retrieval", run_retrieval)
    graph.add_node("compose_answer", compose_answer)
    graph.add_edge(START, "plan_retrieval")
    graph.add_edge("plan_retrieval", "run_retrieval")
    graph.add_edge("run_retrieval", "compose_answer")
    graph.add_edge("compose_answer", END)
    return graph.compile()


_graph = None


def run_agent(ticker: str, question: str, *, fast_composer: bool = False) -> AgentState:
    global _graph
    if _graph is None:
        _graph = build_graph()
    initial = AgentState(ticker=ticker.upper(), question=question, fast_composer=fast_composer)
    final = _graph.invoke(initial)
    # LangGraph may return a dict-like view; coerce back to AgentState.
    if isinstance(final, dict):
        return AgentState(
            ticker=final.get("ticker", ticker.upper()),
            question=final.get("question", question),
            plan=final.get("plan", {}),
            retrieved=final.get("retrieved", []),
            tool_calls=final.get("tool_calls", []),
            answer=final.get("answer"),
            fast_composer=final.get("fast_composer", fast_composer),
        )
    return final  # type: ignore[return-value]
