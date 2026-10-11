"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def mini_10k_html() -> bytes:
    return (FIXTURES_DIR / "mini_10k.html").read_bytes()
