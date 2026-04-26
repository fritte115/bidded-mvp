import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { VerdictBadge } from "@/components/VerdictBadge";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  formatDate,
  formatDuration,
  runDisplayId,
} from "@/data/mock";
import {
  fetchDashboardStats,
  fetchActiveRuns,
  fetchDecisions,
  archiveAgentRun,
  deleteAgentRun,
} from "@/lib/api";
import { usePermissions } from "@/lib/auth";
import { renderFormattedText } from "@/lib/richText";
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
  Loader2,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Timer,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function Dashboard() {
  const queryClient = useQueryClient();
  const permissions = usePermissions();

  const { data: stats } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: fetchDashboardStats,
    refetchInterval: 10_000,
  });

  const [collapsed, setCollapsed] = useState(false);
  const [archiving, setArchiving] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState<Set<string>>(new Set());

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

  const avgConfidence =
    decisions.length > 0
      ? Math.round(decisions.reduce((sum, d) => sum + d.confidence, 0) / decisions.length)
      : null;

  const recentDecisions = decisions.slice(0, 3);

  const invalidateRunQueries = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["active-runs"] }),
      queryClient.invalidateQueries({ queryKey: ["archived-runs"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] }),
      queryClient.invalidateQueries({ queryKey: ["decisions"] }),
      queryClient.invalidateQueries({ queryKey: ["procurements"] }),
      queryClient.invalidateQueries({ queryKey: ["compare-rows"] }),
      queryClient.invalidateQueries({ queryKey: ["bids"] }),
    ]);

  async function handleArchive(id: string) {
    if (!permissions.canDeleteRuns) return;
    setArchiving((prev) => new Set(prev).add(id));
    try {
      await archiveAgentRun(id, "operator archived run from dashboard");
      await invalidateRunQueries();
      toast.success("Run archived", { description: "Hidden from active analyses." });
    } catch (err) {
      toast.error("Archive failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setArchiving((prev) => { const n = new Set(prev); n.delete(id); return n; });
    }
  }

  async function handleDelete(id: string) {
    if (!permissions.canDeleteRuns) return;
    setDeleting((prev) => new Set(prev).add(id));
    try {
      await deleteAgentRun(id);
      await invalidateRunQueries();
      toast.success("Run deleted permanently.");
    } catch (err) {
      toast.error("Delete failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setDeleting((prev) => { const n = new Set(prev); n.delete(id); return n; });
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
          label="Registered documents"
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

      <div className="mt-6">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold">Active analyses</h2>
            {activeRuns.length > 0 && (
              <span className="rounded-full bg-info/10 px-2 py-0.5 text-[11px] font-semibold tabular-nums text-info">
                {activeRuns.length}
              </span>
            )}
          </div>
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
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronUp className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>

        <div
          className={`grid transition-[grid-template-rows] duration-300 ease-in-out ${
            collapsed ? "grid-rows-[0fr]" : "grid-rows-[1fr]"
          }`}
        >
          <div className="overflow-hidden">
            {activeRuns.length === 0 ? (
              <Card>
                <CardContent className="flex flex-col items-center justify-center py-10 text-center">
                  <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-muted">
                    <PlayCircle className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <p className="text-sm font-medium text-foreground">No active analyses</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Register a procurement and start an agent run when ready.
                  </p>
                </CardContent>
              </Card>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {activeRuns.map((r) => {
                  const isTerminal =
                    r.status === "succeeded" ||
                    r.status === "failed" ||
                    r.status === "needs_human_review" ||
                    r.isStale;
                  const isLive = r.status === "running" || r.status === "pending";
                  const isArchiving = archiving.has(r.id);
                  const isDeleting = deleting.has(r.id);

                  // Pipeline stages in order
                  const STAGES = ["Evidence Scout", "Round 1: Specialist Motions", "Round 2: Rebuttals", "Judge"];
                  const stageIndex = STAGES.findIndex((s) => r.stage.includes(s.split(":")[0].trim()));
                  const currentStageIdx = stageIndex >= 0 ? stageIndex : (isLive ? 0 : STAGES.length);

                  // Visual config per status
                  const statusConfig = r.isStale
                    ? { icon: AlertTriangle, iconBg: "bg-warning/10", iconColor: "text-warning", border: "border-warning/20", label: "Stale" }
                    : r.status === "running"
                    ? { icon: Loader2, iconBg: "bg-info/10", iconColor: "text-info", border: "border-info/20", label: "Running" }
                    : r.status === "pending"
                    ? { icon: Clock, iconBg: "bg-muted", iconColor: "text-muted-foreground", border: "", label: "Queued" }
                    : r.status === "succeeded"
                    ? { icon: CheckCircle2, iconBg: "bg-success/10", iconColor: "text-success", border: "border-success/20", label: "Succeeded" }
                    : r.status === "failed"
                    ? { icon: XCircle, iconBg: "bg-danger/10", iconColor: "text-danger", border: "border-danger/20", label: "Failed" }
                    : r.status === "needs_human_review"
                    ? { icon: AlertTriangle, iconBg: "bg-warning/10", iconColor: "text-warning", border: "border-warning/20", label: "Needs review" }
                    : { icon: Clock, iconBg: "bg-muted", iconColor: "text-muted-foreground", border: "", label: r.status };

                  const StatusIcon = statusConfig.icon;

                  const duration = r.durationSec
                    ? formatDuration(r.durationSec)
                    : r.isStale && r.staleAgeMinutes !== null
                    ? `${r.staleAgeMinutes}m stale`
                    : null;

                  return (
                    <Card
                      key={r.id}
                      className={cn(
                        "group relative transition-opacity",
                        statusConfig.border && `border ${statusConfig.border}`,
                        isArchiving && "opacity-40",
                      )}
                    >
                      <CardContent className="p-4">
                        {/* Header */}
                        <div className="flex items-start gap-3">
                          <div className={cn("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md", statusConfig.iconBg)}>
                            <StatusIcon className={cn("h-4 w-4", statusConfig.iconColor, r.status === "running" && !r.isStale && "animate-spin")} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-semibold leading-tight text-foreground">
                              {r.tenderName}
                            </p>
                            <div className="mt-0.5 flex items-center gap-1.5">
                              <span className={cn("text-xs font-medium", statusConfig.iconColor)}>
                                {statusConfig.label}
                              </span>
                              <span className="text-muted-foreground/40">·</span>
                              <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                                {runDisplayId(r)}
                              </span>
                            </div>
                          </div>
                        </div>

                        {/* Pipeline progress bar */}
                        {(isLive || isTerminal) && (
                          <div className="mt-4">
                            <div className="mb-1.5 flex items-center justify-between">
                              <span className="text-[11px] font-medium text-muted-foreground">
                                {isLive ? r.stage : isTerminal && r.status === "succeeded" ? "Completed" : r.stage}
                              </span>
                              {isLive && (
                                <span className="text-[11px] tabular-nums text-muted-foreground">
                                  Step {Math.min(currentStageIdx + 1, STAGES.length)}/{STAGES.length}
                                </span>
                              )}
                            </div>
                            <div className="flex gap-0.5">
                              {STAGES.map((_, i) => {
                                const filled =
                                  r.status === "succeeded"
                                    ? true
                                    : r.status === "failed"
                                    ? i < currentStageIdx
                                    : i < currentStageIdx || (i === currentStageIdx && isLive);
                                const active = isLive && i === currentStageIdx;
                                return (
                                  <div
                                    key={i}
                                    className={cn(
                                      "h-1 flex-1 rounded-full transition-all duration-500",
                                      filled
                                        ? r.status === "failed"
                                          ? "bg-danger"
                                          : r.status === "succeeded"
                                          ? "bg-success"
                                          : "bg-info"
                                        : "bg-border",
                                      active && "animate-pulse",
                                    )}
                                  />
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* Meta row */}
                        <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                          <span className="inline-flex items-center gap-1">
                            <Timer className="h-3 w-3" />
                            {duration ?? formatDate(r.startedAt)}
                          </span>
                          <span>{formatDate(r.startedAt)}</span>
                        </div>

                        {/* Actions */}
                        <div className="mt-3 flex items-center gap-2 border-t border-border/60 pt-3">
                          <Button asChild variant="outline" size="sm" className="h-7 flex-1 text-xs">
                            <Link to={`/runs/${r.id}`}>
                              View analysis <ArrowRight className="h-3 w-3" />
                            </Link>
                          </Button>
                          {permissions.canDeleteRuns && isTerminal && (
                            <>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 shrink-0 p-0 text-muted-foreground hover:text-foreground"
                                onClick={() => handleArchive(r.id)}
                                disabled={isArchiving || isDeleting}
                                title="Archive — hide from dashboard, keep data"
                              >
                                {isArchiving ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <Archive className="h-3.5 w-3.5" />
                                )}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 shrink-0 p-0 text-muted-foreground hover:text-destructive"
                                onClick={() => handleDelete(r.id)}
                                disabled={isArchiving || isDeleting}
                                title="Delete permanently"
                              >
                                {isDeleting ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <Trash2 className="h-3.5 w-3.5" />
                                )}
                              </Button>
                            </>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>

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
                  <p className="line-clamp-2 text-xs text-muted-foreground">
                    {renderFormattedText(r.topReason)}
                  </p>
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
