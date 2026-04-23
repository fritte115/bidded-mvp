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
  const classes = cn(
    "inline-flex max-w-full items-center align-middle leading-normal",
    "rounded-md border border-border bg-secondary px-1.5 py-0.5 font-mono text-[11px] font-medium text-secondary-foreground",
    onClick &&
      "cursor-pointer hover:border-primary/40 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
    className,
  );

  if (onClick) {
    return (
      <button
        type="button"
        title={title ?? id}
        aria-label={`Open source for ${id}`}
        onClick={onClick}
        className={classes}
      >
        {id}
      </button>
    );
  }

  return (
    <span
      title={title ?? id}
      className={classes}
    >
      {id}
    </span>
  );
}
