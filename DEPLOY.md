# Deploying the demo

Free-tier stack: **Vercel (frontend) + Render (backend + MCP) + Neon (Postgres)**.
Total cost at idle: $0. Expected cost per month under light demo traffic: $0.

> **Demo-mode guard.** Set `DEMO_MODE=true` on the backend (the Render blueprint
> already does this). It disables `/companies/{ticker}/ingest` and makes
> `/research/report/{ticker}` cache-only, so a hostile visitor can't drain
> your Anthropic / Voyage credits.

---

## 1. Push the repo to GitHub

```powershell
cd C:\Users\nandh\OneDrive\Desktop\Projects\ai-equity-research
gh repo create ai-equity-research --public --source=. --remote=origin --push
```

Note the GitHub URL — you'll paste it into Render + Vercel.

## 2. Create a Postgres with pgvector on Neon

1. Sign up at <https://neon.tech> (GitHub OAuth works).
2. Create project **ai-equity-research** in the region nearest you.
3. In the SQL editor, run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   CREATE EXTENSION IF NOT EXISTS pg_trgm;
   ```
4. Copy the **pooled connection string** (looks like
   `postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require`).
   Convert the scheme to `postgresql+psycopg://` for SQLAlchemy — you'll
   paste that into Render.

## 3. Deploy the backend on Render

1. Sign in at <https://dashboard.render.com> (GitHub OAuth).
2. **New → Blueprint**. Point it at your GitHub repo. Render will read
   `render.yaml` and offer to create two services: `aer-api` and `aer-mcp`.
3. When prompted for the sync-false env vars, paste:
   - `DATABASE_URL` = your Neon string (with `+psycopg`)
   - `ANTHROPIC_API_KEY` = your key
   - `VOYAGE_API_KEY` = your key
   - `LANGSMITH_API_KEY` = your key (optional)
4. First deploy builds the image (~5 min). Once the api service is live,
   run migrations from the Render shell:
   ```bash
   alembic upgrade head
   ```
5. Pre-warm the demo cache (optional but recommended — the free tier
   sleeps between requests, so the first visitor should hit a cache,
   not a cold ingestion):
   ```bash
   # From the api service shell:
   python -m app.ingestion.cli NVDA AMD INTC
   # Then open http://<your-api>.onrender.com/research/report/NVDA
   # (and the AMD / INTC equivalents) to populate the report cache.
   ```
   Each cached report file lives on the api service's disk, which is
   ephemeral on free tier — redeploys lose it. For a durable cache, use
   Render's paid persistent disk tier.
6. Note the public URL — e.g. `https://aer-api.onrender.com`.

## 4. Deploy the frontend on Vercel

1. Sign in at <https://vercel.com> (GitHub OAuth).
2. **Add New → Project**, pick your `ai-equity-research` repo.
3. Framework preset: **Next.js**. Root directory: `frontend`.
4. Environment variables:
   - `API_URL` = `https://aer-api.onrender.com` (your Render api URL)
5. Deploy. Vercel will build the Next.js app with that `API_URL` baked
   into the server-side rewrites, so `/api/*` on the frontend proxies to
   your Render backend.
6. In `frontend/app/workspace/page.tsx`, the "Open report" / "PDF" buttons
   point at `http://localhost:8000` for direct access. Change those two
   literal URLs to your Vercel-exposed `/api/research/report/{ticker}.html`
   and `/api/research/report/{ticker}/pdf` paths before pushing — or they
   won't work from the deployed frontend.
7. Vercel gives you `ai-equity-research.vercel.app`. Paste that into your
   README, your resume, and your GitHub profile.

## 5. Update the README with the live demo link

```markdown
Live demo: https://ai-equity-research.vercel.app
```

## Watching costs

- **Anthropic**: with `DEMO_MODE=true`, visitors can only generate the three
  pre-warmed reports (cache hits = free) and ask questions about them
  (~$0.03 each). Set a budget alert at <https://console.anthropic.com/settings/billing>.
- **Voyage**: 200M-token free tier; a demo won't come close.
- **Neon / Render / Vercel**: free tiers for all three.

## Common pitfalls

- **Render free tier sleeps after 15 min idle.** First visit cold-starts
  in 10-30 s. Add an uptime monitor (e.g. UptimeRobot pinging `/healthz`
  every 5 min) if you want always-on.
- **Rewrites bake at build time on Vercel.** If you change `API_URL`
  later, trigger a redeploy.
- **Report cache is ephemeral on Render free.** Redeploys wipe it. Either
  re-pre-warm after each deploy or use a paid persistent disk.
- **CORS**: the backend already allows `localhost:3000`. For production
  add your Vercel URL to the CORS allowlist in `backend/app/main.py`.
