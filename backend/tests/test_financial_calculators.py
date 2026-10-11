"""Unit tests for financial_tools calculators (no network)."""

from __future__ import annotations

from typing import Any

from app.financial_tools.calculators import (
    free_cash_flow,
    gross_margin,
    net_margin,
    operating_margin,
    revenue_cagr,
    revenue_yoy_growth,
)
from app.financial_tools.xbrl_client import CompanyFacts


def _facts(**concepts: list[dict[str, Any]]) -> CompanyFacts:
    """Build a CompanyFacts fixture from {concept_name: [obs, obs, ...]}."""
    us_gaap = {
        name: {
            "label": name,
            "description": "",
            "units": {"USD": observations},
        }
        for name, observations in concepts.items()
    }
    raw = {"entityName": "FixtureCo", "cik": 123, "facts": {"us-gaap": us_gaap}}
    return CompanyFacts(cik="0000000123", raw=raw)


def _fy_obs(year: int, value: float, filed: str, accession: str) -> dict[str, Any]:
    return {
        "val": value,
        "fp": "FY",
        "fy": year,
        "end": f"{year}-12-31",
        "start": f"{year}-01-01",
        "filed": filed,
        "accn": accession,
        "form": "10-K",
    }


def test_revenue_yoy_growth() -> None:
    facts = _facts(
        Revenues=[
            _fy_obs(2024, 100.0, "2025-02-01", "A1"),
            _fy_obs(2025, 150.0, "2026-02-01", "A2"),
        ]
    )
    result = revenue_yoy_growth(facts)
    assert result.ok
    assert result.value == 50.0
    assert "FY2024" in result.period_label and "FY2025" in result.period_label
    assert len(result.inputs) == 2


def test_revenue_yoy_growth_restated_pick_latest_filed() -> None:
    """When a FY has two filings (original + restatement), use the later one."""
    facts = _facts(
        Revenues=[
            _fy_obs(2024, 100.0, "2025-02-01", "A1"),
            _fy_obs(2025, 150.0, "2026-02-01", "A2"),
            _fy_obs(2025, 160.0, "2026-05-01", "A3-restated"),  # newer filing wins
        ]
    )
    result = revenue_yoy_growth(facts)
    assert result.ok
    # 160 vs 100 = +60%
    assert result.value == 60.0


def test_revenue_yoy_growth_insufficient_history() -> None:
    facts = _facts(Revenues=[_fy_obs(2025, 100.0, "2026-02-01", "A1")])
    result = revenue_yoy_growth(facts)
    assert not result.ok
    assert "Insufficient" in result.error


def test_gross_margin_direct_gross_profit() -> None:
    facts = _facts(
        Revenues=[_fy_obs(2025, 100.0, "2026-02-01", "A2")],
        GrossProfit=[_fy_obs(2025, 60.0, "2026-02-01", "A2")],
    )
    result = gross_margin(facts)
    assert result.ok
    assert result.value == 60.0
    assert result.unit == "pct"


def test_gross_margin_derived_from_cost() -> None:
    facts = _facts(
        Revenues=[_fy_obs(2025, 100.0, "2026-02-01", "A2")],
        CostOfRevenue=[_fy_obs(2025, 25.0, "2026-02-01", "A2")],
    )
    result = gross_margin(facts)
    assert result.ok
    assert result.value == 75.0


def test_operating_margin() -> None:
    facts = _facts(
        Revenues=[_fy_obs(2025, 200.0, "2026-02-01", "A2")],
        OperatingIncomeLoss=[_fy_obs(2025, 40.0, "2026-02-01", "A2")],
    )
    result = operating_margin(facts)
    assert result.ok
    assert result.value == 20.0


def test_net_margin() -> None:
    facts = _facts(
        Revenues=[_fy_obs(2025, 500.0, "2026-02-01", "A2")],
        NetIncomeLoss=[_fy_obs(2025, 75.0, "2026-02-01", "A2")],
    )
    result = net_margin(facts)
    assert result.ok
    assert result.value == 15.0


def test_free_cash_flow() -> None:
    facts = _facts(
        NetCashProvidedByUsedInOperatingActivities=[_fy_obs(2025, 1000.0, "2026-02-01", "A2")],
        PaymentsToAcquirePropertyPlantAndEquipment=[_fy_obs(2025, 300.0, "2026-02-01", "A2")],
        Revenues=[_fy_obs(2025, 2500.0, "2026-02-01", "A2")],
    )
    result = free_cash_flow(facts)
    assert result.ok
    assert result.value == 700.0
    assert "FCF margin: 28.0%" in result.narrative


def test_free_cash_flow_mismatched_years_fails() -> None:
    facts = _facts(
        NetCashProvidedByUsedInOperatingActivities=[_fy_obs(2025, 1000.0, "2026-02-01", "A2")],
        PaymentsToAcquirePropertyPlantAndEquipment=[_fy_obs(2024, 300.0, "2025-02-01", "A1")],
    )
    result = free_cash_flow(facts)
    assert not result.ok


def test_revenue_cagr_3y() -> None:
    facts = _facts(
        Revenues=[
            _fy_obs(2022, 100.0, "2023-02-01", "A0"),
            _fy_obs(2023, 120.0, "2024-02-01", "A1"),
            _fy_obs(2024, 150.0, "2025-02-01", "A2"),
            _fy_obs(2025, 172.8, "2026-02-01", "A3"),  # exactly 20% CAGR over 3 yrs
        ]
    )
    result = revenue_cagr(facts, years=3)
    assert result.ok
    assert abs(result.value - 20.0) < 0.01


def test_annual_series_ignores_restated_fy_tag() -> None:
    """XBRL `fy` reflects the FILING's fiscal year, not the fact's period.

    A FY2022 10-K that restates FY2020 data tags that FY2020 fact with fy=2022.
    We must infer the real fiscal year from `end_date`, otherwise revenue YoY
    growth returns garbage (observed in the wild on NVDA Company Facts).
    """
    facts = _facts(
        Revenues=[
            # Real FY2020 data filed inside the FY2022 10-K (restatement).
            {
                "val": 10_918_000_000.0,
                "fp": "FY",
                "fy": 2022,  # misleading: this is the filing's FY, not the fact's
                "start": "2019-01-28",
                "end": "2020-01-26",
                "filed": "2022-03-18",
                "accn": "A-restated",
                "form": "10-K",
            },
            # Real FY2024 data filed in the FY2024 10-K.
            {
                "val": 60_922_000_000.0,
                "fp": "FY",
                "fy": 2024,
                "start": "2023-01-30",
                "end": "2024-01-28",
                "filed": "2024-02-21",
                "accn": "A-fy24",
                "form": "10-K",
            },
            # Real FY2023 data filed in the FY2023 10-K.
            {
                "val": 26_974_000_000.0,
                "fp": "FY",
                "fy": 2023,
                "start": "2022-01-31",
                "end": "2023-01-29",
                "filed": "2023-02-24",
                "accn": "A-fy23",
                "form": "10-K",
            },
        ]
    )
    series = facts.annual_series("revenue")
    # Must be ordered by end_date desc.
    assert [p.end_date for p in series] == ["2024-01-28", "2023-01-29", "2020-01-26"]
    # Fiscal year inferred from end_date, NOT the `fy` field.
    assert series[0].fiscal_year == 2024
    assert series[2].fiscal_year == 2020  # NOT 2022


def test_calculator_provenance_present() -> None:
    """Every ok MetricResult must carry at least one input fact point."""
    facts = _facts(
        Revenues=[_fy_obs(2025, 100.0, "2026-02-01", "A2")],
        GrossProfit=[_fy_obs(2025, 40.0, "2026-02-01", "A2")],
    )
    r = gross_margin(facts)
    assert r.ok
    for p in r.inputs:
        assert p.accession
        assert p.filed
        assert p.form
