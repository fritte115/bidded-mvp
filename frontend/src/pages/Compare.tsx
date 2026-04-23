import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { EmptyState } from "@/components/EmptyState";
import { BidRecommendation } from "@/components/BidRecommendation";
import { fetchCompareRows } from "@/lib/api";
import { buildBidDraftPath } from "@/lib/bidIntegrationMapping";
import { humanizeVerdictText, verdictLabel, type Verdict } from "@/data/mock";
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronDown,
  GitCompareArrows,
  X,
  CircleDot,
  FileText,
  Lightbulb,
  Star,
} from "lucide-react";
import { cn } from "@/lib/utils";

const verdictIcon: Record<Verdict, typeof Check> = {
  BID: Check,
  NO_BID: X,
  CONDITIONAL_BID: CircleDot,
};

const verdictTone: Record<Verdict, string> = {
  BID: "text-success",
  NO_BID: "text-danger",
  CONDITIONAL_BID: "text-warning",
};

const verdictBorder: Record<Verdict, string> = {
  BID: "border-l-success",
  NO_BID: "border-l-danger",
  CONDITIONAL_BID: "border-l-warning",
};

const verdictTileBg: Record<Verdict, string> = {
  BID: "bg-success/5 border-success/20",
  NO_BID: "bg-danger/5 border-danger/20",
  CONDITIONAL_BID: "bg-warning/5 border-warning/20",
};

const compactVerdictLabel: Record<Verdict, string> = {
  BID: "Bid",
  NO_BID: "No bid",
  CONDITIONAL_BID: "Cond.",
};

const compactVerdictClass: Record<Verdict, string> = {
  BID: "border-success/30 bg-success/10 text-success",
  NO_BID: "border-danger/30 bg-danger/10 text-danger",
  CONDITIONAL_BID: "border-warning/30 bg-warning/10 text-warning",
};

export default function Compare() {
  const [params, setParams] = useSearchParams();
  const idsParam = params.get("ids");

  const { data: allWithVerdict = [], isLoading } = useQuery({
    queryKey: ["compare-rows"],
    queryFn: fetchCompareRows,
    refetchInterval: 15_000,
  });

  const selectedIds = useMemo(() => {
    if (idsParam) return idsParam.split(",").filter(Boolean);
    return allWithVerdict.map((p) => p.tenderId);
  }, [idsParam, allWithVerdict]);

  const selected = useMemo(
    () => allWithVerdict.filter((p) => selectedIds.includes(p.tenderId)),
    [allWithVerdict, selectedIds],
  );

  const grouped = useMemo(() => {
    const g: Record<Verdict, typeof selected> = { BID: [], NO_BID: [], CONDITIONAL_BID: [] };
    selected.forEach((p) => { if (p.verdict) g[p.verdict].push(p); });
    return g;
  }, [selected]);

  const topPickId = useMemo(() => {
    return grouped.BID.slice().sort((a, b) => b.confidence - a.confidence)[0]?.tenderId;
  }, [grouped]);

  const toggle = (id: string) => {
    const next = selectedIds.includes(id)
      ? selectedIds.filter((x) => x !== id)
      : [...selectedIds, id];
    setParams(next.length === 0 ? {} : { ids: next.join(",") });
  };

  return (
    <>
      <PageHeader
        title="Compare Procurements"
        actions={
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline">
                <GitCompareArrows className="h-4 w-4" />
                Pick procurements
                <span className="ml-1 rounded-md bg-secondary px-1.5 py-0.5 text-xs font-mono tabular-nums text-secondary-foreground">
                  {selected.length}
                </span>
                <ChevronDown className="h-4 w-4 opacity-60" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-72 p-2">
              <div className="px-2 py-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Procurements with a decision
              </div>
              <div className="space-y-1">
                {allWithVerdict.map((p) => {
                  const checked = selectedIds.includes(p.tenderId);
                  return (
                    <label
                      key={p.tenderId}
                      className="flex cursor-pointer items-start gap-2 rounded-md p-2 hover:bg-accent"
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={() => toggle(p.tenderId)}
                        className="mt-0.5"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm">{p.tenderName}</p>
                        <p className={cn("text-xs", verdictTone[p.verdict])}>
                          {verdictLabel[p.verdict]} · {p.confidence}%
                        </p>
                      </div>
                    </label>
                  );
                })}
              </div>
            </PopoverContent>
          </Popover>
        }
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading procurements…</p>
      ) : selected.length === 0 ? (
        <EmptyState
          icon={GitCompareArrows}
          title="No procurements selected"
          description="Pick at least one procurement with a completed decision to start comparing."
        />
      ) : (
        <div className="space-y-6">
          {/* Verdict tiles */}
          <div className="grid gap-4 sm:grid-cols-3">
            {(["BID", "CONDITIONAL_BID", "NO_BID"] as Verdict[]).map((v) => {
              const Icon = verdictIcon[v];
              const items = grouped[v];
              const avgConfidence = items.length
                ? Math.round(items.reduce((s, p) => s + p.confidence, 0) / items.length)
                : 0;
              return (
                <Card key={v} className={cn("border", verdictTileBg[v])}>
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className={cn("flex h-8 w-8 items-center justify-center rounded-md bg-card", verdictTone[v])}>
                          <Icon className="h-4 w-4" />
                        </div>
                        <span className="text-xs font-semibold text-muted-foreground">
                          {verdictLabel[v]}
                        </span>
                      </div>
                      <span className={cn("font-mono text-2xl font-semibold tabular-nums", verdictTone[v])}>
                        {items.length}
                      </span>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-3 border-t border-border/60 pt-3">
                      <div>
                        <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                          Count
                        </p>
                        <p className="mt-0.5 font-mono text-sm font-semibold tabular-nums text-foreground">
                          {items.length}
                        </p>
                      </div>
                      <div>
                        <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                          Avg confidence
                        </p>
                        <div className="mt-1.5">
                          {items.length ? (
                            <ConfidenceBar value={avgConfidence} />
                          ) : (
                            <p className="font-mono text-sm text-muted-foreground">—</p>
                          )}
                        </div>
                      </div>
                    </div>
                    {items.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1">
                        {items.slice(0, 4).map((p) => (
                          <span
                            key={p.tenderId}
                            className="max-w-[12rem] truncate rounded-md bg-card px-1.5 py-0.5 text-[11px] text-muted-foreground"
                            title={p.tenderName}
                          >
                            {p.tenderName}
                          </span>
                        ))}
                        {items.length > 4 && (
                          <span className="rounded-md bg-card px-1.5 py-0.5 text-[11px] text-muted-foreground">
                            +{items.length - 4} more
                          </span>
                        )}
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* Comparison table */}
          <Card>
            <CardContent className="p-0">
              <div className="w-full overflow-hidden">
                <Table className="w-full table-fixed">
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[31%] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Procurement</TableHead>
                      <TableHead className="w-[9%] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Verdict</TableHead>
                      <TableHead className="w-[12%] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Confidence</TableHead>
                      <TableHead className="w-[8%] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Docs</TableHead>
                      <TableHead className="w-[40%] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Top reason</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {selected.map((p) => {
                      const isTopPick = p.tenderId === topPickId;
                      const bidPath = buildBidDraftPath(p);
                      return (
                        <TableRow
                          key={p.tenderId}
                          className={cn(
                            "border-l-2",
                            verdictBorder[p.verdict],
                          )}
                        >
                          <TableCell className="align-top">
                            <div className="flex flex-col gap-1">
                              <div className="flex items-center gap-1.5">
                                <span className="truncate text-sm font-semibold text-foreground">
                                  {p.tenderName}
                                </span>
                                {isTopPick && (
                                  <span className="inline-flex shrink-0 items-center gap-0.5 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-primary">
                                    <Star className="h-2.5 w-2.5 fill-current" />
                                    Top
                                  </span>
                                )}
                              </div>
                              <div className="flex items-center gap-3 text-xs">
                                <Link
                                  to={`/runs/${p.runId}`}
                                  className="group inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
                                >
                                  Open run
                                  <ArrowRight className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
                                </Link>
                                <Link
                                  to={`/decisions/${p.runId}`}
                                  className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                                >
                                  <BookOpen className="h-3 w-3" />
                                  Reasoning
                                </Link>
                                {bidPath && (
                                  <Link
                                    to={bidPath}
                                    className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                                  >
                                    {p.existingBidId ? "Open bid" : "Draft bid"}
                                  </Link>
                                )}
                              </div>
                            </div>
                          </TableCell>
                          <TableCell className="align-top">
                            <span className={cn(
                              "inline-flex max-w-full items-center rounded-sm border px-1.5 py-1 text-[10px] font-semibold leading-none whitespace-nowrap",
                              compactVerdictClass[p.verdict],
                            )}>
                              {compactVerdictLabel[p.verdict]}
                            </span>
                          </TableCell>
                          <TableCell className="align-top">
                            <div className="min-w-0 max-w-full space-y-1">
                              <span className="block truncate font-mono text-[11px] font-medium tabular-nums leading-none text-foreground">
                                {p.confidence}%
                              </span>
                              <ConfidenceBar value={p.confidence} showLabel={false} />
                            </div>
                          </TableCell>
                          <TableCell className="align-top">
                            <div className="flex items-center gap-1.5 text-sm">
                              <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                              <span className="font-medium">{p.documentCount}</span>
                            </div>
                          </TableCell>
                          <TableCell className="max-w-xs align-top">
                            <div className="flex gap-2">
                              <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                              <p className="line-clamp-3 text-sm leading-relaxed text-foreground">
                                {humanizeVerdictText(p.topReason)}
                              </p>
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

          {/* Bid recommendations */}
          <section className="space-y-3">
            <div>
              <h2 className="text-base font-semibold text-foreground">Bid recommendations</h2>
              <p className="text-sm text-muted-foreground">
                Suggested rates and estimated competitor pricing per procurement.
              </p>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {selected.map((p) => (
                <BidRecommendation
                  key={p.runId}
                  decision={p}
                  heading={p.tenderName}
                />
              ))}
            </div>
          </section>
        </div>
      )}
    </>
  );
}
