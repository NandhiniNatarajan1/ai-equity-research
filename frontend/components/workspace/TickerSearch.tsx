"use client";

import { ChevronDown, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SystemCompany } from "@/lib/api";
import { getSystemStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  value: string;
  onChange: (ticker: string) => void;
};

export function TickerSearch({ value, onChange }: Props) {
  const [companies, setCompanies] = useState<SystemCompany[]>([]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getSystemStatus()
      .then((s) => setCompanies(s.companies))
      .catch(() => {});
  }, []);

  const selected = companies.find((c) => c.ticker === value) ?? null;

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return companies;
    return companies.filter(
      (c) => c.ticker.toLowerCase().includes(q) || c.name.toLowerCase().includes(q),
    );
  }, [companies, query]);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    window.addEventListener("mousedown", onDocClick);
    return () => window.removeEventListener("mousedown", onDocClick);
  }, [open]);

  function choose(ticker: string) {
    onChange(ticker);
    setOpen(false);
    setQuery("");
  }

  return (
    <div ref={panelRef} className="relative w-full max-w-md">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-3 rounded-md border border-border bg-surface px-3 py-2 text-left text-sm",
          "hover:border-ring/40",
        )}
      >
        <Search className="size-4 text-mutedFg" />
        {selected ? (
          <div className="flex min-w-0 flex-col leading-tight">
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-sm font-semibold text-fg">
                {selected.ticker}
              </span>
              <span className="truncate text-xs text-mutedFg">{selected.name}</span>
            </div>
            {selected.latest_filing && (
              <div className="text-[10px] text-mutedFg">
                {selected.latest_filing.form_type} ·{" "}
                {selected.latest_filing.filing_date.slice(0, 10)} ·{" "}
                {selected.chunk_count.toLocaleString()} chunks
              </div>
            )}
          </div>
        ) : (
          <span className="text-sm text-mutedFg">Search companies…</span>
        )}
        <ChevronDown className="ml-auto size-4 text-mutedFg" />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-md border border-border bg-surface shadow-xl animate-slide-in">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Search className="size-3.5 text-mutedFg" />
            <input
              autoFocus
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setCursor(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setCursor((c) => Math.min(c + 1, matches.length - 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setCursor((c) => Math.max(c - 1, 0));
                } else if (e.key === "Enter" && matches[cursor]) {
                  e.preventDefault();
                  choose(matches[cursor].ticker);
                } else if (e.key === "Escape") {
                  setOpen(false);
                }
              }}
              placeholder="Ticker or company name…"
              className="w-full bg-transparent text-sm outline-none placeholder:text-mutedFg"
            />
          </div>
          <ul className="max-h-64 overflow-y-auto py-1">
            {matches.length === 0 && (
              <li className="px-3 py-3 text-xs text-mutedFg">No companies match.</li>
            )}
            {matches.map((c, i) => (
              <li key={c.ticker}>
                <button
                  type="button"
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => choose(c.ticker)}
                  className={cn(
                    "flex w-full items-start gap-3 px-3 py-2 text-left",
                    cursor === i ? "bg-surfaceAlt" : "hover:bg-surfaceAlt",
                  )}
                >
                  <span className="mt-0.5 inline-flex min-w-[48px] justify-center rounded border border-border bg-bg px-1.5 py-0.5 font-mono text-xs font-semibold">
                    {c.ticker}
                  </span>
                  <span className="flex min-w-0 flex-col leading-tight">
                    <span className="truncate text-sm text-fg">{c.name}</span>
                    <span className="text-[10px] text-mutedFg">
                      {c.ingested ? "ingested" : "not ingested"}
                      {c.latest_filing &&
                        ` · ${c.latest_filing.form_type} ${c.latest_filing.filing_date.slice(0, 10)}`}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
