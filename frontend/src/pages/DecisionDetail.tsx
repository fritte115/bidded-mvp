import { Link, useParams } from "react-router-dom";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { VerdictBadge } from "@/components/VerdictBadge";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { EvidenceBadge } from "@/components/EvidenceBadge";
import { CitationSourceSheet } from "@/components/CitationSourceSheet";
import { JudgeMemo } from "@/components/JudgeVerdictSummary";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { fetchRunDetail } from "@/lib/api";
import { humanizeVerdictText, runDisplayId, verdictLabel } from "@/data/mock";
import { isDuplicateJudgeDisagreement } from "@/lib/judgeMemo";
import { ArrowLeft, FileCheck2 } from "lucide-react";
import { cn } from "@/lib/utils";

const statusTone = {
  Met: "bg-success/10 text-success border-success/30",
  Partial: "bg-warning/10 text-warning border-warning/30",
  "Not Met": "bg-danger/10 text-danger border-danger/30",
  Unknown: "bg-muted text-muted-foreground border-border",
} as const;

const sevTone = {
  Low: "bg-info/10 text-info border-info/30",
  Medium: "bg-warning/10 text-warning border-warning/30",
  High: "bg-danger/10 text-danger border-danger/30",
} as const;

export default function DecisionDetail() {
  const { id = "" } = useParams();
  const [selectedCitationId, setSelectedCitationId] = useState<string | null>(null);

  const { data: run, isLoading } = useQuery({
    queryKey: ["run-detail", id],
    queryFn: () => fetchRunDetail(id),
    enabled: !!id,
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
    return <p className="text-sm text-muted-foreground">Loading decision…</p>;
  }
  if (!run || !run.judge) {
    return <p className="text-muted-foreground">Decision not found.</p>;
  }

  const j = run.judge;
  const showDisagreement =
    j.disagreement.trim().length > 0 &&
    !isDuplicateJudgeDisagreement(j.disagreement, j.citedMemo);

  return (
    <>
      <PageHeader
        title="Decision Detail"
        description={run.tenderName}
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/decisions"><ArrowLeft className="h-4 w-4" /> All decisions</Link>
            </Button>
            <Button asChild>
              <Link to={`/drafts/${run.id}`}>
                <FileCheck2 className="h-4 w-4" /> Draft anbud
              </Link>
            </Button>
          </>
        }
      />

      {/* Banner */}
      <Card className="mb-6 overflow-hidden">
        <div className="bg-gradient-to-r from-primary/5 to-transparent p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Final Verdict</p>
              <VerdictBadge verdict={j.verdict} size="lg" />
              <p className="text-sm text-muted-foreground">
                {runDisplayId(run)}
              </p>
            </div>
            <div className="min-w-[220px]">
              <p className="mb-1.5 text-xs uppercase tracking-wide text-muted-foreground">Confidence</p>
              <p className="font-mono text-3xl font-semibold tabular-nums">{j.confidence}%</p>
              <ConfidenceBar value={j.confidence} showLabel={false} className="mt-2" />
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardContent className="space-y-4 p-5">
            <Section title="Judge Memo">
              <JudgeMemo
                memo={j.citedMemo}
                verdict={j.verdict}
                onCitationClick={handleCitationClick}
              />
            </Section>
            {showDisagreement && (
              <Section title="Disagreement">
                <p className="text-sm text-muted-foreground">{humanizeVerdictText(j.disagreement)}</p>
              </Section>
            )}
            <Section title="Compliance Matrix">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Requirement</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Evidence</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {j.complianceMatrix.map((r, i) => (
                    <TableRow key={i}>
                      <TableCell className="text-sm">{r.requirement}</TableCell>
                      <TableCell>
                        <span className={cn(
                          "inline-flex items-center rounded-sm border px-2 py-0.5 text-xs font-medium",
                          statusTone[r.status] ?? statusTone.Unknown,
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
            </Section>
            <Section title="Risk Register">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Risk</TableHead>
                    <TableHead>Severity</TableHead>
                    <TableHead>Mitigation</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {j.riskRegister.map((r, i) => (
                    <TableRow key={i}>
                      <TableCell className="text-sm">{r.risk}</TableCell>
                      <TableCell>
                        <span className={cn(
                          "inline-flex items-center rounded-sm border px-2 py-0.5 text-xs font-medium",
                          sevTone[r.severity] ?? sevTone.Medium,
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
            </Section>
            <Section title="Recommended Actions">
              <ol className="list-decimal space-y-1.5 pl-5 text-sm">
                {j.recommendedActions.map((a, i) => <li key={i}>{humanizeVerdictText(a)}</li>)}
              </ol>
            </Section>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardContent className="space-y-3 p-5">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Vote Summary
              </h4>
              <div className="space-y-2">
                <VoteRow label={verdictLabel.BID} count={j.voteSummary.BID} total={4} tone="success" />
                <VoteRow label={verdictLabel.NO_BID} count={j.voteSummary.NO_BID} total={4} tone="danger" />
                <VoteRow label={verdictLabel.CONDITIONAL_BID} count={j.voteSummary.CONDITIONAL_BID} total={4} tone="warning" />
              </div>
            </CardContent>
          </Card>

          {j.complianceBlockers.length > 0 && (
            <Card>
              <CardContent className="space-y-2 p-5">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Compliance Blockers
                </h4>
                <ul className="space-y-1.5">
                  {j.complianceBlockers.map((b, i) => (
                    <li key={i} className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm">
                      {humanizeVerdictText(b)}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {j.potentialBlockers.length > 0 && (
            <Card>
              <CardContent className="space-y-2 p-5">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Potential Blockers
                </h4>
                <ul className="space-y-1.5">
                  {j.potentialBlockers.map((b, i) => (
                    <li key={i} className="rounded-md border border-warning/30 bg-warning/5 px-3 py-2 text-sm">
                      {humanizeVerdictText(b)}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {j.missingInfo.length > 0 && (
            <Card>
              <CardContent className="space-y-2 p-5">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Missing Information
                </h4>
                <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                  {j.missingInfo.map((m, i) => <li key={i}>{humanizeVerdictText(m)}</li>)}
                </ul>
              </CardContent>
            </Card>
          )}

        </div>
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function VoteRow({
  label,
  count,
  total,
  tone,
}: {
  label: string;
  count: number;
  total: number;
  tone: "success" | "danger" | "warning";
}) {
  const t = tone === "success" ? "bg-success" : tone === "danger" ? "bg-danger" : "bg-warning";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="font-medium">{label}</span>
        <span className="font-mono tabular-nums text-muted-foreground">{count} / {total}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", t)} style={{ width: `${(count / total) * 100}%` }} />
      </div>
    </div>
  );
}
