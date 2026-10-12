"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  CircleDashed,
  Clock,
  FileText,
  RotateCw,
} from "lucide-react";
import type { SystemCompany } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Status = "not_ingested" | "in_progress" | "ready" | "stale" | "failed";

function deriveStatus(c: SystemCompany | null): Status {
  if (!c) return "not_ingested";
  if (!c.ingested || !c.latest_filing) return "not_ingested";
  // Stale heuristic: filing older than ~400 days.
  const filingAt = new Date(c.latest_filing.filing_date).getTime();
  const ageDays = (Date.now() - filingAt) / (1000 * 60 * 60 * 24);
  if (ageDays > 400) return "stale";
  return "ready";
}

const STATUS_META: Record<
  Status,
  { label: string; icon: typeof CheckCircle2; variant: "default" | "pos" | "warn" | "neg" | "muted" }
> = {
  ready: { label: "Ready", icon: CheckCircle2, variant: "pos" },
  stale: { label: "Stale", icon: AlertTriangle, variant: "warn" },
  in_progress: { label: "Ingesting", icon: CircleDashed, variant: "accent" as "default" },
  not_ingested: { label: "Not ingested", icon: Circle, variant: "muted" },
  failed: { label: "Failed", icon: AlertTriangle, variant: "neg" },
};

export function FilingStatusCard({
  company,
  onRefresh,
}: {
  company: SystemCompany | null;
  onRefresh?: () => void;
}) {
  const status = deriveStatus(company);
  const meta = STATUS_META[status];
  const Icon = meta.icon;

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-md border border-border bg-surface px-4 py-3 text-sm">
      <div className="flex items-center gap-2">
        <FileText className="size-4 text-mutedFg" />
        <span className="text-xs font-semibold uppercase tracking-wider text-mutedFg">
          Latest annual report
        </span>
      </div>

      {company?.latest_filing ? (
        <>
          <span className="text-sm text-fg">
            {company.latest_filing.form_type === "10-K"
              ? "Annual report"
              : company.latest_filing.form_type}{" "}
            <span className="font-mono text-xs text-mutedFg">
              ({company.latest_filing.form_type})
            </span>
          </span>
          <span className="text-sm text-fg tabnum">
            {company.latest_filing.filing_date.slice(0, 10)}
          </span>
          <span className="text-xs text-mutedFg tabnum">
            {company.section_count} sections · {company.chunk_count.toLocaleString()} passages
          </span>
          <a
            href={company.latest_filing.primary_doc_url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-accent hover:underline"
          >
            open on SEC.gov ↗
          </a>
        </>
      ) : (
        <span className="text-sm text-mutedFg">No annual report loaded yet.</span>
      )}

      <Badge
        variant={meta.variant as "default" | "pos" | "warn" | "neg" | "muted" | "accent"}
        className="ml-auto"
      >
        <Icon
          className={cn(
            "size-3",
            status === "in_progress" && "animate-spin",
          )}
        />
        {meta.label}
      </Badge>

      <Button
        variant="outline"
        size="sm"
        onClick={onRefresh}
        disabled={!company}
        title="Re-fetch SEC EDGAR for a newer filing"
      >
        <RotateCw className="size-3.5" />
        Refresh
      </Button>
    </div>
  );
}
