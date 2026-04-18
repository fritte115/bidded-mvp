import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { VerdictBadge } from "@/components/VerdictBadge";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { EvidenceBadge } from "@/components/EvidenceBadge";
import { cn } from "@/lib/utils";
import type { AgentMotion, AgentMotionFinding } from "@/data/mock";
import { ShieldCheck, Trophy, Wallet, Flame } from "lucide-react";

const agentMeta: Record<
  string,
  { icon: typeof ShieldCheck; tint: string }
> = {
  "Compliance Officer": { icon: ShieldCheck, tint: "text-info" },
  "Win Strategist": { icon: Trophy, tint: "text-success" },
  "Delivery/CFO": { icon: Wallet, tint: "text-warning" },
  "Red Team": { icon: Flame, tint: "text-danger" },
};

/** Collapse odd whitespace from PDF extraction / concatenated templates. */
function formatMotionLine(text: string) {
  return text.replace(/\s+/g, " ").trim();
}

const EVIDENCE_KEY_TOKEN =
  /^(EVD-\d+|TENDER-[A-Za-z0-9._-]+|COMPANY-[A-Za-z0-9._-]+)$/;

function highlightEvidence(text: string) {
  const cleaned = formatMotionLine(text);
  const parts = cleaned.split(
    /(EVD-\d+|TENDER-[A-Za-z0-9._-]+|COMPANY-[A-Za-z0-9._-]+)/,
  );
  return parts.map((p, i) => {
    if (p === "") return null;
    return EVIDENCE_KEY_TOKEN.test(p) ? (
      <EvidenceBadge
        key={i}
        id={p}
        className="my-0.5 inline-flex max-w-full align-middle break-all sm:mx-0.5"
      />
    ) : (
      <span key={i} className="break-words [overflow-wrap:anywhere]">
        {p}
      </span>
    );
  });
}

function FindingRow({ finding }: { finding: AgentMotionFinding }) {
  return (
    <div className="space-y-1.5 rounded-md border border-border bg-secondary/30 px-3 py-2.5">
      <p className="text-sm leading-relaxed break-words text-foreground [overflow-wrap:anywhere]">
        {highlightEvidence(finding.claim)}
      </p>
      {finding.evidenceKeys.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {finding.evidenceKeys.map((k) => (
            <EvidenceBadge key={k} id={k} />
          ))}
        </div>
      )}
    </div>
  );
}

export function AgentMotionCard({
  motion,
  highlightDisagreement = false,
}: {
  motion: AgentMotion;
  highlightDisagreement?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const meta = agentMeta[motion.agent];
  const Icon = meta?.icon ?? ShieldCheck;

  return (
    <>
      <Card className="flex min-w-0 flex-col overflow-hidden">
        <CardHeader className="space-y-3 pb-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <Icon className={cn("h-4 w-4 shrink-0", meta?.tint)} />
              <CardTitle className="truncate text-sm font-semibold">{motion.agent}</CardTitle>
            </div>
            <VerdictBadge verdict={motion.verdict} compact />
          </div>
          <ConfidenceBar value={motion.confidence} />
        </CardHeader>
        <CardContent className="min-w-0 flex-1 space-y-3 pt-0">
          <ul className="space-y-3 text-sm text-foreground">
            {motion.findings.map((f, i) => (
              <li key={i} className="flex gap-2.5">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground" />
                <div className="min-w-0 flex-1 leading-relaxed [overflow-wrap:anywhere]">
                  {highlightEvidence(f)}
                </div>
              </li>
            ))}
          </ul>

          {highlightDisagreement && motion.challenges && motion.challenges.length > 0 && (
            <div className="rounded-md border border-warning/30 bg-warning/5 p-2.5">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-warning">
                Challenges
              </p>
              <ul className="space-y-1 text-xs text-foreground">
                {motion.challenges.map((c, i) => (
                  <li key={i}>• {highlightEvidence(c)}</li>
                ))}
              </ul>
            </div>
          )}

          {highlightDisagreement && motion.rebuttalFocus && (
            <div className="flex flex-wrap gap-1">
              {motion.rebuttalFocus.map((f) => (
                <span
                  key={f}
                  className="inline-flex items-center rounded-sm border border-border bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground"
                >
                  {f}
                </span>
              ))}
            </div>
          )}

          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-primary hover:text-primary"
            onClick={() => setOpen(true)}
          >
            View full motion →
          </Button>
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Icon className={cn("h-4 w-4 shrink-0", meta?.tint)} />
              {motion.agent}
              <VerdictBadge verdict={motion.verdict} compact />
            </DialogTitle>
          </DialogHeader>

          <div className="mt-1 mb-4">
            <ConfidenceBar value={motion.confidence} />
          </div>

          {/* Findings with evidence */}
          {(motion.findingsWithEvidence ?? []).length > 0 ? (
            <section className="space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                {highlightDisagreement ? "Rebuttals" : "Findings"}
              </p>
              <div className="space-y-2">
                {(motion.findingsWithEvidence ?? []).map((f, i) => (
                  <FindingRow key={i} finding={f} />
                ))}
              </div>
            </section>
          ) : motion.findings.length > 0 ? (
            <section className="space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Findings
              </p>
              <ul className="space-y-1.5 text-sm text-foreground">
                {motion.findings.map((f, i) => (
                  <li key={i} className="flex gap-2.5">
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground" />
                    <div className="min-w-0 flex-1 leading-relaxed [overflow-wrap:anywhere]">
                      {highlightEvidence(f)}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {/* Round 2: challenged claims with evidence */}
          {highlightDisagreement && (motion.challengesWithEvidence ?? []).length > 0 && (
            <section className="mt-4 space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-warning">
                Challenged claims
              </p>
              <div className="space-y-2">
                {(motion.challengesWithEvidence ?? []).map((c, i) => (
                  <FindingRow key={i} finding={c} />
                ))}
              </div>
            </section>
          )}

          {/* Revised stance rationale */}
          {motion.revisedStanceRationale && (
            <section className="mt-4 rounded-md border border-primary/20 bg-primary/5 px-3 py-2.5">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-primary">
                Revised stance rationale
              </p>
              <p className="text-sm leading-relaxed text-foreground">
                {motion.revisedStanceRationale}
              </p>
            </section>
          )}

          {/* Rebuttal focus */}
          {highlightDisagreement && motion.rebuttalFocus && motion.rebuttalFocus.length > 0 && (
            <section className="mt-4 space-y-1.5">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Targeting
              </p>
              <div className="flex flex-wrap gap-1">
                {motion.rebuttalFocus.map((f) => (
                  <span
                    key={f}
                    className="inline-flex items-center rounded-sm border border-border bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground"
                  >
                    {f}
                  </span>
                ))}
              </div>
            </section>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
