import { Link } from "react-router-dom";
import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { VerdictBadge } from "@/components/VerdictBadge";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { runs, formatDate } from "@/data/mock";
import { ArrowRight } from "lucide-react";

export default function Decisions() {
  const [verdict, setVerdict] = useState("all");
  const [date, setDate] = useState("");

  const decisions = runs.filter((r) => r.judge);
  const filtered = decisions.filter(
    (r) => verdict === "all" || r.judge!.verdict === verdict,
  );

  return (
    <>
      <PageHeader title="Bid Decisions" />

      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <Select value={verdict} onValueChange={setVerdict}>
          <SelectTrigger className="w-full sm:w-56"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All verdicts</SelectItem>
            <SelectItem value="BID">BID</SelectItem>
            <SelectItem value="NO_BID">NO BID</SelectItem>
            <SelectItem value="CONDITIONAL_BID">CONDITIONAL BID</SelectItem>
          </SelectContent>
        </Select>
        <Input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="sm:w-48"
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {filtered.map((r) => (
          <Card key={r.id}>
            <CardContent className="space-y-3 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Procurement</p>
                  <h3 className="text-base font-semibold leading-tight">{r.tenderName}</h3>
                </div>
                {r.judge && <VerdictBadge verdict={r.judge.verdict} size="md" />}
              </div>
              {r.judge && <ConfidenceBar value={r.judge.confidence} />}
              <p className="line-clamp-2 text-sm text-muted-foreground">{r.judge?.citedMemo}</p>
              <div className="flex items-center justify-between border-t border-border pt-3">
                <span className="text-xs text-muted-foreground">{formatDate(r.completedAt ?? r.startedAt)}</span>
                <div className="flex gap-1">
                  <Button asChild variant="ghost" size="sm" className="h-7 text-xs">
                    <Link to={`/runs/${r.id}`}>View Run</Link>
                  </Button>
                  <Button asChild variant="outline" size="sm" className="h-7 text-xs">
                    <Link to={`/decisions/${r.id}`}>Full Decision <ArrowRight className="h-3 w-3" /></Link>
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}
