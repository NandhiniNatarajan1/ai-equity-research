"use client";

import { CircleHelp, Github } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";

export function TopBar({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-surface/60 backdrop-blur-sm px-5">
      <div className="min-w-0">
        <h1 className="text-sm font-semibold tracking-tight text-fg">{title}</h1>
        {subtitle && <p className="truncate text-xs text-mutedFg">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">
        {right}
        <a
          href="https://github.com/anthropics/claude-code/issues"
          target="_blank"
          rel="noreferrer"
          className="inline-flex size-8 items-center justify-center rounded-md border border-border bg-surfaceAlt text-mutedFg hover:text-fg"
          title="Repo"
        >
          <Github className="size-3.5" />
        </a>
        <a
          href="/docs"
          target="_blank"
          rel="noreferrer"
          className="inline-flex size-8 items-center justify-center rounded-md border border-border bg-surfaceAlt text-mutedFg hover:text-fg"
          title="OpenAPI docs"
        >
          <CircleHelp className="size-3.5" />
        </a>
        <ThemeToggle />
      </div>
    </header>
  );
}
