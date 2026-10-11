"""Competitor Agent — runs the same question across the MVP peer set.

For each peer ticker, we invoke the SEC Filing Agent and collect its answer +
citations. Then a cross-company comparator LLM produces a side-by-side summary
grounded in those answers (no new citations fabricated — references the
per-ticker citations by their original marker prefixed with the ticker).

For M3, the peer set is hardcoded to NVDA/AMD/INTC (seeded in the DB). A
later milestone would resolve peers dynamically from SIC + XBRL metadata.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.schemas import AgentAnswer, AnswerCitation, ToolCallRecord
from app.agents.sec_filing_agent import AgentState as SecState
from app.agents.sec_filing_agent import run_agent as run_sec_filing_agent
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("agent.competitor")

# Default peer set for the MVP. Callers can override via the `peers` kwarg
# on run_agent (e.g. from `/research/report/{ticker}?peers=NVDA,AMD`).
DEFAULT_PEERS: list[str] = ["NVDA", "AMD", "INTC"]


COMPARATOR_SYSTEM = """\
You produce a cross-company comparison for an investment research report,
using ONLY the per-company answers and their citations provided to you.

Rules:
1. Compare and contrast how each company addresses the question. 2-4 short
   paragraphs or a bulleted comparison, your choice based on the question.
2. When you reference a company-specific fact, cite it using the ORIGINAL
   citation marker from that company's answer, prefixed by the ticker:
      e.g. "NVDA cites $4.5B export-control inventory charge (NVDA [1])"
3. Do NOT invent new facts or alter the per-company narratives.
4. If a company's agent deferred or returned no useful answer, say so and
   explain the gap rather than filling it with speculation.

Return a single JSON object:
{
  "comparison_markdown": "..."
}
Output only valid JSON.
"""


@dataclass
class PeerAnswer:
    ticker: str
    sec_state: SecState


@dataclass
class CompetitorAgentState:
    anchor_ticker: str
    question: str
    peer_tickers: list[str] = field(default_factory=list)
    peer_answers: list[PeerAnswer] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    answer: AgentAnswer | None = None


def _llm() -> ChatAnthropic:
    # Comparator summarizes 3 pre-made peer answers — mechanical step, use
    # the fast/cheap model.
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


def _per_company_section(pa: PeerAnswer) -> str:
    ans = pa.sec_state.answer
    if ans is None:
        return f"### {pa.ticker}\n(no answer)\n"
    cite_lines = [
        f"  {c.marker} {c.quoted_text[:200]}"
        for c in ans.citations
    ]
    return (
        f"### {pa.ticker}\n"
        f"{ans.answer_markdown}\n\n"
        f"Citations:\n" + ("\n".join(cite_lines) if cite_lines else "  (none)")
        + "\n"
    )


def _run_peer(ticker: str, question: str) -> PeerAnswer:
    log.info("competitor_peer_start", peer=ticker)
    state = run_sec_filing_agent(ticker, question)
    return PeerAnswer(ticker=ticker, sec_state=state)


def run_agent(
    ticker: str,
    question: str,
    *,
    peers: list[str] | None = None,
) -> CompetitorAgentState:
    anchor = ticker.upper()
    # Normalize peer list: strip blanks, uppercase, dedupe while preserving order,
    # and ensure the anchor ticker is included so the user sees their own company
    # in the comparison.
    raw = peers if peers is not None else DEFAULT_PEERS
    seen: set[str] = set()
    chosen: list[str] = []
    for t in [*raw, anchor]:
        if not t:
            continue
        t = t.upper().strip()
        if t and t not in seen:
            seen.add(t)
            chosen.append(t)
    state = CompetitorAgentState(
        anchor_ticker=anchor, question=question, peer_tickers=chosen
    )

    for peer in chosen:
        try:
            pa = _run_peer(peer, question)
            state.peer_answers.append(pa)
            # Fold the peer agent's tool_calls into our aggregate so citation
            # integrity across peers can be enforced by the API layer later
            # (markers are rewritten peer-prefixed, so uniqueness is preserved).
            for tc in pa.sec_state.tool_calls:
                state.tool_calls.append(
                    ToolCallRecord(
                        tool=tc.tool,
                        arguments={**tc.arguments, "_peer": peer},
                        returned_chunk_ids=tc.returned_chunk_ids,
                    )
                )
        except Exception as exc:
            log.exception("competitor_peer_failed", peer=peer, error=str(exc))

    # ---- cross-company narrative ------------------------------------------
    peer_sections = "\n".join(_per_company_section(pa) for pa in state.peer_answers)
    msgs = [
        SystemMessage(content=COMPARATOR_SYSTEM),
        HumanMessage(
            content=(
                f"Anchor ticker: {anchor}\n"
                f"Question: {question}\n\n"
                f"Per-company answers:\n\n{peer_sections}"
            )
        ),
    ]
    resp = _llm().invoke(msgs)
    raw = _extract_text(resp.content)
    try:
        obj = _parse_json_block(raw)
        md = str(obj.get("comparison_markdown", "")).strip()
    except Exception as exc:
        log.exception("competitor_parse_error", error=str(exc), raw=raw[:400])
        md = raw.strip()  # last-ditch: show the raw output rather than nothing

    # Flatten per-peer citations into a global list, with peer-prefixed markers
    # so the API can render + validate them uniformly.
    all_citations: list[AnswerCitation] = []
    for pa in state.peer_answers:
        if pa.sec_state.answer is None:
            continue
        for c in pa.sec_state.answer.citations:
            all_citations.append(
                AnswerCitation(
                    marker=f"{pa.ticker} {c.marker}",
                    chunk_id=c.chunk_id,
                    quoted_text=c.quoted_text,
                )
            )

    state.answer = AgentAnswer(
        answer_markdown=md or "No comparison produced.",
        citations=all_citations,
        deferred=False,
        deferral_reason=None,
    )
    log.info(
        "competitor_done",
        anchor=anchor,
        n_peers=len(state.peer_answers),
        n_citations=len(all_citations),
    )
    return state
