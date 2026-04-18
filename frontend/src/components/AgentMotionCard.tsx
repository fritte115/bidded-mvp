import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { VerdictBadge } from "@/components/VerdictBadge";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { EvidenceBadge } from "@/components/EvidenceBadge";
import { cn } from "@/lib/utils";
import type { AgentMotion } from "@/data/mock";
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

function highlightEvidence(text: string) {
  const parts = text.split(/(EVD-\d+)/g);
  return parts.map((p, i) =>
    /^EVD-\d+$/.test(p) ? <EvidenceBadge key={i} id={p} className="mx-0.5" /> : <span key={i}>{p}</span>,
  );
}

export function AgentMotionCard({
  motion,
  highlightDisagreement = false,
}: {
  motion: AgentMotion;
  highlightDisagreement?: boolean;
}) {
  const meta = agentMeta[motion.agent];
  const Icon = meta?.icon ?? ShieldCheck;
  return (
    <Card className="flex flex-col">
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
      <CardContent className="flex-1 space-y-3 pt-0">
        <ul className="space-y-1.5 text-sm text-foreground">
          {motion.findings.map((f, i) => (
            <li key={i} className="flex gap-2">
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" />
              <span className="leading-snug">{highlightEvidence(f)}</span>
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

        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-primary hover:text-primary">
          View full motion →
        </Button>
      </CardContent>
    </Card>
  );
}
