import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { EvidenceBadge } from "@/components/EvidenceBadge";
import { buildBidDraftPath, decisionToEstimateInput } from "@/lib/bidIntegrationMapping";
import { Zap, Target } from "lucide-react";
import { estimateBid, formatSEK } from "@/lib/bidEstimator";
import { fetchCompany } from "@/lib/api";
import type { DecisionSummary } from "@/data/mock";

interface Props {
  decision: DecisionSummary;
  /** Optional title shown above the card (used on the Compare page grid). */
  heading?: string;
  className?: string;
}

export function BidRecommendation({ decision, heading, className }: Props) {
  const navigate = useNavigate();
  const { data: companyData } = useQuery({
    queryKey: ["company"],
    queryFn: fetchCompany,
  });
  if (!companyData) return null;
  const e = estimateBid(
    decisionToEstimateInput(decision, decision.tenderId),
    companyData.company,
  );
  const bidPath = buildBidDraftPath(decision);

  const handleUseAsDraft = () => {
    if (bidPath) navigate(bidPath);
    else navigate(`/decisions/${decision.runId}`);
  };

  return (
    <Card className={className}>
      <CardContent className="space-y-4 p-5">
        {heading && (
          <h4 className="truncate text-sm font-semibold text-foreground" title={heading}>
            {heading}
          </h4>
        )}

        {/* Suggested bid */}
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <Zap className="h-3.5 w-3.5 text-primary" />
            Suggested bid
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-2xl font-semibold tabular-nums text-foreground">
              {formatSEK(e.recommendedRate)}
            </span>
            <span className="text-sm text-muted-foreground">SEK/h</span>
          </div>
          <p className="font-mono text-xs tabular-nums text-muted-foreground">
            range {formatSEK(e.recommendedRange[0])} – {formatSEK(e.recommendedRange[1])} SEK/h
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            Based on target margin {e.inputs.targetMarginPct}%, win probability{" "}
            {e.inputs.winProbabilityPct}%, strategic fit {e.inputs.strategicFit}, evaluation
            weights (price {e.inputs.evaluationWeights.price} / quality{" "}
            {e.inputs.evaluationWeights.quality}).
          </p>
        </div>

        <Separator />

        {/* Competitor band */}
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <Target className="h-3.5 w-3.5 text-warning" />
            Competitor price band
            <span className="ml-1 font-normal normal-case tracking-normal text-muted-foreground/70">
              (estimated)
            </span>
          </div>
          <p className="font-mono text-sm tabular-nums text-foreground">
            {formatSEK(e.competitorBand[0])} – {formatSEK(e.competitorBand[1])} SEK/h
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            Likely {e.numLikelyBidders[0]}–{e.numLikelyBidders[1]} bidders · anchored to ceiling{" "}
            {formatSEK(e.ceiling)} SEK/h
            {e.ceilingEvidenceId && (
              <>
                {" "}
                <EvidenceBadge id={e.ceilingEvidenceId} />
              </>
            )}
          </p>
        </div>

        <Button variant="outline" size="sm" className="w-full" onClick={handleUseAsDraft}>
          {decision.existingBidId
            ? "Open bid"
            : decision.isDraftable
              ? "Use as draft bid"
              : "Open reasoning"}
        </Button>
      </CardContent>
    </Card>
  );
}
