import { cn } from "@/lib/utils";

export function EvidenceBadge({
  id,
  className,
  onClick,
  title,
}: {
  id: string;
  className?: string;
  onClick?: () => void;
  /** Optional tooltip for truncated or long keys */
  title?: string;
}) {
  return (
    <span
      title={title ?? id}
      onClick={onClick}
      className={cn(
        "inline-flex max-w-full items-center align-middle leading-normal",
        "rounded-md border border-border bg-secondary px-1.5 py-0.5 font-mono text-[11px] font-medium text-secondary-foreground",
        onClick && "cursor-pointer hover:border-primary/40 hover:text-primary",
        className,
      )}
    >
      {id}
    </span>
  );
}
