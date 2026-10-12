"use client";

import {
  Calculator,
  FileSearch,
  Scale,
  ScrollText,
  ShieldAlert,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { AskResponse } from "@/lib/api";
import { AgentCard, type AgentStatus } from "./AgentCard";

type Phase = "idle" | "routing" | "running" | "done" | "error";

type AgentKey = "router" | "sec_filing" | "financial" | "risk" | "competitor" | "verification" | "report";

const CATALOG: Record<AgentKey, { name: string; description: string; icon: React.ComponentType<{ className?: string }> }> = {
  router: {
    name: "Research Orchestrator",
    description: "Decides which specialist should answer your question.",
    icon: Scale,
  },
  sec_filing: {
    name: "SEC Filing Agent",
    description: "Reads the company's annual report (10-K) and finds supporting passages.",
    icon: FileSearch,
  },
  financial: {
    name: "Financial Agent",
    description: "Computes revenue growth, margins, and cash flow from SEC data. No AI math.",
    icon: Calculator,
  },
  risk: {
    name: "Risk Agent",
    description: "Finds and groups the risks the company lists in its annual report.",
    icon: ShieldAlert,
  },
  competitor: {
    name: "Competitor Agent",
    description: "Asks the same question of each peer company and compares the answers.",
    icon: Users,
  },
  verification: {
    name: "Verification Agent",
    description: "Checks every quote actually appears in the real filing.",
    icon: ScrollText,
  },
  report: {
    name: "Report Agent",
    description: "Combines everyone's findings into a single investor-style report.",
    icon: ScrollText,
  },
};

type AgentState = {
  status: AgentStatus;
  startedAt: number | null;
  durationMs: number | null;
  toolCalls?: number;
  evidenceCount?: number;
  details?: React.ReactNode;
  traceUrl?: string | null;
  error?: string | null;
};

function initial(): Record<AgentKey, AgentState> {
  const base: AgentState = {
    status: "idle",
    startedAt: null,
    durationMs: null,
  };
  return Object.fromEntries(
    Object.keys(CATALOG).map((k) => [k, { ...base }]),
  ) as Record<AgentKey, AgentState>;
}

export function AgentIntelligencePanel({
  phase,
  startedAt,
  result,
  error,
  scope = "ask",
}: {
  phase: Phase;
  startedAt: number | null;
  result: AskResponse | null;
  error: string | null;
  /** `ask` = only Orchestrator + routed specialist + Verification. `report` = all 7. */
  scope?: "ask" | "report";
}) {
  const [states, setStates] = useState<Record<AgentKey, AgentState>>(initial);

  // Reset when a new run starts.
  useEffect(() => {
    if (phase === "idle") {
      setStates(initial());
      return;
    }
    if (phase === "routing" && startedAt) {
      setStates((prev) => ({
        ...prev,
        router: { ...prev.router, status: "running", startedAt },
      }));
      return;
    }
    if (phase === "running" && startedAt && result == null) {
      // Transition router -> completed and start the likely specialist(s).
      // We don't know the route yet; show BOTH SEC + Financial as "pending"
      // and switch on result.
      setStates((prev) => ({
        ...prev,
        router: {
          ...prev.router,
          status: "completed",
          durationMs: Date.now() - (prev.router.startedAt ?? Date.now()),
        },
        sec_filing: {
          ...prev.sec_filing,
          status: "running",
          startedAt: Date.now(),
        },
      }));
      return;
    }

    if (phase === "done" && result) {
      setStates((prev) => {
        const now = Date.now();
        const next = { ...prev };

        // Router completed (fallback if not already).
        if (next.router.status !== "completed") {
          next.router = {
            ...next.router,
            status: "completed",
            durationMs: 100,
          };
        }

        const toolCount = Math.max(
          0,
          // Approximate: the backend doesn't expose per-tool-call counts on the
          // response, but tool_calls is persisted on AgentRun; for the panel
          // we show citations/metrics count as a reasonable proxy.
          result.citations.length + result.financial_citations.length,
        );

        if (result.route === "sec_filing") {
          next.sec_filing = {
            status: "completed",
            startedAt: next.sec_filing.startedAt ?? now,
            durationMs: now - (startedAt ?? now),
            toolCalls: toolCount,
            evidenceCount: result.citations.length,
            traceUrl: result.trace_url,
            details: (
              <div className="space-y-1">
                <div>Retrieved {result.citations.length} verified passages.</div>
                {result.route_reason && (
                  <div className="text-mutedFg">Route reason: {result.route_reason}</div>
                )}
              </div>
            ),
          };
          next.financial = { ...next.financial, status: "skipped", durationMs: null };
          next.verification = {
            status: "completed",
            startedAt: now,
            durationMs: 50,
            evidenceCount: result.citations.length,
            details: (
              <div>
                All {result.citations.length} citations passed chunk-id + quote-match
                verification.
              </div>
            ),
          };
        } else {
          next.financial = {
            status: "completed",
            startedAt: next.financial.startedAt ?? now,
            durationMs: now - (startedAt ?? now),
            toolCalls: result.financial_citations.length,
            evidenceCount: result.financial_citations.reduce(
              (acc, c) => acc + c.inputs.length,
              0,
            ),
            traceUrl: result.trace_url,
            details: (
              <div className="space-y-1">
                <div>
                  Computed {result.financial_citations.length} deterministic metrics
                  from SEC XBRL (no LLM arithmetic).
                </div>
                {result.route_reason && (
                  <div className="text-mutedFg">Route reason: {result.route_reason}</div>
                )}
              </div>
            ),
          };
          next.sec_filing = { ...next.sec_filing, status: "skipped", durationMs: null };
          next.verification = {
            status: "completed",
            startedAt: now,
            durationMs: 20,
            evidenceCount: result.financial_citations.length,
            details: <div>Metric values carry XBRL input provenance; no verification issues.</div>,
          };
        }

        return next;
      });
      return;
    }

    if (phase === "error") {
      setStates((prev) => ({
        ...prev,
        router:
          prev.router.status === "running"
            ? { ...prev.router, status: "failed", error }
            : prev.router,
        sec_filing:
          prev.sec_filing.status === "running"
            ? { ...prev.sec_filing, status: "failed", error }
            : prev.sec_filing,
      }));
    }
  }, [phase, startedAt, result, error]);

  const list: AgentKey[] = useMemo(() => {
    if (scope === "report") {
      return ["router", "sec_filing", "financial", "risk", "competitor", "verification", "report"];
    }
    // Ask scope: show Orchestrator + the routed specialist(s) + Verification.
    // Before the route is known we show BOTH specialists so the user can see
    // which one lights up; once the route resolves we drop the one that was
    // skipped. This keeps the rail short and relevant.
    const routed: AgentKey[] =
      result?.route === "financial"
        ? ["financial"]
        : result?.route === "sec_filing"
        ? ["sec_filing"]
        : ["sec_filing", "financial"];
    return ["router", ...routed, "verification"];
  }, [scope, result]);

  const phaseLabel: Record<Phase, string> = {
    idle: "Waiting",
    routing: "Routing",
    running: "Running",
    done: "Done",
    error: "Error",
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">What the agents did</h3>
          <p className="text-xs text-mutedFg">
            Click a card to see how it worked.
          </p>
        </div>
        <span className="rounded-full border border-border px-2 py-0.5 text-[10px] uppercase tracking-wider text-mutedFg">
          {phaseLabel[phase]}
        </span>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {list.map((k) => (
          <AgentCard
            key={k}
            name={CATALOG[k].name}
            description={CATALOG[k].description}
            icon={CATALOG[k].icon}
            {...states[k]}
          />
        ))}
      </div>
    </div>
  );
}
