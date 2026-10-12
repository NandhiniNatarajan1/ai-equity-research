"use client";

import { useEffect, useRef, useState } from "react";
import type { AskResponse, Citation, ChunkDetail, FinancialCitation } from "@/lib/api";
import { getChunk } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatPercent } from "@/lib/utils";

/** Plain-English label for a 10-K Item code. The short code is kept in parens so
 *  finance folks still see it. */
function sectionLabel(itemCode: string, fallbackTitle: string): { friendly: string; code: string } {
  const map: Record<string, string> = {
    "1": "Business overview",
    "1A": "Risk factors",
    "1B": "Unresolved staff comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal proceedings",
    "4": "Mine safety disclosures",
    "5": "Market for common equity",
    "6": "Reserved",
    "7": "Management's discussion",
    "7A": "Market risk disclosures",
    "8": "Financial statements",
    "9": "Changes in accountants",
    "9A": "Controls and procedures",
    "9B": "Other information",
    "9C": "Foreign jurisdiction disclosures",
    "10": "Directors and governance",
    "11": "Executive compensation",
    "12": "Security ownership",
    "13": "Related transactions",
    "14": "Principal accountant fees",
    "15": "Exhibits and schedules",
    "16": "Form 10-K summary",
    FULL: "Full annual report",
  };
  const friendly = map[itemCode.toUpperCase()] ?? fallbackTitle;
  return { friendly, code: itemCode.toUpperCase() };
}

/** Prefix the raw router reason with a plain-English intro of which agent answered. */
function routeIntro(route: "sec_filing" | "financial"): string {
  return route === "financial"
    ? "Answered by the Financial Agent — computes exact numbers from SEC data; no AI math."
    : "Answered by the SEC Filing Agent — reads filing text and quotes supporting passages.";
}

/** Close when the user clicks outside `ref` or hits Escape. */
function useDismiss(ref: React.RefObject<HTMLElement | null>, open: boolean, close: () => void) {
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, ref, close]);
}

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
  const ref = useRef<HTMLSpanElement>(null);
  useDismiss(ref, open, () => setOpen(false));

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
    <span ref={ref} className="relative inline-block align-baseline">
      <button
        type="button"
        onClick={toggle}
        className="mx-0.5 inline-flex items-center rounded border border-accent/40 bg-accent/10 px-1 py-0 text-[10px] font-medium text-accent hover:bg-accent/20"
        title={`${sectionLabel(cit.section_item_code, cit.section_title).friendly} (Item ${cit.section_item_code})`}
      >
        {cit.marker}
      </button>
      {open && (
        <span className="absolute left-0 top-full z-30 mt-1 block w-[28rem] max-w-[80vw] rounded-md border border-border bg-surface p-3 text-xs shadow-xl animate-slide-in">
          <span className="mb-1 flex items-center justify-between gap-2 text-[11px] text-mutedFg">
            <span>
              <span className="font-semibold text-fg">
                {sectionLabel(cit.section_item_code, cit.section_title).friendly}
              </span>{" "}
              <span className="text-mutedFg">(Item {cit.section_item_code})</span>
            </span>
            <a
              href={cit.primary_doc_url}
              target="_blank"
              rel="noreferrer"
              className="text-accent hover:underline"
            >
              Open on SEC.gov ↗
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
  const ref = useRef<HTMLSpanElement>(null);
  useDismiss(ref, open, () => setOpen(false));
  const label =
    cit.unit === "pct"
      ? formatPercent(cit.value)
      : cit.unit === "USD"
      ? formatCurrency(cit.value)
      : `${cit.value}`;
  return (
    <span ref={ref} className="relative inline-block align-baseline">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mx-0.5 inline-flex items-center rounded border border-pos/40 bg-pos/10 px-1 py-0 font-mono text-[11px] font-semibold text-pos hover:bg-pos/20"
      >
        {label}
      </button>
      {open && (
        <span className="absolute left-0 top-full z-30 mt-1 block w-[32rem] max-w-[80vw] rounded-md border border-border bg-surface p-3 text-xs shadow-xl animate-slide-in">
          <p className="text-sm text-fg">{cit.narrative}</p>
          <p className="mt-1 text-[11px] text-mutedFg">
            Computed in Python from exact numbers the company filed with the SEC — not generated
            by the AI model.
          </p>
          <details className="mt-2 rounded border border-border bg-surfaceAlt/50 p-2 text-[11px]">
            <summary className="cursor-pointer text-mutedFg">
              Source numbers (SEC XBRL)
            </summary>
            <ul className="mt-1 space-y-0.5 font-mono">
              {cit.inputs.map((f, i) => (
                <li key={i} className="text-mutedFg">
                  <span className="text-fg">{f.concept}</span>{" "}
                  <span>FY{f.fiscal_year}:</span>{" "}
                  <span className="text-pos">
                    {f.unit === "USD" ? formatCurrency(f.value) : f.value}
                  </span>{" "}
                  <span className="opacity-70">
                    (SEC filing #{f.accession}, filed {f.filed})
                  </span>
                </li>
              ))}
            </ul>
          </details>
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
          <span className="text-mutedFg">{routeIntro(result.route)}</span>
          {result.trace_url && (
            <a
              href={result.trace_url}
              target="_blank"
              rel="noreferrer"
              className="ml-auto text-accent hover:underline"
            >
              Developer trace ↗
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
