"""Report cache round-trip test (no LLM calls)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.agents import report_cache
from app.agents.competitor_agent import CompetitorAgentState
from app.agents.financial_agent import FinancialAgentState
from app.agents.report_agent import ReportResult, SpecialistOutputs
from app.agents.risk_agent import RiskAgentState
from app.agents.schemas import AgentAnswer, AnswerCitation
from app.agents.sec_filing_agent import AgentState as SecState


def _mk_result(ticker: str) -> ReportResult:
    biz = SecState(ticker=ticker, question="biz?")
    biz.answer = AgentAnswer(
        answer_markdown=f"{ticker} is a company [1].",
        citations=[AnswerCitation(marker="[1]", chunk_id="aa-bb", quoted_text="is a company")],
    )
    risk = RiskAgentState(ticker=ticker, question="risks?")
    risk.answer = AgentAnswer(
        answer_markdown="- **Supply** (high): foundry [1]",
        citations=[AnswerCitation(marker="[1]", chunk_id="cc-dd", quoted_text="foundry")],
    )
    comp = CompetitorAgentState(anchor_ticker=ticker, question="peers?")
    comp.answer = AgentAnswer(
        answer_markdown=f"{ticker} vs peers [NVDA 1].",
        citations=[AnswerCitation(marker="NVDA [1]", chunk_id="ee-ff", quoted_text="vs peers")],
    )
    fin = FinancialAgentState(ticker=ticker, question="fin?")
    fin.answer_markdown = "Revenue +50% [metric: revenue_yoy_growth]"
    fin.metrics = [
        {
            "name": "revenue_yoy_growth",
            "value": 50.0,
            "unit": "pct",
            "period_label": "FY2024 -> FY2025",
            "narrative": "50% growth",
            "error": None,
            "inputs": [],
        }
    ]
    fin.metric_markers = ["revenue_yoy_growth"]

    specs = SpecialistOutputs(business=biz, financial=fin, risk=risk, competitor=comp)
    return ReportResult(
        ticker=ticker,
        report_markdown="## Executive Summary\nShort [1].",
        specialists=specs,
        all_citations=[AnswerCitation(marker="[1]", chunk_id="aa-bb", quoted_text="is a company")],
        financial_metrics=fin.metrics,
    )


@pytest.fixture
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(report_cache, "CACHE_DIR", tmp_path)
    return tmp_path


def test_cache_miss_then_hit_skips_generation(tmp_cache: Path) -> None:
    calls: list[str] = []

    def fake_generate(ticker: str) -> ReportResult:
        calls.append(ticker)
        return _mk_result(ticker)

    with patch.object(report_cache, "generate_report", side_effect=fake_generate):
        with patch.object(report_cache, "_latest_accession", return_value="ACC-1"):
            r1, meta1 = report_cache.get_or_generate("NVDA")
            assert meta1["cached"] is False
            r2, meta2 = report_cache.get_or_generate("NVDA")
            assert meta2["cached"] is True
            # Second call must NOT re-invoke the generator.
            assert calls == ["NVDA"]
            # Round-tripped content should still carry citations + metrics.
            assert r2.report_markdown == r1.report_markdown
            assert len(r2.all_citations) == len(r1.all_citations)
            assert r2.financial_metrics == r1.financial_metrics
            assert r2.specialists.business is not None
            assert r2.specialists.business.answer is not None
            assert r2.specialists.business.answer.citations[0].chunk_id == "aa-bb"


def test_new_accession_invalidates_cache(tmp_cache: Path) -> None:
    calls: list[str] = []

    def fake_generate(ticker: str) -> ReportResult:
        calls.append(ticker)
        return _mk_result(ticker)

    with patch.object(report_cache, "generate_report", side_effect=fake_generate):
        with patch.object(report_cache, "_latest_accession", return_value="ACC-1"):
            report_cache.get_or_generate("NVDA")
        # New filing arrives: accession changes.
        with patch.object(report_cache, "_latest_accession", return_value="ACC-2"):
            _, meta = report_cache.get_or_generate("NVDA")
            assert meta["cached"] is False
    assert calls == ["NVDA", "NVDA"]


def test_force_refresh_bypasses_cache(tmp_cache: Path) -> None:
    calls: list[str] = []
    with patch.object(report_cache, "generate_report", side_effect=lambda t: (calls.append(t), _mk_result(t))[1]):
        with patch.object(report_cache, "_latest_accession", return_value="ACC-1"):
            report_cache.get_or_generate("AMD")
            _, meta = report_cache.get_or_generate("AMD", force_refresh=True)
            assert meta["cached"] is False
    assert calls == ["AMD", "AMD"]


def test_invalidate_removes_cached_file(tmp_cache: Path) -> None:
    with patch.object(report_cache, "generate_report", side_effect=lambda t: _mk_result(t)):
        with patch.object(report_cache, "_latest_accession", return_value="ACC-1"):
            report_cache.get_or_generate("INTC")
    removed = report_cache.invalidate("INTC")
    assert removed == 1
    # Next call misses again.
    with patch.object(report_cache, "generate_report", side_effect=lambda t: _mk_result(t)) as gen:
        with patch.object(report_cache, "_latest_accession", return_value="ACC-1"):
            report_cache.get_or_generate("INTC")
        assert gen.call_count == 1


def test_missing_ticker_raises_lookup_error(tmp_cache: Path) -> None:
    with patch.object(report_cache, "_latest_accession", return_value=None):
        with pytest.raises(LookupError):
            report_cache.get_or_generate("UNKNOWN")
