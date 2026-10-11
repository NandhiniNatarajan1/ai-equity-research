"""End-to-end eval harness driving the Orchestrator.

Runs each question in `questions.yaml` through the full orchestrator:
  - router classifies the question
  - either SEC Filing Agent or Financial Agent runs
  - we assert the right route was taken, citations are integrity-verified
    (SEC filing route), or metrics are present (financial route)

Skipped by default (`@pytest.mark.eval`). Run with:

    pytest -m eval -v

Requires:
  - Postgres running with 10-Ks ingested for all tickers in the set.
  - ANTHROPIC_API_KEY and VOYAGE_API_KEY (or OPENAI_API_KEY) in env.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

from app.agents.citation_integrity import validate_citations  # noqa: E402
from app.agents.orchestrator import run as orchestrator_run  # noqa: E402
from app.db.session import session_scope  # noqa: E402

QUESTIONS_PATH = Path(__file__).parent / "questions.yaml"


def _load_cases() -> list[dict]:
    return yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]


_cases = _load_cases()
_ids = [c["id"] for c in _cases]


@pytest.mark.eval
@pytest.mark.parametrize("case", _cases, ids=_ids)
def test_eval_question(case: dict) -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")

    expects = case.get("expects") or {}
    expected_route = expects.get("route", "sec_filing")

    result = orchestrator_run(case["ticker"], case["question"])
    assert result.route.route == expected_route, (
        f"Expected route={expected_route}, got {result.route.route} "
        f"(reason={result.route.reason!r})"
    )

    # ---------- SEC Filing route ----------
    if expected_route == "sec_filing":
        state = result.sec_state
        assert state is not None and state.answer is not None
        if expects.get("deferred"):
            assert state.answer.deferred, f"Expected deferral: {state.answer.answer_markdown!r}"
            return
        with session_scope() as db:
            v = validate_citations(db, state, state.answer)
            assert v.ok, [i.message for i in v.issues]
            # "Partial deferral" is OK provided the agent still produced
            # citation-backed content; a hard failure is deferred=true AND
            # zero citations, which means the agent gave up entirely.
            if state.answer.deferred:
                assert v.verified, (
                    f"Agent deferred with no citations: {state.answer.deferral_reason!r}"
                )
            else:
                assert v.verified, "expected at least one verified citation"
            allowed = {s.upper() for s in expects.get("cited_sections", [])}
            if allowed:
                observed = {e.section_item_code for e in v.enriched}
                assert observed & allowed, (
                    f"No citation hit allowed sections {sorted(allowed)}; got {sorted(observed)}"
                )
        _assert_contains_any(state.answer.answer_markdown, expects)
        return

    # ---------- Financial route ----------
    fin = result.fin_state
    assert fin is not None
    assert fin.error is None, f"Financial agent errored: {fin.error}"
    assert fin.answer_markdown, "no narration from financial agent"

    cited_names = set(fin.metric_markers)
    expected_metrics = {m for m in expects.get("metrics_any", []) if m}
    if expected_metrics:
        assert cited_names & expected_metrics, (
            f"None of expected metrics {sorted(expected_metrics)} were cited; "
            f"got {sorted(cited_names)}"
        )

    _assert_contains_any(fin.answer_markdown, expects)


def _assert_contains_any(text: str, expects: dict) -> None:
    terms = [t.lower() for t in expects.get("must_contain_any", [])]
    if not terms:
        return
    low = text.lower()
    assert any(t in low for t in terms), (
        f"Expected at least one of {terms} in answer: {text!r}"
    )
