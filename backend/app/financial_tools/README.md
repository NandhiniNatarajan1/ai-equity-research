# financial_tools — deterministic Python over SEC XBRL

**Status:** stubbed for Milestone 2. In Milestone 1, numbers come from
retrieved 10-K passages (quoted and cited); the SEC Filing Agent is
instructed to **defer** any question that requires computed ratios.

## What lives here (M2+)

Pure Python functions over SEC Company Facts XBRL that compute:

- Revenue growth (YoY, QoQ, TTM)
- Gross margin, operating margin, net margin
- Free cash flow and FCF margin
- Net debt, net leverage, interest coverage
- Peer comparison helpers (same-metric cross-company)

Each function:

1. Takes a `CompanyFacts` object or a well-typed dict of XBRL concepts.
2. Returns a `MetricResult` with the value, the units (`USD`, `pct`, `x`),
   the period of report, and the exact `(concept, accession)` provenance so
   the Financial Agent can cite it.
3. Is exhaustively unit-tested against fixtures captured from EDGAR.

No LLM arithmetic. Ever.

## Why isolated

Keeping these functions free of LLM and framework code means they can be
exposed through MCP tools (shared across agents) and audited independently
of the agent prompts.
