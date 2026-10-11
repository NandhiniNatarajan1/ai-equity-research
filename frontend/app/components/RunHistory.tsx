"use client";

import { useEffect, useState } from "react";
import { listRuns, type RunSummary } from "@/lib/api";

type Props = {
  refreshKey: number; // bump to force a refetch (e.g. after a new ask)
  ticker?: string;
};

const STATUS_STYLES: Record<string, string> = {
  ok: "border-green-300 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-950 dark:text-green-200",
  no_data: "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200",
  citation_failed: "border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200",
  error: "border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200",
  running: "border-blue-300 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200",
};

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const diff = (Date.now() - then) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function RunHistory({ refreshKey, ticker }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setRuns(await listRuns(10, ticker));
      } catch (e) {
        if (active) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      active = false;
    };
  }, [refreshKey, ticker]);

  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="text-xs text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
      >
        {open ? "▾ Hide history" : `▸ Recent runs (${runs.length})`}
      </button>
      {open && (
        <div className="mt-2 rounded-md border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
          {err && <div className="p-2 text-xs text-red-600">{err}</div>}
          {!err && runs.length === 0 && (
            <div className="p-3 text-xs text-neutral-500">No runs yet.</div>
          )}
          <ul className="divide-y divide-neutral-100 dark:divide-neutral-800">
            {runs.map((r) => (
              <li key={r.run_id} className="p-2 text-xs">
                <div className="flex items-center gap-2">
                  <span
                    className={
                      "rounded border px-1.5 py-0.5 font-medium " +
                      (STATUS_STYLES[r.status] ??
                        "border-neutral-300 bg-neutral-50 text-neutral-700 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300")
                    }
                  >
                    {r.status}
                  </span>
                  <span className="font-semibold">{r.ticker}</span>
                  <span className="text-neutral-500">{timeAgo(r.started_at)}</span>
                  {r.trace_url && (
                    <a
                      href={r.trace_url}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-auto text-blue-600 hover:underline dark:text-blue-400"
                    >
                      trace ↗
                    </a>
                  )}
                </div>
                <div className="mt-1 text-neutral-700 dark:text-neutral-300">
                  {r.question}
                </div>
                {r.answer_preview && (
                  <div className="mt-0.5 line-clamp-2 text-neutral-500">
                    {r.answer_preview}
                  </div>
                )}
                {r.error && (
                  <div className="mt-0.5 text-red-600 dark:text-red-400">
                    {r.error}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
