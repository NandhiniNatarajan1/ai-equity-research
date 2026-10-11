# AI Equity Research Platform

Multi-agent investment research over SEC filings. Enter a ticker and a question,
get an evidence-backed answer with working citations into the underlying 10-K.

> See [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for the full vision. This README
> tracks the current milestone and how to run it.

## Status

**Milestone 3 — Full research report (4 specialist agents + Verification/Report composer).**
`GET /research/report/{ticker}.html` fans out to **SEC Filing**, **Financial**,
**Risk** (ranked themed Item 1A analysis), and **Competitor** (cross-ticker
comparison) agents in parallel, then merges their outputs into a structured,
print-friendly report (Executive Summary → Business → Financials → Risks →
Competitive Position → Sources). Opens in a new tab; Ctrl+P exports to PDF.
UI also ships ingested-ticker status chips, run history, and per-run
LangSmith trace links.

**Milestone 2 — Multi-agent (SEC Filing + Financial), router-dispatched.**
A LangGraph orchestrator classifies each question and routes it to either
the **SEC Filing Agent** (RAG over 10-K text with verified citations) or
the **Financial Agent** (deterministic Python over SEC XBRL for growth,
margins, FCF, etc.). Both agents share retrieval tools over MCP. The
Financial Agent **never does arithmetic in the LLM** — numbers come from
`backend/app/financial_tools/calculators.py` with full XBRL provenance
(concept, accession, filed date) attached to every cited metric.

**Milestone 1 — RAG over 10-Ks for NVDA, AMD, INTC.** Single SEC Filing Agent
with section-aware retrieval over Postgres + pgvector, exposed as MCP tools.
Every answer carries verifiable citations; the API refuses answers whose
citations do not match the tool calls made during the run.

### What's in M1

| Layer | Status | Notes |
|---|---|---|
| EDGAR client (rate-limited, cached) | ✅ | `backend/app/ingestion/edgar_client.py` |
| 10-K section parser (Item-aware) | ✅ | Deduplicates TOC vs. body |
| Section-aware chunker | ✅ | 800-token target, paragraph-boundary preferred |
| Embedder (Voyage default, OpenAI fallback) | ✅ | `voyage-3` → 1024-dim vectors |
| Postgres + pgvector schema | ✅ | Alembic migrations, HNSW index on embeddings |
| Ingestion CLI | ✅ | `python -m app.ingestion.cli ingest NVDA AMD INTC` |
| MCP server (`search_filings`, `get_filing_section`) | ✅ | Streamable HTTP on `:8765` |
| SEC Filing Agent (LangGraph: plan → retrieve → compose) | ✅ | Claude Sonnet 5.5 |
| Citation-integrity validator | ✅ | Rejects any citation whose chunk wasn't retrieved |
| FastAPI `/research/ask`, `/chunks/{id}`, `/filings/{ticker}` | ✅ | |
| Next.js UI with citation chips + passage popovers | ✅ | |
| LangSmith tracing | ✅ (opt-in via env) | `LANGCHAIN_TRACING_V2=true` + `LANGSMITH_API_KEY` |
| Eval set (10 questions) | ✅ | Harness in `backend/tests/eval/` |
| Docker Compose (postgres, api, mcp, web) | ✅ | `infra/docker-compose.yml` |

### Non-negotiables (encoded as tests)

1. **No invented citations.** `backend/app/agents/citation_integrity.py` + `tests/test_citation_integrity.py`.
2. **Deterministic math seam.** `backend/app/financial_tools/` stub + the agent's
   system prompt forbids computing ratios from retrieved text. Any question
   requiring math returns `deferred=true` with a reason.
3. **EDGAR etiquette.** User-Agent, 8 req/s cap, on-disk cache.

## Architecture

```
Next.js (web) ──HTTP──> FastAPI (api) ──LangGraph──> SEC Filing Agent
                                                         │
                                                         ▼
                                                 Retrieval tools
                                             (also exposed via MCP
                                              server for other agents)
                                                         │
                                                         ▼
                                                   Postgres + pgvector
```

Ingestion is a one-shot CLI: fetch 10-Ks from EDGAR → split by Item → chunk →
embed → upsert.

## Prerequisites

- Docker Desktop
- Python 3.12+ (only for running ingestion or tests outside Docker)
- Node 20 LTS (only for running the frontend outside Docker)
- API keys:
  - **Anthropic** (required for the agent)
  - **Voyage** *or* **OpenAI** (one embedding provider)
  - **LangSmith** (optional, for traces)

## Quickstart

```powershell
# 1. Configure env
Copy-Item .env.example .env
# edit .env and fill in:
#   ANTHROPIC_API_KEY=sk-ant-...
#   VOYAGE_API_KEY=pa-...       (or set EMBEDDING_PROVIDER=openai + OPENAI_API_KEY)
#   LANGSMITH_API_KEY=lsv2_...  (optional)

# 2. Bring the stack up
docker compose -f infra/docker-compose.yml up -d --build

# 3. Run migrations (seeds NVDA, AMD, INTC)
docker compose -f infra/docker-compose.yml exec api alembic upgrade head

# 4. Ingest the three MVP tickers
docker compose -f infra/docker-compose.yml exec api `
    python -m app.ingestion.cli NVDA AMD INTC

# 5. Open the dashboard
start http://localhost:3001
```

## Running tests

```powershell
cd backend
.venv\Scripts\python -m pytest -v           # unit tests, no external services
.venv\Scripts\python -m pytest -m eval -v   # live eval, requires DB + API keys
```

The unit suite (18 tests) covers the parser, chunker, EDGAR client, and
citation-integrity validator. The eval suite (10 questions) runs the full
LangGraph agent against the ingested filings — it costs real tokens.

### Eval results (M1 + M2, 2026-10-11)

Model: Claude Sonnet 5.5 • Embeddings: voyage-3 (1024-dim) • pgvector HNSW

- **12 / 12 passed** in ~112 s
- 8 SEC Filing Agent questions (NVDA/AMD/INTC qualitative disclosures): all
  returned verified citations into expected 10-K Item sections. Partial
  deferrals that still produced citation-backed content are accepted
- 4 Financial Agent questions (NVDA revenue growth / gross margin, AMD FCF,
  INTC operating margin): all routed through the deterministic calculators
  with correct XBRL provenance
- Zero citation-integrity rejections on the SEC path
- Zero LLM arithmetic on the financial path — every number comes from
  Python computation on XBRL facts

Also fix the ingest CLI invocation (no `ingest` subcommand needed):

```powershell
docker compose -f infra/docker-compose.yml exec api `
    python -m app.ingestion.cli NVDA AMD INTC
```

## Repository layout

```
ai-equity-research/
  backend/
    app/
      main.py              # FastAPI entrypoint
      api/                 # research + filings + chunks endpoints
      agents/              # LangGraph graph, schemas, citation-integrity validator
      ingestion/           # edgar_client, section_parser, chunker, embedder, pipeline, CLI
      mcp_server/          # MCP server exposing search_filings / get_filing_section
      financial_tools/     # STUB — Milestone 2 deterministic calculators
      db/                  # SQLAlchemy models, session
      core/                # config, logging, tracing
    migrations/            # Alembic
    tests/                 # pytest; eval/ holds the 10-question set
  frontend/                # Next.js 15 + Tailwind
  infra/                   # docker-compose, Postgres init
  PROJECT_BRIEF.md         # original project brief
```

## Milestone 4 — shipped

- **Report cache** keyed on `(ticker, latest_filing_accession)` under
  `./data/reports/`. New ingestion auto-invalidates (new accession = new
  key). First call ~60s, subsequent calls ~15ms.
- **Sonnet / Haiku split** — the orchestrator LLM router, SEC Filing
  planner, Financial Agent narrator, and Competitor Agent comparator all
  use Claude Haiku 5.5 (~3x cheaper); Sonnet 5.5 reserved for final
  composition and nuanced ranking (SEC Filing composer, Risk Agent,
  Report Agent composer). ~50% token-cost reduction per report.
- **yfinance stock snapshot** (1Y price + 1Y change) and **5-year
  revenue/margin/FCF history** rendered as inline SVG sparklines and bar
  charts in the report's new "Fundamentals snapshot" section. No new
  system deps for the chart rendering (pure Python SVG).
- **Server-side PDF** via WeasyPrint:
  `GET /research/report/{ticker}/pdf` returns a browser-downloadable
  `.pdf`. Falls back to a 503 with a clear message if WeasyPrint deps are
  missing in the build.
- **Configurable peer list** on the Report Agent: pass
  `?peers=NVDA,AMD` to override the default peer set. Custom peer lists
  bypass the cache.

## Milestone 5 (next)

- Dynamic peer resolution from SIC code / XBRL metadata (vs. the user
  typing peer tickers manually).
- Report cache TTL + a periodic refresh hook when new filings land.
- RSS / 8-K ingestion so reports surface material events between 10-Ks.
