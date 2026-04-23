import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Brain,
  ChevronDown,
  Clock,
  FileText,
  Pencil,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import {
  type Bid,
  type BidStatus,
  bidStatusLabel,
  bidStatusOrder,
  formatDate,
  verdictLabel,
} from "@/data/mock";
import { decisionToEstimateInput } from "@/lib/bidIntegrationMapping";
import { estimateBid, formatSEK } from "@/lib/bidEstimator";
import { fetchCompany } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  bid: Bid;
  onMove: (id: string, status: BidStatus) => void;
  onEdit?: (id: string) => void;
}

function marginTone(pct: number): string {
  if (pct >= 12) return "text-success";
  if (pct >= 8) return "text-warning";
  return "text-danger";
}

function marginBarTone(pct: number): string {
  if (pct >= 12) return "bg-success";
  if (pct >= 8) return "bg-warning";
  return "bg-danger";
}

function deltaTone(deltaPct: number): string {
  const a = Math.abs(deltaPct);
  if (a <= 4) return "text-success";
  if (deltaPct > 0) return "text-warning";
  return "text-danger";
}

function deadlineFor(uploadedAt: string | undefined): Date | null {
  if (!uploadedAt) return null;
  const d = new Date(uploadedAt);
  if (Number.isNaN(d.getTime())) return null;
  d.setDate(d.getDate() + 60);
  return d;
}

function relativeDeadline(d: Date): { label: string; tone: string } {
  const diffMs = d.getTime() - Date.now();
  const days = Math.round(diffMs / (1000 * 60 * 60 * 24));
  if (days < 0) return { label: `${Math.abs(days)}d overdue`, tone: "text-danger" };
  if (days === 0) return { label: "due today", tone: "text-danger" };
  if (days <= 7) return { label: `in ${days}d`, tone: "text-warning" };
  if (days <= 30) return { label: `in ${days}d`, tone: "text-foreground" };
  return { label: `in ${days}d`, tone: "text-muted-foreground" };
}

export function BidCard({ bid, onMove, onEdit }: Props) {
  const { data: companyData } = useQuery({
    queryKey: ["company"],
    queryFn: fetchCompany,
  });
  const estimate = bid.decision && companyData
    ? estimateBid(
        decisionToEstimateInput(bid.decision, bid.procurementId),
        companyData.company,
      )
    : null;
  const deltaPct = estimate
    ? Math.round(((bid.rateSEK - estimate.recommendedRate) / estimate.recommendedRate) * 1000) / 10
    : null;
  const deadline = deadlineFor(bid.tenderUploadedAt);
  const rel = deadline ? relativeDeadline(deadline) : null;

  // Margin bar fill: cap at 20% margin = full bar
  const marginFill = Math.min(100, Math.max(0, (bid.marginPct / 20) * 100));

  return (
    <div className="group flex h-[370px] flex-col rounded-lg border border-border/60 bg-card p-4 transition-colors hover:border-border hover:bg-card/80">
      {/* Header: title + deadline */}
      <div className="flex items-start justify-between gap-2">
        <p className="line-clamp-2 h-10 flex-1 text-sm font-semibold leading-5 text-foreground">
          {bid.procurementName}
        </p>
        {rel && (
          <span
            className={cn(
              "inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-[11px] tabular-nums",
              rel.tone,
            )}
          >
            <Clock className="h-3 w-3" />
            {rel.label}
          </span>
        )}
      </div>

      {/* Meta line — id + date, quiet */}
      <p className="mt-1 font-mono text-[10px] tabular-nums text-muted-foreground">
        {bid.id} · {formatDate(bid.updatedAt)}
      </p>

      {bid.decision && (
        <div className="mt-3 flex items-center justify-between gap-2 rounded-md bg-muted/40 px-2.5 py-2">
          <span className="truncate text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Agent decision
          </span>
          <span className="whitespace-nowrap font-mono text-[11px] font-semibold tabular-nums text-foreground">
            {verdictLabel[bid.decision.verdict]} · {bid.decision.confidence}%
          </span>
        </div>
      )}

      {/* Primary metric: rate */}
      <div className="mt-4 flex items-baseline gap-1.5">
        <span className="font-mono text-2xl font-semibold leading-none tabular-nums text-foreground">
          {formatSEK(bid.rateSEK)}
        </span>
        <span className="text-[11px] text-muted-foreground">SEK/h</span>
      </div>

      {/* Metric grid: margin + delta vs rec */}
      <div className="mt-3 grid grid-cols-2 gap-2">
        {/* Margin tile with mini bar */}
        <div className="rounded-md bg-muted/40 px-2.5 py-2">
          <div className="flex items-center justify-between gap-1">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Margin
            </span>
            <span className={cn("font-mono text-xs font-semibold tabular-nums", marginTone(bid.marginPct))}>
              {bid.marginPct}%
            </span>
          </div>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-border/60">
            <div
              className={cn("h-full rounded-full transition-all", marginBarTone(bid.marginPct))}
              style={{ width: `${marginFill}%` }}
            />
          </div>
        </div>

        {/* Delta tile */}
        <div className="rounded-md bg-muted/40 px-2.5 py-2">
          <div className="flex items-center justify-between gap-1">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              vs Rec
            </span>
            {deltaPct !== null ? (
              <span className={cn("inline-flex items-center gap-0.5 font-mono text-xs font-semibold tabular-nums", deltaTone(deltaPct))}>
                {deltaPct > 0 ? (
                  <TrendingUp className="h-3 w-3" />
                ) : deltaPct < 0 ? (
                  <TrendingDown className="h-3 w-3" />
                ) : null}
                {deltaPct > 0 ? "+" : ""}
                {deltaPct}%
              </span>
            ) : (
              <span className="font-mono text-xs text-muted-foreground">—</span>
            )}
          </div>
          <div className="mt-2 font-mono text-[10px] tabular-nums text-muted-foreground">
            {estimate ? formatSEK(estimate.recommendedRate) : "no rec"}
          </div>
        </div>
      </div>

      <p className="mt-2 font-mono text-[10px] tabular-nums text-muted-foreground">
        {bid.hoursEstimated.toLocaleString("sv-SE")}h estimate
      </p>

      {/* Notes — generous space, 3 lines */}
      <div className="mt-4 flex-1 border-t border-border/40 pt-3">
        <p className="line-clamp-3 text-xs leading-relaxed text-muted-foreground">
          {bid.notes || <span className="italic text-muted-foreground/50">No notes</span>}
        </p>
      </div>

      {/* Footer — quiet actions, pinned */}
      <div className="mt-3 flex items-center justify-between gap-1">
        <div className="flex items-center gap-0.5 opacity-60 transition-opacity group-hover:opacity-100">
          {onEdit && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:text-foreground"
              onClick={() => onEdit(bid.id)}
              aria-label="Edit bid"
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          )}
          {bid.runId && (
            <Button
              asChild
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:text-foreground"
              aria-label="View decision"
            >
              <Link to={`/decisions/${bid.runId}`}>
                <Brain className="h-3.5 w-3.5" />
              </Link>
            </Button>
          )}
          <Button
            asChild
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
            aria-label="Open procurement"
          >
            <Link to="/procurements">
              <FileText className="h-3.5 w-3.5" />
            </Link>
          </Button>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1 px-2 text-[11px] text-muted-foreground hover:text-foreground"
            >
              Move
              <ChevronDown className="h-3 w-3 opacity-60" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Move to</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {bidStatusOrder
              .filter((s) => s !== bid.status)
              .map((s) => (
                <DropdownMenuItem key={s} onClick={() => onMove(bid.id, s)}>
                  {bidStatusLabel[s]}
                </DropdownMenuItem>
              ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
