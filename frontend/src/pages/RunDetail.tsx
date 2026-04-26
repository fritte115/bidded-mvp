import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { EvidenceBadge } from "@/components/EvidenceBadge";
import { CitationSourceSheet } from "@/components/CitationSourceSheet";
import { AgentMotionCard } from "@/components/AgentMotionCard";
import { JudgeVerdictSummary } from "@/components/JudgeVerdictSummary";
import { PipelineStep, type StepState } from "@/components/PipelineStep";
import { ParseStatusBadge } from "@/components/ParseStatusBadge";
import { archiveAgentRun, downloadBidDocument, fetchRunDetail } from "@/lib/api";
import { usePermissions } from "@/lib/auth";
import { isDuplicateJudgeDisagreement } from "@/lib/judgeMemo";
import { renderFormattedText } from "@/lib/richText";
import { runDisplayId, type EvidenceCategory } from "@/data/mock";
import {
  Archive,
  ArrowLeft,
  Download,
  ExternalLink,
  Loader2,
  RefreshCw,
  ChevronDown,
  FileSearch,
  AlertTriangle,
  XCircle,
  CheckCircle2,
} from "lucide-react";
import { cn } from "@/lib/utils";

const categoryOrder: EvidenceCategory[] = [
  "Deadlines",
  "Mandatory Requirements",
  "Qualification Criteria",
  "Evaluation Criteria",
  "Contract Risks",
  "Required Submission Documents",
];

const statusToneMap = {
  Met: "bg-success/10 text-success border-success/30",
  Partial: "bg-warning/10 text-warning border-warning/30",
  "Not Met": "bg-danger/10 text-danger border-danger/30",
  Unknown: "bg-muted text-muted-foreground border-border",
} as const;

const severityToneMap = {
  Low: "bg-info/10 text-info border-info/30",
  Medium: "bg-warning/10 text-warning border-warning/30",
  High: "bg-danger/10 text-danger border-danger/30",
} as const;

function DocumentParseIndicator({
  status,
}: {
  status: "pending" | "parsing" | "parsed" | "parser_failed";
}) {
  if (status === "parsed") {
    return (
      <span
        className="inline-flex items-center justify-center rounded-full bg-success/10 p-1 text-success"
        role="img"
        aria-label="Parsed"
        title="Parsed"
      >
        <CheckCircle2 className="h-4 w-4" />
      </span>
    );
  }

  return <ParseStatusBadge status={status} />;
}

export default function RunDetail() {
  const { id = "" } = useParams();
  const [selectedCitationId, setSelectedCitationId] = useState<string | null>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const [isArchiving, setIsArchiving] = useState(false);
  const [isGeneratingDoc, setIsGeneratingDoc] = useState(false);

  const { data: run, isLoading } = useQuery({
    queryKey: ["run-detail", id],
    queryFn: () => fetchRunDetail(id),
    enabled: !!id,
    refetchInterval: (query) => {
      const run = query.state.data;
      const status = run?.status;
      const shouldRefetch =
        !run?.isArchived &&
        !run?.isStale &&
        (status === "running" || status === "pending");
      return shouldRefetch ? 5_000 : false;
    },
  });

  const evidenceById = useMemo(
    () => new Map((run?.evidence ?? []).map((evidence) => [evidence.id, evidence])),
    [run?.evidence],
  );
  const selectedEvidence = selectedCitationId
    ? (evidenceById.get(selectedCitationId) ?? null)
    : null;
  const handleCitationClick = (citationId: string) => {
    setSelectedCitationId(citationId);
  };

  if (isLoading) {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center text-muted-foreground">
        Loading run…
      </div>
    );
  }

  if (!run) {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center text-muted-foreground">
        Run not found.
      </div>
    );
  }

  const stageRank: Record<string, 1 | 2 | 3 | 4> = {
    "Evidence Scout": 1,
    "Round 1: Specialist Motions": 2,
    "Round 2: Rebuttals": 3,
    Judge: 4,
  };
  const currentStep = stageRank[run.stage] ?? 1;

  const stepStates = (function (): Record<1 | 2 | 3 | 4, StepState> {
    if (run.isArchived) {
      return { 1: "pending", 2: "pending", 3: "pending", 4: "pending" };
    }
    if (run.status === "succeeded") {
      return { 1: "completed", 2: "completed", 3: "completed", 4: "completed" };
    }
    if (run.status === "running" && !run.isStale) {
      const s: Record<1 | 2 | 3 | 4, StepState> = {
        1: "pending", 2: "pending", 3: "pending", 4: "pending",
      };
      for (let i = 1 as 1 | 2 | 3 | 4; i < currentStep; i = (i + 1) as 1 | 2 | 3 | 4)
        s[i] = "completed";
      s[currentStep] = "running";
      return s;
    }
    if (run.status === "failed" || run.isStale) {
      const s: Record<1 | 2 | 3 | 4, StepState> = {
        1: "pending", 2: "pending", 3: "pending", 4: "pending",
      };
      for (let i = 1 as 1 | 2 | 3 | 4; i < currentStep; i = (i + 1) as 1 | 2 | 3 | 4)
        s[i] = "completed";
      s[currentStep] = "failed";
      return s;
    }
    if (run.status === "needs_human_review") {
      return { 1: "completed", 2: "completed", 3: "completed", 4: "needs_human_review" };
    }
    return { 1: "pending", 2: "pending", 3: "pending", 4: "pending" };
  })();

  const grouped = categoryOrder.map((cat) => ({
    cat,
    items: run.evidence.filter((e) => e.category === cat),
  }));
  const showJudgeDisagreement =
    !!run.judge?.disagreement &&
    !isDuplicateJudgeDisagreement(run.judge.disagreement, run.judge.citedMemo);

  async function handleArchiveRun() {
    if (!permissions.canDeleteRuns) return;
    setIsArchiving(true);
    try {
      await archiveAgentRun(run.id, "operator archived run from detail view");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["active-runs"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] }),
        queryClient.invalidateQueries({ queryKey: ["decisions"] }),
        queryClient.invalidateQueries({ queryKey: ["procurements"] }),
        queryClient.invalidateQueries({ queryKey: ["compare-rows"] }),
        queryClient.invalidateQueries({ queryKey: ["bids"] }),
        queryClient.invalidateQueries({ queryKey: ["run-detail", run.id] }),
      ]);
      toast.success("Run archived");
      navigate("/procurements");
    } catch (err) {
      toast.error("Archive failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setIsArchiving(false);
    }
  }

  async function handleGenerateBidDocument() {
    setIsGeneratingDoc(true);
    try {
      const blob = await downloadBidDocument(run.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bid-response-${run.id.slice(0, 8)}.md`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Bid document downloaded");
    } catch (err) {
      toast.error("Failed to generate document", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setIsGeneratingDoc(false);
    }
  }

  return (
    <>
      <PageHeader
        title={runDisplayId(run)}
        description={run.tenderName}
        actions={
          <>
            <Button asChild variant="outline">
              <Link to={`/runs/${run.id}/evidence`}>
                <FileSearch className="h-4 w-4" /> Evidence Board
              </Link>
            </Button>
            <Button variant="outline">
              <RefreshCw className="h-4 w-4" /> Re-run
            </Button>
            <Button variant="outline">
              <Download className="h-4 w-4" /> Export
            </Button>
            {run.judge &&
              (run.judge.verdict === "bid" ||
                run.judge.verdict === "conditional_bid") && (
                <Button
                  variant="outline"
                  onClick={handleGenerateBidDocument}
                  disabled={isGeneratingDoc}
                >
                  {isGeneratingDoc ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Download className="h-4 w-4" />
                  )}{" "}
                  Bid Document
                </Button>
              )}
            <Button asChild variant="outline">
              <Link to="/procurements">
                <ArrowLeft className="h-4 w-4" /> Back to procurements
              </Link>
            </Button>
          </>
        }
      />

      {(run.status === "failed" || run.isStale) && (
        <Card className="mb-4 border-danger/40 bg-danger/5">
          <CardContent className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-2 text-sm">
              <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <div>
                <p className="font-medium text-danger">
                  {run.isStale ? "Run stalled at" : "Run failed at"}: {run.stage}
                </p>
                <p className="text-xs text-muted-foreground">
                  {run.isStale
                    ? "The worker is no longer updating this run. Archive it or start a fresh run."
                    : "The orchestrator stopped before a decision could be reached. Review inputs and re-run."}
                </p>
              </div>
            </div>
            <div className="flex shrink-0 gap-2">
              {permissions.canDeleteRuns && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleArchiveRun}
                  disabled={isArchiving}
                >
                  <Archive className="h-3 w-3" /> Archive
                </Button>
              )}
              <Button variant="outline" size="sm">
                <RefreshCw className="h-3 w-3" /> Re-run
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {run.status === "needs_human_review" && (
        <Card className="mb-4 border-warning/40 bg-warning/5">
          <CardContent className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-2 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              <div>
                <p className="font-medium text-warning">Decision needs human review</p>
                <p className="text-xs text-muted-foreground">
                  Critical evidence is missing or specialists are split. The Judge declined to auto-resolve.
                </p>
              </div>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button variant="outline" size="sm">
                <CheckCircle2 className="h-3 w-3" /> Mark resolved
              </Button>
              <Button variant="outline" size="sm">Request override</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {run.documents.length > 0 && (
        <section className="mb-4 space-y-3">
          <p className="text-sm font-medium text-foreground">Submitted files</p>
          <ul className="space-y-2">
            {run.documents.map((document) => (
              <li
                key={document.originalFilename}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-3 py-2"
              >
                <div className="flex min-w-0 items-center gap-2">
                  {document.publicUrl ? (
                    <a
                      href={document.publicUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex min-w-0 items-center gap-1 text-sm text-foreground hover:text-primary hover:underline"
                      aria-label={`Open ${document.originalFilename}`}
                    >
                      <span className="truncate">{document.originalFilename}</span>
                      <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                    </a>
                  ) : (
                    <span className="text-sm text-foreground">
                      {document.originalFilename}
                    </span>
                  )}
                  {document.publicUrl && (
                    <a
                      href={document.publicUrl}
                      download={document.originalFilename}
                      className="inline-flex items-center justify-center rounded-sm p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                      aria-label={`Download ${document.originalFilename}`}
                    >
                      <Download className="h-3.5 w-3.5" />
                    </a>
                  )}
                </div>
                <DocumentParseIndicator status={document.parseStatus} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="min-w-0">
        <PipelineStep index={1} title="Evidence Scout" state={stepStates[1]}>
            <Card>
              <CardContent className="p-2">
                <Accordion type="multiple" defaultValue={["Mandatory Requirements", "Deadlines"]}>
                  {grouped.map(({ cat, items }) => (
                    <AccordionItem key={cat} value={cat} className="border-border">
                      <AccordionTrigger className="px-3 py-2.5 text-sm hover:no-underline">
                        <span className="flex items-center gap-2">
                          {cat}
                          <span className="rounded-sm bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                            {items.length}
                          </span>
                        </span>
                      </AccordionTrigger>
                      <AccordionContent className="px-3">
                        {items.length === 0 ? (
                          <p className="py-2 text-xs text-muted-foreground">No items extracted.</p>
                        ) : (
                          <ul className="space-y-2.5 py-2">
                            {items.map((e) => (
                              <li key={e.id} className="flex gap-3">
                                <EvidenceBadge
                                  id={e.id}
                                  className="mt-0.5 shrink-0"
                                  onClick={() => handleCitationClick(e.id)}
                                />
                                <div className="text-sm">
                                  <p className="leading-snug">{e.excerpt}</p>
                                  <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                                    {e.key} · {e.source}
                                    {e.kind === "tender_document" && e.page > 0
                                      ? ` p.${e.page}`
                                      : ""}
                                  </p>
                                </div>
                              </li>
                            ))}
                          </ul>
                        )}
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </CardContent>
            </Card>
        </PipelineStep>

          <PipelineStep index={2} title="Round 1 — Specialist Motions" state={stepStates[2]}>
            {run.round1.length === 0 ? (
              <p className="text-sm text-muted-foreground">Pending…</p>
            ) : (
              <div className="grid min-w-0 grid-cols-1 items-start gap-4 md:grid-cols-2 2xl:grid-cols-4">
                {run.round1.map((m) => (
                  <AgentMotionCard
                    key={m.agent}
                    motion={m}
                    onCitationClick={handleCitationClick}
                  />
                ))}
              </div>
            )}
          </PipelineStep>

          <PipelineStep index={3} title="Round 2 — Rebuttals" state={stepStates[3]}>
            {run.round2.length === 0 ? (
              <p className="text-sm text-muted-foreground">Awaiting Round 1 completion…</p>
            ) : (
              <div className="grid min-w-0 grid-cols-1 items-start gap-4 md:grid-cols-2 2xl:grid-cols-4">
                {run.round2.map((m) => (
                  <AgentMotionCard
                    key={m.agent}
                    motion={m}
                    highlightDisagreement
                    onCitationClick={handleCitationClick}
                  />
                ))}
              </div>
            )}
          </PipelineStep>

          <PipelineStep index={4} title="Judge Decision" state={stepStates[4]} isLast>
            {!run.judge ? (
              <p className="text-sm text-muted-foreground">Awaiting rebuttals…</p>
            ) : (
              <Card>
                <CardContent className="space-y-5 p-5">
                  <JudgeVerdictSummary
                    verdict={run.judge.verdict}
                    confidence={run.judge.confidence}
                    citedMemo={run.judge.citedMemo}
                    voteSummary={run.judge.voteSummary}
                    onCitationClick={handleCitationClick}
                  />

                  {showJudgeDisagreement && (
                    <div className="rounded-md border border-warning/30 bg-warning/5 p-3 text-sm">
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-warning">
                        Disagreement
                      </p>
                      {renderFormattedText(run.judge.disagreement)}
                    </div>
                  )}

                  <CollapsibleSection title="Compliance Matrix" defaultOpen>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Requirement</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Evidence</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {run.judge.complianceMatrix.map((r, i) => (
                          <TableRow key={i}>
                            <TableCell className="text-sm">{r.requirement}</TableCell>
                            <TableCell>
                              <span className={cn(
                                "inline-flex items-center rounded-sm border px-2 py-0.5 text-xs font-medium",
                                statusToneMap[r.status] ?? statusToneMap.Unknown,
                              )}>
                                {r.status}
                              </span>
                            </TableCell>
                            <TableCell>
                              <div className="flex flex-wrap gap-1">
                                {r.evidence.map((e) => (
                                  <EvidenceBadge
                                    key={e}
                                    id={e}
                                    onClick={() => handleCitationClick(e)}
                                  />
                                ))}
                              </div>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CollapsibleSection>

                  <CollapsibleSection
                    title={`Compliance Blockers (${run.judge.complianceBlockers.length})`}
                  >
                    <ul className="space-y-1.5">
                      {run.judge.complianceBlockers.map((b, i) => (
                        <li
                          key={i}
                          className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm"
                        >
                          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-danger" />
                          {renderFormattedText(b)}
                        </li>
                      ))}
                    </ul>
                  </CollapsibleSection>

                  <CollapsibleSection
                    title={`Potential Blockers (${run.judge.potentialBlockers.length})`}
                  >
                    <ul className="space-y-1.5">
                      {run.judge.potentialBlockers.map((b, i) => (
                        <li
                          key={i}
                          className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/5 px-3 py-2 text-sm"
                        >
                          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-warning" />
                          {renderFormattedText(b)}
                        </li>
                      ))}
                    </ul>
                  </CollapsibleSection>

                  <CollapsibleSection title="Risk Register">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Risk</TableHead>
                          <TableHead>Severity</TableHead>
                          <TableHead>Mitigation</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {run.judge.riskRegister.map((r, i) => (
                          <TableRow key={i}>
                            <TableCell className="text-sm">{r.risk}</TableCell>
                            <TableCell>
                              <span className={cn(
                                "inline-flex items-center rounded-sm border px-2 py-0.5 text-xs font-medium",
                                severityToneMap[r.severity] ?? severityToneMap.Medium,
                              )}>
                                {r.severity}
                              </span>
                            </TableCell>
                            <TableCell className="text-sm text-muted-foreground">
                              {r.mitigation}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CollapsibleSection>

                  <CollapsibleSection title="Missing Information">
                    <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                      {run.judge.missingInfo.map((m, i) => <li key={i}>{renderFormattedText(m)}</li>)}
                    </ul>
                  </CollapsibleSection>

                  <CollapsibleSection title="Recommended Actions" defaultOpen>
                    <ol className="list-decimal space-y-1.5 pl-5 text-sm">
                      {run.judge.recommendedActions.map((a, i) => <li key={i}>{renderFormattedText(a)}</li>)}
                    </ol>
                  </CollapsibleSection>

                  <CollapsibleSection title="Cited Evidence">
                    <div className="flex flex-wrap gap-1.5">
                      {run.judge.evidenceIds.map((e) => (
                        <EvidenceBadge
                          key={e}
                          id={e}
                          onClick={() => handleCitationClick(e)}
                        />
                      ))}
                    </div>
                  </CollapsibleSection>
                </CardContent>
              </Card>
            )}
          </PipelineStep>
      </div>
      <CitationSourceSheet
        open={selectedCitationId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedCitationId(null);
        }}
        citationId={selectedCitationId}
        evidence={selectedEvidence}
        evidenceBoardHref={`/runs/${run.id}/evidence`}
      />
    </>
  );
}

function CollapsibleSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Collapsible defaultOpen={defaultOpen} className="rounded-md border border-border">
      <CollapsibleTrigger className="group flex w-full items-center justify-between px-3 py-2 text-sm font-medium hover:bg-secondary/50">
        {title}
        <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t border-border p-3">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}
