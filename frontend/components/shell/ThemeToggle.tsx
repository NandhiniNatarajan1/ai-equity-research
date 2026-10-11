"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

const options = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
] as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) {
    return <div className="h-8 w-24 rounded-md border border-border bg-surfaceAlt" />;
  }
  return (
    <div className="inline-flex items-center rounded-md border border-border bg-surfaceAlt p-0.5">
      {options.map((opt) => {
        const Icon = opt.icon;
        const active = theme === opt.value;
        return (
          <Button
            key={opt.value}
            variant="ghost"
            size="icon"
            onClick={() => setTheme(opt.value)}
            className={active ? "bg-bg text-fg shadow-sm" : "text-mutedFg"}
            title={opt.label}
            aria-label={opt.label}
          >
            <Icon className="size-3.5" />
          </Button>
        );
      })}
    </div>
  );
}
