"""yfinance wrapper for recent price history + current spot.

yfinance scrapes Yahoo Finance (unofficial, free). Rates can change intraday,
and the project doesn't persist price points — this is strictly for the
report's "stock snapshot" panel. If Yahoo blocks or rate-limits us, the
report just omits the panel.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger

log = get_logger("financial.price")


@dataclass(frozen=True)
class PriceSnapshot:
    ticker: str
    currency: str
    last_price: float
    change_1d_pct: float | None
    change_1y_pct: float | None
    history_1y_closes: list[float]  # newest-last; downsampled to ~52 points


def _downsample(xs: list[float], max_points: int = 52) -> list[float]:
    if len(xs) <= max_points:
        return xs
    step = len(xs) / max_points
    return [xs[int(i * step)] for i in range(max_points)]


def fetch_price_snapshot(ticker: str) -> PriceSnapshot | None:
    """Fetch 1Y price history. Returns None on any failure (never raises)."""
    try:
        import yfinance as yf
    except Exception as exc:
        log.warning("yfinance_import_failed", error=str(exc))
        return None

    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1y", auto_adjust=True)
    except Exception as exc:
        log.warning("yfinance_fetch_failed", ticker=ticker, error=str(exc))
        return None

    if hist is None or hist.empty:
        log.info("yfinance_empty", ticker=ticker)
        return None

    closes_raw = [float(v) for v in hist["Close"].tolist() if v is not None]
    if not closes_raw:
        return None

    last = closes_raw[-1]
    prev = closes_raw[-2] if len(closes_raw) > 1 else None
    first = closes_raw[0]

    def _pct(a: float, b: float) -> float | None:
        if b == 0:
            return None
        return (a - b) / b * 100.0

    try:
        currency = str(getattr(t, "fast_info", {}).get("currency") or "USD")
    except Exception:
        currency = "USD"

    return PriceSnapshot(
        ticker=ticker.upper(),
        currency=currency,
        last_price=round(last, 2),
        change_1d_pct=round(_pct(last, prev), 2) if prev is not None else None,
        change_1y_pct=round(_pct(last, first), 2) if first else None,
        history_1y_closes=_downsample(closes_raw, max_points=52),
    )
