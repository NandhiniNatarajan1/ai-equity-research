import { Construction } from "lucide-react";
import { TopBar } from "./TopBar";

export function PlaceholderScreen({
  title,
  description,
  nextUp,
}: {
  title: string;
  description: string;
  nextUp?: string;
}) {
  return (
    <>
      <TopBar title={title} subtitle={description} />
      <div className="flex flex-1 items-center justify-center p-8">
        <div className="max-w-md rounded-md border border-dashed border-border bg-surface/50 p-6 text-center">
          <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-full bg-warn/15 text-warn">
            <Construction className="size-5" />
          </div>
          <h3 className="text-sm font-semibold">Not yet shipped</h3>
          <p className="mt-1 text-xs text-mutedFg">
            This screen is scaffolded in the sidebar but hasn&apos;t been built out yet.
          </p>
          {nextUp && (
            <p className="mt-3 rounded border border-border bg-bg p-2 text-left text-[11px] text-mutedFg">
              <span className="font-semibold text-fg">Next up:</span> {nextUp}
            </p>
          )}
        </div>
      </div>
    </>
  );
}
