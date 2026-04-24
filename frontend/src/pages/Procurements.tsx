import { Link, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { VerdictBadge } from "@/components/VerdictBadge";
import { formatRelativeTime, runDisplayId } from "@/data/mock";
import { usePermissions } from "@/lib/auth";
import { fetchProcurements, deleteProcurement, startAgentRun, fetchArchivedRuns, deleteAgentRun, archiveAgentRun } from "@/lib/api";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Archive,
  ArrowUpDown,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Compass,
  Eye,
  FileText,
  Files,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import type { RunStatus } from "@/data/mock";

type RunFilter = "all" | "not_run" | "running" | "done";
type SortKey = "recent" | "name" | "status";

const DELETE_BLOCKED_REASON =
  "This procurement has run history. Bidded preserves linked run audit rows, so it cannot be hard-deleted.";

const RUN_STATUS_LABELS = {
  pending: "Pending",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  needs_human_review: "Review",
} as const;

const RUN_STATUS_DOT_CLASSES = {
  pending: "bg-muted-foreground",
  running: "bg-info",
  succeeded: "bg-success",
  failed: "bg-danger",
  needs_human_review: "bg-warning",
} as const;

const STATUS_RANK: Record<RunStatus, number> = {
  running: 0,
  pending: 1,
  needs_human_review: 2,
  failed: 3,
  succeeded: 4,
};

const STAGE_PROGRESS: Record<string, number> = {
  // stage 1 – Evidence Scout
  ingest: 1, parsing: 1, preflight: 1, evidence_scout: 1, "evidence scout": 1,
  // stage 2 – Round 1
  retrieval: 2, round1: 2, debate: 2, "round 1": 2, round_1: 2, specialist: 2,
  // stage 3 – Round 2 / Judge
  round2: 3, "round 2": 3, round_2: 3, rebuttal: 3, judge: 3,
  // stage 4 – Finished
  done: 4, finished: 4, persist: 4, failed: 4,
};

function stageProgress(stage?: string | null): number {
  if (!stage) return 0;
  const key = stage.toLowerCase();
  for (const k of Object.keys(STAGE_PROGRESS)) {
    if (key.includes(k)) return STAGE_PROGRESS[k];
  }
  return 1;
}

function FilterPill({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        active
          ? "bg-background text-foreground shadow-sm ring-1 ring-border"
          : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
      )}
    >
      {label}
      <span
        className={cn(
          "rounded-sm px-1.5 py-0 text-[11px] font-mono tabular-nums",
          active ? "bg-muted text-foreground" : "bg-transparent text-muted-foreground/80",
        )}
      >
        {count}
      </span>
    </button>
  );
}

function StageProgressDots({ stage, status }: { stage?: string | null; status: RunStatus }) {
  const reached = stageProgress(stage);
  const isFinished = reached === 4;
  const isRunning = status === "running";
  return (
    <div className="flex items-center gap-1">
      {[1, 2, 3, 4].map((i) => (
        <span
          key={i}
          className={cn(
            "h-1 w-4 rounded-full transition-colors",
            i < reached && (isFinished ? "bg-success" : "bg-info"),
            i === reached && isFinished && "bg-success",
            i === reached && !isFinished && isRunning && "bg-info animate-pulse",
            i === reached && !isFinished && !isRunning && "bg-info",
            i > reached && "bg-muted",
          )}
        />
      ))}
    </div>
  );
}

function RunStatusDot({
  status,
  isStale = false,
  selected = false,
}: {
  status?: keyof typeof RUN_STATUS_LABELS;
  isStale?: boolean;
  selected?: boolean;
}) {
  const toneStatus = status ? (isStale ? "failed" : status) : null;
  const label = status ? (isStale ? "Stale" : RUN_STATUS_LABELS[status]) : "Not run";

  return (
    <span
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors",
        selected && "bg-primary/5 ring-1 ring-primary/30",
      )}
      role="img"
      aria-label={label}
      title={label}
    >
      {status === "running" && !isStale ? (
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-info opacity-50" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-info" />
        </span>
      ) : toneStatus ? (
        <span
          className={cn(
            "inline-flex h-2.5 w-2.5 rounded-full",
            RUN_STATUS_DOT_CLASSES[toneStatus],
          )}
        />
      ) : (
        <span
          className="inline-flex h-2.5 w-2.5 rounded-full border border-muted-foreground/35"
        />
      )}
      <span className="sr-only">{label}</span>
    </span>
  );
}

export default function Procurements() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const [q, setQ] = useState("");
  const [runFilter, setRunFilter] = useState<RunFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("recent");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null);
  const [page, setPage] = useState(0);
  const [allProcurements, setAllProcurements] = useState<Awaited<ReturnType<typeof fetchProcurements>>>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const PAGE_SIZE = 50;
  const [archivedCollapsed, setArchivedCollapsed] = useState(true);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
  const [archivingRunId, setArchivingRunId] = useState<string | null>(null);

  const { data: pageData = [], isLoading } = useQuery({
    queryKey: ["procurements", page],
    queryFn: () => fetchProcurements(page, PAGE_SIZE),
    refetchInterval: 10_000,
  });

  // Merge pages: on page 0 reset, on subsequent pages append
  const prevPageRef = useRef(page);
  useEffect(() => {
    if (page === 0) {
      setAllProcurements(pageData);
      setHasMore(pageData.length === PAGE_SIZE);
    } else if (page > prevPageRef.current) {
      setAllProcurements((prev) => {
        const existingIds = new Set(prev.map((p) => p.id));
        const fresh = pageData.filter((p) => !existingIds.has(p.id));
        return [...prev, ...fresh];
      });
      setHasMore(pageData.length === PAGE_SIZE);
      setLoadingMore(false);
    }
    prevPageRef.current = page;
  }, [pageData, page]);

  const procurements = allProcurements;

  const { data: archivedRuns = [] } = useQuery({
    queryKey: ["archived-runs"],
    queryFn: fetchArchivedRuns,
    enabled: !archivedCollapsed,
    staleTime: 30_000,
  });

  const handleArchiveRun = async (id: string) => {
    setArchivingRunId(id);
    try {
      await archiveAgentRun(id, "operator archived run from procurements");
      await queryClient.invalidateQueries({ queryKey: ["procurements"] });
      await queryClient.invalidateQueries({ queryKey: ["archived-runs"] });
      toast.success("Run archived", { description: "Hidden from active view, visible in archived runs." });
    } catch (err) {
      toast.error("Archive failed", { description: err instanceof Error ? err.message : "Unknown error" });
    } finally {
      setArchivingRunId(null);
    }
  };

  const handleDeleteRun = async (id: string) => {
    setDeletingRunId(id);
    try {
      await deleteAgentRun(id);
      await queryClient.invalidateQueries({ queryKey: ["archived-runs"] });
      await queryClient.invalidateQueries({ queryKey: ["procurements"] });
      toast.success("Run deleted permanently.");
    } catch (err) {
      toast.error("Delete failed", { description: err instanceof Error ? err.message : "Unknown error" });
    } finally {
      setDeletingRunId(null);
    }
  };

  const rows = useMemo(
    () => procurements.map((p) => ({ procurement: p, run: p.latestRun })),
    [procurements],
  );

  const counts = useMemo(() => {
    let notRun = 0;
    let running = 0;
    let done = 0;
    for (const { run } of rows) {
      if (!run || run.isArchived) {
        notRun++;
        continue;
      }
      const isActive = !run.isStale && (run.status === "running" || run.status === "pending");
      if (isActive) running++;
      else done++;
    }
    return { total: rows.length, notRun, running, done };
  }, [rows]);

  const filtered = useMemo(() => {
    const base = rows.filter(({ procurement: p, run }) => {
      if (q !== "" && !p.name.toLowerCase().includes(q.toLowerCase())) return false;
      if (runFilter === "all") return true;
      if (runFilter === "not_run") return !run || run.isArchived;
      if (runFilter === "running")
        return !!run && !run.isStale && (run.status === "running" || run.status === "pending");
      if (runFilter === "done")
        return (
          !!run &&
          (run.isStale ||
            run.status === "succeeded" ||
            run.status === "failed" ||
            run.status === "needs_human_review")
        );
      return true;
    });

    const sorted = [...base];
    if (sortKey === "name") {
      sorted.sort((a, b) => a.procurement.name.localeCompare(b.procurement.name));
    } else if (sortKey === "status") {
      sorted.sort((a, b) => {
        const ra = a.run ? STATUS_RANK[a.run.status] : 99;
        const rb = b.run ? STATUS_RANK[b.run.status] : 99;
        return ra - rb;
      });
    } else {
      sorted.sort((a, b) => {
        const ta = a.run
          ? new Date(a.run.startedAt).getTime()
          : new Date(a.procurement.uploadedAt).getTime();
        const tb = b.run
          ? new Date(b.run.startedAt).getTime()
          : new Date(b.procurement.uploadedAt).getTime();
        return tb - ta;
      });
    }
    return sorted;
  }, [q, runFilter, sortKey, rows]);

  const neverRunIds = useMemo(
    () => rows.filter(({ run }) => !run).map(({ procurement }) => procurement.id),
    [rows],
  );

  const toggleOne = (id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const startRuns = async (ids: string[], label: "start" | "rerun" = "start") => {
    if (ids.length === 0) return;
    if (!permissions.canStartRuns) {
      toast.error("Access required", { description: "You do not have permission to start agent runs." });
      return;
    }
    const verb = label === "rerun" ? "Re-run" : "Run";
    const results = await Promise.allSettled(ids.map((id) => startAgentRun(id)));
    const succeeded = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.filter((r) => r.status === "rejected");
    if (succeeded > 0) {
      toast.success(`${verb} started`, {
        description: `${succeeded} agent ${succeeded === 1 ? "run" : "runs"} queued.`,
      });
      await queryClient.invalidateQueries({ queryKey: ["procurements"] });
    }
    if (failed.length > 0) {
      const firstError = (failed[0] as PromiseRejectedResult).reason;
      toast.error("Failed to start run", {
        description: firstError instanceof Error ? firstError.message : String(firstError),
      });
    }
  };

  const handleDelete = async () => {
    if (!pendingDelete) return;
    const { id, name } = pendingDelete;
    setPendingDelete(null);
    setDeletingId(id);
    try {
      await deleteProcurement(id);
      setSelectedIds((prev) => prev.filter((x) => x !== id));
      setAllProcurements((prev) => prev.filter((p) => p.id !== id));
      await queryClient.invalidateQueries({ queryKey: ["procurements"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success("Procurement deleted", { description: name });
    } catch (err) {
      toast.error("Delete failed", { description: err instanceof Error ? err.message : "Unknown error" });
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <>
      <PageHeader
        title="Procurements"
        actions={
          <>
            {permissions.canStartRuns && neverRunIds.length > 0 && (
              <Button variant="outline" onClick={() => startRuns(neverRunIds)}>
                <Zap className="h-4 w-4" />
                Run all not-yet-run ({neverRunIds.length})
              </Button>
            )}
            <Button variant="outline" asChild>
              <Link to="/procurements/explore">
                <Compass className="h-4 w-4" />
                Explore Procurements
              </Link>
            </Button>
            {permissions.canRegisterProcurements && (
              <Button asChild>
                <Link to="/procurements/new">
                  <Plus className="h-4 w-4" />
                  Register Procurement
                </Link>
              </Button>
            )}
          </>
        }
      />

      <div className="space-y-4">
          {/* Toolbar */}
          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center">
              <div className="relative w-full sm:max-w-xs">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search procurements…"
                  className="pl-8 pr-8"
                />
                {q && (
                  <button
                    type="button"
                    onClick={() => setQ("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded-sm p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                    aria-label="Clear search"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              <div className="inline-flex flex-wrap items-center gap-1">
                <FilterPill
                  label="All"
                  count={counts.total}
                  active={runFilter === "all"}
                  onClick={() => setRunFilter("all")}
                />
                <FilterPill
                  label="Not run"
                  count={counts.notRun}
                  active={runFilter === "not_run"}
                  onClick={() => setRunFilter("not_run")}
                />
                <FilterPill
                  label="Running"
                  count={counts.running}
                  active={runFilter === "running"}
                  onClick={() => setRunFilter("running")}
                />
                <FilterPill
                  label="Done"
                  count={counts.done}
                  active={runFilter === "done"}
                  onClick={() => setRunFilter("done")}
                />
              </div>
            </div>

            <div className="flex items-center gap-2">
              <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground" />
              <Select value={sortKey} onValueChange={(v) => setSortKey(v as SortKey)}>
                <SelectTrigger className="h-9 w-[180px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="recent">Recently updated</SelectItem>
                  <SelectItem value="name">Name (A→Z)</SelectItem>
                  <SelectItem value="status">Status</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {isLoading && (
            <p className="py-8 text-center text-sm text-muted-foreground">Loading procurements…</p>
          )}

          {!isLoading && filtered.length === 0 && (
            <div className="rounded-md border border-dashed border-border bg-muted/20 p-6">
              <EmptyState
                icon={FileText}
                title="No procurements match"
                description="Try a different search or filter, or register a new procurement."
                action={
                  permissions.canRegisterProcurements ? (
                    <Button asChild>
                      <Link to="/procurements/new">
                        <Plus className="h-4 w-4" /> Register Procurement
                      </Link>
                    </Button>
                  ) : undefined
                }
              />
            </div>
          )}

          {!isLoading && filtered.length > 0 && (
            <div className="overflow-hidden rounded-md border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10" />
                    <TableHead>Procurement</TableHead>
                    <TableHead className="whitespace-nowrap">Latest run</TableHead>
                    <TableHead>Stage</TableHead>
                    <TableHead>Decision</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map(({ procurement: t, run }) => {
                    const checked = selectedIds.includes(t.id);
                    const isActiveRun =
                      !!run && !run.isStale && (run.status === "running" || run.status === "pending");
                    const isFinishedRun =
                      !!run &&
                      (run.isStale ||
                        run.status === "succeeded" ||
                        run.status === "failed" ||
                        run.status === "needs_human_review");

                    return (
                      <TableRow
                        key={t.id}
                        data-state={checked ? "selected" : undefined}
                        onClick={() => run && navigate(`/runs/${run.id}`)}
                        className={cn(
                          "group relative border-l-2 border-l-transparent transition-colors",
                          run && "cursor-pointer",
                          "hover:bg-muted/40",
                          checked && "border-l-primary bg-primary/5 hover:bg-primary/10",
                        )}
                      >
                        <TableCell
                          className="py-3.5"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            type="button"
                            className="inline-flex rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                            onClick={() => toggleOne(t.id)}
                            aria-label={`${checked ? "Deselect" : "Select"} ${t.name}`}
                          >
                            <RunStatusDot
                              status={run?.status}
                              isStale={run?.isStale}
                              selected={checked}
                            />
                          </button>
                        </TableCell>

                        {/* Procurement name + doc meta */}
                        <TableCell className="py-3.5">
                          <div className="flex flex-col leading-tight">
                            <span className="font-medium text-foreground group-hover:text-primary">
                              {t.name}
                            </span>
                            <span className="mt-0.5 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                              <Files className="h-3 w-3" />
                              <span>
                                {t.documentCount} {t.documentCount === 1 ? "PDF" : "PDFs"}
                              </span>
                              <span className="text-muted-foreground/40">·</span>
                              <span>registered {formatRelativeTime(t.uploadedAt)}</span>
                            </span>
                          </div>
                        </TableCell>

                        {/* Latest run */}
                        <TableCell className="py-3.5 text-sm">
                          {run ? (
                            <div className="flex flex-col leading-tight">
                              <span className="font-medium tabular-nums text-foreground group-hover:text-primary group-hover:underline">
                                {runDisplayId(run)}
                              </span>
                              <span className="text-xs text-muted-foreground">
                                {formatRelativeTime(run.startedAt)}
                              </span>
                            </div>
                          ) : (
                            null
                          )}
                        </TableCell>

                        {/* Stage progress */}
                        <TableCell className="py-3.5 text-sm">
                          {run ? (
                            <div className="flex flex-col gap-1.5">
                              <span className={cn(
                                "text-xs font-medium",
                                isFinishedRun ? "text-success" : "text-foreground",
                              )}>
                                {isFinishedRun ? "Finished" : run.stage}
                              </span>
                              <StageProgressDots stage={isFinishedRun ? "finished" : run.stage} status={run.status} />
                            </div>
                          ) : (
                            null
                          )}
                        </TableCell>

                        {/* Decision */}
                        <TableCell className="py-3.5">
                          {run?.needsJudgeReview ? (
                            <span className="inline-flex items-center rounded-sm border border-warning/30 bg-warning/10 px-2 py-0.5 text-[11px] font-semibold text-warning">
                              Review
                            </span>
                          ) : run?.decision ? (
                            <VerdictBadge verdict={run.decision} />
                          ) : (
                            null
                          )}
                        </TableCell>

                        {/* Actions */}
                        <TableCell
                          className="py-3.5 text-right"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div
                            className={cn(
                              "flex justify-end gap-1 transition-opacity",
                              isActiveRun
                                ? "opacity-100"
                                : "opacity-0 focus-within:opacity-100 group-hover:opacity-100",
                            )}
                          >
                            {permissions.canStartRuns && !run && (
                              <Button size="sm" className="h-8" onClick={() => startRuns([t.id])}>
                                <Play className="h-3 w-3" /> Start Run
                              </Button>
                            )}
                            {isActiveRun && run && (
                              <>
                                <Button variant="ghost" size="sm" className="h-8 text-info" disabled>
                                  <Loader2 className="h-3 w-3 animate-spin" /> Running…
                                </Button>
                                <Button asChild variant="ghost" size="sm" className="h-8 px-2">
                                  <Link to={`/runs/${run.id}`} aria-label="View run">
                                    <Eye className="h-3 w-3" />
                                  </Link>
                                </Button>
                              </>
                            )}
                            {isFinishedRun && run && (
                              <>
                                {permissions.canStartRuns && (
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-8"
                                    onClick={() => startRuns([t.id], "rerun")}
                                  >
                                    <RefreshCw className="h-3 w-3" /> Re-run
                                  </Button>
                                )}
                                <Button asChild variant="ghost" size="sm" className="h-8 px-2">
                                  <Link to={`/runs/${run.id}`} aria-label="View run">
                                    <Eye className="h-3 w-3" />
                                  </Link>
                                </Button>
                                {permissions.canDeleteRuns && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 px-2 text-muted-foreground hover:text-foreground"
                                    onClick={() => handleArchiveRun(run.id)}
                                    disabled={archivingRunId === run.id}
                                    title="Archive run — hide from active view"
                                  >
                                    {archivingRunId === run.id ? (
                                      <Loader2 className="h-3 w-3 animate-spin" />
                                    ) : (
                                      <Archive className="h-3 w-3" />
                                    )}
                                  </Button>
                                )}
                              </>
                            )}
                            {permissions.canDeleteProcurements && (
                              t.hasRunHistory ? (
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <span className="inline-flex" tabIndex={0}>
                                      <Button
                                        variant="ghost"
                                        size="sm"
                                        className="h-8 text-muted-foreground hover:text-destructive"
                                        disabled
                                        aria-label="Delete unavailable"
                                      >
                                        <Trash2 className="h-3 w-3" />
                                      </Button>
                                    </span>
                                  </TooltipTrigger>
                                  <TooltipContent className="max-w-xs text-xs">
                                    {DELETE_BLOCKED_REASON}
                                  </TooltipContent>
                                </Tooltip>
                              ) : (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 text-muted-foreground hover:text-destructive"
                                  disabled={deletingId === t.id}
                                  onClick={() => setPendingDelete({ id: t.id, name: t.name })}
                                  aria-label="Delete procurement"
                                >
                                  {deletingId === t.id ? (
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                  ) : (
                                    <Trash2 className="h-3 w-3" />
                                  )}
                                </Button>
                              )
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}

          {!isLoading && hasMore && (
            <div className="mt-3 flex justify-center">
              <Button
                variant="outline"
                onClick={() => {
                  setLoadingMore(true);
                  setPage((p) => p + 1);
                }}
                disabled={loadingMore}
              >
                {loadingMore ? (
                  <><Loader2 className="h-4 w-4 animate-spin" /> Loading…</>
                ) : (
                  `Load 50 more`
                )}
              </Button>
            </div>
          )}
      </div>

      {/* Archived runs */}
      <div className="mt-4">
        <button
          type="button"
          className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left hover:bg-muted/40 transition-colors"
          onClick={() => setArchivedCollapsed((c) => !c)}
        >
          <div className="flex items-center gap-2">
            <Archive className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground">Archived runs</span>
            {!archivedCollapsed && archivedRuns.length > 0 && (
              <span className="rounded-full bg-muted px-1.5 py-px text-[11px] font-mono tabular-nums text-muted-foreground">
                {archivedRuns.length}
              </span>
            )}
          </div>
          {archivedCollapsed ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          ) : (
            <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </button>

        <div
          className={`grid transition-[grid-template-rows] duration-300 ease-in-out ${
            archivedCollapsed ? "grid-rows-[0fr]" : "grid-rows-[1fr]"
          }`}
        >
          <div className="overflow-hidden">
            <div className="mt-2 overflow-hidden rounded-md border border-border">
              {archivedRuns.length === 0 ? (
                <p className="py-4 text-center text-xs text-muted-foreground">No archived runs.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/30">
                      <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">Procurement</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">Status</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">Started</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">Duration</th>
                      <th className="px-4 py-2 text-right text-xs font-medium text-muted-foreground">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {archivedRuns.map((r, i) => {
                      const isDeleting = deletingRunId === r.id;
                      return (
                        <tr
                          key={r.id}
                          className={cn(
                            "border-b border-border/50 last:border-0",
                            i % 2 === 0 ? "bg-card" : "bg-muted/10",
                            isDeleting && "opacity-40",
                          )}
                        >
                          <td className="px-4 py-2.5">
                            <div className="flex flex-col leading-tight">
                              <span className="font-medium text-foreground">{r.tenderName}</span>
                              <span className="font-mono text-[11px] text-muted-foreground">{runDisplayId(r)}</span>
                            </div>
                          </td>
                          <td className="px-4 py-2.5">
                            <span className={cn(
                              "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
                              r.status === "succeeded" ? "bg-success/10 text-success" :
                              r.status === "failed" ? "bg-danger/10 text-danger" :
                              "bg-muted text-muted-foreground",
                            )}>
                              {r.status === "succeeded" ? <CheckCircle2 className="h-3 w-3" /> :
                               r.status === "failed" ? <XCircle className="h-3 w-3" /> :
                               <Archive className="h-3 w-3" />}
                              {r.status}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-xs text-muted-foreground">{formatRelativeTime(r.startedAt)}</td>
                          <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                            {r.durationSec ? `${Math.round(r.durationSec)}s` : null}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Button asChild variant="ghost" size="sm" className="h-7 text-xs">
                                <Link to={`/runs/${r.id}`}>View</Link>
                              </Button>
                              {permissions.canDeleteRuns && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                                  onClick={() => handleDeleteRun(r.id)}
                                  disabled={isDeleting}
                                  title="Delete permanently"
                                >
                                  {isDeleting ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <Trash2 className="h-3.5 w-3.5" />
                                  )}
                                </Button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      </div>

      <AlertDialog open={!!pendingDelete} onOpenChange={(open) => { if (!open) setPendingDelete(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete procurement?</AlertDialogTitle>
            <AlertDialogDescription>
              <span className="font-medium text-foreground">{pendingDelete?.name}</span> and all its
              attached documents will be permanently removed. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleDelete}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
