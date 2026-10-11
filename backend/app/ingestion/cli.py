"""Ingestion CLI.

    python -m app.ingestion.cli NVDA AMD INTC
"""

from __future__ import annotations

import json

import typer

from app.core.logging import configure_logging, get_logger
from app.ingestion.pipeline import ingest_ticker

log = get_logger("ingestion.cli")


def ingest(
    tickers: list[str] = typer.Argument(..., help="Tickers to ingest, e.g. NVDA AMD INTC"),
) -> None:
    """Fetch, parse, chunk, embed, and store the latest 10-K for each ticker."""
    configure_logging()
    results = []
    for ticker in tickers:
        # Guard: don't let a stray subcommand name like "ingest" be treated as a ticker.
        if ticker.lower() == "ingest":
            continue
        try:
            result = ingest_ticker(ticker)
            results.append(result)
            log.info("ingest_done", **{k: v for k, v in result.items() if v is not None})
        except Exception as exc:
            log.exception("ingest_failed", ticker=ticker, error=str(exc))
            results.append({"ticker": ticker, "status": "error", "error": str(exc)})
    typer.echo(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    typer.run(ingest)
