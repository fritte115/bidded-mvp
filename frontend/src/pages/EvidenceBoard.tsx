import { Link, useParams } from "react-router-dom";
import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EvidenceBadge } from "@/components/EvidenceBadge";
import { findRun, type EvidenceCategory } from "@/data/mock";
import { ArrowLeft } from "lucide-react";

const cats: ("all" | EvidenceCategory)[] = [
  "all",
  "Deadlines",
  "Mandatory Requirements",
  "Qualification Criteria",
  "Evaluation Criteria",
  "Contract Risks",
  "Required Submission Documents",
];

export default function EvidenceBoard() {
  const { id = "" } = useParams();
  const run = findRun(id);
  const [source, setSource] = useState("all");
  const [cat, setCat] = useState<string>("all");

  if (!run) return <p>Run not found.</p>;

  const evidenceKind = (e: typeof run.evidence[number]) =>
    e.kind ?? (e.companyFieldPath ? "company_profile" : "tender_document");

  const filtered = run.evidence.filter((e) => {
    if (cat !== "all" && e.category !== cat) return false;
    if (source === "tender" && evidenceKind(e) !== "tender_document") return false;
    if (source === "company" && evidenceKind(e) !== "company_profile") return false;
    return true;
  });

  return (
    <>
      <PageHeader
        title="Evidence Board"
        description={`Indexed evidence for run ${run.id}`}
        actions={
          <Button asChild variant="outline">
            <Link to={`/runs/${run.id}`}><ArrowLeft className="h-4 w-4" /> Back to run</Link>
          </Button>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        <Card>
          <CardContent className="space-y-4 p-4">
            <div>
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Source</p>
              <Select value={source} onValueChange={setSource}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All sources</SelectItem>
                  <SelectItem value="tender">Procurement document</SelectItem>
                  <SelectItem value="company">Company profile</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Category</p>
              <Select value={cat} onValueChange={setCat}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {cats.map((c) => (
                    <SelectItem key={c} value={c}>{c === "all" ? "All categories" : c}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="rounded-md border border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
              <span className="font-mono">{filtered.length}</span> of <span className="font-mono">{run.evidence.length}</span> items shown.
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-3 md:grid-cols-2">
          {filtered.map((e) => {
            const kind = evidenceKind(e);
            return (
              <Card key={e.id}>
                <CardContent className="space-y-2 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <EvidenceBadge id={e.id} />
                    <div className="flex items-center gap-1.5">
                      <span
                        className={
                          kind === "company_profile"
                            ? "rounded-sm border border-info/30 bg-info/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-info"
                            : "rounded-sm border border-border bg-secondary px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground"
                        }
                      >
                        {kind === "company_profile" ? "Company" : "Tender"}
                      </span>
                      <span className="rounded-sm bg-secondary px-2 py-0.5 text-[11px] font-medium text-secondary-foreground">
                        {e.category}
                      </span>
                    </div>
                  </div>
                  <p className="font-mono text-[11px] text-muted-foreground break-all">{e.key}</p>
                  <blockquote className="rounded-md border-l-2 border-primary bg-secondary/40 px-3 py-2 text-sm leading-snug">
                    “{e.excerpt}”
                  </blockquote>
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                    <span className="font-mono break-all">
                      {e.source}
                      {kind === "tender_document" && e.page > 0 ? ` · p.${e.page}` : ""}
                      {kind === "company_profile" && e.companyFieldPath ? ` · ${e.companyFieldPath}` : ""}
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {e.referencedBy.map((a) => (
                        <span key={a} className="rounded-md border border-border bg-card px-1.5 py-0.5 text-[10px]">
                          {a}
                        </span>
                      ))}
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </>
  );
}
