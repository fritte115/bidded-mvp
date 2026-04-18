import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useState, useEffect } from "react";
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
import { formatDate, formatDuration } from "@/data/mock";
import {
  fetchDashboardStats,
  fetchActiveRuns,
  fetchDecisions,
  stageDisplayName,
} from "@/lib/api";
import {
  FileText,
  Files,
  PlayCircle,
  ArrowRight,
  FileSignature,
  ChevronDown,
  ChevronUp,
  X,
  Target,
} from "lucide-react";

const DISMISSED_KEY = "dashboard:dismissed-runs";

function useDismissedRuns() {
  const [dismissed, setDismissed] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(DISMISSED_KEY);
      return new Set(raw ? JSON.parse(raw) : []);
    } catch {
      return new Set();
    }
  });

  function dismiss(id: string) {
    setDismissed((prev) => {
      const next = new Set(prev);
      next.add(id);
      localStorage.setItem(DISMISSED_KEY, JSON.stringify([...next]));
      return next;
    });
  }

  return { dismissed, dismiss };
}

function shortRunId(id: string): string {
  return `RUN-${id.replace(/-/g, "").slice(0, 4).toUpperCase()}`;
}

export default function Dashboard() {
  const { data: stats } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: fetchDashboardStats,
    refetchInterval: 10_000,
  });

  const { data: activeRuns = [] } = useQuery({
    queryKey: ["active-runs"],
    queryFn: fetchActiveRuns,
    refetchInterval: 10_000,
  });

  const { data: decisions = [] } = useQuery({
    queryKey: ["decisions"],
    queryFn: fetchDecisions,
    refetchInterval: 10_000,
  });

  const [analysesCollapsed, setAnalysesCollapsed] = useState(false);
  const { dismissed, dismiss } = useDismissedRuns();

  // Clear dismissed IDs that are no longer in the list (stale cleanup)
  useEffect(() => {
    const activeIds = new Set(activeRuns.map((r) => r.id));
    const stale = [...dismissed].filter((id) => !activeIds.has(id));
    if (stale.length > 0) {
      const pruned = [...dismissed].filter((id) => activeIds.has(id));
      localStorage.setItem(DISMISSED_KEY, JSON.stringify(pruned));
    }
  }, [activeRuns, dismissed]);

  const visibleRuns = activeRuns.filter((r) => !dismissed.has(r.id));

  const avgConfidence =
    decisions.length > 0
      ? Math.round(decisions.reduce((sum, d) => sum + d.confidence, 0) / decisions.length)
      : null;

  const recentDecisions = decisions.slice(0, 3);

  return (
    <>
      <PageHeader title="Dashboard" />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total Procurements"
          value={stats?.totalProcurements ?? "—"}
          hint="Registered tenders"
          icon={FileText}
        />
        <StatCard
          label="Registered PDFs"
          value={stats?.totalPdfDocuments ?? "—"}
          hint="Stored tender documents"
          icon={Files}
        />
        <StatCard
          label="Active Runs"
          value={stats?.activeRuns ?? "—"}
          hint="Running or queued"
          icon={PlayCircle}
        />
        <StatCard
          label="Avg. Judge Confidence"
          value={avgConfidence !== null ? `${avgConfidence}%` : "—"}
          hint={decisions.length > 0 ? `Across ${decisions.length} decision${decisions.length === 1 ? "" : "s"}` : "No decisions yet"}
          icon={Target}
        />
      </div>

      <Card className="mt-6">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">Active analyses</CardTitle>
          <div className="flex items-center gap-2">
            <Button asChild variant="ghost" size="sm" className="text-xs text-primary">
              <Link to="/procurements">
                View procurements <ArrowRight className="h-3 w-3" />
              </Link>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              onClick={() => setAnalysesCollapsed((c) => !c)}
              title={analysesCollapsed ? "Expand" : "Collapse"}
            >
              {analysesCollapsed ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronUp className="h-4 w-4" />
              )}
            </Button>
          </div>
        </CardHeader>

        {!analysesCollapsed && (
          <CardContent className="p-0">
            {visibleRuns.length === 0 ? (
              <p className="px-6 py-8 text-center text-sm text-muted-foreground">
                No queued or in-flight runs.{" "}
                {dismissed.size > 0 && (
                  <button
                    className="text-primary hover:underline"
                    onClick={() => {
                      localStorage.removeItem(DISMISSED_KEY);
                      window.location.reload();
                    }}
                  >
                    Show {dismissed.size} dismissed
                  </button>
                )}
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
                  {visibleRuns.map((r) => {
                    const isTerminal =
                      r.status === "succeeded" ||
                      r.status === "failed" ||
                      r.status === "needs_human_review";
                    return (
                      <TableRow key={r.id}>
                        <TableCell className="text-sm font-medium">
                          {shortRunId(r.id)}
                        </TableCell>
                        <TableCell>
                          <Link
                            to="/procurements"
                            className="font-medium hover:text-primary hover:underline"
                          >
                            {r.tenderName}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={r.status} />
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {stageDisplayName(r.stage)}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {formatDate(r.startedAt)}
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {r.durationSec ? formatDuration(r.durationSec) : "—"}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button asChild variant="ghost" size="sm" className="h-8">
                              <Link to={`/runs/${r.id}`}>View</Link>
                            </Button>
                            {isTerminal && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
                                onClick={() => dismiss(r.id)}
                                title="Dismiss"
                              >
                                <X className="h-3.5 w-3.5" />
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        )}
      </Card>

      <div className="mt-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Latest Verdicts</h2>
          <Button asChild variant="ghost" size="sm" className="text-xs text-primary">
            <Link to="/decisions">
              View all decisions <ArrowRight className="h-3 w-3" />
            </Link>
          </Button>
        </div>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {recentDecisions.length === 0 ? (
            <Card>
              <CardContent className="p-4 text-sm text-muted-foreground">
                No Judge decisions yet.
              </CardContent>
            </Card>
          ) : (
            recentDecisions.map((r) => (
              <Card key={r.id}>
                <CardContent className="p-4">
                  <div className="mb-3 flex items-start justify-between gap-2">
                    <div>
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">
                        Procurement
                      </p>
                      <p className="text-sm font-medium leading-tight">{r.tenderName}</p>
                    </div>
                    <VerdictBadge verdict={r.verdict} />
                  </div>
                  <ConfidenceBar value={r.confidence} className="mb-3" />
                  <p className="line-clamp-2 text-xs text-muted-foreground">{r.citedMemo}</p>
                  <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                    <span>{formatDate(r.completedAt ?? r.startedAt)}</span>
                    <span className="font-mono">{r.confidence}% confidence</span>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <Button
                      asChild
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs text-primary"
                    >
                      <Link to={`/decisions/${r.id}`}>
                        Details <ArrowRight className="h-3 w-3" />
                      </Link>
                    </Button>
                    <Button asChild variant="outline" size="sm" className="h-7 text-xs">
                      <Link to={`/bids/new?procurement=${r.tenderId}`}>
                        <FileSignature className="h-3 w-3" /> Draft bid
                      </Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </div>
    </>
  );
}
