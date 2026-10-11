"""MCP server exposing the SEC filing retrieval tools.

Transport: streamable HTTP on 0.0.0.0:$MCP_PORT by default.
These tools are designed to be reused by every future agent (Financial, Risk,
Competitor, Report) — their shape is intentionally stable and provider-agnostic.
"""

from __future__ import annotations

import argparse
import asyncio

from mcp.server.mcpserver import MCPServer

from app.core.logging import configure_logging, get_logger
from app.mcp_server.tools import get_filing_section as _get_filing_section
from app.mcp_server.tools import get_financial_metrics as _get_financial_metrics
from app.mcp_server.tools import get_revenue_history as _get_revenue_history
from app.mcp_server.tools import search_filings as _search_filings

log = get_logger("mcp.server")

mcp = MCPServer(
    "ai-equity-research",
    instructions=(
        "Retrieval tools over SEC 10-K filings for a small MVP universe "
        "(NVDA, AMD, INTC). Always call these tools before answering a question "
        "about a company's business, risks, or MD&A; never invent citations."
    ),
)


@mcp.tool(
    name="search_filings",
    description=(
        "Semantic search over the latest ingested 10-K for a ticker. "
        "Returns the top-k chunks with cosine distance scores and full "
        "provenance (chunk_id, section item_code, accession, URL)."
    ),
)
def search_filings(
    ticker: str,
    query: str,
    k: int = 6,
    item_codes: list[str] | None = None,
) -> list[dict]:
    return _search_filings(ticker, query, k=k, item_codes=item_codes)


@mcp.tool(
    name="get_filing_section",
    description=(
        "Fetch the full text of a specific 10-K section (by Item code) for a "
        "ticker. Useful when the agent wants context around a retrieved chunk."
    ),
)
def get_filing_section(ticker: str, item_code: str, max_chars: int = 20000) -> dict:
    return _get_filing_section(ticker, item_code, max_chars=max_chars)


@mcp.tool(
    name="get_financial_metrics",
    description=(
        "Compute deterministic financial metrics (revenue growth, margins, "
        "FCF, etc.) for a ticker's latest fiscal year. Metrics are computed "
        "by pure Python over SEC XBRL facts — never by LLM arithmetic. The "
        "response includes the full provenance (concept, accession, filed "
        "date) of every input fact so the agent can cite the source."
    ),
)
def get_financial_metrics(ticker: str, metrics: list[str] | None = None) -> dict:
    return _get_financial_metrics(ticker, metrics=metrics)


@mcp.tool(
    name="get_revenue_history",
    description=(
        "Return the last N annual revenue values for a ticker, newest first, "
        "with full provenance (fiscal year, accession, filed date). Pulls "
        "directly from SEC Company Facts XBRL — no LLM arithmetic."
    ),
)
def get_revenue_history(ticker: str, years: int = 5) -> dict:
    return _get_revenue_history(ticker, years=years)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Equity Research MCP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--transport",
        choices=["streamable-http", "sse", "stdio"],
        default="streamable-http",
    )
    args = parser.parse_args()
    configure_logging()

    log.info("mcp_server_start", host=args.host, port=args.port, transport=args.transport)
    if args.transport == "stdio":
        asyncio.run(mcp.run_stdio_async())
    elif args.transport == "sse":
        asyncio.run(mcp.run_sse_async(host=args.host, port=args.port))
    else:
        asyncio.run(mcp.run_streamable_http_async(host=args.host, port=args.port))


if __name__ == "__main__":
    main()
