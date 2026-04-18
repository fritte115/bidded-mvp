import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { StatusBadge } from "@/components/StatusBadge";
import { VerdictBadge } from "@/components/VerdictBadge";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { runs, formatDate, formatDuration } from "@/data/mock";
import { fetchDashboardStats, fetchActiveRuns } from "@/lib/api";
import { FileText, Files, PlayCircle, Gavel, ArrowRight, FileSignature } from "lucide-react";

/** Shorten a UUID to a display run ID: "RUN-a1b2" */
function shortRunId(id: string): string {
  return `RUN-${id.replace(/-/g, "").slice(0, 4).toUpperCase()}`;
}

export default function Dashboard() {
  const { data: stats } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: fetchDashboardStats,
    refetchInterval: 10_000, // poll every 10s so active runs update live
  });

  const { data: activeRuns = [] } = useQuery({
    queryKey: ["active-runs"],
    queryFn: fetchActiveRuns,
    refetchInterval: 10_000,
  });

  // Latest Verdicts: keep mock until US-021 (Judge node) lands and bid_decisions have rows
  const recentDecisions = runs.filter((r) => r.judge).slice(0, 3);

  return (
    <>
      <PageHeader title="Dashboard" />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total Procurements" value={stats?.totalProcurements ?? "—"} hint="Registered tenders" icon={FileText} />
        <StatCard label="Registered PDFs" value={stats?.totalPdfDocuments ?? "—"} hint="Stored tender documents" icon={Files} />
        <StatCard label="Active Runs" value={stats?.activeRuns ?? "—"} hint="Running or queued" icon={PlayCircle} />
        <StatCard label="Judge decisions" value="—" hint="After PRD judge + worker" icon={Gavel} />
      </div>

      <Card className="mt-6">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">Active analyses</CardTitle>
          <Button asChild variant="ghost" size="sm" className="text-xs text-primary">
            <Link to="/procurements">View procurements <ArrowRight className="h-3 w-3" /></Link>
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          {activeRuns.length === 0 ? (
            <p className="px-6 py-8 text-center text-sm text-muted-foreground">
              No queued or in-flight runs. Run creation from the UI is deferred to the PRD backlog;
              you can still register procurements and documents.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Procurement</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Stage</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activeRuns.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="text-sm font-medium">{shortRunId(r.id)}</TableCell>
                    <TableCell>
                      <Link to="/procurements" className="font-medium hover:text-primary hover:underline">
                        {r.tenderName}
                      </Link>
                    </TableCell>
                    <TableCell><StatusBadge status={r.status} /></TableCell>
                    <TableCell className="text-muted-foreground text-sm">{r.stage ?? "—"}</TableCell>
                    <TableCell className="text-muted-foreground text-sm">{formatDate(r.startedAt)}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {r.durationSec ? formatDuration(r.durationSec) : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button asChild variant="ghost" size="sm" className="h-8">
                        <Link to={`/runs/${r.id}`}>View</Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <div className="mt-6">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold">Latest Verdicts</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Sample data only — live judge output will connect after the relevant PRD stories.
            </p>
          </div>
          <Button asChild variant="ghost" size="sm" className="text-xs text-primary">
            <Link to="/decisions">View all decisions <ArrowRight className="h-3 w-3" /></Link>
          </Button>
        </div>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {recentDecisions.map((r) => (
            <Card key={r.id}>
              <CardContent className="p-4">
                <div className="mb-3 flex items-start justify-between gap-2">
                  <div>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Procurement</p>
                    <p className="text-sm font-medium leading-tight">{r.tenderName}</p>
                  </div>
                  {r.judge && <VerdictBadge verdict={r.judge.verdict} />}
                </div>
                {r.judge && <ConfidenceBar value={r.judge.confidence} className="mb-3" />}
                <p className="line-clamp-2 text-xs text-muted-foreground">{r.judge?.citedMemo}</p>
                <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                  <span>{formatDate(r.completedAt ?? r.startedAt)}</span>
                  <span className="font-mono">{r.evidence.length} evidence</span>
                </div>
                <div className="mt-3 flex items-center justify-between gap-2">
                  <Button asChild variant="ghost" size="sm" className="h-7 text-xs text-primary">
                    <Link to={`/decisions/${r.id}`}>Details <ArrowRight className="h-3 w-3" /></Link>
                  </Button>
                  <Button asChild variant="outline" size="sm" className="h-7 text-xs">
                    <Link to={`/bids/new?procurement=${r.tenderId}`}>
                      <FileSignature className="h-3 w-3" /> Draft bid
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </>
  );
}
