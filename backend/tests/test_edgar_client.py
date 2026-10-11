"""EDGAR client tests (no network)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.ingestion.edgar_client import EdgarClient, FilingRef, RateLimiter


def test_filing_ref_urls() -> None:
    ref = FilingRef(
        cik="0001045810",
        accession="0001045810-25-000147",
        form_type="10-K",
        filing_date="2025-02-26",
        primary_document="nvda-20250126.htm",
    )
    assert ref.accession_nodash == "000104581025000147"
    assert ref.primary_doc_url == (
        "https://www.sec.gov/Archives/edgar/data/1045810/"
        "000104581025000147/nvda-20250126.htm"
    )
    assert ref.filing_index_url.endswith("-index.htm")


def test_rate_limiter_spaces_calls() -> None:
    limiter = RateLimiter(per_sec=10)  # 100ms gap
    t0 = time.monotonic()
    for _ in range(3):
        limiter.wait()
    elapsed = time.monotonic() - t0
    # 3 waits = 2 enforced gaps ~= 200ms minimum.
    assert elapsed >= 0.18, f"expected >=180ms, got {elapsed * 1000:.1f}ms"


def test_latest_10k_from_submissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    submissions = {
        "filings": {
            "recent": {
                "form":            ["10-Q",    "10-K",    "8-K"],
                "accessionNumber": ["0000-24-1", "0001045810-25-000147", "0000-24-5"],
                "primaryDocument": ["q.htm",   "nvda-20250126.htm",     "k.htm"],
                "filingDate":      ["2024-09-01","2025-02-26",           "2024-11-01"],
                "reportDate":      ["2024-07-28","2025-01-26",           ""],
            }
        }
    }

    client = EdgarClient(cache_dir=tmp_path, per_sec=100)

    def fake_fetch(self: EdgarClient, url: str, *, use_cache: bool = True) -> bytes:  # noqa: ARG001
        return json.dumps(submissions).encode()

    monkeypatch.setattr(EdgarClient, "fetch", fake_fetch)

    ref = client.latest_10k("0001045810")
    assert ref.form_type == "10-K"
    assert ref.accession == "0001045810-25-000147"
    assert ref.primary_document == "nvda-20250126.htm"
    assert ref.report_date == "2025-01-26"


def test_disk_cache_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = EdgarClient(cache_dir=tmp_path, per_sec=100)
    calls: list[str] = []

    def fake_get(self: EdgarClient, url: str) -> bytes:  # noqa: ARG001
        calls.append(url)
        return b"hello"

    monkeypatch.setattr(EdgarClient, "_get", fake_get)

    url = "https://example.sec.gov/doc.htm"
    assert client.fetch(url) == b"hello"
    assert client.fetch(url) == b"hello"
    assert len(calls) == 1, "second fetch should hit the on-disk cache"
