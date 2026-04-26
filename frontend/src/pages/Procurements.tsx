import { Link } from "react-router-dom";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
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
import { StatusBadge } from "@/components/StatusBadge";
import { VerdictBadge } from "@/components/VerdictBadge";
import { formatRelativeTime } from "@/data/mock";
import { fetchProcurements, deleteProcurement, startAgentRun } from "@/lib/api";
import { ParseStatusBadge } from "@/components/ParseStatusBadge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  FileText,
  Plus,
  Search,
  Play,
  Files,
  RefreshCw,
  Eye,
  Zap,
  Loader2,
  Trash2,
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

type RunFilter = "all" | "not_run" | "running" | "done";

/** Short display ID from UUID */
function shortRunId(id: string): string {
  return `RUN-${id.replace(/-/g, "").slice(0, 4).toUpperCase()}`;
}

export default function Procurements() {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [runFilter, setRunFilter] = useState<RunFilter>("all");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null);

  const { data: procurements = [], isLoading } = useQuery({
    queryKey: ["procurements"],
    queryFn: fetchProcurements,
    refetchInterval: 10_000,
  });

  const rows = useMemo(
    () => procurements.map((p) => ({ procurement: p, run: p.latestRun })),
    [procurements],
  );

  const filtered = useMemo(
    () =>
      rows.filter(({ procurement: p, run }) => {
        if (q !== "" && !p.name.toLowerCase().includes(q.toLowerCase())) return false;
        if (runFilter === "all") return true;
        if (runFilter === "not_run") return !run;
        if (runFilter === "running") return run?.status === "running" || run?.status === "pending";
        if (runFilter === "done")
          return (
            run?.status === "succeeded" ||
            run?.status === "failed" ||
            run?.status === "needs_human_review"
          );
        return true;
      }),
    [q, runFilter, rows],
  );

  const inFlight = useMemo(
    () => rows.filter(({ run }) => run?.status === "running" || run?.status === "pending").length,
    [rows],
  );

  const neverRunIds = useMemo(
    () => rows.filter(({ run }) => !run).map(({ procurement }) => procurement.id),
    [rows],
  );

  const startRuns = async (ids: string[], label: "start" | "rerun" = "start") => {
    if (ids.length === 0) return;
    const verb = label === "rerun" ? "Re-run" : "Run";
    const results = await Promise.allSettled(ids.map((id) => startAgentRun(id)));
    const succeeded = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.filter((r) => r.status === "rejected");
    if (succeeded > 0) {
      toast.success(`${verb} started`, {
        description: `${succeeded} agent ${succeeded === 1 ? "run" : "runs"} queued. Results will appear automatically.`,
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
            {neverRunIds.length > 0 && (
              <Button variant="outline" onClick={() => startRuns(neverRunIds)}>
                <Zap className="h-4 w-4" />
                Run all not-yet-run ({neverRunIds.length})
              </Button>
            )}
            <Button asChild>
              <Link to="/procurements/new">
                <Plus className="h-4 w-4" />
                Register Procurement
              </Link>
            </Button>
          </>
        }
      />

      {inFlight > 0 && (
        <Card className="mb-4 border-info/40 bg-info/5">
          <CardContent className="flex items-center justify-between px-4 py-3">
            <span className="text-sm">
              <span className="font-mono font-semibold tabular-nums">{inFlight}</span>{" "}
              {inFlight === 1 ? "run" : "runs"} in flight
            </span>
            <span className="text-xs text-muted-foreground">Auto-refreshes every 10s</span>
          </CardContent>
        </Card>
      )}

      {isLoading && (
        <p className="mb-4 text-center text-sm text-muted-foreground">Loading procurements…</p>
      )}

      <Card>
        <CardContent className="p-4">
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search procurements…"
                className="pl-8"
              />
            </div>
            <Select value={runFilter} onValueChange={(v) => setRunFilter(v as RunFilter)}>
              <SelectTrigger className="w-full sm:w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                <SelectItem value="not_run">Not run</SelectItem>
                <SelectItem value="running">Running</SelectItem>
                <SelectItem value="done">Done</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              icon={FileText}
              title="No procurements match"
              description="Try a different search or filter, or register a new procurement."
              action={
                <Button asChild>
                  <Link to="/procurements/new"><Plus className="h-4 w-4" /> Register Procurement</Link>
                </Button>
              }
            />
          ) : (
            <div className="overflow-hidden rounded-md border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Procurement</TableHead>
                    <TableHead>Documents</TableHead>
                    <TableHead className="whitespace-nowrap">Latest run</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Stage</TableHead>
                    <TableHead>Decision</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map(({ procurement: t, run }) => {
                    const isActiveRun = run?.status === "running" || run?.status === "pending";
                    const isFinishedRun =
                      run?.status === "succeeded" ||
                      run?.status === "failed" ||
                      run?.status === "needs_human_review";
                    return (
                      <TableRow key={t.id}>
                        <TableCell className="font-medium">{t.name}</TableCell>
                        <TableCell className="align-top">
                          <div className="max-w-[240px] space-y-1.5">
                            <span className="inline-flex items-center gap-1.5 rounded-sm bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">
                              <Files className="h-3 w-3" />
                              {t.documentCount} {t.documentCount === 1 ? "PDF" : "PDFs"}
                            </span>
                            {t.documents.length > 0 && (
                              <ul className="space-y-1">
                                {t.documents.map((d) => (
                                  <li
                                    key={d.originalFilename}
                                    className="flex flex-wrap items-center gap-1.5 text-[11px] leading-tight"
                                  >
                                    <span className="min-w-0 truncate text-muted-foreground" title={d.originalFilename}>
                                      {d.originalFilename}
                                    </span>
                                    {d.parseNote ? (
                                      <Tooltip>
                                        <TooltipTrigger asChild>
                                          <span className="inline-flex cursor-help">
                                            <ParseStatusBadge status={d.parseStatus} />
                                          </span>
                                        </TooltipTrigger>
                                        <TooltipContent className="max-w-xs text-xs">
                                          {d.parseNote}
                                        </TooltipContent>
                                      </Tooltip>
                                    ) : (
                                      <ParseStatusBadge status={d.parseStatus} />
                                    )}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-sm">
                          {run ? (
                            <Link
                              to={`/runs/${run.id}`}
                              className="group inline-flex flex-col leading-tight"
                            >
                              <span className="font-medium text-foreground group-hover:text-primary group-hover:underline">
                                {shortRunId(run.id)}
                              </span>
                              <span className="text-xs text-muted-foreground">
                                {formatRelativeTime(run.startedAt)}
                              </span>
                            </Link>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell>
                          {run ? (
                            <StatusBadge status={run.status} />
                          ) : (
                            <span className="inline-flex items-center rounded-sm border border-border bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                              Not run
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {run ? run.stage : "—"}
                        </TableCell>
                        <TableCell>
                          {run?.needsJudgeReview ? (
                            <span className="inline-flex items-center rounded-sm border border-warning/30 bg-warning/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-warning">
                              Review
                            </span>
                          ) : run?.decision ? (
                            <VerdictBadge verdict={run.decision} />
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
                            {!run && (
                              <Button
                                size="sm"
                                className="h-8"
                                onClick={() => startRuns([t.id])}
                              >
                                <Play className="h-3 w-3" /> Start Run
                              </Button>
                            )}
                            {isActiveRun && run && (
                              <>
                                <Button variant="ghost" size="sm" className="h-8" disabled>
                                  <Loader2 className="h-3 w-3 animate-spin" /> Running…
                                </Button>
                                <Button asChild variant="ghost" size="sm" className="h-8">
                                  <Link to={`/runs/${run.id}`}>
                                    <Eye className="h-3 w-3" /> View
                                  </Link>
                                </Button>
                              </>
                            )}
                            {isFinishedRun && run && (
                              <>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="h-8"
                                  onClick={() => startRuns([t.id], "rerun")}
                                >
                                  <RefreshCw className="h-3 w-3" /> Re-run
                                </Button>
                                <Button asChild variant="ghost" size="sm" className="h-8">
                                  <Link to={`/runs/${run.id}`}>
                                    <Eye className="h-3 w-3" /> View
                                  </Link>
                                </Button>
                              </>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 text-muted-foreground hover:text-destructive"
                              disabled={deletingId === t.id}
                              onClick={() => setPendingDelete({ id: t.id, name: t.name })}
                            >
                              {deletingId === t.id ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Trash2 className="h-3 w-3" />
                              )}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
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
