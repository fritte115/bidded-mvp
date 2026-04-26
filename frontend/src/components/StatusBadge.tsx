import { cn } from "@/lib/utils";
import type { RunStatus } from "@/data/mock";

const styles: Record<RunStatus, string> = {
  pending: "bg-muted text-muted-foreground border-border",
  running: "bg-info/10 text-info border-info/30",
  succeeded: "bg-success/10 text-success border-success/30",
  failed: "bg-danger/10 text-danger border-danger/30",
  needs_human_review: "bg-warning/10 text-warning border-warning/30",
};

const labels: Record<RunStatus, string> = {
  pending: "Pending",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  needs_human_review: "Review",
};

export function StatusBadge({
  status,
  className,
  isStale = false,
}: {
  status: RunStatus;
  className?: string;
  isStale?: boolean;
}) {
  const toneStatus = isStale ? "failed" : status;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-xs font-medium",
        styles[toneStatus],
        className,
      )}
    >
      {status === "running" && !isStale && (
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-info opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-info" />
        </span>
      )}
      {(status !== "running" || isStale) && (
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            toneStatus === "pending" && "bg-muted-foreground",
            toneStatus === "succeeded" && "bg-success",
            toneStatus === "failed" && "bg-danger",
            toneStatus === "needs_human_review" && "bg-warning",
          )}
        />
      )}
      {isStale ? "Stale" : labels[status]}
    </span>
  );
}
