import { Link } from "react-router-dom";
import { FileSearch } from "lucide-react";

import { EvidenceBadge } from "@/components/EvidenceBadge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import type { Evidence } from "@/data/mock";

function sourceTypeLabel(kind: Evidence["kind"] | undefined) {
  return kind === "company_profile" ? "Company" : "Tender";
}

function sourceTypeClass(kind: Evidence["kind"] | undefined) {
  return kind === "company_profile"
    ? "border-info/30 bg-info/10 text-info"
    : "border-border bg-secondary text-secondary-foreground";
}

function provenanceLabel(evidence: Evidence) {
  const kind = evidence.kind ?? "tender_document";
  if (kind === "company_profile" && evidence.companyFieldPath) {
    return evidence.companyFieldPath;
  }
  if (kind === "tender_document" && evidence.page > 0) {
    return `Page ${evidence.page}`;
  }
  return null;
}

export function CitationSourceSheet({
  open,
  onOpenChange,
  citationId,
  evidence,
  evidenceBoardHref,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  citationId: string | null;
  evidence: Evidence | null;
  evidenceBoardHref: string;
}) {
  const citedId = citationId ?? evidence?.id ?? "";
  const provenance = evidence ? provenanceLabel(evidence) : null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex h-full w-[92vw] flex-col overflow-y-auto p-0 sm:max-w-md"
      >
        <SheetHeader className="border-b border-border px-5 py-4">
          <SheetTitle>Citation source</SheetTitle>
          <SheetDescription>
            Excerpt-level source content from this run&apos;s evidence board.
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-5 px-5 py-5">
          <div className="flex flex-wrap items-center gap-2">
            <EvidenceBadge id={citedId} />
            {evidence && (
              <>
                <span
                  className={cn(
                    "inline-flex items-center rounded-sm border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                    sourceTypeClass(evidence.kind),
                  )}
                >
                  {sourceTypeLabel(evidence.kind)}
                </span>
                <span className="inline-flex items-center rounded-sm border border-border bg-secondary px-2 py-0.5 text-[11px] font-medium text-secondary-foreground">
                  {evidence.category}
                </span>
              </>
            )}
          </div>

          {evidence ? (
            <>
              <blockquote className="rounded-md border-l-2 border-primary bg-secondary/40 px-3 py-2.5 text-sm leading-relaxed text-foreground">
                &quot;{evidence.excerpt}&quot;
              </blockquote>

              <dl className="space-y-3 text-sm">
                <div>
                  <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Evidence key
                  </dt>
                  <dd className="mt-1 break-words font-mono text-xs text-foreground">
                    {evidence.key}
                  </dd>
                </div>

                <div>
                  <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Source
                  </dt>
                  <dd className="mt-1 break-words font-mono text-xs text-foreground">
                    {evidence.source}
                  </dd>
                </div>

                {provenance && (
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Location
                    </dt>
                    <dd className="mt-1 font-mono text-xs text-foreground">
                      {provenance}
                    </dd>
                  </div>
                )}

                {evidence.referencedBy.length > 0 && (
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Referenced by
                    </dt>
                    <dd className="mt-1 flex flex-wrap gap-1">
                      {evidence.referencedBy.map((agent) => (
                        <span
                          key={agent}
                          className="rounded-md border border-border bg-card px-2 py-1 text-xs text-muted-foreground"
                        >
                          {agent}
                        </span>
                      ))}
                    </dd>
                  </div>
                )}
              </dl>
            </>
          ) : (
            <div className="rounded-md border border-warning/30 bg-warning/5 px-3 py-2.5 text-sm">
              <p className="font-medium text-warning">
                Source not found in this run&apos;s evidence board.
              </p>
              <p className="mt-1 text-muted-foreground">
                The citation exists in an agent artifact, but no matching evidence item
                was loaded for this run.
              </p>
            </div>
          )}

          <Button asChild variant="outline" className="mt-auto w-full">
            <Link to={evidenceBoardHref}>
              <FileSearch className="h-4 w-4" /> Open Evidence Board
            </Link>
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
