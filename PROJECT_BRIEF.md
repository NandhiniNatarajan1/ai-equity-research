# AI Equity Research Platform — Project Brief

A user enters a ticker (e.g. `NVDA`) and a team of specialized AI agents researches
the company, analyzes its financials, benchmarks competitors, and produces an
evidence-backed investment report (dashboard + downloadable PDF). Every major
factual claim links back to its source.

## Agents

- **Research Orchestrator** (LangGraph): coordinates tasks and agent dependencies
- **SEC Filing Agent**: 10-K / 10-Q retrieval, filing sections, citations
- **Financial Agent**: revenue, margins, cash flows, ratios
- **Competitor Agent**: peer comparisons, industry benchmarking
- **Risk Agent**: business risks, leverage, exposure
- **Verification + Report Agent**: checks citations, reconciles numbers, summarizes conclusions

Financial calculations are **deterministic Python tools**, never LLM arithmetic.

## Tech stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | Next.js + Tailwind | Interactive research dashboard |
| Backend | Python + FastAPI | APIs and research execution |
| Agent orchestration | LangGraph | Coordinate agents, persist workflows |
| Tool integration | MCP | Expose financial data and calculation tools |
| Retrieval | RAG + pgvector | Semantic search over filing passages |
| Database | PostgreSQL | Filings, metrics, reports, research history |
| Infrastructure | Docker + AWS | Deploy and run |
| Evaluation | pytest + LangSmith | Test outputs, trace agent steps, monitor failures |

## Data sources

- **SEC EDGAR**: annual and quarterly filings
- **SEC Data APIs**: structured company facts / XBRL
- **FRED API**: interest rates, macro indicators
- **Yahoo Finance or a licensed provider**: prices / market data (subject to terms)

Use SEC structured data for numbers. Use RAG over 10-K/10-Q text for explanations and risk.
Store accession numbers, filing dates, source URLs, and passages for verification.

## Roadmap

1. **Data foundation**: fetch SEC company facts and filings, normalize metrics, store in PostgreSQL
2. **Analysis tools**: growth, profitability, leverage, cash-flow, peer comparison, with unit tests
3. **RAG over filings**: chunk sections, embed, retrieve, return verifiable references
4. **Multi-agent system**: LangGraph + MCP tools, workflow persistence, explicit failure handling
5. **Dashboard and reports**: ticker search, charts, research progress, citations, PDF export
6. **Evaluate and deploy**: 20–30 research questions vs. source docs, numeric accuracy and
   citation validity, Docker deployment

## MVP scope

Start with **NVIDIA, AMD, and Intel**. Build a reliable end-to-end comparison before
supporting the broader market.

## Resume-worthy highlights

1. **Agent coordination**: independent analyses, shared structured results, conflict reconciliation
2. **Financial reliability**: deterministic metrics, insights grounded in cited filings
3. **Production readiness**: API endpoints, persisted workflow state, automated evaluation,
   observability, deployment
