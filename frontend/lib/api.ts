export type Citation = {
  marker: string;
  chunk_id: string;
  quoted_text: string;
  section_item_code: string;
  section_title: string;
  filing_accession: string;
  filing_date: string;
  primary_doc_url: string;
};

export type FinancialFact = {
  concept: string;
  value: number;
  unit: string;
  fiscal_year: number;
  fiscal_period: string;
  end_date: string;
  filed: string;
  accession: string;
  form: string;
};

export type FinancialCitation = {
  marker: string;
  name: string;
  value: number | null;
  unit: string;
  period_label: string;
  narrative: string;
  inputs: FinancialFact[];
};

export type AskResponse = {
  run_id: string;
  ticker: string;
  question: string;
  route: "sec_filing" | "financial";
  route_reason: string | null;
  answer_markdown: string;
  citations: Citation[];
  financial_citations: FinancialCitation[];
  deferred: boolean;
  deferral_reason: string | null;
  trace_url: string | null;
};

export type ChunkDetail = {
  chunk_id: string;
  text: string;
  char_start: number;
  char_end: number;
  section: { item_code: string; title: string };
  filing: {
    accession: string;
    form_type: string;
    filing_date: string;
    primary_doc_url: string;
  };
};

export async function askResearch(ticker: string, question: string): Promise<AskResponse> {
  const r = await fetch("/api/research/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, question }),
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(`Research ask failed (${r.status}): ${detail}`);
  }
  return r.json();
}

export async function getChunk(chunkId: string): Promise<ChunkDetail> {
  const r = await fetch(`/api/chunks/${chunkId}`);
  if (!r.ok) throw new Error(`chunk fetch failed (${r.status})`);
  return r.json();
}

export type SystemCompany = {
  ticker: string;
  name: string;
  cik: string;
  ingested: boolean;
  latest_filing: {
    accession: string;
    form_type: string;
    filing_date: string;
    primary_doc_url: string;
  } | null;
  section_count: number;
  chunk_count: number;
};

export type SystemStatus = {
  companies: SystemCompany[];
  generated_at: string;
};

export async function getSystemStatus(): Promise<SystemStatus> {
  const r = await fetch("/api/system/status");
  if (!r.ok) throw new Error(`status fetch failed (${r.status})`);
  return r.json();
}

export type RunSummary = {
  run_id: string;
  ticker: string;
  question: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  trace_url: string | null;
  error: string | null;
  answer_preview: string;
  n_tool_calls: number;
};

export async function listRuns(limit = 25, ticker?: string): Promise<RunSummary[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (ticker) qs.set("ticker", ticker);
  const r = await fetch(`/api/runs?${qs.toString()}`);
  if (!r.ok) throw new Error(`runs fetch failed (${r.status})`);
  return r.json();
}
