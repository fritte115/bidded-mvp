import { cn } from "@/lib/utils";
import type { Verdict } from "@/data/mock";
import { verdictLabel, verdictLabelShort } from "@/data/mock";

const styles: Record<Verdict, string> = {
  BID: "bg-success/10 text-success border-success/30",
  NO_BID: "bg-danger/10 text-danger border-danger/30",
  CONDITIONAL_BID: "bg-warning/10 text-warning border-warning/30",
};

export function VerdictBadge({
  verdict,
  size = "sm",
  compact = false,
  className,
}: {
  verdict: Verdict;
  size?: "sm" | "md" | "lg";
  compact?: boolean;
  className?: string;
}) {
  return (
    <span
      title={verdictLabel[verdict]}
      className={cn(
        "inline-flex shrink-0 items-center whitespace-nowrap rounded-sm border font-semibold",
        size === "sm" && "px-2 py-0.5 text-[11px]",
        size === "md" && "px-2.5 py-1 text-xs",
        size === "lg" && "px-3 py-1.5 text-sm",
        styles[verdict],
        className,
      )}
    >
      {compact ? verdictLabelShort[verdict] : verdictLabel[verdict]}
    </span>
  );
}
