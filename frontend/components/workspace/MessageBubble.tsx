"use client";

import { useState } from "react";
import type { AskResponse, Citation, ChunkDetail, FinancialCitation } from "@/lib/api";
import { getChunk } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatPercent } from "@/lib/utils";

type Part = string | Citation | FinancialCitation;

function renderParts(text: string, textual: Citation[], financial: FinancialCitation[]): Part[] {
  const byMarker = new Map<string, Citation | FinancialCitation>();
  textual.forEach((c) => byMarker.set(c.marker, c));
  financial.forEach((c) => byMarker.set(c.marker, c));
  const regex = /\[(?:metric:\s*[a-z0-9_]+|\d+)\]/gi;
  const parts: Part[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push(byMarker.get(m[0]) ?? m[0]);
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function isFinancial(c: Citation | FinancialCitation): c is FinancialCitation {
  return (c as FinancialCitation).inputs !== undefined;
}

function CitationChip({ cit }: { cit: Citation }) {
  const [open, setOpen] = useState(false);
  const [chunk, setChunk] = useState<ChunkDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function toggle() {
    setOpen((v) => !v);
    if (!chunk && !err) {
      try {
        setChunk(await getChunk(cit.chunk_id));
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    }
  }

  return (
    <span className="relative inline-block align-baseline">
      <button
        type="button"
        onClick={toggle}
        className="mx-0.5 inline-flex items-center rounded border border-accent/40 bg-accent/10 px-1 py-0 text-[10px] font-medium text-accent hover:bg-accent/20"
        title={`Item ${cit.section_item_code} — ${cit.section_title}`}
      >
        {cit.marker}
      </button>
      {open && (
        <span className="absolute left-0 top-full z-30 mt-1 block w-[28rem] max-w-[80vw] rounded-md border border-border bg-surface p-3 text-xs shadow-xl animate-slide-in">
          <span className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wide text-mutedFg">
            <span>
              Item {cit.section_item_code} — {cit.section_title}
            </span>
            <a
              href={cit.primary_doc_url}
              target="_blank"
              rel="noreferrer"
              className="text-accent hover:underline"
            >
              SEC ↗
            </a>
          </span>
          <blockquote className="border-l-2 border-border pl-2 italic text-fg">
            “{cit.quoted_text}”
          </blockquote>
          {err && <div className="mt-2 text-neg">{err}</div>}
          {chunk && (
            <details className="mt-2 text-mutedFg">
              <summary className="cursor-pointer">Show full chunk</summary>
              <p className="mt-1 whitespace-pre-wrap text-[11px]">{chunk.text}</p>
            </details>
          )}
        </span>
      )}
    </span>
  );
}

function MetricChip({ cit }: { cit: FinancialCitation }) {
  const [open, setOpen] = useState(false);
  const label =
    cit.unit === "pct"
      ? formatPercent(cit.value)
      : cit.unit === "USD"
      ? formatCurrency(cit.value)
      : `${cit.value}`;
  return (
    <span className="relative inline-block align-baseline">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mx-0.5 inline-flex items-center rounded border border-pos/40 bg-pos/10 px-1 py-0 font-mono text-[11px] font-semibold text-pos hover:bg-pos/20"
      >
        {label}
      </button>
      {open && (
        <span className="absolute left-0 top-full z-30 mt-1 block w-[32rem] max-w-[80vw] rounded-md border border-border bg-surface p-3 text-xs shadow-xl animate-slide-in">
          <span className="mb-1 block text-[10px] uppercase tracking-wide text-mutedFg">
            {cit.name} · {cit.period_label}
          </span>
          <p className="mb-2 text-fg">{cit.narrative}</p>
          <div className="rounded border border-border bg-surfaceAlt/50 p-2">
            <div className="mb-1 text-[10px] uppercase tracking-wide text-mutedFg">
              XBRL inputs
            </div>
            <ul className="space-y-0.5 font-mono text-[11px]">
              {cit.inputs.map((f, i) => (
                <li key={i} className="text-mutedFg">
                  <span className="text-fg">{f.concept}</span>{" "}
                  <span>FY{f.fiscal_year}:</span>{" "}
                  <span className="text-pos">
                    {f.unit === "USD" ? formatCurrency(f.value) : f.value}
                  </span>{" "}
                  <span className="opacity-70">
                    ({f.form} {f.accession}, filed {f.filed})
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </span>
      )}
    </span>
  );
}

export function AnswerBubble({ result }: { result: AskResponse }) {
  const parts = renderParts(result.answer_markdown, result.citations, result.financial_citations);

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-surfaceAlt text-[10px] font-semibold text-accent">
        AI
      </div>
      <div className="min-w-0 flex-1 space-y-2 text-sm leading-relaxed">
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-mutedFg">
          <Badge variant={result.route === "financial" ? "pos" : "accent"}>
            {result.route === "financial" ? "Financial Agent" : "SEC Filing Agent"}
          </Badge>
          {result.route_reason && <span className="truncate">{result.route_reason}</span>}
          {result.trace_url && (
            <a
              href={result.trace_url}
              target="_blank"
              rel="noreferrer"
              className="ml-auto text-accent hover:underline"
            >
              LangSmith trace ↗
            </a>
          )}
        </div>

        {result.deferred && (
          <div className="rounded-md border border-warn/40 bg-warn/10 p-2 text-xs text-warn">
            <strong>Deferred.</strong>{" "}
            {result.deferral_reason ?? "This question is out of scope."}
          </div>
        )}

        <p className="text-fg">
          {parts.map((p, i) =>
            typeof p === "string" ? (
              <span key={i}>{p}</span>
            ) : isFinancial(p) ? (
              <MetricChip key={i} cit={p} />
            ) : (
              <CitationChip key={i} cit={p} />
            ),
          )}
        </p>
      </div>
    </div>
  );
}

export function QuestionBubble({ ticker, question }: { ticker: string; question: string }) {
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-surfaceAlt text-[10px] font-semibold text-mutedFg">
        YOU
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="text-[11px] text-mutedFg">
          <span className="font-mono text-accent">{ticker}</span>
        </div>
        <p className="text-sm text-fg">{question}</p>
      </div>
    </div>
  );
}
