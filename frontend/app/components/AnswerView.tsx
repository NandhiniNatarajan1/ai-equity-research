"use client";

import { useState } from "react";
import type {
  AskResponse,
  Citation,
  ChunkDetail,
  FinancialCitation,
} from "@/lib/api";
import { getChunk } from "@/lib/api";

type Props = { result: AskResponse };

type Part = string | Citation | FinancialCitation;

function renderWithCitations(
  text: string,
  textual: Citation[],
  financial: FinancialCitation[],
): Part[] {
  const byMarker = new Map<string, Citation | FinancialCitation>();
  textual.forEach((c) => byMarker.set(c.marker, c));
  financial.forEach((c) => byMarker.set(c.marker, c));

  const parts: Part[] = [];
  const regex = /\[(?:metric:\s*[a-z0-9_]+|\d+)\]/gi;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const hit = byMarker.get(match[0]);
    parts.push(hit ?? match[0]);
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function formatValue(value: number | null, unit: string): string {
  if (value === null || Number.isNaN(value)) return "—";
  if (unit === "pct") return `${value.toFixed(2)}%`;
  if (unit === "USD") {
    const abs = Math.abs(value);
    const sign = value < 0 ? "-" : "";
    if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
    if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
    return `${sign}$${value.toLocaleString()}`;
  }
  return `${value}`;
}

function TextualChip({ cit }: { cit: Citation }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<ChunkDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !detail && !loading) {
      setLoading(true);
      try {
        setDetail(await getChunk(cit.chunk_id));
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <span className="relative inline-block align-baseline">
      <button
        type="button"
        onClick={toggle}
        className="mx-0.5 inline-flex items-center rounded border border-blue-300 bg-blue-50 px-1.5 py-0.5 text-xs font-medium text-blue-700 hover:bg-blue-100 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200 dark:hover:bg-blue-900"
        title={`Item ${cit.section_item_code} — ${cit.section_title}`}
      >
        {cit.marker}
      </button>
      {open && (
        <span className="absolute left-0 top-full z-20 mt-1 block w-[32rem] max-w-[80vw] rounded-md border border-neutral-200 bg-white p-3 text-sm shadow-lg dark:border-neutral-700 dark:bg-neutral-900">
          <span className="mb-1 block text-xs font-semibold text-neutral-500">
            Item {cit.section_item_code} — {cit.section_title}
            {" · "}
            <a
              href={cit.primary_doc_url}
              target="_blank"
              rel="noreferrer"
              className="underline hover:text-blue-600"
            >
              10-K {cit.filing_accession}
            </a>
          </span>
          <blockquote className="mb-2 border-l-2 border-neutral-300 pl-2 italic text-neutral-700 dark:border-neutral-600 dark:text-neutral-300">
            “{cit.quoted_text}”
          </blockquote>
          {loading && <span className="block text-xs text-neutral-500">Loading passage…</span>}
          {err && <span className="block text-xs text-red-600">{err}</span>}
          {detail && (
            <details className="text-xs text-neutral-600 dark:text-neutral-300">
              <summary className="cursor-pointer select-none">Show full chunk</summary>
              <p className="mt-2 whitespace-pre-wrap">{detail.text}</p>
            </details>
          )}
        </span>
      )}
    </span>
  );
}

function MetricChip({ cit }: { cit: FinancialCitation }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-block align-baseline">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="mx-0.5 inline-flex items-center rounded border border-emerald-300 bg-emerald-50 px-1.5 py-0.5 font-mono text-xs font-semibold text-emerald-800 hover:bg-emerald-100 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200 dark:hover:bg-emerald-900"
        title={cit.narrative}
      >
        {formatValue(cit.value, cit.unit)}
      </button>
      {open && (
        <span className="absolute left-0 top-full z-20 mt-1 block w-[32rem] max-w-[80vw] rounded-md border border-neutral-200 bg-white p-3 text-sm shadow-lg dark:border-neutral-700 dark:bg-neutral-900">
          <span className="mb-1 block text-xs font-semibold text-neutral-500">
            {cit.name} · {cit.period_label}
          </span>
          <p className="mb-2 text-neutral-700 dark:text-neutral-300">{cit.narrative}</p>
          <div className="rounded border border-neutral-200 bg-neutral-50 p-2 text-xs dark:border-neutral-700 dark:bg-neutral-800">
            <div className="mb-1 font-semibold uppercase tracking-wide text-neutral-500">
              XBRL inputs
            </div>
            <ul className="space-y-1">
              {cit.inputs.map((f, i) => (
                <li key={i} className="font-mono text-[11px]">
                  <span className="text-neutral-700 dark:text-neutral-300">
                    {f.concept}
                  </span>{" "}
                  <span className="text-neutral-500">
                    FY{f.fiscal_year}: {formatValue(f.value, f.unit)}
                  </span>{" "}
                  <span className="text-neutral-400">
                    (filed {f.filed}, {f.form} {f.accession})
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

function isTextual(c: Citation | FinancialCitation): c is Citation {
  return (c as Citation).chunk_id !== undefined;
}

export default function AnswerView({ result }: Props) {
  const parts = renderWithCitations(
    result.answer_markdown,
    result.citations,
    result.financial_citations,
  );
  const routeLabel =
    result.route === "financial" ? "Financial Agent" : "SEC Filing Agent";

  return (
    <section className="mt-6 space-y-4">
      <div className="flex items-center gap-2 text-xs text-neutral-500">
        <span
          className={
            "rounded-full border px-2 py-0.5 font-medium " +
            (result.route === "financial"
              ? "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
              : "border-blue-300 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200")
          }
        >
          {routeLabel}
        </span>
        {result.route_reason && <span>{result.route_reason}</span>}
      </div>

      {result.deferred && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100">
          <strong>Deferred.</strong>{" "}
          {result.deferral_reason ?? "This question is out of scope."}
        </div>
      )}

      <article className="prose prose-neutral max-w-none text-base leading-relaxed dark:prose-invert">
        <p>
          {parts.map((p, i) =>
            typeof p === "string" ? (
              <span key={i}>{p}</span>
            ) : isTextual(p) ? (
              <TextualChip key={i} cit={p} />
            ) : (
              <MetricChip key={i} cit={p} />
            )
          )}
        </p>
      </article>

      {result.citations.length > 0 && (
        <aside className="rounded-md border border-neutral-200 bg-neutral-50 p-4 text-sm dark:border-neutral-800 dark:bg-neutral-900">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
            Filing citations
          </h3>
          <ol className="list-decimal space-y-1 pl-5">
            {result.citations.map((c) => (
              <li key={c.chunk_id}>
                <a
                  href={c.primary_doc_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-blue-700 hover:underline dark:text-blue-300"
                >
                  Item {c.section_item_code} — {c.section_title}
                </a>{" "}
                <span className="text-neutral-500">
                  (10-K {c.filing_accession} · filed {c.filing_date.slice(0, 10)})
                </span>
              </li>
            ))}
          </ol>
        </aside>
      )}

      {result.financial_citations.length > 0 && (
        <aside className="rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm dark:border-emerald-900 dark:bg-emerald-950">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
            Deterministic metrics
          </h3>
          <ul className="space-y-2">
            {result.financial_citations.map((m) => (
              <li key={m.name}>
                <span className="font-mono font-semibold">
                  {formatValue(m.value, m.unit)}
                </span>{" "}
                <span className="font-medium">{m.name}</span>{" "}
                <span className="text-neutral-500">({m.period_label})</span>
                <span className="ml-1 text-neutral-600 dark:text-neutral-400">
                  — {m.narrative}
                </span>
              </li>
            ))}
          </ul>
        </aside>
      )}
    </section>
  );
}
