// Deterministic bid estimator.
// Structured so a future edge function can swap in real numbers without
// changing the UI: same input shape, same output shape.

import type { Company } from "@/data/mock";

export interface BidEstimateInput {
  id: string;
  estimatedValueMSEK: number;
  winProbability: number;
  strategicFit: "Low" | "Medium" | "High";
}

export interface BidEstimate {
  /** Recommended hourly rate in SEK (rounded to nearest 5 SEK). */
  recommendedRate: number;
  /** ±8% band around the recommended rate. */
  recommendedRange: [number, number];
  /** Estimated competitor price band in SEK/h. */
  competitorBand: [number, number];
  /** Likely number of competing bidders. */
  numLikelyBidders: [number, number];
  /** Tender ceiling in SEK/h that informs the band. */
  ceiling: number;
  /** Source evidence id for the ceiling, if any. */
  ceilingEvidenceId?: string;
  /** Inputs used for the rate calc — surfaced in the UI. */
  inputs: {
    targetMarginPct: number;
    winProbabilityPct: number;
    strategicFit: BidEstimateInput["strategicFit"];
    evaluationWeights: { price: number; quality: number };
  };
}

const DEFAULT_CEILING = 1450;
const BASE_TARGET_COST = 1100; // SEK/h fully loaded — internal cost baseline

const FIT_MULTIPLIER: Record<BidEstimateInput["strategicFit"], number> = {
  Low: 1.05,
  Medium: 1.0,
  High: 0.97,
};

/** Stable hash → 0..1 for deterministic per-procurement jitter. */
function hash01(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 1000) / 1000;
}

function parseTargetMargin(raw: string): number {
  const m = /([\d.]+)/.exec(raw);
  return m ? Number(m[1]) / 100 : 0.12;
}

function roundTo(n: number, step = 5): number {
  return Math.round(n / step) * step;
}

export function estimateBid(p: BidEstimateInput, company: Company): BidEstimate {
  const targetMargin = parseTargetMargin(company.financialAssumptions.targetMargin);
  const fitMultiplier = FIT_MULTIPLIER[p.strategicFit];

  // Win probability adjustment: aggressive when low chance, can lift when comfortable.
  const winAdj =
    p.winProbability < 0.4 ? 0.95 : p.winProbability > 0.6 ? 1.03 : 1.0;

  const ceiling = DEFAULT_CEILING; // Could be enriched from evidence in future.
  const ceilingEvidenceId = "EVD-008";

  const raw = BASE_TARGET_COST * (1 + targetMargin) * fitMultiplier * winAdj;
  const recommendedRate = Math.min(roundTo(raw), ceiling);

  const recommendedRange: [number, number] = [
    roundTo(recommendedRate * 0.92),
    roundTo(recommendedRate * 1.08),
  ];

  // Deterministic jitter ±4% on each side of the competitor band.
  const jitter = (hash01(p.id) - 0.5) * 0.08;
  const competitorBand: [number, number] = [
    roundTo(ceiling * (0.78 + jitter)),
    roundTo(ceiling * (0.96 + jitter)),
  ];

  // Bigger contracts attract more bidders — capped 2..6.
  const lower = Math.max(2, Math.min(5, Math.round(p.estimatedValueMSEK / 15)));
  const upper = Math.min(6, lower + 2);
  const numLikelyBidders: [number, number] = [lower, upper];

  return {
    recommendedRate,
    recommendedRange,
    competitorBand,
    numLikelyBidders,
    ceiling,
    ceilingEvidenceId,
    inputs: {
      targetMarginPct: Math.round(targetMargin * 100),
      winProbabilityPct: Math.round(p.winProbability * 100),
      strategicFit: p.strategicFit,
      evaluationWeights: { price: 40, quality: 60 },
    },
  };
}

/** Format an integer with thin spaces (Swedish style). */
export function formatSEK(n: number): string {
  return Math.round(n)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, "\u2009");
}
