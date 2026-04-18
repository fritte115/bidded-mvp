import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { EmptyState } from "@/components/EmptyState";
import {
  procurements,
  bidStatusLabel,
  bidStatusOrder,
  runs,
  type BidStatus,
  type Procurement,
} from "@/data/mock";
import { estimateBid, formatSEK, type BidEstimate } from "@/lib/bidEstimator";
import {
  ArrowLeft,
  BookOpen,
  Calendar,
  FileQuestion,
  Sparkles,
  Target,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

const WIN_THEMES = [
  "Sovereign cloud",
  "Incumbent advantage",
  "Aggressive pricing",
  "Quality differentiator",
];

function marginTone(pct: number): string {
  if (pct >= 12) return "bg-success/15 text-success";
  if (pct >= 8) return "bg-warning/15 text-warning";
  return "bg-danger/15 text-danger";
}

function deltaInfo(rate: number, estimate: BidEstimate) {
  const deltaPct =
    Math.round(((rate - estimate.recommendedRate) / estimate.recommendedRate) * 1000) / 10;
  const a = Math.abs(deltaPct);
  let tone = "bg-success/15 text-success";
  if (a > 4) tone = deltaPct > 0 ? "bg-warning/15 text-warning" : "bg-danger/15 text-danger";
  return { deltaPct, tone };
}

/** Synthetic stable submission deadline: uploadedAt + 60 days. */
function deadlineFor(p: Procurement): Date {
  const d = new Date(p.uploadedAt);
  d.setDate(d.getDate() + 60);
  return d;
}

function RateBar({
  rate,
  estimate,
}: {
  rate: number;
  estimate: BidEstimate;
}) {
  const min = Math.min(estimate.competitorBand[0], estimate.recommendedRate, rate) * 0.95;
  const max = Math.max(estimate.ceiling, estimate.competitorBand[1], rate) * 1.02;
  const pct = (v: number) => ((v - min) / (max - min)) * 100;

  return (
    <div className="space-y-1.5">
      <div className="relative h-6 rounded-sm bg-muted">
        {/* competitor band */}
        <div
          className="absolute top-1 bottom-1 rounded-sm bg-primary/20"
          style={{
            left: `${pct(estimate.competitorBand[0])}%`,
            width: `${pct(estimate.competitorBand[1]) - pct(estimate.competitorBand[0])}%`,
          }}
          title="Competitor band"
        />
        {/* recommended marker */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-primary"
          style={{ left: `${pct(estimate.recommendedRate)}%` }}
          title="Recommended"
        />
        {/* ceiling marker */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-danger"
          style={{ left: `${pct(estimate.ceiling)}%` }}
          title="Ceiling"
        />
        {/* user rate */}
        <div
          className="absolute -top-1 -bottom-1 w-1 rounded-sm bg-foreground"
          style={{ left: `calc(${pct(rate)}% - 2px)` }}
          title="Your rate"
        />
      </div>
      <div className="flex justify-between font-mono text-[10px] tabular-nums text-muted-foreground">
        <span>{formatSEK(min)}</span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-primary/40" /> band
          <span className="ml-2 inline-block h-2 w-0.5 bg-primary" /> rec
          <span className="ml-2 inline-block h-2 w-0.5 bg-danger" /> ceiling
        </span>
        <span>{formatSEK(max)}</span>
      </div>
    </div>
  );
}

export default function BidEditor() {
  const [params] = useSearchParams();
  const navigate = useNavigate();

  const [procurementId, setProcurementId] = useState<string>(
    params.get("procurement") ?? procurements[0]?.id ?? "",
  );

  const procurement = useMemo(
    () => procurements.find((p) => p.id === procurementId),
    [procurementId],
  );
  const estimate = useMemo(
    () => (procurement ? estimateBid(procurement) : null),
    [procurement],
  );
  const runId = useMemo(
    () => runs.find((r) => r.tenderId === procurementId)?.id,
    [procurementId],
  );

  const [rate, setRate] = useState<number>(estimate?.recommendedRate ?? 1200);
  const [margin, setMargin] = useState<number>(estimate?.inputs.targetMarginPct ?? 12);
  const [hours, setHours] = useState<number>(1600);
  const [status, setStatus] = useState<BidStatus>("draft");
  const [notes, setNotes] = useState<string>("");

  const onPickProcurement = (id: string) => {
    setProcurementId(id);
    const p = procurements.find((x) => x.id === id);
    if (p) {
      const e = estimateBid(p);
      setRate(e.recommendedRate);
      setMargin(e.inputs.targetMarginPct);
    }
  };

  const applyRecommended = () => {
    if (estimate) {
      setRate(estimate.recommendedRate);
      toast.success("Applied recommended rate");
    }
  };

  const addTheme = (theme: string) => {
    const bullet = `• ${theme}: `;
    if (notes.includes(bullet)) return;
    setNotes((prev) => (prev.trim() === "" ? bullet : `${bullet}\n${prev}`));
  };

  const handleSave = () => {
    if (!procurement) return;
    toast.success("Draft bid saved", {
      description: `${formatSEK(rate)} SEK/h · ${bidStatusLabel[status]}`,
    });
    navigate("/bids");
  };

  const totalContractValue = rate * hours;
  const delta = estimate ? deltaInfo(rate, estimate) : null;
  const deadline = procurement ? deadlineFor(procurement) : null;
  const daysToDeadline = deadline
    ? Math.round((deadline.getTime() - Date.now()) / (1000 * 60 * 60 * 24))
    : null;

  return (
    <>
      <PageHeader
        title="New Bid"
        description="Prefilled from the agent recommendation — adjust before adding to the pipeline."
        actions={
          <Button asChild variant="outline">
            <Link to="/bids">
              <ArrowLeft className="h-4 w-4" /> Back to Bids
            </Link>
          </Button>
        }
      />

      {!procurement ? (
        <EmptyState
          icon={FileQuestion}
          title="Pick a procurement to start"
          description="The bid editor needs a procurement to anchor pricing and recommendations."
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardContent className="space-y-5 p-5">
              <div className="space-y-2">
                <Label htmlFor="procurement">Procurement</Label>
                <Select value={procurementId} onValueChange={onPickProcurement}>
                  <SelectTrigger id="procurement">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {procurements.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Procurement context strip */}
              <div className="grid gap-3 rounded-md border border-border bg-muted/30 p-3 sm:grid-cols-4">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Value
                  </p>
                  <p className="font-mono text-sm font-semibold tabular-nums">
                    {procurement.estimatedValueMSEK} MSEK
                  </p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Deadline
                  </p>
                  <p className="inline-flex items-center gap-1 font-mono text-sm tabular-nums">
                    <Calendar className="h-3 w-3 text-muted-foreground" />
                    {daysToDeadline !== null && daysToDeadline >= 0
                      ? `${daysToDeadline}d`
                      : `${Math.abs(daysToDeadline ?? 0)}d ago`}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Strategic fit
                  </p>
                  <p className="text-sm font-medium">{procurement.strategicFit}</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Win prob.
                  </p>
                  <p className="inline-flex items-center gap-1 font-mono text-sm tabular-nums">
                    <TrendingUp className="h-3 w-3 text-muted-foreground" />
                    {Math.round(procurement.winProbability * 100)}%
                  </p>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="rate">Hourly rate (SEK/h)</Label>
                    {delta && (
                      <span
                        className={cn(
                          "inline-flex items-center rounded-sm px-1.5 py-0.5 font-mono text-[11px] tabular-nums",
                          delta.tone,
                        )}
                      >
                        {delta.deltaPct > 0 ? "+" : ""}
                        {delta.deltaPct}% vs. rec
                      </span>
                    )}
                  </div>
                  <Input
                    id="rate"
                    type="number"
                    value={rate}
                    onChange={(e) => setRate(Number(e.target.value))}
                    className="font-mono tabular-nums"
                  />
                  {estimate && <RateBar rate={rate} estimate={estimate} />}
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="margin">Target margin (%)</Label>
                    <span
                      className={cn(
                        "inline-flex items-center rounded-sm px-1.5 py-0.5 font-mono text-[11px] tabular-nums",
                        marginTone(margin),
                      )}
                    >
                      {margin >= 12 ? "healthy" : margin >= 8 ? "thin" : "tight"}
                    </span>
                  </div>
                  <Input
                    id="margin"
                    type="number"
                    value={margin}
                    onChange={(e) => setMargin(Number(e.target.value))}
                    className="font-mono tabular-nums"
                  />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="hours">Estimated hours</Label>
                  <Input
                    id="hours"
                    type="number"
                    value={hours}
                    onChange={(e) => setHours(Number(e.target.value))}
                    className="font-mono tabular-nums"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Total contract value</Label>
                  <div className="flex h-10 items-center rounded-md border border-input bg-muted/40 px-3">
                    <Target className="mr-2 h-3.5 w-3.5 text-muted-foreground" />
                    <span className="font-mono text-sm font-semibold tabular-nums">
                      {formatSEK(totalContractValue)} SEK
                    </span>
                    <span className="ml-auto font-mono text-xs tabular-nums text-muted-foreground">
                      {(totalContractValue / 1_000_000).toFixed(2)} MSEK
                    </span>
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="status">Pipeline status</Label>
                <Select value={status} onValueChange={(v) => setStatus(v as BidStatus)}>
                  <SelectTrigger id="status">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {bidStatusOrder.map((s) => (
                      <SelectItem key={s} value={s}>
                        {bidStatusLabel[s]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="notes">Notes</Label>
                  <div className="flex flex-wrap gap-1">
                    {WIN_THEMES.map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => addTheme(t)}
                        className="rounded-sm border border-border bg-muted/40 px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                      >
                        + {t}
                      </button>
                    ))}
                  </div>
                </div>
                <Textarea
                  id="notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={5}
                  placeholder="Win themes, pricing rationale, sign-off conditions…"
                />
              </div>

              <div className="flex justify-end gap-2 border-t border-border pt-4">
                <Button variant="ghost" asChild>
                  <Link to="/bids">Cancel</Link>
                </Button>
                <Button onClick={handleSave}>Save draft</Button>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-4">
            {estimate && (
              <Card>
                <CardContent className="space-y-3 p-5">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    <Sparkles className="h-3.5 w-3.5 text-primary" />
                    Agent recommendation
                  </div>
                  <div>
                    <p className="font-mono text-2xl font-semibold tabular-nums">
                      {formatSEK(estimate.recommendedRate)}{" "}
                      <span className="text-sm font-normal text-muted-foreground">
                        SEK/h
                      </span>
                    </p>
                    <p className="font-mono text-xs tabular-nums text-muted-foreground">
                      range {formatSEK(estimate.recommendedRange[0])} –{" "}
                      {formatSEK(estimate.recommendedRange[1])}
                    </p>
                  </div>

                  <Button
                    onClick={applyRecommended}
                    variant="secondary"
                    size="sm"
                    className="w-full"
                    disabled={rate === estimate.recommendedRate}
                  >
                    Apply recommended rate
                  </Button>

                  <Separator />

                  <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Competitor band
                    </p>
                    <RateBar rate={rate} estimate={estimate} />
                    <p className="font-mono text-sm tabular-nums">
                      {formatSEK(estimate.competitorBand[0])} –{" "}
                      {formatSEK(estimate.competitorBand[1])} SEK/h
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Likely {estimate.numLikelyBidders[0]}–{estimate.numLikelyBidders[1]}{" "}
                      bidders · ceiling {formatSEK(estimate.ceiling)} SEK/h
                    </p>
                  </div>

                  <Separator />

                  <p className="text-xs leading-relaxed text-muted-foreground">
                    Margin {estimate.inputs.targetMarginPct}% · win{" "}
                    {estimate.inputs.winProbabilityPct}% · fit{" "}
                    {estimate.inputs.strategicFit} · weights price{" "}
                    {estimate.inputs.evaluationWeights.price} / quality{" "}
                    {estimate.inputs.evaluationWeights.quality}
                  </p>

                  {runId && (
                    <Button asChild variant="outline" size="sm" className="w-full">
                      <Link to={`/decisions/${runId}`}>
                        <BookOpen className="h-3.5 w-3.5" />
                        See full reasoning
                      </Link>
                    </Button>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
    </>
  );
}
