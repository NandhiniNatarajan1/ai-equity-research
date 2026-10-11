"""Seed the three MVP companies: NVIDIA, AMD, Intel.

Revision ID: 0002_seed_companies
Revises: 0001_initial
Create Date: 2026-10-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_seed_companies"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COMPANIES = [
    # CIK is zero-padded to 10 digits (SEC convention). SIC 3674 = semiconductors.
    ("0001045810", "NVDA", "NVIDIA CORP", "3674"),
    ("0000002488", "AMD", "ADVANCED MICRO DEVICES INC", "3674"),
    ("0000050863", "INTC", "INTEL CORP", "3674"),
]


def upgrade() -> None:
    for cik, ticker, name, sic in COMPANIES:
        op.execute(
            "INSERT INTO companies (cik, ticker, name, sic) VALUES "
            f"('{cik}', '{ticker}', '{name}', '{sic}') "
            "ON CONFLICT (cik) DO NOTHING"
        )


def downgrade() -> None:
    for cik, _, _, _ in COMPANIES:
        op.execute(f"DELETE FROM companies WHERE cik = '{cik}'")
