"""Deterministic financial ratio calculators (pure Python over XBRL facts).

NO LLM arithmetic. Each function:
  - takes a CompanyFacts object (or inputs derived from it)
  - returns a MetricResult carrying the value, units, period(s), and the
    exact (concept, accession, filed) provenance for every input used, so
    the Financial Agent can emit real, verifiable citations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.financial_tools.xbrl_client import CompanyFacts, XbrlFactPoint


@dataclass(frozen=True)
class MetricResult:
    name: str
    value: float | None
    unit: str  # "USD", "pct", "x", "ratio"
    period_label: str  # e.g. "FY2025", "FY2024 -> FY2025"
    narrative: str  # one short human-readable sentence
    inputs: list[XbrlFactPoint] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.value is not None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "period_label": self.period_label,
            "narrative": self.narrative,
            "error": self.error,
            "inputs": [
                {
                    "concept": p.concept,
                    "value": p.value,
                    "unit": p.unit,
                    "fiscal_year": p.fiscal_year,
                    "fiscal_period": p.fiscal_period,
                    "end_date": p.end_date,
                    "filed": p.filed,
                    "accession": p.accession,
                    "form": p.form,
                }
                for p in self.inputs
            ],
        }


def _fail(name: str, reason: str) -> MetricResult:
    return MetricResult(
        name=name, value=None, unit="", period_label="", narrative=reason, error=reason
    )


def _ratio_pct(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return (numerator / denominator) * 100.0


def _fmt_usd(x: float) -> str:
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e9:
        return f"{sign}${x / 1e9:,.2f}B"
    if x >= 1e6:
        return f"{sign}${x / 1e6:,.2f}M"
    return f"{sign}${x:,.0f}"


def revenue_yoy_growth(facts: CompanyFacts) -> MetricResult:
    """Latest-fiscal-year revenue growth vs. the prior fiscal year."""
    series = facts.annual_series("revenue", limit=2)
    if len(series) < 2:
        return _fail("revenue_yoy_growth", "Insufficient annual revenue history (need 2 FYs).")
    current, prior = series[0], series[1]
    if prior.value == 0:
        return _fail("revenue_yoy_growth", "Prior-year revenue is zero.")
    growth = ((current.value - prior.value) / prior.value) * 100.0
    return MetricResult(
        name="revenue_yoy_growth",
        value=round(growth, 2),
        unit="pct",
        period_label=f"FY{prior.fiscal_year} -> FY{current.fiscal_year}",
        narrative=(
            f"Revenue grew {growth:+.1f}% YoY, from {_fmt_usd(prior.value)} in "
            f"FY{prior.fiscal_year} to {_fmt_usd(current.value)} in FY{current.fiscal_year}."
        ),
        inputs=[current, prior],
    )


def revenue_cagr(facts: CompanyFacts, years: int = 3) -> MetricResult:
    """Compound annual growth rate of revenue over the last `years` full years."""
    series = facts.annual_series("revenue", limit=years + 1)
    if len(series) < years + 1:
        return _fail(
            "revenue_cagr", f"Insufficient history (have {len(series)} FYs, need {years + 1})."
        )
    end, start = series[0], series[-1]
    if start.value <= 0:
        return _fail("revenue_cagr", "Starting-period revenue is non-positive.")
    n = end.fiscal_year - start.fiscal_year
    if n <= 0:
        return _fail("revenue_cagr", "Period span is non-positive.")
    cagr = ((end.value / start.value) ** (1.0 / n) - 1.0) * 100.0
    return MetricResult(
        name=f"revenue_cagr_{n}y",
        value=round(cagr, 2),
        unit="pct",
        period_label=f"FY{start.fiscal_year} -> FY{end.fiscal_year}",
        narrative=(
            f"Revenue CAGR over {n} years is {cagr:+.1f}%, from {_fmt_usd(start.value)} "
            f"(FY{start.fiscal_year}) to {_fmt_usd(end.value)} (FY{end.fiscal_year})."
        ),
        inputs=[end, start],
    )


def gross_margin(facts: CompanyFacts) -> MetricResult:
    """Gross margin = (Revenue - Cost of Revenue) / Revenue, latest FY.

    If `GrossProfit` is directly reported, prefer it; otherwise compute from
    revenue minus cost of revenue.
    """
    rev = facts.latest_annual("revenue")
    if rev is None:
        return _fail("gross_margin", "No annual revenue data.")

    gp = facts.latest_annual("gross_profit")
    if gp is not None and gp.fiscal_year == rev.fiscal_year:
        margin = _ratio_pct(gp.value, rev.value)
        if margin is None:
            return _fail("gross_margin", "Revenue is zero.")
        return MetricResult(
            name="gross_margin",
            value=round(margin, 2),
            unit="pct",
            period_label=f"FY{rev.fiscal_year}",
            narrative=(
                f"Gross margin was {margin:.1f}% in FY{rev.fiscal_year} "
                f"({_fmt_usd(gp.value)} gross profit on {_fmt_usd(rev.value)} revenue)."
            ),
            inputs=[gp, rev],
        )

    cost = facts.latest_annual("cost_of_revenue")
    if cost is None or cost.fiscal_year != rev.fiscal_year:
        return _fail("gross_margin", "No GrossProfit or CostOfRevenue for latest FY.")
    gp_value = rev.value - cost.value
    margin = _ratio_pct(gp_value, rev.value)
    if margin is None:
        return _fail("gross_margin", "Revenue is zero.")
    return MetricResult(
        name="gross_margin",
        value=round(margin, 2),
        unit="pct",
        period_label=f"FY{rev.fiscal_year}",
        narrative=(
            f"Gross margin was {margin:.1f}% in FY{rev.fiscal_year} "
            f"(derived: {_fmt_usd(rev.value)} revenue - {_fmt_usd(cost.value)} cost)."
        ),
        inputs=[rev, cost],
    )


def operating_margin(facts: CompanyFacts) -> MetricResult:
    rev = facts.latest_annual("revenue")
    op = facts.latest_annual("operating_income")
    if rev is None or op is None:
        return _fail("operating_margin", "Missing revenue or operating income.")
    if rev.fiscal_year != op.fiscal_year:
        return _fail("operating_margin", "Revenue and operating income are from different FYs.")
    margin = _ratio_pct(op.value, rev.value)
    if margin is None:
        return _fail("operating_margin", "Revenue is zero.")
    return MetricResult(
        name="operating_margin",
        value=round(margin, 2),
        unit="pct",
        period_label=f"FY{rev.fiscal_year}",
        narrative=(
            f"Operating margin was {margin:.1f}% in FY{rev.fiscal_year} "
            f"({_fmt_usd(op.value)} operating income on {_fmt_usd(rev.value)} revenue)."
        ),
        inputs=[op, rev],
    )


def net_margin(facts: CompanyFacts) -> MetricResult:
    rev = facts.latest_annual("revenue")
    ni = facts.latest_annual("net_income")
    if rev is None or ni is None:
        return _fail("net_margin", "Missing revenue or net income.")
    if rev.fiscal_year != ni.fiscal_year:
        return _fail("net_margin", "Revenue and net income are from different FYs.")
    margin = _ratio_pct(ni.value, rev.value)
    if margin is None:
        return _fail("net_margin", "Revenue is zero.")
    return MetricResult(
        name="net_margin",
        value=round(margin, 2),
        unit="pct",
        period_label=f"FY{rev.fiscal_year}",
        narrative=(
            f"Net margin was {margin:.1f}% in FY{rev.fiscal_year} "
            f"({_fmt_usd(ni.value)} net income on {_fmt_usd(rev.value)} revenue)."
        ),
        inputs=[ni, rev],
    )


def free_cash_flow(facts: CompanyFacts) -> MetricResult:
    """FCF = Cash From Operations - Capital Expenditures (latest FY)."""
    cfo = facts.latest_annual("cash_from_operations")
    capex = facts.latest_annual("capex")
    if cfo is None or capex is None:
        return _fail("free_cash_flow", "Missing CFO or CapEx.")
    if cfo.fiscal_year != capex.fiscal_year:
        return _fail("free_cash_flow", "CFO and CapEx are from different FYs.")
    fcf = cfo.value - capex.value
    rev = facts.latest_annual("revenue")
    margin_frag = ""
    inputs = [cfo, capex]
    if rev is not None and rev.fiscal_year == cfo.fiscal_year and rev.value:
        margin = _ratio_pct(fcf, rev.value)
        if margin is not None:
            margin_frag = f" (FCF margin: {margin:.1f}%)"
        inputs.append(rev)
    return MetricResult(
        name="free_cash_flow",
        value=round(fcf, 2),
        unit="USD",
        period_label=f"FY{cfo.fiscal_year}",
        narrative=(
            f"Free cash flow in FY{cfo.fiscal_year} was {_fmt_usd(fcf)}: "
            f"{_fmt_usd(cfo.value)} CFO - {_fmt_usd(capex.value)} CapEx{margin_frag}."
        ),
        inputs=inputs,
    )
