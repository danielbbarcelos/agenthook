import { cn } from "@/lib/utils";

export type ServerStatus = "up-running" | "up" | "down" | "unknown";

/** The agenthook bolt — inline SVG so it themes via currentColor and stays
 *  crisp at any DPI. The webhook → agent "jolt" that names the product. */
export function Bolt({ className, live = false }: { className?: string; live?: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn(live && "bolt-live", className)}
      fill="currentColor"
      aria-hidden
    >
      <polygon points="13,2 4,14 10,14 8,22 20,9 13,9" />
    </svg>
  );
}

const STATUS_COLOR: Record<ServerStatus, string> = {
  "up-running": "text-primary",
  up: "text-primary",
  down: "text-muted-foreground",
  unknown: "text-muted-foreground",
};

/** Brand lockup: bolt mark + mono wordmark + control-plane tag. The bolt
 *  doubles as the live system indicator (signature element). */
export function Brand({
  status = "unknown",
  collapsed = false,
  className,
}: {
  status?: ServerStatus;
  collapsed?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <span
        className={cn(
          "grid h-8 w-8 shrink-0 place-items-center rounded-md border border-border bg-surface",
          STATUS_COLOR[status],
        )}
      >
        <Bolt className="h-[18px] w-[18px]" live={status === "up-running"} />
      </span>
      {!collapsed && (
        <span className="flex flex-col leading-none">
          <span className="text-[15px] font-bold tracking-tight text-foreground">agenthook</span>
          <span className="mt-1 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            control plane
          </span>
        </span>
      )}
    </div>
  );
}
