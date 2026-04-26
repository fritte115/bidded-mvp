import { Fragment } from "react";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { EvidenceBadge } from "@/components/EvidenceBadge";
import { VerdictBadge } from "@/components/VerdictBadge";
import { formatJudgeMemo } from "@/lib/judgeMemo";
import { renderFormattedText } from "@/lib/richText";
import { cn } from "@/lib/utils";
import { verdictLabel, type Verdict } from "@/data/mock";

type VoteSummary = {
  BID: number;
  NO_BID: number;
  CONDITIONAL_BID: number;
};

type CitationClickHandler = (id: string) => void;

const EVIDENCE_KEY_TOKEN =
  /^(EVD-\d+|TENDER-[A-Za-z0-9._-]+|COMPANY-[A-Za-z0-9._-]+)$/;

function renderMemoText(text: string, onCitationClick?: CitationClickHandler) {
  const parts = text.split(
    /(EVD-\d+|TENDER-[A-Za-z0-9._-]+|COMPANY-[A-Za-z0-9._-]+)/,
  );

  return parts.map((part, index) => {
    if (part === "") return null;
    if (EVIDENCE_KEY_TOKEN.test(part)) {
      return (
        <EvidenceBadge
          key={index}
          id={part}
          onClick={onCitationClick ? () => onCitationClick(part) : undefined}
          className="my-0.5 inline-flex max-w-full align-middle break-all sm:mx-0.5"
        />
      );
    }
    return <Fragment key={index}>{renderFormattedText(part)}</Fragment>;
  });
}

export function JudgeMemo({
  memo,
  verdict,
  className,
  onCitationClick,
}: {
  memo: string;
  verdict: Verdict;
  className?: string;
  onCitationClick?: CitationClickHandler;
}) {
  const { title, blocks } = formatJudgeMemo(memo, verdict);

  return (
    <div className={cn("space-y-3", className)}>
      <h3 className="text-base font-semibold leading-snug text-foreground">
        {renderMemoText(title, onCitationClick)}
      </h3>
      {blocks.length > 0 && (
        <div className="space-y-3 text-sm leading-relaxed text-foreground">
          {blocks.map((block, index) =>
            block.type === "list" ? (
              <ol key={index} className="list-decimal space-y-1.5 pl-5">
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>{renderMemoText(item, onCitationClick)}</li>
                ))}
              </ol>
            ) : (
              <p key={index}>{renderMemoText(block.text, onCitationClick)}</p>
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
  onCitationClick,
}: {
  verdict: Verdict;
  confidence: number;
  citedMemo: string;
  voteSummary?: VoteSummary;
  className?: string;
  onCitationClick?: CitationClickHandler;
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
        onCitationClick={onCitationClick}
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
