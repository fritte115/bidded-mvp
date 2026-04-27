import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ChevronDown, ChevronUp, Gavel } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { VerdictBadge } from "@/components/VerdictBadge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatDate, verdictLabel, type Verdict } from "@/data/mock";
import type { DecisionRow } from "@/lib/api";
import { renderFormattedText } from "@/lib/richText";

type Props = {
  decisions: DecisionRow[];
  isLoading: boolean;
};

export function DashboardDecisionDropdown({ decisions, isLoading }: Props) {
  const [open, setOpen] = useState(false);
  const [verdict, setVerdict] = useState<Verdict | "all">("all");
  const [date, setDate] = useState("");

  const filtered = useMemo(
    () =>
      decisions.filter((decision) => {
        if (verdict !== "all" && decision.verdict !== verdict) return false;
        if (date) {
          const rowDate = new Date(decision.completedAt ?? decision.startedAt)
            .toISOString()
            .slice(0, 10);
          if (rowDate !== date) return false;
        }
        return true;
      }),
    [date, decisions, verdict],
  );

  return (
    <div id="decisions" className="mt-4 border-t border-border pt-4">
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-9 w-full justify-between sm:w-auto"
        aria-expanded={open}
        aria-controls="dashboard-decisions-list"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="inline-flex items-center gap-2">
          <Gavel className="h-4 w-4" />
          All decisions
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold tabular-nums text-muted-foreground">
            {decisions.length}
          </span>
        </span>
        {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </Button>

      {open && (
        <section
          id="dashboard-decisions-list"
          aria-label="All decisions list"
          className="mt-3 space-y-3"
        >
          <div className="flex flex-col gap-2 sm:flex-row">
            <Select value={verdict} onValueChange={(value) => setVerdict(value as Verdict | "all")}>
              <SelectTrigger className="w-full sm:w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All verdicts</SelectItem>
                <SelectItem value="BID">{verdictLabel.BID}</SelectItem>
                <SelectItem value="NO_BID">{verdictLabel.NO_BID}</SelectItem>
                <SelectItem value="CONDITIONAL_BID">{verdictLabel.CONDITIONAL_BID}</SelectItem>
              </SelectContent>
            </Select>
            <Input
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
              className="sm:w-48"
            />
          </div>

          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading decisions...</p>
          ) : filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground">No decisions found.</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {filtered.map((decision) => (
                <Card key={decision.id}>
                  <CardContent className="space-y-3 p-5">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-xs uppercase tracking-wide text-muted-foreground">
                          Procurement
                        </p>
                        <h3 className="text-base font-semibold leading-tight">
                          {decision.tenderName}
                        </h3>
                      </div>
                      <VerdictBadge verdict={decision.verdict} size="md" />
                    </div>
                    <ConfidenceBar value={decision.confidence} />
                    <p className="line-clamp-2 text-sm text-muted-foreground">
                      {renderFormattedText(decision.topReason)}
                    </p>
                    <div className="flex items-center justify-between border-t border-border pt-3">
                      <span className="text-xs text-muted-foreground">
                        {formatDate(decision.completedAt ?? decision.startedAt)}
                      </span>
                      <div className="flex gap-1">
                        <Button asChild variant="ghost" size="sm" className="h-7 text-xs">
                          <Link to={`/runs/${decision.id}`}>View Run</Link>
                        </Button>
                        <Button asChild variant="outline" size="sm" className="h-7 text-xs">
                          <Link to={`/decisions/${decision.id}`}>
                            Full Decision <ArrowRight className="h-3 w-3" />
                          </Link>
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
