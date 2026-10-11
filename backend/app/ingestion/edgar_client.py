"""Polite SEC EDGAR client.

Fetches company 10-K filings. Respects EDGAR's requirements:
- Sends a descriptive User-Agent that identifies us and includes a contact email.
- Rate-limits to a conservative ~8 req/s (EDGAR's hard cap is 10).
- Caches downloaded bytes on disk, keyed by URL, under settings.edgar_cache_dir.

References:
  https://www.sec.gov/os/accessing-edgar-data
  https://data.sec.gov/submissions/CIK##########.json
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("ingestion.edgar")

EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


@dataclass(frozen=True)
class FilingRef:
    cik: str  # zero-padded, 10 digits
    accession: str  # with dashes, e.g. 0001045810-25-000147
    form_type: str
    filing_date: str  # ISO date
    primary_document: str  # filename within the accession dir
    report_date: str | None = None  # period of report

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def filing_index_url(self) -> str:
        return (
            f"{EDGAR_ARCHIVES_BASE}/{int(self.cik)}/{self.accession_nodash}/"
            f"{self.accession}-index.htm"
        )

    @property
    def primary_doc_url(self) -> str:
        return (
            f"{EDGAR_ARCHIVES_BASE}/{int(self.cik)}/{self.accession_nodash}/"
            f"{self.primary_document}"
        )


class RateLimiter:
    """Token-bucket-ish gate: at most N requests per second across threads."""

    def __init__(self, per_sec: int) -> None:
        self._interval = 1.0 / max(per_sec, 1)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                time.sleep(self._next_allowed - now)
                now = time.monotonic()
            self._next_allowed = now + self._interval


class EdgarClient:
    def __init__(
        self,
        user_agent: str | None = None,
        cache_dir: Path | None = None,
        per_sec: int | None = None,
        timeout: float = 30.0,
    ) -> None:
        s = get_settings()
        self._user_agent = user_agent or s.sec_user_agent
        self._cache_dir = cache_dir or s.edgar_cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._limiter = RateLimiter(per_sec or s.sec_rate_limit_per_sec)
        self._client = httpx.Client(
            headers={
                "User-Agent": self._user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Host-Hint": "sec.gov",
            },
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EdgarClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        before_sleep=before_sleep_log(log._logger, 30) if hasattr(log, "_logger") else None,  # type: ignore[arg-type]
    )
    def _get(self, url: str) -> bytes:
        self._limiter.wait()
        log.info("edgar_get", url=url)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.content

    def _cache_path(self, url: str) -> Path:
        key = hashlib.sha256(url.encode()).hexdigest()[:40]
        return self._cache_dir / key

    def fetch(self, url: str, *, use_cache: bool = True) -> bytes:
        path = self._cache_path(url)
        if use_cache and path.exists():
            return path.read_bytes()
        content = self._get(url)
        path.write_bytes(content)
        return content

    def get_submissions(self, cik: str) -> dict[str, Any]:
        """Return the submissions JSON for a CIK (zero-padded)."""
        url = EDGAR_SUBMISSIONS_URL.format(cik=cik)
        import json

        return json.loads(self.fetch(url))

    def latest_10k(self, cik: str) -> FilingRef:
        """Return a FilingRef for the most recent 10-K filing for this CIK."""
        data = self.get_submissions(cik)
        recent = data["filings"]["recent"]
        forms: list[str] = recent["form"]
        accessions: list[str] = recent["accessionNumber"]
        primary_docs: list[str] = recent["primaryDocument"]
        filing_dates: list[str] = recent["filingDate"]
        report_dates: list[str] = recent["reportDate"]
        for i, form in enumerate(forms):
            if form == "10-K":
                return FilingRef(
                    cik=cik,
                    accession=accessions[i],
                    form_type=form,
                    filing_date=filing_dates[i],
                    primary_document=primary_docs[i],
                    report_date=report_dates[i] or None,
                )
        raise LookupError(f"No 10-K found in recent filings for CIK {cik}")

    def fetch_primary_document(self, ref: FilingRef) -> bytes:
        return self.fetch(ref.primary_doc_url)
