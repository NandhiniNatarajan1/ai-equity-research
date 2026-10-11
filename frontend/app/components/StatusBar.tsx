"use client";

import { useEffect, useState } from "react";
import { getSystemStatus, type SystemCompany } from "@/lib/api";

export default function StatusBar() {
  const [companies, setCompanies] = useState<SystemCompany[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const s = await getSystemStatus();
        if (active) setCompanies(s.companies);
      } catch (e) {
        if (active) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (err) {
    return (
      <div className="text-xs text-red-600" title={err}>
        status unavailable
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="text-neutral-500">Ingested:</span>
      {companies.map((c) => (
        <span
          key={c.ticker}
          title={
            c.ingested
              ? `${c.name} — ${c.latest_filing?.form_type} ${c.latest_filing?.accession} · ${c.section_count} sections · ${c.chunk_count} chunks`
              : `${c.name} — not ingested`
          }
          className={
            "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium " +
            (c.ingested
              ? "border-green-300 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-950 dark:text-green-200"
              : "border-neutral-300 bg-neutral-50 text-neutral-600 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-400")
          }
        >
          <span
            className={
              "inline-block h-1.5 w-1.5 rounded-full " +
              (c.ingested ? "bg-green-500" : "bg-neutral-400")
            }
          />
          {c.ticker}
          {c.ingested && (
            <span className="text-[10px] opacity-60">
              {c.latest_filing?.filing_date.slice(0, 10)}
            </span>
          )}
        </span>
      ))}
    </div>
  );
}
