"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Loader2 } from "lucide-react";
import { TopBar } from "@/components/shell/TopBar";
import { Badge } from "@/components/ui/badge";
import { listRuns, type RunSummary } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

const STATUS_VARIANT: Record<string, "default" | "pos" | "warn" | "neg" | "accent" | "muted"> = {
  ok: "pos",
  no_data: "warn",
  citation_failed: "neg",
  error: "neg",
  running: "accent",
};

export default function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    listRuns(100)
      .then(setRuns)
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <>
      <TopBar
        title="Run History"
        subtitle="Every /research/ask invocation · click a trace link for the LangSmith run"
      />
      <div className="flex-1 overflow-auto p-5">
        {err && (
          <div className="mb-3 rounded-md border border-neg/40 bg-neg/10 p-3 text-xs text-neg">{err}</div>
        )}
        {runs === null && !err && (
          <div className="flex items-center gap-2 text-xs text-mutedFg">
            <Loader2 className="size-3.5 animate-spin" />
            Loading runs…
          </div>
        )}
        {runs && runs.length === 0 && (
          <div className="rounded-md border border-border bg-surface p-6 text-center text-xs text-mutedFg">
            No runs yet. Ask something in the Research Workspace to populate this.
          </div>
        )}
        {runs && runs.length > 0 && (
          <div className="overflow-hidden rounded-md border border-border bg-surface">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-surfaceAlt/50 text-left text-[10px] uppercase tracking-wider text-mutedFg">
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 font-semibold">Ticker</th>
                  <th className="px-3 py-2 font-semibold">Question</th>
                  <th className="px-3 py-2 font-semibold">Started</th>
                  <th className="px-3 py-2 font-semibold">Tools</th>
                  <th className="px-3 py-2 font-semibold">Trace</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr
                    key={r.run_id}
                    className="border-b border-border last:border-0 hover:bg-surfaceAlt/40"
                  >
                    <td className="px-3 py-2">
                      <Badge variant={STATUS_VARIANT[r.status] ?? "muted"}>{r.status}</Badge>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{r.ticker}</td>
                    <td className="px-3 py-2 text-xs">
                      <div className="line-clamp-1 text-fg">{r.question}</div>
                      {r.answer_preview && (
                        <div className="mt-0.5 line-clamp-1 text-mutedFg">{r.answer_preview}</div>
                      )}
                      {r.error && <div className="mt-0.5 text-neg">{r.error}</div>}
                    </td>
                    <td className="px-3 py-2 text-xs text-mutedFg tabnum">
                      {timeAgo(r.started_at)}
                    </td>
                    <td className="px-3 py-2 text-xs text-mutedFg tabnum">{r.n_tool_calls}</td>
                    <td className="px-3 py-2 text-xs">
                      {r.trace_url ? (
                        <a
                          href={r.trace_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-accent hover:underline"
                        >
                          open <ExternalLink className="size-3" />
                        </a>
                      ) : (
                        <span className="text-mutedFg">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
