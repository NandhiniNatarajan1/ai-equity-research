"""Pydantic I/O contracts for the agents and the research API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    """One MCP tool invocation during an agent run."""

    tool: str
    arguments: dict
    returned_chunk_ids: list[str] = Field(default_factory=list)


class AnswerCitation(BaseModel):
    marker: str  # e.g. "[1]"
    chunk_id: str
    quoted_text: str


class AgentAnswer(BaseModel):
    """What the LLM is required to produce."""

    answer_markdown: str
    citations: list[AnswerCitation]
    deferred: bool = False
    deferral_reason: str | None = None


class ResearchAskRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    question: str = Field(min_length=3, max_length=2000)


class CitationOut(BaseModel):
    marker: str
    chunk_id: str
    quoted_text: str
    section_item_code: str
    section_title: str
    filing_accession: str
    filing_date: str
    primary_doc_url: str


class FinancialFactOut(BaseModel):
    """One XBRL fact that backed a computed metric."""

    concept: str
    value: float
    unit: str
    fiscal_year: int
    fiscal_period: str
    end_date: str
    filed: str
    accession: str
    form: str


class FinancialCitationOut(BaseModel):
    """A deterministic financial metric, with its inputs' provenance."""

    marker: str  # e.g. "[metric: revenue_yoy_growth]"
    name: str
    value: float | None
    unit: str
    period_label: str
    narrative: str
    inputs: list[FinancialFactOut]


class ResearchAskResponse(BaseModel):
    run_id: str
    ticker: str
    question: str
    route: str  # "sec_filing" | "financial"
    route_reason: str | None = None
    answer_markdown: str
    citations: list[CitationOut] = Field(default_factory=list)
    financial_citations: list[FinancialCitationOut] = Field(default_factory=list)
    deferred: bool = False
    deferral_reason: str | None = None
    trace_url: str | None = None
