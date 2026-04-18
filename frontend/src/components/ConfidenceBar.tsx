import { cn } from "@/lib/utils";

export function ConfidenceBar({
  value,
  showLabel = true,
  className,
}: {
  value: number;
  showLabel?: boolean;
  className?: string;
}) {
  const tone =
    value >= 75 ? "bg-success" : value >= 50 ? "bg-info" : value >= 30 ? "bg-warning" : "bg-danger";

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all", tone)}
          style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
        />
      </div>
      {showLabel && (
        <span className="font-mono text-xs tabular-nums text-muted-foreground">{value}%</span>
      )}
    </div>
  );
}
