import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, ExternalLink, FileCheck2, Paperclip, WandSparkles } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { EvidenceBadge } from "@/components/EvidenceBadge";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchLatestBidDraft, fetchRunDetail, generateBidDraft } from "@/lib/api";
import { formatSEK } from "@/lib/bidEstimator";
import { cn } from "@/lib/utils";
import type { BidDraftAnswerStatus, BidDraftAttachmentStatus } from "@/data/mock";

const answerTone: Record<BidDraftAnswerStatus, string> = {
  drafted: "border-success/30 bg-success/10 text-success",
  needs_input: "border-warning/30 bg-warning/10 text-warning",
  blocked: "border-danger/30 bg-danger/10 text-danger",
  not_applicable: "border-muted bg-muted text-muted-foreground",
};

const attachmentTone: Record<BidDraftAttachmentStatus, string> = {
  attached: "border-success/30 bg-success/10 text-success",
  suggested: "border-info/30 bg-info/10 text-info",
  missing: "border-danger/30 bg-danger/10 text-danger",
  needs_review: "border-warning/30 bg-warning/10 text-warning",
};

export default function BidDraft() {
  const { runId = "" } = useParams();
  const queryClient = useQueryClient();

  const { data: run } = useQuery({
    queryKey: ["run-detail", runId],
    queryFn: () => fetchRunDetail(runId),
    enabled: !!runId,
  });

  const { data: draft = null, isLoading } = useQuery({
    queryKey: ["bid-draft", runId],
    queryFn: () => fetchLatestBidDraft(runId),
    enabled: !!runId,
  });

  const generate = useMutation({
    mutationFn: () => generateBidDraft(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bid-draft", runId] });
      toast.success("Draft response generated");
    },
    onError: (error) => {
      toast.error("Failed to generate draft", {
        description: error instanceof Error ? error.message : undefined,
      });
    },
  });

  return (
    <>
      <PageHeader
        title="Draft Anbud"
        description={run?.tenderName ?? `Run ${runId.slice(0, 8)}`}
        actions={
          <>
            <Button asChild variant="outline">
              <Link to={`/decisions/${runId}`}>
                <ArrowLeft className="h-4 w-4" />
                Decision
              </Link>
            </Button>
            <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
              <WandSparkles className="h-4 w-4" />
              {generate.isPending ? "Generating..." : draft ? "Regenerate" : "Generate"}
            </Button>
          </>
        }
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading draft...</p>
      ) : !draft ? (
        <EmptyState
          icon={FileCheck2}
          title="No draft response yet"
          description="Generate a draft from the completed bid decision and approved KB evidence."
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardContent className="space-y-5 p-5">
              <div className="grid gap-3 sm:grid-cols-3">
                <Metric label="Status" value={draft.status.replace("_", " ")} />
                <Metric label="Language" value={draft.language.toUpperCase()} />
                <Metric label="Verdict" value={draft.verdict.replace("_", " ")} />
              </div>

              <section>
                <h3 className="mb-3 text-sm font-semibold">Draft Answers</h3>
                <div className="space-y-3">
                  {draft.answers.map((answer) => (
                    <div key={answer.questionId} className="rounded-md border border-border p-3">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <Badge variant="outline" className={cn("capitalize", answerTone[answer.status])}>
                          {answer.status.replace("_", " ")}
                        </Badge>
                        <span className="font-mono text-xs text-muted-foreground">{answer.questionId}</span>
                      </div>
                      <p className="text-sm font-medium">{answer.prompt}</p>
                      <p className="mt-2 text-sm text-muted-foreground">{answer.answer}</p>
                      <EvidenceList keys={answer.evidenceKeys} />
                    </div>
                  ))}
                </div>
              </section>
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card>
              <CardContent className="space-y-2 p-5">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Pricing
                </h3>
                <p className="font-mono text-2xl font-semibold tabular-nums">
                  {formatSEK(draft.pricing.rateSEK)} SEK/h
                </p>
                <p className="text-xs text-muted-foreground">
                  {draft.pricing.source.replace("_", " ")} · margin {draft.pricing.marginPct}% ·{" "}
                  {formatSEK(draft.pricing.totalValueSEK)} SEK total
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="space-y-3 p-5">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  <Paperclip className="h-3.5 w-3.5" />
                  Attachments
                </div>
                {draft.attachments.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No required attachments detected.</p>
                ) : (
                  <div className="space-y-2">
                    {draft.attachments.map((attachment) => (
                      <div key={`${attachment.requiredByEvidenceKey}-${attachment.attachmentType}`} className="rounded-md border border-border p-3">
                        <div className="mb-1 flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className={cn("capitalize", attachmentTone[attachment.status])}>
                            {attachment.status.replace("_", " ")}
                          </Badge>
                          <span className="text-xs text-muted-foreground">{attachment.attachmentType}</span>
                        </div>
                        <p className="truncate text-sm font-medium">{attachment.filename}</p>
                        {attachment.publicUrl ? (
                          <Button asChild variant="link" size="sm" className="h-auto p-0 text-xs">
                            <a href={attachment.publicUrl} target="_blank" rel="noreferrer">
                              Open PDF <ExternalLink className="h-3 w-3" />
                            </a>
                          </Button>
                        ) : (
                          <p className="font-mono text-[11px] text-muted-foreground">
                            {attachment.storagePath ?? "Missing source PDF"}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {draft.missingInfo.length > 0 && (
              <Card>
                <CardContent className="space-y-2 p-5">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Missing Info
                  </h3>
                  <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                    {draft.missingInfo.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-muted/30 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-sm font-medium capitalize">{value}</p>
    </div>
  );
}

function EvidenceList({ keys }: { keys: string[] }) {
  if (keys.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-1">
      {keys.map((key) => (
        <EvidenceBadge key={key} id={key} />
      ))}
    </div>
  );
}
