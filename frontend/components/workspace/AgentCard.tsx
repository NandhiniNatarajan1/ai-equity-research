"use client";

import {
  CheckCircle2,
  ChevronRight,
  Circle,
  CircleDashed,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type AgentStatus = "idle" | "running" | "completed" | "failed" | "skipped";

export type AgentCardProps = {
  name: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  status: AgentStatus;
  startedAt?: number | null;
  durationMs?: number | null;
  toolCalls?: number;
  evidenceCount?: number;
  details?: React.ReactNode;
  traceUrl?: string | null;
  error?: string | null;
};

const STATUS_META: Record<AgentStatus, { label: string; variant: "muted" | "accent" | "pos" | "neg"; Icon: typeof CheckCircle2 }> = {
  idle: { label: "Idle", variant: "muted", Icon: Circle },
  running: { label: "Running", variant: "accent", Icon: CircleDashed },
  completed: { label: "Completed", variant: "pos", Icon: CheckCircle2 },
  failed: { label: "Failed", variant: "neg", Icon: TriangleAlert },
  skipped: { label: "Skipped", variant: "muted", Icon: Circle },
};

function useElapsed(startedAt: number | null | undefined, running: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running || !startedAt) return;
    const id = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(id);
  }, [running, startedAt]);
  if (!startedAt) return 0;
  return Math.max(0, now - startedAt);
}

function formatMs(ms: number) {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function AgentCard(props: AgentCardProps) {
  const meta = STATUS_META[props.status];
  const Icon = props.icon;
  const StatusIcon = meta.Icon;
  const [open, setOpen] = useState(false);
  const elapsed = useElapsed(props.startedAt, props.status === "running");

  const timeLabel =
    props.status === "running"
      ? formatMs(elapsed)
      : props.durationMs != null
      ? formatMs(props.durationMs)
      : null;

  return (
    <div
      className={cn(
        "rounded-md border border-border bg-surface transition-colors",
        props.status === "running" && "border-accent/40 bg-accent/[0.03]",
        props.status === "failed" && "border-neg/40 bg-neg/[0.03]",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-3 px-3 py-2.5 text-left"
      >
        <div
          className={cn(
            "mt-0.5 flex size-7 items-center justify-center rounded-md border border-border bg-surfaceAlt text-fg",
            props.status === "running" && "border-accent/40 text-accent",
            props.status === "completed" && "text-fg",
            props.status === "failed" && "border-neg/40 text-neg",
          )}
        >
          <Icon className="size-3.5" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-fg">{props.name}</span>
            <Badge variant={meta.variant}>
              <StatusIcon
                className={cn("size-3", props.status === "running" && "animate-spin")}
              />
              {meta.label}
            </Badge>
            {timeLabel && (
              <span className="font-mono text-[11px] text-mutedFg tabnum">{timeLabel}</span>
            )}
            <ChevronRight
              className={cn(
                "ml-auto size-4 text-mutedFg transition-transform",
                open && "rotate-90",
              )}
            />
          </div>
          <p className="mt-0.5 text-xs text-mutedFg">{props.description}</p>

          {(props.toolCalls != null || props.evidenceCount != null) && (
            <div className="mt-1.5 flex items-center gap-3 text-[11px] text-mutedFg tabnum">
              {props.toolCalls != null && <span>{props.toolCalls} tool calls</span>}
              {props.evidenceCount != null && <span>{props.evidenceCount} passages</span>}
              {props.traceUrl && (
                <a
                  href={props.traceUrl}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="text-accent hover:underline"
                >
                  trace ↗
                </a>
              )}
            </div>
          )}

          {props.error && (
            <div className="mt-1 rounded border border-neg/40 bg-neg/10 px-2 py-1 text-[11px] text-neg">
              {props.error}
            </div>
          )}
        </div>
      </button>

      {open && props.details && (
        <div className="border-t border-border px-3 py-2 text-[11px] text-mutedFg animate-fade-in">
          {props.details}
        </div>
      )}
    </div>
  );
}
