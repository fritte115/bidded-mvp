import { cn } from "@/lib/utils";
import { Check, Loader2, X, AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";

export type StepState = "completed" | "running" | "pending" | "failed" | "needs_human_review";

export function PipelineStep({
  index,
  title,
  state,
  children,
  isLast,
}: {
  index: number;
  title: string;
  state: StepState;
  children: ReactNode;
  isLast?: boolean;
}) {
  return (
    <div className="relative flex gap-4">
      <div className="flex flex-col items-center">
        <div
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 bg-card font-mono text-xs font-semibold",
            state === "completed" && "border-success text-success",
            state === "running" && "border-info text-info",
            state === "pending" && "border-border text-muted-foreground",
            state === "failed" && "border-danger text-danger",
            state === "needs_human_review" && "border-warning text-warning",
          )}
        >
          {state === "completed" ? (
            <Check className="h-4 w-4" />
          ) : state === "running" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : state === "failed" ? (
            <X className="h-4 w-4" />
          ) : state === "needs_human_review" ? (
            <AlertTriangle className="h-4 w-4" />
          ) : (
            index
          )}
        </div>
        {!isLast && (
          <div
            className={cn(
              "mt-1 w-px flex-1",
              state === "completed" ? "bg-success/40"
              : state === "failed" ? "bg-danger/40"
              : state === "needs_human_review" ? "bg-warning/40"
              : "bg-border",
            )}
          />
        )}
      </div>
      <div className={cn("flex-1 pb-10", isLast && "pb-0")}>
        <div className="mb-3 flex items-center gap-2">
          <h2 className="text-base font-semibold text-foreground">{title}</h2>
          <span
            className={cn(
              "inline-flex items-center rounded-sm border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide",
              state === "completed" && "border-success/30 bg-success/10 text-success",
              state === "running" && "border-info/30 bg-info/10 text-info",
              state === "pending" && "border-border bg-muted text-muted-foreground",
              state === "failed" && "border-danger/30 bg-danger/10 text-danger",
              state === "needs_human_review" && "border-warning/30 bg-warning/10 text-warning",
            )}
          >
            {state === "needs_human_review" ? "needs review" : state}
          </span>
        </div>
        {children}
      </div>
    </div>
  );
}
