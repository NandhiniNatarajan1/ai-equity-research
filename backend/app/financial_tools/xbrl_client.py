"""SEC Company Facts (XBRL) client.

Fetches https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json which
returns every reported numeric fact across the company's filings, keyed by
US-GAAP concept (e.g. "Revenues", "GrossProfit", "OperatingIncomeLoss").

We only expose the concepts the calculators need, with helpers to pick a
single annual value for a given fiscal year, and to list the N most recent
annual values with provenance (accession, filed date, fiscal period).

Reuses the same rate-limited, cached EDGAR HTTP client used by the 10-K
pipeline so SEC's User-Agent + 10 req/s rules are respected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.ingestion.edgar_client import EdgarClient

log = get_logger("financial.xbrl")

COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Preferred US-GAAP concepts in order; different filers use different tags.
# The resolver walks this list and returns the first concept with any facts.
CONCEPT_ALIASES: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    "cost_of_revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ],
    "cash_from_operations": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "total_debt": [
        "LongTermDebt",
        "LongTermDebtNoncurrent",
    ],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
}


@dataclass(frozen=True)
class XbrlFactPoint:
    """One reported numeric observation for a concept."""

    concept: str
    value: float
    unit: str
    fiscal_year: int
    fiscal_period: str  # "FY", "Q1", "Q2", "Q3"
    start_date: str | None  # ISO date; None for instantaneous facts
    end_date: str  # ISO date
    filed: str  # ISO date the filing was accepted
    accession: str
    form: str  # "10-K", "10-Q", "20-F", etc.

    @property
    def filing_url(self) -> str:
        acc_nodash = self.accession.replace("-", "")
        return (
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={acc_nodash[:10]}&type={self.form}&dateb=&owner=include&count=40"
        )


class CompanyFacts:
    """Thin typed wrapper around the raw Company Facts JSON blob."""

    def __init__(self, cik: str, raw: dict[str, Any]) -> None:
        self.cik = cik
        self.entity_name: str = raw.get("entityName", "")
        self._raw = raw
        self._us_gaap: dict[str, Any] = raw.get("facts", {}).get("us-gaap", {})

    def has_concept(self, concept: str) -> bool:
        return concept in self._us_gaap

    def resolve_concept(self, alias_key: str, *, unit: str = "USD") -> str | None:
        """Return the aliased concept name whose data runs most recently.

        Different filers tag the same underlying metric with different US-GAAP
        concepts, and companies sometimes switch concepts over time (e.g. NVDA
        moved off `RevenueFromContractWithCustomerExcludingAssessedTax` in
        recent 10-Ks). Picking the first alias that merely EXISTS yields
        stale data; instead we rank aliases by the most-recent 10-K FY
        observation and return the one that reaches furthest into the future.
        """
        best_concept: str | None = None
        best_end: str = ""
        for concept in CONCEPT_ALIASES.get(alias_key, []):
            if not self.has_concept(concept):
                continue
            obs = self._us_gaap[concept].get("units", {}).get(unit, [])
            latest_end = ""
            for o in obs:
                if o.get("fp") != "FY":
                    continue
                form = str(o.get("form", ""))
                if not (form == "10-K" or form.startswith("10-K/")):
                    continue
                end = str(o.get("end", ""))
                if end > latest_end:
                    latest_end = end
            if latest_end and latest_end > best_end:
                best_end = latest_end
                best_concept = concept
        return best_concept

    def annual_series(
        self, alias_key: str, *, unit: str = "USD", limit: int | None = None
    ) -> list[XbrlFactPoint]:
        """Return annual data points for an aliased concept, newest first.

        XBRL's `fy` field in Company Facts reflects the enclosing FILING's
        fiscal year, not necessarily the fact's own period (restated prior
        years in a later 10-K are tagged with the later fy). We use the
        fact's `end_date` as the authoritative fiscal-year marker instead.

        Filter rules:
          - form must be "10-K" or "10-K/A" (annual filings only)
          - fp must be "FY" (annual-period facts, not quarterly)
          - start/end span must be ~a full year (280-400 days) to drop
            partial-year or snapshot facts that slipped through
          - for a given end_date (unique annual period), keep the fact with
            the latest `filed` date (= most recent restatement)
        """
        concept = self.resolve_concept(alias_key)
        if concept is None:
            return []
        concept_data = self._us_gaap[concept]
        units = concept_data.get("units", {})
        obs_list = units.get(unit) or units.get(f"{unit}/shares") or []

        from datetime import date

        latest_by_end: dict[str, XbrlFactPoint] = {}
        for obs in obs_list:
            if obs.get("fp") != "FY":
                continue
            form = str(obs.get("form", ""))
            if not (form == "10-K" or form.startswith("10-K/")):
                continue
            end_s = obs.get("end")
            start_s = obs.get("start")
            if not end_s:
                continue
            # Require ~annual span if start is present (balance-sheet items
            # like total debt have no start; let them through).
            if start_s:
                try:
                    span_days = (date.fromisoformat(end_s) - date.fromisoformat(start_s)).days
                except ValueError:
                    continue
                if not (280 <= span_days <= 400):
                    continue
            try:
                inferred_fy = int(end_s[:4])
            except ValueError:
                continue

            point = XbrlFactPoint(
                concept=concept,
                value=float(obs["val"]),
                unit=unit,
                fiscal_year=inferred_fy,
                fiscal_period="FY",
                start_date=start_s,
                end_date=str(end_s),
                filed=str(obs.get("filed")),
                accession=str(obs.get("accn")),
                form=form,
            )
            prev = latest_by_end.get(end_s)
            if prev is None or point.filed > prev.filed:
                latest_by_end[end_s] = point

        points = sorted(latest_by_end.values(), key=lambda p: p.end_date, reverse=True)
        if limit is not None:
            points = points[:limit]
        return points

    def latest_annual(self, alias_key: str, *, unit: str = "USD") -> XbrlFactPoint | None:
        series = self.annual_series(alias_key, unit=unit, limit=1)
        return series[0] if series else None


class XbrlClient:
    """Fetches and caches Company Facts JSON blobs."""

    def __init__(self, edgar: EdgarClient | None = None) -> None:
        self._edgar = edgar or EdgarClient()
        self._owns_edgar = edgar is None

    def close(self) -> None:
        if self._owns_edgar:
            self._edgar.close()

    def __enter__(self) -> XbrlClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch(self, cik: str) -> CompanyFacts:
        url = COMPANY_FACTS_URL.format(cik=cik)
        raw = self._edgar.fetch(url)
        parsed = json.loads(raw)
        log.info(
            "xbrl_fetch",
            cik=cik,
            entity=parsed.get("entityName"),
            concepts=len(parsed.get("facts", {}).get("us-gaap", {})),
        )
        return CompanyFacts(cik=cik, raw=parsed)
