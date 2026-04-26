import { useMemo, useState } from "react";
import type { DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { BidCard } from "@/components/BidCard";
import { EmptyState } from "@/components/EmptyState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fetchBids, updateBidStatus, fetchProcurements } from "@/lib/api";
import { summarizeBidPipeline } from "@/lib/bidIntegrationMapping";
import {
  bidStatusLabel,
  bidStatusOrder,
  type Bid,
  type BidStatus,
} from "@/data/mock";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileEdit,
  Gavel,
  Plus,
  Search,
  Send,
  Target,
} from "lucide-react";
import { cn } from "@/lib/utils";

type SortKey = "updated" | "rate" | "margin";

const BID_DRAG_MIME = "application/x-bidded-bid-id";

const statusDot: Record<BidStatus, string> = {
  draft: "bg-muted-foreground/50",
  review: "bg-warning",
  submitted: "bg-info",
  won: "bg-success",
  lost: "bg-danger",
};

export default function Bids() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [filter, setFilter] = useState<string>("all");
  const [query, setQuery] = useState<string>("");
  const [sort, setSort] = useState<SortKey>("updated");
  const [draggedBid, setDraggedBid] = useState<{ id: string; status: BidStatus } | null>(null);
  const [dropTargetStatus, setDropTargetStatus] = useState<BidStatus | null>(null);
  const [expandedColumns, setExpandedColumns] = useState<Record<BidStatus, boolean>>({
    draft: false, review: false, submitted: false, won: false, lost: false,
  });

  const { data: bids = [], isLoading } = useQuery({
    queryKey: ["bids"],
    queryFn: fetchBids,
    refetchInterval: 15_000,
  });

  const { data: procurementList = [] } = useQuery({
    queryKey: ["procurements"],
    queryFn: fetchProcurements,
  });

  const COLLAPSED_LIMIT = 4;

  const toggleColumn = (status: BidStatus) => {
    setExpandedColumns((prev) => ({ ...prev, [status]: !prev[status] }));
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return bids
      .filter((b) => filter === "all" || b.procurementId === filter)
      .filter(
        (b) =>
          q === "" ||
          b.procurementName.toLowerCase().includes(q) ||
          b.notes.toLowerCase().includes(q),
      )
      .sort((a, b) => {
        if (sort === "rate") return b.rateSEK - a.rateSEK;
        if (sort === "margin") return b.marginPct - a.marginPct;
        return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
      });
  }, [bids, filter, query, sort]);

  const grouped = useMemo(() => {
    const g: Record<BidStatus, Bid[]> = {
      draft: [], review: [], submitted: [], won: [], lost: [],
    };
    filtered.forEach((b) => g[b.status].push(b));
    return g;
  }, [filtered]);

  const stats = useMemo(() => {
    return summarizeBidPipeline(bids);
  }, [bids]);

  const columnTotal = (status: BidStatus): string => {
    const total = grouped[status].reduce((s, b) => s + b.rateSEK * b.hoursEstimated, 0);
    if (total === 0) return "—";
    return `${(total / 1_000_000).toFixed(1)} MSEK`;
  };

  const handleMove = async (id: string, status: BidStatus) => {
    try {
      await updateBidStatus(id, status);
      queryClient.invalidateQueries({ queryKey: ["bids"] });
      toast.success(`Moved to ${bidStatusLabel[status]}`);
    } catch {
      toast.error("Failed to update bid status");
    }
  };

  const handleDragStart = (event: DragEvent<HTMLDivElement>, bid: Bid) => {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData(BID_DRAG_MIME, bid.id);
    event.dataTransfer.setData("text/plain", bid.id);
    setDraggedBid({ id: bid.id, status: bid.status });
  };

  const clearDragState = () => {
    setDraggedBid(null);
    setDropTargetStatus(null);
  };

  const handleColumnDragOver = (event: DragEvent<HTMLElement>, status: BidStatus) => {
    if (!draggedBid || draggedBid.status === status) return;

    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDropTargetStatus(status);
  };

  const handleColumnDragLeave = (event: DragEvent<HTMLElement>, status: BidStatus) => {
    const nextTarget = event.relatedTarget as Node | null;
    if (nextTarget && event.currentTarget.contains(nextTarget)) return;

    setDropTargetStatus((current) => (current === status ? null : current));
  };

  const handleColumnDrop = (event: DragEvent<HTMLElement>, status: BidStatus) => {
    event.preventDefault();

    const bidId =
      event.dataTransfer.getData(BID_DRAG_MIME) ||
      event.dataTransfer.getData("text/plain") ||
      draggedBid?.id;
    const sourceStatus =
      draggedBid?.id === bidId
        ? draggedBid.status
        : bids.find((bid) => bid.id === bidId)?.status;

    clearDragState();

    if (!bidId || sourceStatus === status) return;

    void handleMove(bidId, status);
  };

  const handleEdit = (id: string) => {
    navigate(`/bids/${id}/edit`);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        title="Bids"
        actions={
          <Button asChild>
            <Link to="/bids/new">
              <Plus className="h-4 w-4" />
              New Bid
            </Link>
          </Button>
        }
      />

      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard compact label="Active bids" value={stats.active} hint="Draft + review" icon={FileEdit} />
        <StatCard compact label="Submitted" value={stats.submitted} hint="Awaiting outcome" icon={Send} />
        <StatCard compact label="Win rate" value={`${stats.winRate}%`} hint="Won / decided" icon={CheckCircle2} />
        <StatCard
          compact
          label="Pipeline"
          value={`${stats.pipelineMSEK} MSEK`}
          hint="Estimated hours × rate"
          icon={Target}
        />
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search procurement or notes…"
            className="h-9 pl-8 text-sm"
          />
        </div>
        <Select value={filter} onValueChange={setFilter}>
          <SelectTrigger className="h-9 w-56">
            <SelectValue placeholder="Filter by procurement" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All procurements</SelectItem>
            {procurementList.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
          <SelectTrigger className="h-9 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="updated">Recently updated</SelectItem>
            <SelectItem value="rate">Highest rate</SelectItem>
            <SelectItem value="margin">Highest margin</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <div className="mt-6">
          <p className="text-sm text-muted-foreground">Loading bids…</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            icon={Gavel}
            title="No bids match"
            description="Try clearing the search or filter, or start a new bid."
            action={
              <Button asChild>
                <Link to="/bids/new">
                  <Plus className="h-4 w-4" /> New Bid
                </Link>
              </Button>
            }
          />
        </div>
      ) : (
        <div className="mt-6 -mx-2 grid min-h-0 flex-1 grid-cols-1 gap-3 px-2 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {bidStatusOrder.map((status) => {
            const items = grouped[status];
            const isExpanded = expandedColumns[status];
            const visibleItems =
              isExpanded || items.length <= COLLAPSED_LIMIT
                ? items
                : items.slice(0, COLLAPSED_LIMIT);
            const hiddenCount = items.length - COLLAPSED_LIMIT;
            return (
              <section
                key={status}
                role="region"
                aria-label={`${bidStatusLabel[status]} bids`}
                onDragOver={(event) => handleColumnDragOver(event, status)}
                onDragLeave={(event) => handleColumnDragLeave(event, status)}
                onDrop={(event) => handleColumnDrop(event, status)}
                className={cn(
                  "flex min-h-[280px] flex-col rounded-lg bg-muted/30 transition-colors",
                  dropTargetStatus === status && "bg-primary/5 ring-2 ring-inset ring-primary/30",
                )}
              >
                <header className="sticky top-0 z-10 flex items-center justify-between gap-2 rounded-t-lg border-b border-border/60 bg-muted/30 px-3 py-2 backdrop-blur">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", statusDot[status])} />
                    <span className="text-xs font-medium text-foreground truncate">
                      {bidStatusLabel[status]}
                    </span>
                    <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                      {items.length}
                    </span>
                  </div>
                  <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
                    {columnTotal(status)}
                  </span>
                </header>

                <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-2 max-h-[calc(100vh-22rem)]">
                  {items.length === 0 ? (
                    <p className="px-1 py-6 text-center text-[11px] text-muted-foreground/70">
                      No {bidStatusLabel[status].toLowerCase()} bids
                    </p>
                  ) : (
                    <>
                      {visibleItems.map((b) => (
                        <BidCard
                          key={b.id}
                          bid={b}
                          onMove={handleMove}
                          onEdit={handleEdit}
                          onDragStart={handleDragStart}
                          onDragEnd={clearDragState}
                          isDragging={draggedBid?.id === b.id}
                        />
                      ))}
                      {items.length > COLLAPSED_LIMIT && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => toggleColumn(status)}
                          className="h-7 w-full gap-1 text-[11px] text-muted-foreground hover:text-foreground"
                        >
                          {isExpanded ? (
                            <><ChevronUp className="h-3 w-3" /> Show less</>
                          ) : (
                            <><ChevronDown className="h-3 w-3" /> Show {hiddenCount} more</>
                          )}
                        </Button>
                      )}
                    </>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
