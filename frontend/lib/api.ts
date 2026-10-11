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

export type AskResponse = {
  run_id: string;
  ticker: string;
  question: string;
  answer_markdown: string;
  citations: Citation[];
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
