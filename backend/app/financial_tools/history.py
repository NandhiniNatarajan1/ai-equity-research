"""Multi-year financial history series for sparkline rendering.

Pulls N-year annual series from the already-downloaded SEC Company Facts
blob (no additional network calls) and derives per-year margins from the
same deterministic pairs the single-year calculators use.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.financial_tools.xbrl_client import CompanyFacts, XbrlFactPoint


@dataclass(frozen=True)
class HistoryPoint:
    fiscal_year: int
    value: float
    end_date: str


@dataclass(frozen=True)
class HistorySeries:
    name: str
    unit: str  # "USD" | "pct"
    points: list[HistoryPoint]  # newest-last for chart ordering


def _by_end(points: list[XbrlFactPoint]) -> dict[str, XbrlFactPoint]:
    return {p.end_date: p for p in points}


def _derive_pct(
    numerator: list[XbrlFactPoint],
    denominator: list[XbrlFactPoint],
    name: str,
) -> HistorySeries:
    nmap = _by_end(numerator)
    dmap = _by_end(denominator)
    common = sorted(set(nmap) & set(dmap))
    pts: list[HistoryPoint] = []
    for end in common:
        n_val = nmap[end].value
        d_val = dmap[end].value
        if d_val == 0:
            continue
        pts.append(
            HistoryPoint(
                fiscal_year=nmap[end].fiscal_year,
                value=round(n_val / d_val * 100.0, 2),
                end_date=end,
            )
        )
    return HistorySeries(name=name, unit="pct", points=pts)


def multi_year(facts: CompanyFacts, years: int = 5) -> dict[str, HistorySeries]:
    """Return revenue + margin + FCF series over the last ~`years` fiscal years."""
    rev = facts.annual_series("revenue", limit=years)
    gp = facts.annual_series("gross_profit", limit=years)
    op = facts.annual_series("operating_income", limit=years)
    ni = facts.annual_series("net_income", limit=years)
    cfo = facts.annual_series("cash_from_operations", limit=years)
    capex = facts.annual_series("capex", limit=years)
    # Derived cost-of-revenue path for gross margin when GP isn't tagged.
    cost = facts.annual_series("cost_of_revenue", limit=years)

    series: dict[str, HistorySeries] = {}

    series["revenue"] = HistorySeries(
        name="revenue",
        unit="USD",
        points=[
            HistoryPoint(fiscal_year=p.fiscal_year, value=p.value, end_date=p.end_date)
            for p in sorted(rev, key=lambda p: p.end_date)
        ],
    )

    # Gross margin: prefer direct GP, fall back to derived.
    if gp:
        series["gross_margin"] = _derive_pct(gp, rev, "gross_margin")
    elif cost:
        rev_map = _by_end(rev)
        cost_map = _by_end(cost)
        common = sorted(set(rev_map) & set(cost_map))
        series["gross_margin"] = HistorySeries(
            name="gross_margin",
            unit="pct",
            points=[
                HistoryPoint(
                    fiscal_year=rev_map[end].fiscal_year,
                    value=round(
                        (rev_map[end].value - cost_map[end].value) / rev_map[end].value * 100.0,
                        2,
                    ),
                    end_date=end,
                )
                for end in common
                if rev_map[end].value
            ],
        )

    if op:
        series["operating_margin"] = _derive_pct(op, rev, "operating_margin")
    if ni:
        series["net_margin"] = _derive_pct(ni, rev, "net_margin")

    # Free cash flow in dollars per year.
    if cfo and capex:
        cfo_map = _by_end(cfo)
        capex_map = _by_end(capex)
        common = sorted(set(cfo_map) & set(capex_map))
        series["free_cash_flow"] = HistorySeries(
            name="free_cash_flow",
            unit="USD",
            points=[
                HistoryPoint(
                    fiscal_year=cfo_map[end].fiscal_year,
                    value=round(cfo_map[end].value - capex_map[end].value, 2),
                    end_date=end,
                )
                for end in common
            ],
        )

    return series
