"use client";

import { useState } from "react";
import type { AskResponse, Citation, ChunkDetail } from "@/lib/api";
import { getChunk } from "@/lib/api";

type Props = { result: AskResponse };

function renderWithCitations(text: string, citations: Citation[]) {
  const byMarker = new Map(citations.map((c) => [c.marker, c]));
  const parts: Array<string | Citation> = [];
  const regex = /\[(\d+)\]/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    const marker = `[${match[1]}]`;
    if (match.index > last) parts.push(text.slice(last, match.index));
    const cit = byMarker.get(marker);
    if (cit) parts.push(cit);
    else parts.push(marker);
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function CitationChip({ cit }: { cit: Citation }) {
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

export default function AnswerView({ result }: Props) {
  const parts = renderWithCitations(result.answer_markdown, result.citations);
  return (
    <section className="mt-6 space-y-4">
      {result.deferred && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100">
          <strong>Deferred.</strong> {result.deferral_reason ?? "This question is out of scope for the SEC Filing Agent."}
        </div>
      )}
      <article className="prose prose-neutral max-w-none text-base leading-relaxed dark:prose-invert">
        <p>
          {parts.map((p, i) =>
            typeof p === "string" ? <span key={i}>{p}</span> : <CitationChip key={i} cit={p} />
          )}
        </p>
      </article>
      {result.citations.length > 0 && (
        <aside className="rounded-md border border-neutral-200 bg-neutral-50 p-4 text-sm dark:border-neutral-800 dark:bg-neutral-900">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
            Citations
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
    </section>
  );
}
