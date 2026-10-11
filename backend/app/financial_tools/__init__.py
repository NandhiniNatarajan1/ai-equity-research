"""Deterministic financial calculators over SEC XBRL (Milestone 2).

NO LLM arithmetic. Every number returned here comes from a Python computation
on numeric XBRL facts fetched from SEC Company Facts, with full provenance.
"""

from app.financial_tools.calculators import (
    MetricResult,
    free_cash_flow,
    gross_margin,
    net_margin,
    operating_margin,
    revenue_cagr,
    revenue_yoy_growth,
)
from app.financial_tools.xbrl_client import CompanyFacts, XbrlClient, XbrlFactPoint

__all__ = [
    "CompanyFacts",
    "XbrlClient",
    "XbrlFactPoint",
    "MetricResult",
    "revenue_yoy_growth",
    "revenue_cagr",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "free_cash_flow",
]
