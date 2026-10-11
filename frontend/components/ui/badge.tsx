import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none",
  {
    variants: {
      variant: {
        default: "border-border bg-surfaceAlt text-fg",
        muted: "border-border bg-transparent text-mutedFg",
        accent: "border-accent/40 bg-accent/10 text-accent",
        pos: "border-pos/40 bg-pos/10 text-pos",
        neg: "border-neg/40 bg-neg/10 text-neg",
        warn: "border-warn/40 bg-warn/10 text-warn",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />;
}
