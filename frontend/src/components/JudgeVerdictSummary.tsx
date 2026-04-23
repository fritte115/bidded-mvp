import { ConfidenceBar } from "@/components/ConfidenceBar";
import { VerdictBadge } from "@/components/VerdictBadge";
import { formatJudgeMemo } from "@/lib/judgeMemo";
import { cn } from "@/lib/utils";
import { verdictLabel, type Verdict } from "@/data/mock";

type VoteSummary = {
  BID: number;
  NO_BID: number;
  CONDITIONAL_BID: number;
};

export function JudgeMemo({
  memo,
  verdict,
  className,
}: {
  memo: string;
  verdict: Verdict;
  className?: string;
}) {
  const { title, blocks } = formatJudgeMemo(memo, verdict);

  return (
    <div className={cn("space-y-3", className)}>
      <h3 className="text-base font-semibold leading-snug text-foreground">
        <EmphasizedVerdictText text={title} />
      </h3>
      {blocks.length > 0 && (
        <div className="space-y-3 text-sm leading-relaxed text-foreground">
          {blocks.map((block, index) =>
            block.type === "list" ? (
              <ol key={index} className="list-decimal space-y-1.5 pl-5">
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>
                    <EmphasizedVerdictText text={item} />
                  </li>
                ))}
              </ol>
            ) : (
              <p key={index}>
                <EmphasizedVerdictText text={block.text} />
              </p>
            ),
          )}
        </div>
      )}
    </div>
  );
}

export function JudgeVerdictSummary({
  verdict,
  confidence,
  citedMemo,
  voteSummary,
  className,
}: {
  verdict: Verdict;
  confidence: number;
  citedMemo: string;
  voteSummary?: VoteSummary;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "rounded-md border border-border bg-secondary/35 p-4",
        className,
      )}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Final verdict
          </p>
          <VerdictBadge verdict={verdict} size="lg" />
        </div>
        <div className="w-full max-w-xs space-y-3 sm:text-right">
          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Confidence
            </p>
            <p className="font-mono text-2xl font-semibold tabular-nums">
              {confidence}%
            </p>
            <ConfidenceBar
              value={confidence}
              showLabel={false}
              className="mt-2"
            />
          </div>
          {voteSummary && <VoteSummaryChips voteSummary={voteSummary} />}
        </div>
      </div>

      <JudgeMemo
        memo={citedMemo}
        verdict={verdict}
        className="mt-4 border-t border-border pt-4"
      />
    </section>
  );
}

function VoteSummaryChips({ voteSummary }: { voteSummary: VoteSummary }) {
  return (
    <div className="flex flex-wrap gap-1.5 sm:justify-end">
      <VoteChip label={verdictLabel.BID} count={voteSummary.BID} tone="success" />
      <VoteChip label={verdictLabel.NO_BID} count={voteSummary.NO_BID} tone="danger" />
      <VoteChip
        label={verdictLabel.CONDITIONAL_BID}
        count={voteSummary.CONDITIONAL_BID}
        tone="warning"
      />
    </div>
  );
}

function VoteChip({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: "success" | "danger" | "warning";
}) {
  const toneClass =
    tone === "success"
      ? "border-success/30 bg-success/10 text-success"
      : tone === "danger"
        ? "border-danger/30 bg-danger/10 text-danger"
        : "border-warning/30 bg-warning/10 text-warning";

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold",
        toneClass,
      )}
    >
      <span className="font-mono tabular-nums">{count}</span>
      <span>{label}</span>
    </div>
  );
}

function EmphasizedVerdictText({ text }: { text: string }) {
  return text.split(/(\bnot bid\b)/i).map((part, index) =>
    part.toLowerCase() === "not bid" ? (
      <em key={index} className="font-medium">
        {part.toLowerCase()}
      </em>
    ) : (
      <span key={index}>{part}</span>
    ),
  );
}
