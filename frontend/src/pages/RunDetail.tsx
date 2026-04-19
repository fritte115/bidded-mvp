import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { StatusBadge } from "@/components/StatusBadge";
import { VerdictBadge } from "@/components/VerdictBadge";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { EvidenceBadge } from "@/components/EvidenceBadge";
import { AgentMotionCard } from "@/components/AgentMotionCard";
import { PipelineStep, type StepState } from "@/components/PipelineStep";
import { fetchRunDetail } from "@/lib/api";
import { formatDate, formatDuration, type EvidenceCategory } from "@/data/mock";
import {
  ArrowLeft,
  Download,
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

function runDisplayId(id: string): string {
  let sum = 0;
  for (let i = 0; i < id.length; i++) sum = (sum + id.charCodeAt(i) * (i + 1)) % 9000;
  return `#${1000 + sum}`;
}

export default function RunDetail() {
  const { id = "" } = useParams();

  const { data: run, isLoading } = useQuery({
    queryKey: ["run-detail", id],
    queryFn: () => fetchRunDetail(id),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "running" || status === "pending" ? 5_000 : false;
    },
  });

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
    if (run.status === "succeeded") {
      return { 1: "completed", 2: "completed", 3: "completed", 4: "completed" };
    }
    if (run.status === "running") {
      const s: Record<1 | 2 | 3 | 4, StepState> = {
        1: "pending", 2: "pending", 3: "pending", 4: "pending",
      };
      for (let i = 1 as 1 | 2 | 3 | 4; i < currentStep; i = (i + 1) as 1 | 2 | 3 | 4)
        s[i] = "completed";
      s[currentStep] = "running";
      return s;
    }
    if (run.status === "failed") {
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

  return (
    <>
      <PageHeader
        title={runDisplayId(run.id)}
        description={run.tenderName}
        actions={
          <Button asChild variant="outline">
            <Link to="/procurements">
              <ArrowLeft className="h-4 w-4" /> Back to procurements
            </Link>
          </Button>
        }
      />

      {run.status === "failed" && (
        <Card className="mb-4 border-danger/40 bg-danger/5">
          <CardContent className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-2 text-sm">
              <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <div>
                <p className="font-medium text-danger">Run failed at: {run.stage}</p>
                <p className="text-xs text-muted-foreground">
                  The orchestrator stopped before a decision could be reached. Review inputs and re-run.
                </p>
              </div>
            </div>
            <Button variant="outline" size="sm" className="shrink-0">
              <RefreshCw className="h-3 w-3" /> Re-run
            </Button>
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

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        {/* Metadata card */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Run metadata</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <Field label="Run" value={<span className="font-medium">{runDisplayId(run.id)}</span>} />
              <Field label="Run ID" value={<span className="font-mono text-xs text-muted-foreground">{run.id.slice(0, 8)}…</span>} />
              <Field
                label="Procurement"
                value={
                  <Link className="text-primary hover:underline" to="/procurements">
                    {run.tenderName}
                  </Link>
                }
              />
              <Field label="Company" value={run.company} />
              <Field label="Status" value={<StatusBadge status={run.status} />} />
              <Field label="Started" value={formatDate(run.startedAt)} />
              <Field
                label="Completed"
                value={run.completedAt ? formatDate(run.completedAt) : "—"}
              />
              <Field
                label="Duration"
                value={
                  <span className="font-mono text-xs">
                    {formatDuration(run.durationSec ?? undefined)}
                  </span>
                }
              />
              <Field label="Stage" value={run.stage} />
              {run.decision && (
                <Field label="Decision" value={<VerdictBadge verdict={run.decision} />} />
              )}
            </CardContent>
            <div className="flex gap-2 border-t border-border p-3">
              <Button variant="outline" size="sm" className="flex-1">
                <RefreshCw className="h-3 w-3" /> Re-run
              </Button>
              <Button variant="outline" size="sm" className="flex-1">
                <Download className="h-3 w-3" /> Export
              </Button>
            </div>
          </Card>

          <Button asChild variant="outline" className="w-full">
            <Link to={`/runs/${run.id}/evidence`}>
              <FileSearch className="h-4 w-4" /> Evidence Board
            </Link>
          </Button>
        </div>

        {/* Pipeline */}
        <div>
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
                                <EvidenceBadge id={e.id} className="mt-0.5 shrink-0" />
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
                  <AgentMotionCard key={m.agent} motion={m} />
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
                  <AgentMotionCard key={m.agent} motion={m} highlightDisagreement />
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
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-3">
                      <VerdictBadge verdict={run.judge.verdict} size="lg" />
                      <div>
                        <p className="text-xs uppercase tracking-wide text-muted-foreground">
                          Confidence
                        </p>
                        <p className="font-mono text-lg tabular-nums">
                          {run.judge.confidence}%
                        </p>
                      </div>
                    </div>
                    <div className="flex gap-1.5">
                      <VoteChip label="BID" count={run.judge.voteSummary.BID} tone="success" />
                      <VoteChip label="NO BID" count={run.judge.voteSummary.NO_BID} tone="danger" />
                      <VoteChip label="COND." count={run.judge.voteSummary.CONDITIONAL_BID} tone="warning" />
                    </div>
                  </div>

                  <ConfidenceBar value={run.judge.confidence} showLabel={false} />

                  <div className="rounded-md border border-border bg-secondary/40 p-3 text-sm leading-relaxed">
                    {run.judge.citedMemo}
                  </div>

                  {run.judge.disagreement && (
                    <div className="rounded-md border border-warning/30 bg-warning/5 p-3 text-sm">
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-warning">
                        Disagreement
                      </p>
                      {run.judge.disagreement}
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
                                {r.evidence.map((e) => <EvidenceBadge key={e} id={e} />)}
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
                          {b}
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
                          {b}
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
                      {run.judge.missingInfo.map((m, i) => <li key={i}>{m}</li>)}
                    </ul>
                  </CollapsibleSection>

                  <CollapsibleSection title="Recommended Actions" defaultOpen>
                    <ol className="list-decimal space-y-1.5 pl-5 text-sm">
                      {run.judge.recommendedActions.map((a, i) => <li key={i}>{a}</li>)}
                    </ol>
                  </CollapsibleSection>

                  <CollapsibleSection title="Cited Evidence">
                    <div className="flex flex-wrap gap-1.5">
                      {run.judge.evidenceIds.map((e) => <EvidenceBadge key={e} id={e} />)}
                    </div>
                  </CollapsibleSection>
                </CardContent>
              </Card>
            )}
          </PipelineStep>
        </div>
      </div>
    </>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/60 pb-2 last:border-0 last:pb-0">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="text-right text-sm">{value}</span>
    </div>
  );
}

function VoteChip({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: "success" | "danger" | "warning";
}) {
  const t =
    tone === "success"
      ? "border-success/30 bg-success/10 text-success"
      : tone === "danger"
      ? "border-danger/30 bg-danger/10 text-danger"
      : "border-warning/30 bg-warning/10 text-warning";
  return (
    <div className={cn("flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold", t)}>
      <span className="font-mono tabular-nums">{count}</span>
      <span className="uppercase tracking-wide">{label}</span>
    </div>
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
