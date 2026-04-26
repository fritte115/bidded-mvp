import { Link, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Activity,
  ArrowLeft,
  ArrowUpDown,
  Bookmark,
  BookmarkCheck,
  Building2,
  Calendar,
  Compass,
  Download,
  ExternalLink,
  Eye,
  FileText,
  Globe,
  Hourglass,
  Inbox,
  Loader2,
  MapPin,
  Maximize2,
  RefreshCw,
  Search,
  Sparkles,
  Tag,
  X,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
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
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { fetchExploreTenders, fetchMoreExploreTenders, fetchTendersFromTed } from "@/lib/api";
import {
  daysUntil,
  sourceMeta,
  type ExternalSource,
  type ExternalTender,
} from "@/data/exploreMock";
import {
  getSavedTenderIds,
  importExternalTender,
  isTenderImported,
  toggleSavedTender,
} from "@/lib/explore";

type SortKey = "default" | "recent" | "closing" | "value";
type SourceFilter = ExternalSource | "ALL" | "SAVED";

const SOURCES: ExternalSource[] = ["TED", "Clira", "Mercell", "Visma"];

function StatTile({
  icon: Icon,
  label,
  value,
  hint,
  tone = "default",
  pulse = false,
  onClick,
  active = false,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number | string;
  hint?: string;
  tone?: "default" | "info" | "success" | "warning";
  pulse?: boolean;
  onClick?: () => void;
  active?: boolean;
}) {
  const toneStyles = {
    default: "text-foreground",
    info: "text-info",
    success: "text-success",
    warning: "text-warning",
  }[tone];
  const iconBg = {
    default: "bg-muted text-muted-foreground",
    info: "bg-info/10 text-info",
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
  }[tone];
  const interactive = !!onClick;
  const Comp = interactive ? "button" : "div";
  return (
    <Comp
      {...(interactive ? { onClick } : {})}
      className={cn(
        "group relative flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-left transition-all",
        interactive && "hover:border-foreground/20 hover:shadow-sm cursor-pointer",
        active && "border-primary/40 bg-primary/5 ring-1 ring-primary/20",
      )}
    >
      <div className={cn("relative flex h-9 w-9 items-center justify-center rounded-md", iconBg)}>
        <Icon className="h-4 w-4" />
        {pulse && (
          <span className="absolute -right-0.5 -top-0.5 flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-info opacity-70" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-info" />
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <div className="mt-0.5 flex items-baseline gap-2">
          <p className={cn("text-xl font-semibold tabular-nums tracking-tight", toneStyles)}>
            {value}
          </p>
          {hint && <p className="truncate text-[11px] text-muted-foreground">{hint}</p>}
        </div>
      </div>
    </Comp>
  );
}

function SourcePill({
  source,
  count,
  active,
  onClick,
}: {
  source: ExternalSource | "ALL" | "SAVED";
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  const label =
    source === "ALL" ? "All sources" : source === "SAVED" ? "Saved" : sourceMeta(source).label;
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
      {source === "SAVED" && <Bookmark className="h-3.5 w-3.5" />}
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

function SourceBadge({ source }: { source: ExternalSource }) {
  const meta = sourceMeta(source);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1",
        meta.bg,
        meta.text,
        meta.ring,
      )}
    >
      {meta.label}
    </span>
  );
}

function ClosingPill({ deadline }: { deadline: string }) {
  const days = daysUntil(deadline);
  if (days <= -2) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
        {days === -999 ? "—" : "Closed"}
      </span>
    );
  }
  const tone =
    days <= 3
      ? "bg-danger/10 text-danger ring-danger/20"
      : days <= 10
      ? "bg-warning/10 text-warning ring-warning/20"
      : "bg-muted text-muted-foreground ring-border";
  const showIcon = days <= 7;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium tabular-nums ring-1",
        tone,
      )}
    >
      {showIcon && <Hourglass className="h-3 w-3" />}
      {days === 0 ? "Today" : `${days}d`}
    </span>
  );
}

function formatValue(value: number, currency: "SEK" | "EUR") {
  if (!value || !isFinite(value) || value <= 0) return "Not disclosed";
  return `${value.toLocaleString("sv-SE")} M${currency}`;
}

function formatDate(iso: string) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("sv-SE", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function Fact({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div>
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-0.5 inline-flex items-center gap-1 text-sm font-medium text-foreground">
        {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground" />}
        {value}
      </p>
    </div>
  );
}

export default function ExploreProcurements() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [q, setQ] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("ALL");
  const [sortKey, setSortKey] = useState<SortKey>("default");
  const [country, setCountry] = useState<string>("ALL");
  const [valueRange, setValueRange] = useState<string>("ALL");
  const [refreshing, setRefreshing] = useState(false);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [savedIds, setSavedIds] = useState<string[]>(() => getSavedTenderIds());
  const [allTenders, setAllTenders] = useState<ExternalTender[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const seenIds = useRef(new Set<string>());

  // Load page 1 on mount
  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    fetchExploreTenders().then((results) => {
      if (cancelled) return;
      seenIds.current = new Set(results.map((t) => t.id));
      setAllTenders(results);
      setHasMore(results.length >= 50);
      setIsLoading(false);
    }).catch(() => {
      if (!cancelled) setIsLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  const countries = useMemo(() => {
    const set = new Set<string>();
    allTenders.forEach((t) => set.add(t.country));
    return Array.from(set).sort();
  }, [allTenders]);

  const counts = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    let live = 0;
    let newToday = 0;
    let closingThisWeek = 0;
    for (const t of allTenders) {
      const d = daysUntil(t.deadline);
      if (d >= 0) live++;
      const pub = new Date(t.publishedAt);
      pub.setHours(0, 0, 0, 0);
      if (pub.getTime() === today.getTime()) newToday++;
      if (d >= 0 && d <= 7) closingThisWeek++;
    }
    const bySource: Record<ExternalSource, number> = { TED: 0, Clira: 0, Mercell: 0, Visma: 0 };
    allTenders.forEach((t) => { bySource[t.source]++; });
    return { total: allTenders.length, live, newToday, closingThisWeek, saved: savedIds.length, bySource };
  }, [allTenders, savedIds]);

  const filtered = useMemo(() => {
    const base = allTenders.filter((t) => {
      if (sourceFilter === "SAVED" && !savedIds.includes(t.id)) return false;
      if (sourceFilter !== "ALL" && sourceFilter !== "SAVED" && t.source !== sourceFilter) return false;
      if (country !== "ALL" && t.country !== country) return false;
      if (q && !`${t.title} ${t.buyer}`.toLowerCase().includes(q.toLowerCase())) return false;
      if (valueRange !== "ALL") {
        const v = t.estimatedValueMSEK;
        if (valueRange === "lt25" && v >= 25) return false;
        if (valueRange === "25to100" && (v < 25 || v >= 100)) return false;
        if (valueRange === "gte100" && v < 100) return false;
      }
      return true;
    });
    if (sortKey === "default") return base;
    const sorted = [...base];
    if (sortKey === "closing") {
      sorted.sort((a, b) => new Date(a.deadline).getTime() - new Date(b.deadline).getTime());
    } else if (sortKey === "value") {
      sorted.sort((a, b) => b.estimatedValueMSEK - a.estimatedValueMSEK);
    } else {
      sorted.sort((a, b) => new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime());
    }
    return sorted;
  }, [allTenders, q, sourceFilter, country, valueRange, sortKey, savedIds]);

  const previewTender = useMemo(
    () => (previewId ? allTenders.find((t) => t.id === previewId) ?? null : null),
    [previewId, allTenders],
  );

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await fetchTendersFromTed();
      toast.success("TED feed refreshed", {
        description: "Reloading latest notices…",
      });
      // Reload from page 1, reset accumulated list
      const results = await fetchExploreTenders();
      seenIds.current = new Set(results.map((t) => t.id));
      setAllTenders(results);
      setCurrentPage(1);
      setHasMore(results.length >= 50);
    } catch {
      toast.success("Feed refreshed", { description: "All sources are up to date." });
    } finally {
      setRefreshing(false);
    }
  };

  const handleToggleSave = (id: string, title: string) => {
    const nowSaved = toggleSavedTender(id);
    setSavedIds(getSavedTenderIds());
    toast(nowSaved ? "Saved for later" : "Removed from saved", { description: title });
  };

  const handleImport = (t: ExternalTender) => {
    if (!user?.companyId) {
      toast.error("Cannot import", { description: "No company context — please log in." });
      return;
    }
    if (isTenderImported(t.id, user.companyId)) {
      toast("Already imported", { description: "This tender is already in your procurements." });
      navigate("/procurements");
      return;
    }
    importExternalTender(t, user.companyId);
    toast.success("Imported — opening in My Procurements", { description: t.title });
    setPreviewId(null);
    setTimeout(() => navigate("/procurements"), 250);
  };

  const handleLoadMore = async () => {
    setLoadingMore(true);
    try {
      const nextPage = currentPage + 1;
      const more = await fetchMoreExploreTenders(nextPage);
      if (more.length === 0) {
        setHasMore(false);
      } else {
        // Deduplicate: only append tenders we haven't seen yet
        const fresh = more.filter((t) => !seenIds.current.has(t.id));
        fresh.forEach((t) => seenIds.current.add(t.id));
        setAllTenders((prev) => [...prev, ...fresh]);
        setCurrentPage(nextPage);
        if (more.length < 50) setHasMore(false);
      }
    } catch {
      toast.error("Failed to load more tenders");
    } finally {
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    if (!previewId) setSavedIds(getSavedTenderIds());
  }, [previewId]);

  return (
    <>
      <PageHeader
        title="Explore Procurements"
        description="Discover live Swedish & EU tenders from TED, Clira, Mercell and Visma Opic. Preview, save, and import promising opportunities."
        actions={
          <>
            <Button variant="ghost" asChild>
              <Link to="/procurements">
                <ArrowLeft className="h-4 w-4" />
                My procurements
              </Link>
            </Button>
            <Button variant="outline" onClick={handleRefresh} disabled={refreshing}>
              <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
              Refresh
            </Button>
          </>
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile
          icon={Globe}
          label="Live opportunities"
          value={isLoading ? "…" : counts.live}
          hint={`across ${SOURCES.length} sources`}
        />
        <StatTile
          icon={Sparkles}
          label="New today"
          value={isLoading ? "…" : counts.newToday}
          hint={counts.newToday > 0 ? "fresh from feed" : "—"}
          tone="info"
          pulse={counts.newToday > 0}
        />
        <StatTile
          icon={Hourglass}
          label="Closing this week"
          value={isLoading ? "…" : counts.closingThisWeek}
          hint={counts.closingThisWeek > 0 ? "act fast" : "—"}
          tone="warning"
        />
        <StatTile
          icon={BookmarkCheck}
          label="Saved"
          value={counts.saved}
          hint={counts.saved > 0 ? "click to filter" : "—"}
          tone="success"
          onClick={counts.saved > 0 ? () => setSourceFilter("SAVED") : undefined}
          active={sourceFilter === "SAVED"}
        />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="mb-4 inline-flex flex-wrap items-center gap-1 rounded-lg border border-border bg-muted/40 p-1">
            <SourcePill
              source="ALL"
              count={counts.total}
              active={sourceFilter === "ALL"}
              onClick={() => setSourceFilter("ALL")}
            />
            {SOURCES.map((s) => (
              <SourcePill
                key={s}
                source={s}
                count={counts.bySource[s]}
                active={sourceFilter === s}
                onClick={() => setSourceFilter(s)}
              />
            ))}
            <SourcePill
              source="SAVED"
              count={counts.saved}
              active={sourceFilter === "SAVED"}
              onClick={() => setSourceFilter("SAVED")}
            />
          </div>

          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center">
              <div className="relative w-full sm:max-w-xs">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search title or buyer…"
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

              <Select value={country} onValueChange={setCountry}>
                <SelectTrigger className="h-9 w-[140px]">
                  <SelectValue placeholder="Country" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All countries</SelectItem>
                  {countries.map((c) => (
                    <SelectItem key={c} value={c}>{c}</SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select value={valueRange} onValueChange={setValueRange}>
                <SelectTrigger className="h-9 w-[160px]">
                  <SelectValue placeholder="Value" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">Any value</SelectItem>
                  <SelectItem value="lt25">&lt; 25 M</SelectItem>
                  <SelectItem value="25to100">25 – 100 M</SelectItem>
                  <SelectItem value="gte100">≥ 100 M</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-2">
              <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground" />
              <Select value={sortKey} onValueChange={(v) => setSortKey(v as SortKey)}>
                <SelectTrigger className="h-9 w-[180px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">As loaded</SelectItem>
                  <SelectItem value="recent">Most recent</SelectItem>
                  <SelectItem value="closing">Closing soon</SelectItem>
                  <SelectItem value="value">Value (high→low)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {filtered.length === 0 && !isLoading ? (
            <div className="rounded-md border border-dashed border-border bg-muted/20 p-6">
              <EmptyState
                icon={Compass}
                title="No tenders match your filters"
                description="Try widening the source, country, or value range — or clear the search."
                action={
                  <Button
                    variant="outline"
                    onClick={() => {
                      setQ("");
                      setSourceFilter("ALL");
                      setCountry("ALL");
                      setValueRange("ALL");
                    }}
                  >
                    Reset filters
                  </Button>
                }
              />
            </div>
          ) : (
            <div className="overflow-hidden rounded-md border border-border">
              <Table>
                <TableHeader className="sticky top-0 z-10 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Tender</TableHead>
                    <TableHead className="whitespace-nowrap">Source</TableHead>
                    <TableHead className="whitespace-nowrap">Country</TableHead>
                    <TableHead className="whitespace-nowrap text-right">Est. value</TableHead>
                    <TableHead className="whitespace-nowrap">Closes in</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((t) => {
                    const saved = savedIds.includes(t.id);
                    const imported = user?.companyId ? isTenderImported(t.id, user.companyId) : false;
                    return (
                      <TableRow
                        key={t.id}
                        onClick={() => setPreviewId(t.id)}
                        className="group cursor-pointer transition-colors hover:bg-muted/40"
                      >
                        <TableCell className="py-3.5">
                          <div className="flex flex-col leading-tight">
                            <span className="font-medium text-foreground group-hover:text-primary">
                              {t.title}
                            </span>
                            <span className="mt-0.5 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                              <Building2 className="h-3 w-3" />
                              {t.buyer}
                              <span className="text-muted-foreground/50">·</span>
                              <span>{t.procedureType}</span>
                              {imported && (
                                <>
                                  <span className="text-muted-foreground/50">·</span>
                                  <span className="inline-flex items-center gap-0.5 text-success">
                                    <Inbox className="h-3 w-3" /> Imported
                                  </span>
                                </>
                              )}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="py-3.5">
                          <SourceBadge source={t.source} />
                        </TableCell>
                        <TableCell className="py-3.5 text-sm text-muted-foreground">
                          <span className="inline-flex items-center gap-1">
                            <MapPin className="h-3 w-3" />
                            {t.country}
                          </span>
                        </TableCell>
                        <TableCell className="py-3.5 text-right text-sm font-medium tabular-nums text-foreground">
                          {formatValue(t.estimatedValueMSEK, t.currency)}
                        </TableCell>
                        <TableCell className="py-3.5">
                          <ClosingPill deadline={t.deadline} />
                        </TableCell>
                        <TableCell
                          className="py-3.5 text-right"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="flex justify-end gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 px-2"
                              onClick={() => setPreviewId(t.id)}
                              aria-label="Preview"
                            >
                              <Eye className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className={cn("h-8 px-2", saved && "text-primary")}
                              onClick={() => handleToggleSave(t.id, t.title)}
                              aria-label={saved ? "Unsave" : "Save"}
                            >
                              {saved ? (
                                <BookmarkCheck className="h-3.5 w-3.5" />
                              ) : (
                                <Bookmark className="h-3.5 w-3.5" />
                              )}
                            </Button>
                            <Button
                              size="sm"
                              className="h-8"
                              onClick={() => handleImport(t)}
                              disabled={imported}
                            >
                              <Download className="h-3.5 w-3.5" />
                              {imported ? "Imported" : "Import"}
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

          {hasMore && (
            <div className="mt-3 flex justify-center">
              <Button variant="outline" onClick={handleLoadMore} disabled={loadingMore}>
                {loadingMore ? (
                  <><Loader2 className="h-4 w-4 animate-spin" /> Loading…</>
                ) : (
                  "Load 50 more"
                )}
              </Button>
            </div>
          )}

          <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
            <span className="tabular-nums">
              {isLoading ? "Loading…" : `Showing ${filtered.length} of ${counts.total} opportunities`}
            </span>
            <span className="inline-flex items-center gap-1">
              <Activity className="h-3 w-3" />
              TED · Clira · Mercell · Visma Opic
            </span>
          </div>
        </CardContent>
      </Card>

      <Sheet open={!!previewTender} onOpenChange={(open) => !open && setPreviewId(null)}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          {previewTender && (
            <>
              <SheetHeader className="text-left">
                <div className="mb-2 flex items-center gap-2">
                  <SourceBadge source={previewTender.source} />
                  <ClosingPill deadline={previewTender.deadline} />
                </div>
                <SheetTitle className="pr-6 text-xl leading-snug">
                  {previewTender.title}
                </SheetTitle>
                <SheetDescription className="flex items-center gap-1.5">
                  <Building2 className="h-3.5 w-3.5" />
                  {previewTender.buyer}
                </SheetDescription>
              </SheetHeader>

              <div className="mt-6 space-y-6">
                <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-muted/30 p-3">
                  <Fact
                    label="Estimated value"
                    value={formatValue(previewTender.estimatedValueMSEK, previewTender.currency)}
                  />
                  <Fact label="Procedure" value={previewTender.procedureType} />
                  <Fact label="Contract type" value={previewTender.contractType} />
                  <Fact
                    label="Country / NUTS"
                    value={`${previewTender.country} · ${previewTender.nutsCode}`}
                  />
                  <Fact label="Published" value={formatDate(previewTender.publishedAt)} icon={Calendar} />
                  <Fact label="Deadline" value={formatDate(previewTender.deadline)} icon={Hourglass} />
                </div>

                {previewTender.cpvCodes.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      CPV codes
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {previewTender.cpvCodes.map((code) => (
                        <Badge key={code} variant="secondary" className="font-mono">
                          <Tag className="h-3 w-3" />
                          {code}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Summary
                  </p>
                  <p className="text-sm leading-relaxed text-foreground">
                    {previewTender.summary ||
                      `${previewTender.buyer} is seeking bids for a ${previewTender.contractType.toLowerCase()} contract in ${previewTender.country}. ` +
                      (previewTender.procedureType ? `The procurement follows a ${previewTender.procedureType.toLowerCase()} procedure. ` : "") +
                      (previewTender.estimatedValueMSEK > 0 ? `Estimated contract value: ${previewTender.estimatedValueMSEK} M${previewTender.currency}. ` : "") +
                      "Import this tender to run the full AI analysis pipeline and generate a bid recommendation."}
                  </p>
                </div>

                {previewTender.requirements.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Key requirements
                    </p>
                    <ul className="space-y-1.5">
                      {previewTender.requirements.map((r, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-foreground">
                          <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" />
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {previewTender.attachments.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Source documents
                    </p>
                    <div className="space-y-1.5">
                      {previewTender.attachments.map((a) => (
                        <div
                          key={a.filename}
                          className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm"
                        >
                          <span className="flex items-center gap-2 truncate text-foreground">
                            <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            <span className="truncate">{a.filename}</span>
                          </span>
                          <span className="ml-2 shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                            {a.sizeKB} KB
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {previewTender.sourceUrl && (
                  <a
                    href={previewTender.sourceUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    View original notice
                  </a>
                )}
              </div>

              <div className="mt-8 flex flex-col gap-2 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
                <Button
                  variant="ghost"
                  size="sm"
                  className="justify-start text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    const tid = previewTender.id;
                    setPreviewId(null);
                    navigate(`/procurements/explore/${encodeURIComponent(tid)}`, {
                      state: { tender: previewTender },
                    });
                  }}
                >
                  <Maximize2 className="h-3.5 w-3.5" />
                  View full details
                </Button>
                <div className="flex items-center gap-2 sm:justify-end">
                  <Button
                    variant="outline"
                    onClick={() => handleToggleSave(previewTender.id, previewTender.title)}
                  >
                    {savedIds.includes(previewTender.id) ? (
                      <>
                        <BookmarkCheck className="h-4 w-4" /> Saved
                      </>
                    ) : (
                      <>
                        <Bookmark className="h-4 w-4" /> Save
                      </>
                    )}
                  </Button>
                  <Button
                    onClick={() => handleImport(previewTender)}
                    disabled={user?.companyId ? isTenderImported(previewTender.id, user.companyId) : false}
                  >
                    <Download className="h-4 w-4" />
                    {user?.companyId && isTenderImported(previewTender.id, user.companyId)
                      ? "Imported"
                      : "Import"}
                  </Button>
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
