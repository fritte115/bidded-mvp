import type {
  Bid,
  BidStatus,
  DecisionSummary,
  Verdict,
} from "@/data/mock";

export interface RawDecisionRow {
  agent_run_id?: string;
  created_at?: string;
  verdict?: string;
  confidence?: number | string | null;
  final_decision?: Record<string, unknown> | null;
  agent_runs?: RawAgentRun | RawAgentRun[] | null;
}

export interface RawAgentRun {
  id?: string;
  tender_id?: string;
  status?: string;
  started_at?: string | null;
  completed_at?: string | null;
  archived_at?: string | null;
  archived_reason?: string | null;
  tenders?: RawTender | RawTender[] | null;
  bid_decisions?: RawDecisionRow[] | RawDecisionRow | null;
}

export interface RawTender {
  title?: string;
  created_at?: string;
  documents?: unknown[] | null;
}

export interface RawExistingBidRow {
  id?: string;
  agent_run_id?: string | null;
  status?: string;
  updated_at?: string;
}

export interface RawBidRow {
  id?: string;
  tender_id?: string;
  rate_sek?: number | string | null;
  margin_pct?: number | string | null;
  hours_estimated?: number | string | null;
  status?: string;
  notes?: string | null;
  updated_at?: string;
  metadata?: Record<string, unknown> | null;
  agent_run_id?: string | null;
  tenders?: RawTender | RawTender[] | null;
  agent_runs?: RawAgentRun | RawAgentRun[] | null;
}

export interface BidPipelineSummary {
  active: number;
  submitted: number;
  winRate: number;
  pipelineSEK: number;
  pipelineMSEK: string;
}

function firstObject<T>(value: T | T[] | null | undefined): T | null {
  if (Array.isArray(value)) return value[0] ?? null;
  return value ?? null;
}

function numberValue(value: number | string | null | undefined, fallback = 0): number {
  if (value == null) return fallback;
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function normalizeVerdict(value: string | undefined): Verdict | null {
  const normalized = value?.toUpperCase();
  if (normalized === "BID" || normalized === "NO_BID" || normalized === "CONDITIONAL_BID") {
    return normalized;
  }
  return null;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
}

function countArray(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

function riskScore(riskCount: number, blockerCount: number): "Low" | "Medium" | "High" {
  if (blockerCount > 0 || riskCount >= 3) return "High";
  if (riskCount >= 1) return "Medium";
  return "Low";
}

function topReason(citedMemo: string): string {
  const first = citedMemo.split(/\.\s/)[0]?.trim();
  const reason = first || citedMemo || "No rationale recorded.";
  return reason.replace(/\.$/, "");
}

export function mapDecisionRow(
  row: RawDecisionRow,
  existingBidByRunId = new Map<string, RawExistingBidRow>(),
): DecisionSummary | null {
  const run = firstObject(row.agent_runs);
  if (!run) return null;
  if (run.archived_at) return null;
  const tender = firstObject(run.tenders);
  const verdict = normalizeVerdict(row.verdict);
  if (!verdict) return null;

  const runId = row.agent_run_id ?? run.id;
  const tenderId = run.tender_id;
  if (!runId || !tenderId) return null;

  const fd = row.final_decision ?? {};
  const riskCount = countArray(fd.risk_register);
  const complianceBlockerCount = countArray(fd.compliance_blockers);
  const potentialBlockerCount = countArray(fd.potential_blockers);
  const citedMemo = typeof fd.cited_memo === "string" ? fd.cited_memo : "";
  const existingBid = existingBidByRunId.get(runId);

  return {
    runId,
    tenderId,
    tenderName: tender?.title ?? "Unknown procurement",
    uploadedAt: tender?.created_at ?? "",
    documentCount: Array.isArray(tender?.documents) ? tender.documents.length : 0,
    verdict,
    confidence: Math.round(numberValue(row.confidence) * 100),
    citedMemo,
    topReason: topReason(citedMemo),
    startedAt: run.started_at ?? "",
    completedAt: run.completed_at ?? null,
    riskScore: riskScore(riskCount, complianceBlockerCount),
    riskCount,
    complianceBlockerCount,
    potentialBlockerCount,
    recommendedActions: stringArray(fd.recommended_actions),
    missingInfo: stringArray(fd.missing_info),
    isDraftable: verdict === "BID" || verdict === "CONDITIONAL_BID",
    existingBidId: existingBid?.id,
    existingBidStatus: existingBid?.status as BidStatus | undefined,
    decisionCreatedAt: row.created_at,
  };
}

function latestTime(decision: DecisionSummary): number {
  const raw = decision.decisionCreatedAt ?? decision.completedAt ?? decision.startedAt;
  return raw ? new Date(raw).getTime() : 0;
}

export function mapCompareRows(
  decisionRows: RawDecisionRow[],
  existingBidRows: RawExistingBidRow[] = [],
): DecisionSummary[] {
  const existingBidByRunId = new Map<string, RawExistingBidRow>();
  for (const bid of existingBidRows) {
    if (bid.agent_run_id && !existingBidByRunId.has(bid.agent_run_id)) {
      existingBidByRunId.set(bid.agent_run_id, bid);
    }
  }

  const latestByTender = new Map<string, DecisionSummary>();
  for (const row of decisionRows) {
    const decision = mapDecisionRow(row, existingBidByRunId);
    if (!decision) continue;
    const current = latestByTender.get(decision.tenderId);
    if (!current || latestTime(decision) > latestTime(current)) {
      latestByTender.set(decision.tenderId, decision);
    }
  }

  return Array.from(latestByTender.values()).sort(
    (a, b) => latestTime(b) - latestTime(a),
  );
}

export function buildBidDraftPath(
  decision: Pick<DecisionSummary, "tenderId" | "runId" | "isDraftable" | "existingBidId">,
): string | null {
  if (decision.existingBidId) return `/bids/${decision.existingBidId}/edit`;
  if (!decision.isDraftable) return null;
  return `/bids/new?procurement=${decision.tenderId}&run=${decision.runId}`;
}

function mapLinkedDecision(
  run: RawAgentRun | null,
  tender: RawTender | null,
): DecisionSummary | undefined {
  if (!run) return undefined;
  if (run.archived_at) return undefined;
  const rawDecision = firstObject(run.bid_decisions);
  if (!rawDecision) return undefined;
  return mapDecisionRow({
    ...rawDecision,
    agent_run_id: run.id,
    agent_runs: {
      ...run,
      tenders: tender,
    },
  }) ?? undefined;
}

export function mapBidRow(row: RawBidRow): Bid {
  const tender = firstObject(row.tenders);
  const run = firstObject(row.agent_runs);
  const metadata = row.metadata && typeof row.metadata === "object" ? row.metadata : {};
  const tenderId = row.tender_id ?? run?.tender_id ?? "";

  return {
    id: row.id ?? "",
    procurementId: tenderId,
    procurementName: tender?.title ?? "Unknown procurement",
    rateSEK: numberValue(row.rate_sek),
    marginPct: numberValue(row.margin_pct),
    hoursEstimated: numberValue(row.hours_estimated, 1600),
    status: (row.status as BidStatus) ?? "draft",
    notes: row.notes ?? "",
    updatedAt: row.updated_at ?? "",
    tenderUploadedAt: tender?.created_at,
    decision: mapLinkedDecision(run, tender),
    metadata,
    runId: row.agent_run_id ?? undefined,
  };
}

export function summarizeBidPipeline(bids: Bid[]): BidPipelineSummary {
  const active = bids.filter((b) => b.status === "draft" || b.status === "review").length;
  const submitted = bids.filter((b) => b.status === "submitted").length;
  const won = bids.filter((b) => b.status === "won").length;
  const lost = bids.filter((b) => b.status === "lost").length;
  const decided = won + lost;
  const winRate = decided === 0 ? 0 : Math.round((won / decided) * 100);
  const pipelineSEK = bids
    .filter((b) => b.status !== "lost")
    .reduce((sum, b) => sum + b.rateSEK * b.hoursEstimated, 0);

  return {
    active,
    submitted,
    winRate,
    pipelineSEK,
    pipelineMSEK: (pipelineSEK / 1_000_000).toFixed(1),
  };
}

export function decisionToEstimateInput(decision: DecisionSummary | null | undefined, id: string) {
  const strategicFit =
    decision?.verdict === "BID"
      ? "High"
      : decision?.verdict === "NO_BID"
        ? "Low"
        : "Medium";

  return {
    id,
    estimatedValueMSEK: 0,
    winProbability: decision ? decision.confidence / 100 : 0.5,
    strategicFit,
  };
}

export function buildSourceDecisionMetadata(
  decision: DecisionSummary | null | undefined,
): Record<string, unknown> {
  if (!decision || !decision.isDraftable) return {};
  return {
    sourceDecision: {
      runId: decision.runId,
      tenderId: decision.tenderId,
      verdict: decision.verdict,
      confidence: decision.confidence,
      decisionCreatedAt: decision.decisionCreatedAt ?? null,
    },
  };
}
