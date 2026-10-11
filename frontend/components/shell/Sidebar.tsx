"use client";

import {
  Activity,
  Building2,
  FileText,
  History,
  LayoutDashboard,
  Settings,
  Sparkles,
  Terminal,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  shortcut?: string;
};

const NAV: { heading?: string; items: NavItem[] }[] = [
  {
    items: [
      { href: "/workspace", label: "Overview", icon: LayoutDashboard, shortcut: "⇧O" },
      { href: "/workspace", label: "Research Workspace", icon: Sparkles, shortcut: "⇧R" },
    ],
  },
  {
    heading: "Data",
    items: [
      { href: "/companies", label: "Companies", icon: Building2 },
      { href: "/reports", label: "Reports", icon: FileText },
    ],
  },
  {
    heading: "Engineering",
    items: [
      { href: "/runs", label: "Run History", icon: History },
      { href: "/observability", label: "Observability", icon: Activity },
    ],
  },
  {
    heading: "Workspace",
    items: [{ href: "/settings", label: "Settings", icon: Settings }],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="hidden lg:flex h-full w-60 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex items-center gap-2 px-4 py-4 border-b border-border">
        <div className="flex size-7 items-center justify-center rounded-md bg-accent text-accentFg">
          <Terminal className="size-4" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">Equity Research</div>
          <div className="text-[10px] uppercase tracking-wider text-mutedFg">
            Multi-agent · MVP
          </div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {NAV.map((group, gi) => (
          <div key={gi} className="mb-4 last:mb-0">
            {group.heading && (
              <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-mutedFg">
                {group.heading}
              </div>
            )}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active =
                  item.href === "/workspace"
                    ? pathname === "/" || pathname.startsWith("/workspace")
                    : pathname.startsWith(item.href);
                const Icon = item.icon;
                return (
                  <li key={item.label}>
                    <Link
                      href={item.href}
                      className={cn(
                        "group flex items-center justify-between rounded-md px-2 py-1.5 text-sm transition-colors",
                        active
                          ? "bg-surfaceAlt text-fg"
                          : "text-mutedFg hover:bg-surfaceAlt hover:text-fg",
                      )}
                    >
                      <span className="flex items-center gap-2">
                        <Icon
                          className={cn(
                            "size-4 shrink-0",
                            active ? "text-accent" : "text-mutedFg group-hover:text-fg",
                          )}
                        />
                        {item.label}
                      </span>
                      {item.shortcut && (
                        <span className="font-mono text-[10px] text-mutedFg">
                          {item.shortcut}
                        </span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-border px-4 py-3 text-[10px] text-mutedFg">
        <div>v0.4 · milestone 4</div>
        <div className="mt-1">NVDA · AMD · INTC</div>
      </div>
    </aside>
  );
}
