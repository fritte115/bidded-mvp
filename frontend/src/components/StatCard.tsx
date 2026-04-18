import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  className,
  compact = false,
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon?: LucideIcon;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-card",
        compact ? "px-3 py-2" : "p-4",
        className,
      )}
    >
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
        {Icon && <Icon className={cn("text-muted-foreground", compact ? "h-3.5 w-3.5" : "h-4 w-4")} />}
      </div>
      {compact ? (
        <div className="mt-1 flex items-baseline gap-2">
          <p className="text-lg font-semibold tabular-nums tracking-tight text-foreground">{value}</p>
          {hint && <p className="truncate text-[11px] text-muted-foreground">{hint}</p>}
        </div>
      ) : (
        <>
          <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight text-foreground">{value}</p>
          {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
        </>
      )}
    </div>
  );
}
