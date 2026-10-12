"use client";

import { Check, ChevronDown, PlusCircle, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CompanySearchHit, SystemCompany } from "@/lib/api";
import { getSystemStatus, searchCompanies } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  value: string;
  onChange: (ticker: string) => void;
  /** Bumped by the parent after a successful ingestion so this control
   *  re-reads /system/status and shows the newly-loaded badge. */
  reloadKey?: number;
};

/** A single row in the dropdown: either a locally-ingested company or a
 *  SEC-wide search hit (which may or may not be loaded). */
type Row = {
  ticker: string;
  name: string;
  loaded: boolean;
  filingDate?: string;
};

function companyToRow(c: SystemCompany): Row {
  return {
    ticker: c.ticker,
    name: c.name,
    loaded: c.ingested,
    filingDate: c.latest_filing?.filing_date,
  };
}

function hitToRow(h: CompanySearchHit): Row {
  return {
    ticker: h.ticker,
    name: h.name,
    loaded: h.loaded,
    filingDate: h.latest_filing?.filing_date,
  };
}

export function TickerSearch({ value, onChange, reloadKey = 0 }: Props) {
  const [loaded, setLoaded] = useState<SystemCompany[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CompanySearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getSystemStatus()
      .then((s) => setLoaded(s.companies))
      .catch(() => {});
  }, [reloadKey]);

  const selected =
    loaded.find((c) => c.ticker === value) ??
    (value ? { ticker: value, name: value, ingested: false, latest_filing: null, cik: "", section_count: 0, chunk_count: 0 } as SystemCompany : null);

  // Debounce the remote search.
  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    if (!q) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    const id = window.setTimeout(async () => {
      try {
        setResults(await searchCompanies(q, 15));
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 180);
    return () => window.clearTimeout(id);
  }, [open, query]);

  // Click-outside and Escape.
  useEffect(() => {
    if (!open) return;
    function onDocMouse(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("mousedown", onDocMouse);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDocMouse);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Compose the rows: when the user is typing, show remote hits (which
  // already include a `loaded` flag). Otherwise show the loaded set.
  const rows: Row[] = useMemo(() => {
    if (query.trim()) {
      return results.map(hitToRow);
    }
    return loaded.map(companyToRow);
  }, [query, results, loaded]);

  const choose = useCallback(
    (ticker: string) => {
      onChange(ticker);
      setOpen(false);
      setQuery("");
    },
    [onChange],
  );

  return (
    <div ref={panelRef} className="relative w-full max-w-md">
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          setTimeout(() => inputRef.current?.focus(), 0);
        }}
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
            {selected.ingested && selected.latest_filing && (
              <div className="text-[10px] text-mutedFg">
                Loaded · Annual report {selected.latest_filing.filing_date.slice(0, 10)} ·{" "}
                {selected.chunk_count.toLocaleString()} passages
              </div>
            )}
            {!selected.ingested && (
              <div className="text-[10px] text-warn">Not loaded yet · open to load</div>
            )}
          </div>
        ) : (
          <span className="text-sm text-mutedFg">Search any public company…</span>
        )}
        <ChevronDown className="ml-auto size-4 text-mutedFg" />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-md border border-border bg-surface shadow-xl animate-slide-in">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Search className="size-3.5 text-mutedFg" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setCursor(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setCursor((c) => Math.min(c + 1, rows.length - 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setCursor((c) => Math.max(c - 1, 0));
                } else if (e.key === "Enter" && rows[cursor]) {
                  e.preventDefault();
                  choose(rows[cursor].ticker);
                }
              }}
              placeholder="Any ticker or company name (e.g. AAPL, MSFT, 'Tesla')…"
              className="w-full bg-transparent text-sm outline-none placeholder:text-mutedFg"
            />
          </div>
          <div className="flex items-center justify-between gap-2 border-b border-border bg-surfaceAlt/30 px-3 py-1.5 text-[10px] uppercase tracking-wide text-mutedFg">
            <span>
              {query.trim() ? "Search results · SEC filers" : "Already loaded"}
            </span>
            {searching && <span className="text-mutedFg">Searching…</span>}
          </div>
          <ul className="max-h-72 overflow-y-auto py-1">
            {rows.length === 0 && !searching && (
              <li className="px-3 py-4 text-xs text-mutedFg">
                {query.trim()
                  ? "No matches. SEC's public list only covers US-filing companies."
                  : "No companies loaded yet. Start typing a ticker above."}
              </li>
            )}
            {rows.map((r, i) => (
              <li key={r.ticker}>
                <button
                  type="button"
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => choose(r.ticker)}
                  className={cn(
                    "flex w-full items-start gap-3 px-3 py-2 text-left",
                    cursor === i ? "bg-surfaceAlt" : "hover:bg-surfaceAlt",
                  )}
                >
                  <span className="mt-0.5 inline-flex min-w-[56px] justify-center rounded border border-border bg-bg px-1.5 py-0.5 font-mono text-xs font-semibold">
                    {r.ticker}
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col leading-tight">
                    <span className="truncate text-sm text-fg">{r.name}</span>
                    <span className="text-[10px] text-mutedFg">
                      {r.loaded
                        ? r.filingDate
                          ? `Loaded · Annual report ${r.filingDate.slice(0, 10)}`
                          : "Loaded"
                        : "Not loaded — pick to load"}
                    </span>
                  </span>
                  <span className="mt-1 shrink-0">
                    {r.loaded ? (
                      <Check className="size-3.5 text-pos" aria-label="Loaded" />
                    ) : (
                      <PlusCircle className="size-3.5 text-mutedFg" aria-label="Not loaded" />
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="border-t border-border bg-surfaceAlt/30 px-3 py-1.5 text-[10px] text-mutedFg">
            Source: SEC public company list (updated daily)
          </div>
        </div>
      )}
    </div>
  );
}
