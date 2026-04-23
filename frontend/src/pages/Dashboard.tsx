import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
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
  archiveAgentRun,
} from "@/lib/api";
import {
  Archive,
  FileText,
  Files,
  PlayCircle,
  ArrowRight,
  FileSignature,
  ChevronDown,
  ChevronUp,
  Target,
} from "lucide-react";

function shortRunId(id: string): string {
  return `RUN-${id.replace(/-/g, "").slice(0, 4).toUpperCase()}`;
}

export default function Dashboard() {
  const queryClient = useQueryClient();

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

  const [collapsed, setCollapsed] = useState(false);
  const [archiving, setArchiving] = useState<Set<string>>(new Set());

  const avgConfidence =
    decisions.length > 0
      ? Math.round(decisions.reduce((sum, d) => sum + d.confidence, 0) / decisions.length)
      : null;

  const recentDecisions = decisions.slice(0, 3);

  async function handleArchive(id: string) {
    setArchiving((prev) => new Set(prev).add(id));
    try {
      await archiveAgentRun(id, "operator archived run from dashboard");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["active-runs"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] }),
        queryClient.invalidateQueries({ queryKey: ["decisions"] }),
        queryClient.invalidateQueries({ queryKey: ["procurements"] }),
        queryClient.invalidateQueries({ queryKey: ["compare-rows"] }),
        queryClient.invalidateQueries({ queryKey: ["bids"] }),
      ]);
      toast.success("Run archived");
    } catch (err) {
      toast.error("Archive failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setArchiving((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

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
          hint={
            decisions.length > 0
              ? `Across ${decisions.length} decision${decisions.length === 1 ? "" : "s"}`
              : "No decisions yet"
          }
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
              onClick={() => setCollapsed((c) => !c)}
              title={collapsed ? "Expand" : "Collapse"}
            >
              {collapsed ? (
                <ChevronDown className="h-4 w-4 transition-transform duration-200" />
              ) : (
                <ChevronUp className="h-4 w-4 transition-transform duration-200" />
              )}
            </Button>
          </div>
        </CardHeader>

        {/* Smooth grid-rows animation: 0fr → 1fr */}
        <div
          className={`grid transition-[grid-template-rows] duration-300 ease-in-out ${
            collapsed ? "grid-rows-[0fr]" : "grid-rows-[1fr]"
          }`}
        >
          <div className="overflow-hidden">
            <CardContent className="p-0">
              {activeRuns.length === 0 ? (
                <p className="px-6 py-8 text-center text-sm text-muted-foreground">
                  No queued or in-flight runs. Register a procurement and start an agent
                  run when ready.
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
                    {activeRuns.map((r) => {
                      const isTerminal =
                        r.status === "succeeded" ||
                        r.status === "failed" ||
                        r.status === "needs_human_review" ||
                        r.isStale;
                      const isArchiving = archiving.has(r.id);
                      return (
                        <TableRow
                          key={r.id}
                          className={isArchiving ? "opacity-40 transition-opacity duration-300" : ""}
                        >
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
                            <StatusBadge status={r.status} isStale={r.isStale} />
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {r.stage}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {formatDate(r.startedAt)}
                          </TableCell>
                          <TableCell className="font-mono text-xs text-muted-foreground">
                            {r.durationSec
                              ? formatDuration(r.durationSec)
                              : r.isStale && r.staleAgeMinutes !== null
                                ? `${r.staleAgeMinutes}m stale`
                                : "—"}
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
                                  className="h-8 w-8 p-0 text-muted-foreground hover:text-primary"
                                  onClick={() => handleArchive(r.id)}
                                  disabled={isArchiving}
                                  title="Archive run"
                                >
                                  <Archive className="h-3.5 w-3.5" />
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
          </div>
        </div>
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
