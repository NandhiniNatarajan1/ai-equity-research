"""End-to-end eval harness.

Runs each question in `questions.yaml` through the live agent + DB and asserts:
  - Non-deferred answers return >= 1 verified citation.
  - Each verified citation points to an allowed Item code (if specified).
  - The answer text contains at least one expected term (if specified).
  - Questions marked `deferred: true` must return `deferred=true`.

Skipped by default (`@pytest.mark.eval`). Run with:

    pytest -m eval -v

Requires:
  - Postgres running with the latest 10-Ks ingested for all tickers in the set.
  - ANTHROPIC_API_KEY and VOYAGE_API_KEY (or OPENAI_API_KEY) in env.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from dotenv import load_dotenv

# Load .env from the repo root so ANTHROPIC_API_KEY etc. are available even
# when running outside Docker (e.g. host venv against containerized Postgres).
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

from app.agents.citation_integrity import validate_citations  # noqa: E402
from app.agents.sec_filing_agent import run_agent  # noqa: E402
from app.db.session import session_scope  # noqa: E402

QUESTIONS_PATH = Path(__file__).parent / "questions.yaml"


def _load_cases() -> list[dict]:
    data = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))
    return data["questions"]


_cases = _load_cases()
_ids = [c["id"] for c in _cases]


@pytest.mark.eval
@pytest.mark.parametrize("case", _cases, ids=_ids)
def test_eval_question(case: dict) -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")

    state = run_agent(case["ticker"], case["question"])
    assert state.answer is not None, "agent produced no answer"
    expects = case.get("expects") or {}

    if expects.get("deferred"):
        assert state.answer.deferred, (
            f"Expected deferral for math question, got: {state.answer.answer_markdown!r}"
        )
        return

    assert not state.answer.deferred, (
        f"Agent unexpectedly deferred: {state.answer.deferral_reason!r}"
    )

    with session_scope() as db:
        result = validate_citations(db, state, state.answer)
        assert result.ok, [i.message for i in result.issues]
        assert result.verified, "expected at least one verified citation"

        allowed_sections = {s.upper() for s in expects.get("cited_sections", [])}
        if allowed_sections:
            observed = {e.section_item_code for e in result.enriched}
            assert observed & allowed_sections, (
                f"No citation hit allowed sections {sorted(allowed_sections)}; "
                f"got {sorted(observed)}"
            )

    terms = [t.lower() for t in expects.get("must_contain_any", [])]
    if terms:
        answer_l = state.answer.answer_markdown.lower()
        assert any(t in answer_l for t in terms), (
            f"Expected at least one of {terms} in answer: {state.answer.answer_markdown!r}"
        )
