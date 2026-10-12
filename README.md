# AI Equity Research Platform

A multi-agent investment research platform. Pick any public US-listed company,
ask a question in plain English, and get a cited answer whose every quote
links back to the exact passage in the company's SEC filing — plus a full
investor-style research report that fans out six specialist agents in
parallel and renders to PDF.

> **Why this exists.** Portfolio project exploring where real engineering
> rigor meets agentic AI: LangGraph orchestration, model-split cost control,
> deterministic financial math (never LLM arithmetic), citation-integrity
> verification that rejects hallucinated sources, and a report cache
> keyed on SEC accession numbers so repeat views are free.

---

## Highlights

- **Multi-agent orchestration** with LangGraph: a router dispatches each
  question to one of two specialists (SEC Filing or Financial), and the
  full report fans out four specialists in parallel + a verification +
  report composer.
- **Deterministic financial math.** Numbers never come from the LLM.
  Revenue growth, margins, FCF, CAGR, etc. are pure Python functions
  over SEC XBRL facts, with full provenance (concept, accession, filed
  date) attached to every cited metric.
- **Citation integrity enforced server-side.** The API rejects any
  answer whose claimed `chunk_id`s weren't actually returned by the MCP
  retrieval tools during that run, and fuzzy-matches each quoted span
  against the real chunk text.
- **Any US-listed company.** Backed by SEC's public `company_tickers.json`
  (10,445 filers). Click a ticker you've never loaded and the pipeline
  fetches the 10-K from EDGAR, section-parses it, chunks, embeds, and
  indexes — in about 90 seconds.
- **Cost control through model split.** The orchestrator router,
  planners, narrators, and per-peer composers run on Claude Haiku 5.5
  (~3× cheaper); nuanced final composition stays on Sonnet 5.5. Report
  cost dropped from ~$0.30 to ~$0.10 per generation.
- **Report cache keyed on accession.** New filings auto-invalidate; repeat
  views of the same report drop from ~60s to ~15ms.
- **Server-side PDF** via WeasyPrint, with inline SVG sparklines and
  5-year revenue/margin/FCF bar charts from the already-indexed XBRL.
- **Observability built in.** LangSmith traces persisted per agent run;
  `/runs` endpoint and in-app run history surface them.

## Live screenshots

> Add `docs/workspace.png`, `docs/report.png`, `docs/agents.png` and link
> them here. (Recommend screen-recording the full flow as a 30-second GIF
> for the top of this README.)

## Architecture

```
                                 ┌────────────────────┐
   Any US ticker ──> search ──>  │  SEC company_tickers│
                                 └─────────┬──────────┘
                                           │ resolve CIK
                                           ▼
                                 ┌────────────────────┐
                                 │   EDGAR pipeline   │  rate-limited, cached
                                 │  fetch 10-K ─> parse ─> chunk ─> embed
                                 └─────────┬──────────┘
                                           ▼
                                 ┌────────────────────┐
                                 │ Postgres + pgvector │  HNSW index
                                 └─────────┬──────────┘
                                           │
          ┌────────────────────────────────┼──────────────────────────┐
          ▼                                ▼                          ▼
┌───────────────────┐          ┌───────────────────┐       ┌───────────────────┐
│  LangGraph router │          │   MCP retrieval   │       │  XBRL + yfinance  │
│  (Haiku 5.5)      │          │   tools           │       │  non-LLM data     │
└─────┬─────────────┘          └─────────┬─────────┘       └─────────┬─────────┘
      │                                  │                           │
      │ ask ─ one specialist             │ reused across every agent │
      ▼                                  ▼                           ▼
┌───────────────────┐          ┌───────────────────┐       ┌───────────────────┐
│  SEC Filing Agent │          │   Risk Agent      │       │ Financial Agent   │
│  (Sonnet composer)│          │   (Haiku)         │       │ Haiku narrator +  │
└─────┬─────────────┘          └─────────┬─────────┘       │ Python calculators│
      │                                  │                 └─────────┬─────────┘
      ▼                                  ▼                           │
┌───────────────────┐          ┌───────────────────┐                 │
│  Verification     │          │ Competitor Agent  │                 │
│  (citation check) │          │ Haiku per-peer    │                 │
└─────┬─────────────┘          └─────────┬─────────┘                 │
      │                                  │                           │
      └──────────────┬───────────────────┴───────────────────────────┘
                     ▼
             ┌───────────────────┐
             │   Report Agent    │   fan-out composer + accession-keyed cache
             │   (Sonnet)        │   HTML / PDF via WeasyPrint
             └───────────────────┘
```

## Tech stack

| Layer | Tech |
|---|---|
| Agents | **LangGraph** · **Anthropic Claude** (Sonnet 5.5 + Haiku 5.5 model split) |
| Retrieval | **pgvector** (HNSW index) · **Voyage AI** `voyage-3` embeddings |
| Tool integration | **Model Context Protocol (MCP)** — retrieval tools shared across agents |
| Financial data | **SEC Company Facts XBRL** (deterministic Python calculators) · **yfinance** for prices |
| Observability | **LangSmith** traces per agent run |
| Backend | **FastAPI** · **SQLAlchemy 2** · **Alembic** · **Pydantic** |
| Frontend | **Next.js 15** · **React 19** · **Tailwind** · **Recharts** · **next-themes** |
| Report rendering | **WeasyPrint** (HTML + inline SVG → PDF) |
| Infra | **Docker Compose** · Postgres with pgvector · Debian-slim images |
| Testing | **pytest** (41 unit + 12 live eval) |

## Running it locally

```powershell
# 1. Configure env
Copy-Item .env.example .env
# fill in: ANTHROPIC_API_KEY, VOYAGE_API_KEY (or OPENAI_API_KEY)
# optional: LANGSMITH_API_KEY

# 2. Bring the stack up
docker compose -f infra/docker-compose.yml up -d --build

# 3. Run migrations
docker compose -f infra/docker-compose.yml exec api alembic upgrade head

# 4. Open the workspace
start http://localhost:3001
```

The seed migration pre-loads NVDA, AMD, INTC. For any other ticker just
type it into the search bar and click **Load this company** — the pipeline
downloads, parses, chunks, embeds, and indexes the latest 10-K in ~90
seconds.

### Non-negotiables (enforced in code)

1. **No invented citations.** `app/agents/citation_integrity.py` +
   `tests/test_citation_integrity.py`. Any answer with a `chunk_id` that
   wasn't returned by an MCP tool during that run is rejected server-side.
2. **Deterministic math seam.** `app/financial_tools/calculators.py` —
   pure Python over SEC XBRL. The SEC Filing Agent's system prompt
   explicitly forbids computing ratios from retrieved text; math-shaped
   questions route to the Financial Agent.
3. **EDGAR etiquette.** User-Agent with a contact email, 8 req/s cap,
   on-disk cache.

## Testing

```powershell
cd backend
.venv\Scripts\python -m pytest -q              # 41 unit tests
.venv\Scripts\python -m pytest -m eval -v      # 12 live-eval questions
```

Latest eval run (Oct 2026): **12 / 12 passed in ~102 s** at the current
model split. Zero citation-integrity rejections.

## Project history

Six milestones shipped as discrete commits — each one adds a specific
capability and keeps the tests green:

```
M5  feat: search + load any public ticker (not just NVDA/AMD/INTC)
    feat(ui): simplify Research Intelligence rail + plain-English layer
    feat(ui): new app shell + Research Workspace

M4  feat(cost): shift Risk + per-peer composer to Haiku; default 2 peers
    feat(M4): sparklines, server-side PDF, configurable peers
    feat(M4): report cache + Sonnet/Haiku split (~50% cost cut)

M3  feat(M3): Risk Agent + Competitor Agent + Report composer + UI polish

M2  feat(M2): Financial Agent + router — deterministic math over SEC XBRL

M1  feat: title-based parser fallback + 10/10 eval pass
    feat: Milestone 1 — RAG-grounded SEC filing agent for NVDA/AMD/INTC
```

See `PROJECT_BRIEF.md` for the original design brief.

## Repository layout

```
ai-equity-research/
  backend/
    app/
      agents/             # LangGraph specialists + orchestrator + verification
      api/                # FastAPI routers (/research, /companies, /runs, /system)
      companies/          # SEC ticker resolver
      financial_tools/    # Deterministic calculators + SEC XBRL client
      ingestion/          # EDGAR client, section parser, chunker, pipeline, CLI
      mcp_server/         # MCP server exposing retrieval tools
      report_assets/      # Inline SVG sparkline + bar chart generators
      core/, db/          # Config, logging, tracing, SQLAlchemy models
    migrations/           # Alembic
    tests/                # 41 unit + 12 live-eval
  frontend/
    app/                  # Next.js 15 App Router (7 routes)
    components/           # shell, workspace, ui primitives
    lib/                  # typed API client, utils
  infra/                  # docker-compose, Postgres bootstrap
```

## Resume blurb

> **AI Equity Research Platform** · Python · TypeScript · LangGraph · MCP · FastAPI · Next.js · Postgres + pgvector · Docker
> - Engineered a multi-agent LangGraph orchestration (SEC Filing, Financial, Risk, Competitor, Verification, Report Composer) over SEC EDGAR filings, exposing retrieval as reusable **MCP tools** and delivering investor-style reports with inline SVG sparklines and server-side PDF export via WeasyPrint.
> - Enforced **citation integrity** server-side: every answer's `chunk_id`s and quoted spans are intersected with the tool-call record from that run and fuzzy-matched against the source chunk text; failing answers are rejected before persistence.
> - Built a **deterministic Python layer over SEC XBRL** for revenue growth, margins, FCF, and CAGR; the Financial Agent narrates these pre-computed values with full provenance (XBRL concept, accession, filing date) — the LLM never does arithmetic.
> - Cut per-report LLM cost ~65% (**\$0.30 → \$0.10**) via a Sonnet/Haiku model split (Haiku for routing, planning, narration, and per-peer composers; Sonnet for final composition and nuanced ranking) plus an accession-keyed **report cache** that drops repeat-view latency from ~60s to ~15ms.
> - Shipped a dark-first Next.js + Tailwind workspace with chat-style conversation, live agent-execution rail, autocomplete over the full SEC public company universe (10,445 filers), on-demand ingestion, and LangSmith trace links per run.
> - **41 unit tests + 12 live-eval questions pass** against the running stack; zero citation-integrity rejections on the SEC Filing path, zero LLM arithmetic on the Financial path.

## License

MIT — see [LICENSE](LICENSE). Not investment advice.
