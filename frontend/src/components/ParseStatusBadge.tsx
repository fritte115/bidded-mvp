import { cn } from "@/lib/utils";

export type DocumentParseStatus = "pending" | "parsing" | "parsed" | "parser_failed";

const LABELS: Record<DocumentParseStatus, string> = {
  pending: "Pending",
  parsing: "Parsing",
  parsed: "Parsed",
  parser_failed: "Failed",
};

export function ParseStatusBadge({
  status,
  className,
}: {
  status: DocumentParseStatus;
  className?: string;
}) {
  const tone =
    status === "parsed"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200"
      : status === "parser_failed"
        ? "border-destructive/40 bg-destructive/10 text-destructive"
        : status === "parsing"
          ? "border-info/40 bg-info/10 text-info"
          : "border-border bg-muted text-muted-foreground";

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        tone,
        className,
      )}
    >
      {LABELS[status]}
    </span>
  );
}
