"""Resolve any ticker symbol -> SEC CIK + company name.

Backed by SEC's public `company_tickers.json` file, which lists every
public filer with its ticker and CIK (~10,000 entries, ~1.5 MB). Cached
on disk for 24h; polite single refresh via our rate-limited EDGAR client.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.ingestion.edgar_client import EdgarClient

log = get_logger("companies.resolver")

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
CACHE_TTL_SECONDS = 24 * 3600


@dataclass(frozen=True)
class TickerHit:
    ticker: str  # upper-case
    cik: str  # zero-padded, 10 digits
    name: str


class TickerResolver:
    """Lazy cache around the SEC's company_tickers.json file."""

    _instance: "TickerResolver | None" = None

    @classmethod
    def shared(cls) -> "TickerResolver":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, edgar: EdgarClient | None = None) -> None:
        self._edgar_override = edgar
        s = get_settings()
        self._cache_path: Path = s.edgar_cache_dir / "company_tickers.json"
        self._mem_cache: list[TickerHit] | None = None
        self._mem_cached_at: float = 0.0

    # ----- cache plumbing ---------------------------------------------------
    def _parse(self, blob: dict) -> list[TickerHit]:
        """SEC file is {"0": {"cik_str": ..., "ticker": ..., "title": ...}, ...}."""
        out: list[TickerHit] = []
        for entry in blob.values():
            try:
                ticker = str(entry["ticker"]).upper().strip()
                cik = str(entry["cik_str"]).zfill(10)
                name = str(entry["title"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if ticker:
                out.append(TickerHit(ticker=ticker, cik=cik, name=name))
        return out

    def _load(self) -> list[TickerHit]:
        now = time.time()
        if self._mem_cache and now - self._mem_cached_at < CACHE_TTL_SECONDS:
            return self._mem_cache

        if self._cache_path.exists():
            try:
                mtime = self._cache_path.stat().st_mtime
                if now - mtime < CACHE_TTL_SECONDS:
                    blob = json.loads(self._cache_path.read_text(encoding="utf-8"))
                    hits = self._parse(blob)
                    log.info("ticker_cache_hit", source="disk", count=len(hits))
                    self._mem_cache = hits
                    self._mem_cached_at = mtime
                    return hits
            except Exception as exc:
                log.warning("ticker_cache_read_fail", error=str(exc))

        # Fetch fresh via the rate-limited EDGAR client.
        client = self._edgar_override or EdgarClient()
        try:
            raw = client.fetch(SEC_TICKERS_URL, use_cache=False)
        finally:
            if self._edgar_override is None:
                client.close()

        blob = json.loads(raw)
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_bytes(raw)
        hits = self._parse(blob)
        log.info("ticker_cache_refresh", count=len(hits))
        self._mem_cache = hits
        self._mem_cached_at = time.time()
        return hits

    # ----- public API -------------------------------------------------------
    def resolve(self, ticker: str) -> TickerHit | None:
        want = ticker.strip().upper()
        if not want:
            return None
        for h in self._load():
            if h.ticker == want:
                return h
        return None

    def search(self, query: str, *, limit: int = 20) -> list[TickerHit]:
        q = query.strip().upper()
        if not q:
            return []
        hits = self._load()

        # Score: exact ticker match > ticker prefix > ticker contains > name contains.
        scored: list[tuple[int, int, TickerHit]] = []
        for h in hits:
            name_u = h.name.upper()
            score: int | None = None
            if h.ticker == q:
                score = 0
            elif h.ticker.startswith(q):
                score = 1
            elif q in h.ticker:
                score = 2
            elif name_u.startswith(q):
                score = 3
            elif q in name_u:
                score = 4
            if score is not None:
                scored.append((score, len(h.ticker), h))
        scored.sort(key=lambda t: (t[0], t[1], t[2].ticker))
        return [h for _, _, h in scored[:limit]]
