import { cn } from "@/lib/utils";

export function EvidenceBadge({
  id,
  className,
  onClick,
}: {
  id: string;
  className?: string;
  onClick?: () => void;
}) {
  return (
    <span
      onClick={onClick}
      className={cn(
        "inline-flex items-center rounded-md border border-border bg-secondary px-1.5 py-0.5 font-mono text-[11px] font-medium text-secondary-foreground",
        onClick && "cursor-pointer hover:border-primary/40 hover:text-primary",
        className,
      )}
    >
      {id}
    </span>
  );
}
