/**
 * Data access layer — Supabase reads/writes for the US-001–US-012 surface
 * (core domain, storage registration, seeded company). See `.cursor/plans/frontend-backend-scope.md`.
 *
 * Do not query worker-owned outcomes (`bid_decisions`) for “real” metrics until the PRD judge
 * story lands; do not insert into `agent_runs` from the UI (pending runs are a later PRD story).
 *
 * Rules:
 *  - Only tables from Ralph migrations; anon key.
 *  - Map DB columns → mock.ts field names where components still share those types.
 */

import {
  company as mockCompany,
  bidDrafts as mockBidDrafts,
  bids as mockBids,
  procurements as mockProcurements,
  runs as mockRuns,
  type AgentMotion,
  type AgentName,
  type Bid,
  type BidResponseDraft,
  type BidStatus,
  type Company,
  type CompanyWebsiteImportRecord,
  type ComplianceMatrixRow,
  type DecisionSummary,
  type Evidence,
  type EvidenceCategory,
  type JudgeOutput,
  type Procurement,
  type RiskRow,
  type Run,
  type RunStatus,
  type Verdict,
} from "@/data/mock";
import { isSupabaseConfigured, supabase } from "@/lib/supabase";
import {
  AGENT_ROLE_LABELS,
  mapRound1Output,
  mapRound2Output,
} from "@/lib/agentOutputMapping";
import {
  buildSourceDecisionMetadata,
  mapBidRow,
  mapCompareRows,
  mapDecisionRow,
} from "@/lib/bidIntegrationMapping";
import { mapBidDraftPayload, type RawBidResponseDraft } from "@/lib/bidDraftMapping";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MOCK_MODE_WRITE_MESSAGE =
  "Frontend is running in mock mode because the public Supabase env vars are missing. Copy frontend/.env.example to frontend/.env to enable live writes.";
const generatedMockBidDrafts = new Map<string, BidResponseDraft>();

/** "SE" → "Sweden", fallback to the raw value */
const COUNTRY_NAMES: Record<string, string> = {
  SE: "Sweden",
  DK: "Denmark",
  NO: "Norway",
  FI: "Finland",
};

function countryName(code: string): string {
  return COUNTRY_NAMES[code] ?? code;
}

/** "2023-2025" → 2023 */
function parseStartYear(deliveryYears: string): number {
  const match = deliveryYears.match(/\d{4}/);
  return match ? parseInt(match[0], 10) : new Date().getFullYear();
}

/** 2_650_000_000 → "2,650 MSEK" */
function formatMSEK(sek: number): string {
  return `${(sek / 1_000_000).toLocaleString("sv-SE")} MSEK`;
}

function isMockMode(): boolean {
  return !isSupabaseConfigured || supabase === null;
}

function requireSupabase() {
  if (!supabase) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }
  return supabase;
}

export const STALE_RUN_AFTER_MINUTES = 30;
export const STALE_RUN_STAGE = "Stale - worker stopped";
export const ARCHIVED_RUN_STAGE = "Archived";

const MOCK_ARCHIVED_AGENT_RUN_IDS_KEY = "bidded:mock-archived-agent-run-ids";

interface RunLifecycleInput {
  status: RunStatus;
  startedAt: string | null | undefined;
  createdAt: string | null | undefined;
  completedAt: string | null | undefined;
  archivedAt?: string | null | undefined;
  metadata: unknown;
}

export interface RunLifecycleDisplay {
  isActive: boolean;
  isStale: boolean;
  isArchived: boolean;
  staleAgeMinutes: number | null;
  stage: string;
}

function timestampMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

function workerUpdatedAt(metadata: unknown): string | null {
  if (!metadata || typeof metadata !== "object") return null;
  const worker = (metadata as Record<string, unknown>).worker;
  if (!worker || typeof worker !== "object") return null;
  const updatedAt = (worker as Record<string, unknown>).updated_at;
  return typeof updatedAt === "string" && updatedAt.length > 0 ? updatedAt : null;
}

function staleReferenceMs(input: RunLifecycleInput): number | null {
  return (
    timestampMs(workerUpdatedAt(input.metadata)) ??
    timestampMs(input.startedAt) ??
    timestampMs(input.createdAt)
  );
}

export function runLifecycleForDisplay(
  input: RunLifecycleInput,
  options: { nowMs?: number; staleAfterMinutes?: number } = {},
): RunLifecycleDisplay {
  const status = input.status;
  const isInFlight = status === "running" || status === "pending";
  const fallbackStage = dashboardStageLabel(status, input.metadata);
  if (input.archivedAt) {
    return {
      isActive: false,
      isStale: false,
      isArchived: true,
      staleAgeMinutes: null,
      stage: ARCHIVED_RUN_STAGE,
    };
  }
  if (!isInFlight || input.completedAt) {
    return {
      isActive: false,
      isStale: false,
      isArchived: false,
      staleAgeMinutes: null,
      stage: fallbackStage,
    };
  }

  const referenceMs = staleReferenceMs(input);
  if (referenceMs === null) {
    return {
      isActive: true,
      isStale: false,
      isArchived: false,
      staleAgeMinutes: null,
      stage: fallbackStage,
    };
  }

  const nowMs = options.nowMs ?? Date.now();
  const staleAfterMinutes = options.staleAfterMinutes ?? STALE_RUN_AFTER_MINUTES;
  const ageMinutes = Math.max(0, Math.floor((nowMs - referenceMs) / 60_000));
  const isStale = ageMinutes > staleAfterMinutes;
  return {
    isActive: !isStale,
    isStale,
    isArchived: false,
    staleAgeMinutes: isStale ? ageMinutes : null,
    stage: isStale ? STALE_RUN_STAGE : fallbackStage,
  };
}

function readMockArchivedRunIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(MOCK_ARCHIVED_AGENT_RUN_IDS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set(
      Array.isArray(parsed)
        ? parsed.filter((value): value is string => typeof value === "string")
        : [],
    );
  } catch {
    return new Set();
  }
}

function archiveMockAgentRun(runId: string): void {
  if (typeof window === "undefined") return;
  const archived = readMockArchivedRunIds();
  archived.add(runId);
  window.localStorage.setItem(
    MOCK_ARCHIVED_AGENT_RUN_IDS_KEY,
    JSON.stringify(Array.from(archived).sort()),
  );
}

function visibleMockRuns(): Run[] {
  const archived = readMockArchivedRunIds();
  return mockRuns.filter((run) => !archived.has(run.id));
}

function mockLifecycle(run: Run): RunLifecycleDisplay {
  return runLifecycleForDisplay({
    status: run.status,
    startedAt: run.startedAt,
    createdAt: run.startedAt,
    completedAt: run.completedAt ?? null,
    archivedAt: null,
    metadata: {},
  });
}

async function requireAccessToken(): Promise<string> {
  const client = requireSupabase();
  const { data, error } = await client.auth.getSession();
  if (error) throw new Error(`getSession: ${error.message}`);
  const token = data.session?.access_token;
  if (!token) {
    throw new Error("You must be signed in to call the Bidded agent API.");
  }
  return token;
}

function mockParseStatus(procurement: Procurement): ProcurementDocumentRow["parseStatus"] {
  if (procurement.status === "done") return "parsed";
  if (procurement.status === "processing") return "parsing";
  return "pending";
}

function mockDashboardStats(): DashboardStats {
  const runs = visibleMockRuns();
  return {
    totalProcurements: mockProcurements.length,
    totalPdfDocuments: mockProcurements.reduce(
      (sum, procurement) => sum + procurement.documents.length,
      0,
    ),
    activeRuns: runs.filter((run) => mockLifecycle(run).isActive).length,
  };
}

function mockActiveRuns(): ActiveRun[] {
  return visibleMockRuns()
    .filter((run) => run.status === "running" || run.status === "pending")
    .map((run) => {
      const lifecycle = mockLifecycle(run);
      return {
        id: run.id,
        tenderName: run.tenderName,
        status: run.status,
        stage: lifecycle.stage,
        startedAt: run.startedAt,
        completedAt: run.completedAt ?? null,
        durationSec: run.durationSec ?? null,
        isStale: lifecycle.isStale,
        isArchived: lifecycle.isArchived,
        staleAgeMinutes: lifecycle.staleAgeMinutes,
      };
    })
    .sort(
      (left, right) =>
        new Date(right.startedAt).getTime() - new Date(left.startedAt).getTime(),
    );
}

function mockProcurementLatestRun(
  procurementId: string,
): ProcurementLatestRun | null {
  const latestRun = visibleMockRuns()
    .filter((run) => run.tenderId === procurementId)
    .sort(
      (left, right) =>
        new Date(right.startedAt).getTime() - new Date(left.startedAt).getTime(),
    )[0];
  if (!latestRun) return null;
  const lifecycle = mockLifecycle(latestRun);

  return {
    id: latestRun.id,
    status: latestRun.status,
    startedAt: latestRun.startedAt,
    stage: lifecycle.stage,
    decision:
      latestRun.status === "needs_human_review"
        ? null
        : (latestRun.decision ?? null),
    needsJudgeReview: latestRun.status === "needs_human_review",
    isStale: lifecycle.isStale,
    isArchived: lifecycle.isArchived,
    staleAgeMinutes: lifecycle.staleAgeMinutes,
  };
}

function mockProcurementRows(): ProcurementRow[] {
  return mockProcurements.map((procurement) => ({
    id: procurement.id,
    name: procurement.name,
    uploadedAt: procurement.uploadedAt,
    documentFilenames: procurement.documents,
    documents:
      procurement.documentRefs?.map((doc) => ({
        originalFilename: doc.filename,
        parseStatus: doc.parseStatus,
        parseNote: null,
      })) ??
      procurement.documents.map((filename) => ({
        originalFilename: filename,
        parseStatus: mockParseStatus(procurement),
        parseNote: null,
      })),
    documentCount: procurement.documents.length,
    latestRun: mockProcurementLatestRun(procurement.id),
  }));
}

function riskScoreFromJudge(
  judge: JudgeOutput | null | undefined,
  fallback: Procurement["riskScore"],
): DecisionSummary["riskScore"] {
  if (!judge) return fallback;
  if (judge.riskRegister.some((risk) => risk.severity === "High")) return "High";
  if (judge.riskRegister.some((risk) => risk.severity === "Medium")) return "Medium";
  return fallback;
}

function mockDecisionSummary(run: Run): DecisionSummary | null {
  if (!run.decision) return null;
  const procurement = mockProcurements.find((row) => row.id === run.tenderId);
  if (!procurement) return null;

  const existingBid = mockBids.find(
    (bid) => bid.runId === run.id || bid.procurementId === run.tenderId,
  );
  const judge = run.judge ?? null;

  return {
    runId: run.id,
    tenderId: procurement.id,
    tenderName: procurement.name,
    uploadedAt: procurement.uploadedAt,
    documentCount: procurement.documents.length,
    verdict: run.decision,
    confidence: run.confidence ?? 0,
    citedMemo: judge?.citedMemo ?? procurement.topReason,
    topReason:
      procurement.topReason ||
      judge?.recommendedActions[0] ||
      judge?.citedMemo ||
      "Mock decision summary",
    startedAt: run.startedAt,
    completedAt: run.completedAt ?? null,
    riskScore: riskScoreFromJudge(judge, procurement.riskScore),
    riskCount: judge?.riskRegister.length ?? 0,
    complianceBlockerCount: judge?.complianceBlockers.length ?? 0,
    potentialBlockerCount: judge?.potentialBlockers.length ?? 0,
    recommendedActions: judge?.recommendedActions ?? [],
    missingInfo: judge?.missingInfo ?? [],
    isDraftable: run.decision !== "NO_BID",
    existingBidId: existingBid?.id,
    existingBidStatus: existingBid?.status,
    decisionCreatedAt: run.completedAt ?? run.startedAt,
  };
}

function mockDecisionRows(): DecisionRow[] {
  return visibleMockRuns()
    .map((run) => {
      const summary = mockDecisionSummary(run);
      if (!summary) return null;
      return {
        ...summary,
        id: run.id,
        status: run.status,
      };
    })
    .filter((row): row is DecisionRow => row !== null)
    .sort((left, right) => {
      const leftTime = new Date(left.completedAt ?? left.startedAt).getTime();
      const rightTime = new Date(right.completedAt ?? right.startedAt).getTime();
      return rightTime - leftTime;
    });
}

function mockRunDetail(runId: string): RunDetail | null {
  const run = visibleMockRuns().find((row) => row.id === runId);
  if (!run) return null;
  const lifecycle = mockLifecycle(run);

  return {
    id: run.id,
    tenderName: run.tenderName,
    tenderId: run.tenderId,
    company: run.company,
    status: run.status,
    stage: lifecycle.stage,
    isStale: lifecycle.isStale,
    isArchived: lifecycle.isArchived,
    staleAgeMinutes: lifecycle.staleAgeMinutes,
    startedAt: run.startedAt,
    completedAt: run.completedAt ?? null,
    durationSec: run.durationSec ?? null,
    decision: run.decision ?? null,
    confidence: run.confidence ?? null,
    evidence: run.evidence,
    round1: run.round1,
    round2: run.round2,
    judge: run.judge ?? null,
  };
}

function mockBidRows(): Bid[] {
  const runs = visibleMockRuns();
  return mockBids
    .map((bid) => {
      const procurement = mockProcurements.find(
        (row) => row.id === bid.procurementId,
      );
      const run = bid.runId
        ? runs.find((candidate) => candidate.id === bid.runId)
        : runs.find((candidate) => candidate.tenderId === bid.procurementId);
      const decision = run ? mockDecisionSummary(run) : null;

      return {
        ...bid,
        decision: decision ?? undefined,
        tenderUploadedAt: procurement?.uploadedAt,
      };
    })
    .sort(
      (left, right) =>
        new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime(),
    );
}

function mockDbCompany(): DbCompany {
  return {
    name: mockCompany.name,
    organization_number: mockCompany.orgNumber === "—" ? null : mockCompany.orgNumber,
    headquarters_country: "SE",
    employee_count: mockCompany.headcount ?? null,
    annual_revenue_sek: null,
    capabilities: {
      service_lines: { user_edits: mockCompany.capabilities },
    },
    certifications: mockCompany.certifications.map((cert) => ({
      name: cert.name,
      scope: cert.issuer,
      status: cert.validUntil === "Active" ? "active" : cert.validUntil,
      source_label: "mock_data",
    })),
    reference_projects: mockCompany.references.map((ref, index) => ({
      reference_id: `mock-ref-${index + 1}`,
      customer_type: ref.client,
      case_study_summary: ref.scope,
      contract_value_band_sek: ref.value.replace(/\s?SEK$/i, "").trim(),
      delivery_years: String(ref.year),
      source_label: "mock_data",
    })),
    financial_assumptions: {},
    profile_details: {
      company_size: mockCompany.size,
      legal_name: mockCompany.legalName,
      vat_number: mockCompany.vatNumber,
      founded: mockCompany.founded,
      headcount: mockCompany.headcount,
      offices: mockCompany.offices,
      website: mockCompany.website,
      email: mockCompany.email,
      phone: mockCompany.phone,
      description: mockCompany.description,
      leadership: mockCompany.leadership,
      industries: mockCompany.industries,
      insurance: mockCompany.insurance,
    },
  };
}

// ---------------------------------------------------------------------------
// Company
// ---------------------------------------------------------------------------

/** Raw shape returned by Supabase for the companies table.
 *
 * Exported so callers (see `updateCompany`) can hand back the last-fetched row
 * as the merge baseline — protects rich JSONB fields (rate cards, CV summaries,
 * delivery_capacity, etc.) that the UI doesn't expose for editing but the
 * swarm relies on when materializing `company_profile` evidence items. */
export interface DbCompany {
  name: string;
  organization_number: string | null;
  headquarters_country: string;
  employee_count: number | null;
  annual_revenue_sek: number | null;
  capabilities: {
    service_lines?: Record<string, string[]>;
    delivery_capacity?: Record<string, unknown>;
    geographic_availability?: Record<string, unknown>;
  };
  certifications: Array<{
    name: string;
    scope?: string;
    status?: string;
    source_label?: string;
    [key: string]: unknown;
  }>;
  reference_projects: Array<{
    reference_id?: string;
    sector?: string;
    customer_type?: string;
    case_study_summary?: string;
    contract_value_band_sek?: string;
    delivery_years?: string;
    capabilities_used?: unknown;
    source_label?: string;
    [key: string]: unknown;
  }>;
  financial_assumptions: {
    revenue_band_sek?: { min: number; max: number };
    target_gross_margin_percent?: number;
    minimum_acceptable_margin_percent?: number;
    [key: string]: unknown;
  };
  profile_details: {
    company_size?: string;
    legal_name?: string;
    vat_number?: string;
    founded?: number;
    headcount?: number;
    offices?: string[];
    website?: string;
    email?: string;
    phone?: string;
    description?: string;
    leadership?: Array<{ name: string; title: string; email?: string }>;
    industries?: string[];
    financials?: Array<{
      year: number;
      revenue_msek: number;
      ebit_margin_pct: number;
      headcount: number;
    }>;
    team_composition?: Array<{ role: string; count: number; avg_years: number }>;
    insurance?: Array<{ type: string; insurer: string; coverage: string }>;
    framework_agreements?: Array<{
      name: string;
      authority: string;
      valid_until: string;
      status: "Active" | "Expiring" | "Expired";
    }>;
    security_posture?: Array<{
      item: string;
      status: "Implemented" | "Partial" | "Planned";
      note?: string;
    }>;
    sustainability?: {
      co2_reduction_pct: number;
      renewable_energy_pct: number;
      diversity_pct: number;
      code_of_conduct_signed: boolean;
    };
    bid_stats?: {
      total_bids: number;
      won: number;
      lost: number;
      in_progress: number;
      win_rate_pct: number;
      avg_contract_msek: number;
    };
    website_imports?: CompanyWebsiteImportRecord[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

/** Return shape for `fetchCompany` — mapped UI shape plus the raw DB row so
 * callers (the save path) can merge-update without losing JSONB fields. */
export interface CompanyWithRaw {
  company: Company;
  raw: DbCompany;
}

function mapDbCompany(row: DbCompany): Company {
  // Flatten service_lines into a single capabilities array.
  // Prefer user-edited list when present (see `mergeCompanyIntoDb`).
  const serviceLines = row.capabilities?.service_lines ?? {};
  const userEdits = (serviceLines as Record<string, unknown>).user_edits;
  const capabilities = Array.isArray(userEdits)
    ? (userEdits as string[])
    : (Object.values(serviceLines).flat() as string[]);

  // Certifications: scope is the closest thing to an issuer description
  const certifications = (row.certifications ?? []).map((c) => ({
    name: c.name,
    issuer: c.scope ?? "—",
    validUntil: c.status === "active" ? "Active" : (c.status ?? "—"),
  }));

  // References: customer_type as client, case_study_summary as scope
  const references = (row.reference_projects ?? []).map((r) => ({
    client: r.customer_type ?? "—",
    scope: r.case_study_summary ?? "—",
    value: r.contract_value_band_sek
      ? `${r.contract_value_band_sek} SEK`
      : "—",
    year: parseStartYear(r.delivery_years ?? ""),
    sector: typeof r.sector === "string" ? (r.sector as string) : undefined,
    duration: typeof r.duration === "string" ? (r.duration as string) : undefined,
    outcome: typeof r.outcome === "string" ? (r.outcome as string) : undefined,
  }));

  // Financial assumptions
  const fa = row.financial_assumptions ?? {};
  const revBand = fa.revenue_band_sek;
  const revenueRange = revBand
    ? `${formatMSEK(revBand.min)} – ${formatMSEK(revBand.max)} / year`
    : row.annual_revenue_sek
    ? `${formatMSEK(row.annual_revenue_sek)} / year`
    : "—";
  const targetMargin = fa.target_gross_margin_percent != null
    ? `${fa.target_gross_margin_percent}%`
    : "—";
  const maxContractSize = fa.minimum_acceptable_margin_percent != null
    ? `Min. margin ${fa.minimum_acceptable_margin_percent}%`
    : "—";

  // Extended fields — all live under profile_details JSONB (no schema change).
  const pd = row.profile_details ?? {};
  const financials = (pd.financials ?? []).map((f) => ({
    year: f.year,
    revenueMSEK: f.revenue_msek,
    ebitMarginPct: f.ebit_margin_pct,
    headcount: f.headcount,
  }));
  const teamComposition = (pd.team_composition ?? []).map((t) => ({
    role: t.role,
    count: t.count,
    avgYears: t.avg_years,
  }));
  const frameworkAgreements = (pd.framework_agreements ?? []).map((f) => ({
    name: f.name,
    authority: f.authority,
    validUntil: f.valid_until,
    status: f.status,
  }));
  const securityPosture = (pd.security_posture ?? []).map((s) => ({
    item: s.item,
    status: s.status,
    note: s.note,
  }));
  const sustainability = pd.sustainability
    ? {
        co2ReductionPct: pd.sustainability.co2_reduction_pct,
        renewableEnergyPct: pd.sustainability.renewable_energy_pct,
        diversityPct: pd.sustainability.diversity_pct,
        codeOfConductSigned: pd.sustainability.code_of_conduct_signed,
      }
    : undefined;
  const bidStats = pd.bid_stats
    ? {
        totalBids: pd.bid_stats.total_bids,
        won: pd.bid_stats.won,
        lost: pd.bid_stats.lost,
        inProgress: pd.bid_stats.in_progress,
        winRatePct: pd.bid_stats.win_rate_pct,
        avgContractMSEK: pd.bid_stats.avg_contract_msek,
      }
    : undefined;

  return {
    name: row.name,
    legalName: pd.legal_name,
    orgNumber: row.organization_number ?? "—",
    vatNumber: pd.vat_number,
    founded: pd.founded,
    size: row.employee_count != null
      ? `${row.employee_count.toLocaleString("sv-SE")} employees`
      : (pd.company_size ?? "—"),
    headcount: pd.headcount ?? row.employee_count ?? undefined,
    hq: countryName(row.headquarters_country),
    offices: pd.offices,
    website: pd.website,
    email: pd.email,
    phone: pd.phone,
    description: pd.description,
    leadership: pd.leadership,
    industries: pd.industries,
    capabilities,
    certifications,
    references,
    financialAssumptions: { revenueRange, targetMargin, maxContractSize },
    financials: financials.length > 0 ? financials : undefined,
    teamComposition: teamComposition.length > 0 ? teamComposition : undefined,
    insurance: pd.insurance,
    frameworkAgreements:
      frameworkAgreements.length > 0 ? frameworkAgreements : undefined,
    securityPosture:
      securityPosture.length > 0 ? securityPosture : undefined,
    sustainability,
    bidStats,
    websiteImports: pd.website_imports,
  };
}

export type CompanyWebsiteProfilePatch = Partial<
  Pick<
    Company,
    | "website"
    | "email"
    | "phone"
    | "description"
    | "offices"
    | "industries"
    | "capabilities"
    | "certifications"
    | "references"
    | "securityPosture"
    | "sustainability"
  >
>;

export interface CompanyWebsiteImportPreview {
  source_url: string;
  pages: Array<{ url: string; title?: string | null; text_excerpt?: string }>;
  profile_patch: CompanyWebsiteProfilePatch;
  field_sources: Record<
    string,
    { page_url: string; excerpt: string; source_label: string }
  >;
  warnings: string[];
}

export function applyCompanyWebsiteImportPreview(
  company: Company,
  preview: CompanyWebsiteImportPreview,
  importedAt = new Date().toISOString(),
): Company {
  const patch = preview.profile_patch;
  const next: Company = {
    ...company,
    website: patch.website ?? company.website,
    email: patch.email ?? company.email,
    phone: patch.phone ?? company.phone,
    description: patch.description ?? company.description,
    offices: patch.offices ?? company.offices,
    industries: patch.industries ?? company.industries,
    sustainability: patch.sustainability ?? company.sustainability,
    websiteImports: [
      { ...preview, imported_at: importedAt },
      ...(company.websiteImports ?? []),
    ].slice(0, 5),
  };

  if (patch.capabilities) {
    next.capabilities = mergeUnique(company.capabilities, patch.capabilities);
  }
  if (patch.certifications) {
    next.certifications = mergeByKey(
      company.certifications,
      patch.certifications,
      (cert) => cert.name,
    );
  }
  if (patch.references) {
    next.references = mergeByKey(
      company.references,
      patch.references,
      (reference) => `${reference.client}-${reference.year}`,
    );
  }
  if (patch.securityPosture) {
    next.securityPosture = mergeByKey(
      company.securityPosture ?? [],
      patch.securityPosture,
      (item) => item.item,
    );
  }

  return next;
}

function mergeUnique(existing: string[], imported: string[]): string[] {
  return Array.from(new Set([...existing, ...imported].filter(Boolean)));
}

function mergeByKey<T>(
  existing: T[],
  imported: T[],
  keyFn: (item: T) => string,
): T[] {
  const byKey = new Map(existing.map((item) => [keyFn(item), item]));
  for (const item of imported) {
    const key = keyFn(item);
    if (!byKey.has(key)) byKey.set(key, item);
  }
  return Array.from(byKey.values());
}

/**
 * Merge a user-edited Company onto the last-fetched raw DB row.
 *
 * The UI now edits a superset of the canonical schema: top-level columns
 * (name, orgNumber, HQ, employees) plus ~15 fields under `profile_details`
 * JSONB (leadership, offices, financials, sustainability, bid_stats, etc.).
 * We deep-clone `prev` and overlay only the fields the UI exposes — every
 * other JSONB key (rate cards, CV summaries, delivery_capacity,
 * geographic_availability, metadata.*) is preserved untouched.
 *
 * Merge rules:
 *   - Top-level scalars: overwrite from UI values.
 *   - capabilities.service_lines: store the UI's flat list under a reserved
 *     `user_edits` key; leave seeded category-keyed arrays intact.
 *   - certifications / reference_projects: merge by identity (name / client).
 *     Matched rows are updated in place, new rows tagged `source_label:
 *     'user_edit'`, rows missing from the UI draft are dropped.
 *   - financial_assumptions: only patch `target_gross_margin_percent`;
 *     everything else (revenue band, rate cards, margin floors) passes through.
 *   - profile_details: overwrite only keys the editor exposes. Reserved keys
 *     like `company_size` (seeded) and `metadata.*` are never written here.
 */
export function mergeCompanyIntoDb(
  c: Company,
  prev: DbCompany,
): Record<string, unknown> {
  const base = structuredClone(prev) as DbCompany;

  // Reverse country name → code ("Sweden" → "SE")
  const COUNTRY_CODES = Object.fromEntries(
    Object.entries(COUNTRY_NAMES).map(([k, v]) => [v, k]),
  );

  // Parse "1 850 employees" → 1850 (sv-SE locale uses non-breaking space)
  const empMatch = c.size.replace(/\s/g, "").match(/\d+/);
  const employeeCount =
    empMatch && !Number.isNaN(parseInt(empMatch[0], 10))
      ? parseInt(empMatch[0], 10)
      : base.employee_count;

  // ── capabilities: preserve seeded category buckets; keep user edits isolated
  const baseServiceLines = base.capabilities?.service_lines ?? {};
  const nextCapabilities = {
    ...base.capabilities,
    service_lines: {
      ...baseServiceLines,
      user_edits: c.capabilities,
    },
  };

  // ── certifications: merge by name
  const prevCerts = base.certifications ?? [];
  const mergedCerts = c.certifications.map((cert) => {
    const existing = prevCerts.find((p) => p.name === cert.name);
    if (existing) {
      return {
        ...existing,
        name: cert.name,
        scope: cert.issuer !== "—" ? cert.issuer : (existing.scope ?? ""),
        status: cert.validUntil === "Active" ? "active" : (existing.status ?? "active"),
      };
    }
    return {
      name: cert.name,
      scope: cert.issuer !== "—" ? cert.issuer : "",
      status: "active",
      source_label: "user_edit",
    };
  });

  // ── references: merge by customer_type; carry UI-surface fields through
  const prevRefs = base.reference_projects ?? [];
  const mergedRefs = c.references.map((ref, i) => {
    const existing = prevRefs.find((p) => p.customer_type === ref.client);
    const valueBand = ref.value.replace(/\s?SEK$/i, "").trim();
    const uiExtras: Record<string, unknown> = {};
    if (ref.sector !== undefined) uiExtras.sector = ref.sector;
    if (ref.duration !== undefined) uiExtras.duration = ref.duration;
    if (ref.outcome !== undefined) uiExtras.outcome = ref.outcome;

    if (existing) {
      return {
        ...existing,
        ...uiExtras,
        customer_type: ref.client,
        case_study_summary: ref.scope,
        contract_value_band_sek: valueBand || existing.contract_value_band_sek,
        delivery_years: String(ref.year),
      };
    }
    return {
      reference_id: `ref-user-${i + 1}`,
      sector: ref.sector ?? "public_sector",
      customer_type: ref.client,
      delivery_years: String(ref.year),
      contract_value_band_sek: valueBand,
      case_study_summary: ref.scope,
      capabilities_used: [],
      source_label: "user_edit",
      ...(ref.duration !== undefined ? { duration: ref.duration } : {}),
      ...(ref.outcome !== undefined ? { outcome: ref.outcome } : {}),
    };
  });

  // ── financial assumptions: only patch target margin; preserve everything else
  const prevFa = base.financial_assumptions ?? {};
  const marginMatch = c.financialAssumptions.targetMargin.match(/\d+/);
  const nextFa = {
    ...prevFa,
    target_gross_margin_percent:
      marginMatch != null
        ? parseInt(marginMatch[0], 10)
        : prevFa.target_gross_margin_percent,
  };

  // ── profile_details: start from prev, then overlay each UI-edited key.
  //    Keys not present in the UI are preserved. `undefined` UI values DO NOT
  //    clear DB keys — use an explicit empty array / empty string to clear.
  const pd = { ...(base.profile_details ?? {}) } as Record<string, unknown>;
  const setIfDefined = (key: string, value: unknown) => {
    if (value !== undefined) pd[key] = value;
  };
  setIfDefined("legal_name", c.legalName);
  setIfDefined("vat_number", c.vatNumber);
  setIfDefined("founded", c.founded);
  setIfDefined("headcount", c.headcount);
  setIfDefined("offices", c.offices);
  setIfDefined("website", c.website);
  setIfDefined("email", c.email);
  setIfDefined("phone", c.phone);
  setIfDefined("description", c.description);
  setIfDefined("leadership", c.leadership);
  setIfDefined("industries", c.industries);
  // Convert camelCase UI shapes → snake_case JSONB at the boundary.
  if (c.financials !== undefined) {
    pd.financials = c.financials.map((f) => ({
      year: f.year,
      revenue_msek: f.revenueMSEK,
      ebit_margin_pct: f.ebitMarginPct,
      headcount: f.headcount,
    }));
  }
  if (c.teamComposition !== undefined) {
    pd.team_composition = c.teamComposition.map((t) => ({
      role: t.role,
      count: t.count,
      avg_years: t.avgYears,
    }));
  }
  setIfDefined("insurance", c.insurance);
  if (c.frameworkAgreements !== undefined) {
    pd.framework_agreements = c.frameworkAgreements.map((f) => ({
      name: f.name,
      authority: f.authority,
      valid_until: f.validUntil,
      status: f.status,
    }));
  }
  if (c.securityPosture !== undefined) {
    pd.security_posture = c.securityPosture.map((s) => ({
      item: s.item,
      status: s.status,
      ...(s.note !== undefined ? { note: s.note } : {}),
    }));
  }
  if (c.sustainability !== undefined) {
    pd.sustainability = {
      co2_reduction_pct: c.sustainability.co2ReductionPct,
      renewable_energy_pct: c.sustainability.renewableEnergyPct,
      diversity_pct: c.sustainability.diversityPct,
      code_of_conduct_signed: c.sustainability.codeOfConductSigned,
    };
  }
  if (c.bidStats !== undefined) {
    pd.bid_stats = {
      total_bids: c.bidStats.totalBids,
      won: c.bidStats.won,
      lost: c.bidStats.lost,
      in_progress: c.bidStats.inProgress,
      win_rate_pct: c.bidStats.winRatePct,
      avg_contract_msek: c.bidStats.avgContractMSEK,
    };
  }
  if (c.websiteImports !== undefined) {
    pd.website_imports = c.websiteImports;
  }

  return {
    name: c.name,
    organization_number: c.orgNumber !== "—" ? c.orgNumber : null,
    headquarters_country: COUNTRY_CODES[c.hq] ?? c.hq,
    employee_count: employeeCount,
    capabilities: nextCapabilities,
    certifications: mergedCerts,
    reference_projects: mergedRefs,
    financial_assumptions: nextFa,
    profile_details: pd,
    // metadata and annual_revenue_sek pass through `base` untouched — not in payload.
  };
}

/** Fetch the single demo company from Supabase. Returns both the mapped UI
 * shape and the raw DB row — pass `raw` back to `updateCompany` to keep saves
 * merge-based instead of destructive. */
export async function fetchCompany(): Promise<CompanyWithRaw> {
  if (isMockMode()) {
    return { company: mockCompany, raw: mockDbCompany() };
  }

  const client = requireSupabase();
  const { data, error } = await client
    .from("companies")
    .select("*")
    .eq("tenant_key", "demo")
    .limit(1)
    .single();

  if (error) throw new Error(`fetchCompany: ${error.message}`);
  const raw = data as DbCompany;
  return { company: mapDbCompany(raw), raw };
}

/** Persist edited company data back to Supabase. Callers must pass the raw DB
 * row that was last fetched so we can merge UI edits onto it instead of
 * replacing rich JSONB fields.
 *
 * After the Supabase write succeeds, best-effort triggers the FastAPI
 * `/api/company/resync-evidence` endpoint so the swarm sees the edit on its
 * next run. If the FastAPI server is unreachable the save still succeeds —
 * evidence simply stays stale until the next tender run rebuilds it. */
export async function updateCompany(c: Company, prev: DbCompany): Promise<void> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }

  const companyId = typeof prev.id === "string" ? prev.id : undefined;
  const token = await requireAccessToken();
  const url = new URL(`${AGENT_API_URL}/api/company/profile`);
  if (companyId) url.searchParams.set("company_id", companyId);
  const res = await fetch(url.toString(), {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(mergeCompanyIntoDb(c, prev)),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
}

/** Ask the FastAPI worker to re-materialize `company_profile` evidence rows
 * from the current `companies` row. Returns the number of evidence items
 * upserted; throws on HTTP error. */
export async function resyncCompanyEvidence(): Promise<{
  evidence_count: number;
  rows_returned: number;
}> {
  const token = await requireAccessToken();
  const res = await fetch(`${AGENT_API_URL}/api/company/resync-evidence`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`resyncCompanyEvidence: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function importCompanyWebsite(
  url: string,
  maxPages = 5,
): Promise<CompanyWebsiteImportPreview> {
  const res = await fetch(`${AGENT_API_URL}/api/company/import-website`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, max_pages: maxPages }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      (body as { detail?: string }).detail ??
        `importCompanyWebsite: ${res.status} ${res.statusText}`,
    );
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export interface DashboardStats {
  totalProcurements: number;
  /** Tender PDF rows in `documents` (tender_document role) */
  totalPdfDocuments: number;
  activeRuns: number;
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  if (isMockMode()) {
    return mockDashboardStats();
  }

  const client = requireSupabase();
  const [tendersRes, docsRes, activeRunsRes] = await Promise.all([
    client
      .from("tenders")
      .select("id", { count: "exact", head: true })
      .eq("tenant_key", "demo"),
    client
      .from("documents")
      .select("id", { count: "exact", head: true })
      .eq("tenant_key", "demo")
      .eq("document_role", "tender_document"),
    client
      .from("agent_runs")
      .select("id, status, started_at, created_at, completed_at, archived_at, metadata")
      .eq("tenant_key", "demo")
      .in("status", ["running", "pending"])
      .is("archived_at", null),
  ]);

  const activeRuns = ((activeRunsRes.data ?? []) as Record<string, unknown>[]).filter(
    (row) =>
      runLifecycleForDisplay({
        status: (row.status as RunStatus) ?? "pending",
        startedAt: row.started_at as string | null,
        createdAt: row.created_at as string | null,
        completedAt: row.completed_at as string | null,
        archivedAt: row.archived_at as string | null,
        metadata: row.metadata,
      }).isActive,
  ).length;

  return {
    totalProcurements: tendersRes.count ?? 0,
    totalPdfDocuments: docsRes.count ?? 0,
    activeRuns,
  };
}

// Lightweight run shape for the Dashboard active-analyses table
export interface ActiveRun {
  id: string;
  tenderName: string;
  status: RunStatus;
  isStale: boolean;
  isArchived: boolean;
  staleAgeMinutes: number | null;
  /** Human-readable pipeline stage (resolved from metadata + status). */
  stage: string;
  startedAt: string;
  completedAt: string | null;
  durationSec: number | null;
}

export function stageDisplayName(step: string | null | undefined): string {
  if (!step) return "Pending";
  const m: Record<string, string> = {
    preflight: "Evidence Scout",
    evidence_scout: "Evidence Scout",
    round_1_specialist: "Round 1: Specialist Motions",
    round_1_join: "Round 1: Specialist Motions",
    round_2_rebuttal: "Round 2: Rebuttals",
    round_2_join: "Round 2: Rebuttals",
    judge: "Judge",
    persist_decision: "Judge",
    failed: "Failed",
  };
  return m[step] ?? step;
}

/**
 * Reads `current_step` from worker-persisted metadata (top-level or `worker` mirror).
 */
export function resolveMetadataCurrentStep(metadata: unknown): string | null {
  if (!metadata || typeof metadata !== "object") return null;
  const m = metadata as Record<string, unknown>;
  const top = m.current_step;
  if (typeof top === "string" && top.trim().length > 0) return top.trim();
  const w = m.worker;
  if (w && typeof w === "object") {
    const inner = (w as Record<string, unknown>).current_step;
    if (typeof inner === "string" && inner.trim().length > 0) return inner.trim();
  }
  return null;
}

/**
 * Stage column for dashboard / procurement lists: graph step when present,
 * otherwise Pending / Running / Finished from run status.
 */
export function dashboardStageLabel(status: RunStatus, metadata: unknown): string {
  const step = resolveMetadataCurrentStep(metadata);
  if (step) return stageDisplayName(step);
  if (status === "succeeded" || status === "failed" || status === "needs_human_review") {
    return "Finished";
  }
  if (status === "running") {
    return "Running";
  }
  return "Pending";
}

export async function fetchActiveRuns(): Promise<ActiveRun[]> {
  if (isMockMode()) {
    return mockActiveRuns();
  }

  const client = requireSupabase();
  const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

  const { data, error } = await client
    .from("agent_runs")
    .select("id, status, started_at, created_at, completed_at, archived_at, metadata, tenders(title)")
    .eq("tenant_key", "demo")
    .is("archived_at", null)
    .or(
      `status.in.(running,pending),and(status.in.(succeeded,failed,needs_human_review),completed_at.gte.${yesterday})`,
    )
    .order("created_at", { ascending: false })
    .limit(20);

  if (error) throw new Error(`fetchActiveRuns: ${error.message}`);

  return (data ?? []).map((r: Record<string, unknown>) => {
    const tender = r.tenders as { title: string } | null;
    const startedAt = r.started_at as string | null;
    const createdAt = r.created_at as string | null;
    const completedAt = r.completed_at as string | null;
    const durationSec =
      startedAt && completedAt
        ? Math.round(
            (new Date(completedAt).getTime() - new Date(startedAt).getTime()) / 1000,
          )
        : null;

    const status = (r.status as RunStatus) ?? "pending";
    const lifecycle = runLifecycleForDisplay({
      status,
      startedAt,
      createdAt,
      completedAt,
      archivedAt: r.archived_at as string | null,
      metadata: r.metadata,
    });
    return {
      id: r.id as string,
      tenderName: tender?.title ?? "Unknown procurement",
      status,
      isStale: lifecycle.isStale,
      isArchived: lifecycle.isArchived,
      staleAgeMinutes: lifecycle.staleAgeMinutes,
      stage: lifecycle.stage,
      startedAt: startedAt ?? createdAt ?? "",
      completedAt,
      durationSec,
    };
  });
}

// ---------------------------------------------------------------------------
// Procurements
// ---------------------------------------------------------------------------

// Minimal run info embedded in each procurement row
export interface ProcurementLatestRun {
  id: string;
  status: RunStatus;
  isStale: boolean;
  isArchived: boolean;
  staleAgeMinutes: number | null;
  startedAt: string;
  stage: string;
  decision: Verdict | null;
  /** True when bid_decisions.verdict is needs_human_review */
  needsJudgeReview: boolean;
}

export interface ProcurementDocumentRow {
  originalFilename: string;
  parseStatus: "pending" | "parsing" | "parsed" | "parser_failed";
  /** From `metadata` when workers store an error string; DB has no dedicated column yet */
  parseNote: string | null;
}

export interface ProcurementRow {
  id: string;
  name: string;
  uploadedAt: string;
  documentFilenames: string[];
  documents: ProcurementDocumentRow[];
  documentCount: number;
  latestRun: ProcurementLatestRun | null;
}

function metadataParseNote(metadata: unknown): string | null {
  if (!metadata || typeof metadata !== "object") return null;
  const m = metadata as Record<string, unknown>;
  if (typeof m.parse_error === "string" && m.parse_error.length > 0) return m.parse_error;
  return null;
}

function verdictFromBidDecisionRow(
  raw: string | null | undefined,
): { decision: Verdict | null; needsJudgeReview: boolean } {
  if (!raw) return { decision: null, needsJudgeReview: false };
  if (raw === "needs_human_review") return { decision: null, needsJudgeReview: true };
  if (raw === "bid") return { decision: "BID", needsJudgeReview: false };
  if (raw === "no_bid") return { decision: "NO_BID", needsJudgeReview: false };
  if (raw === "conditional_bid") return { decision: "CONDITIONAL_BID", needsJudgeReview: false };
  return { decision: null, needsJudgeReview: false };
}

export async function fetchProcurements(): Promise<ProcurementRow[]> {
  if (isMockMode()) {
    return mockProcurementRows();
  }

  const client = requireSupabase();
  const { data, error } = await client
    .from("tenders")
    .select(`
      id,
      title,
      created_at,
      documents(original_filename, parse_status, metadata),
      agent_runs(
        id,
        status,
        started_at,
        created_at,
        archived_at,
        archived_reason,
        metadata,
        bid_decisions(verdict)
      )
    `)
    .eq("tenant_key", "demo")
    .order("created_at", { ascending: false });

  if (error) throw new Error(`fetchProcurements: ${error.message}`);

  return (data ?? []).map((t: Record<string, unknown>) => {
    const docs =
      (t.documents as Array<{
        original_filename: string;
        parse_status: ProcurementDocumentRow["parseStatus"];
        metadata: unknown;
      }>) ?? [];
    const runs = (
      t.agent_runs as Array<{
        id: string;
        status: string;
        started_at: string | null;
        created_at: string;
        archived_at: string | null;
        archived_reason: string | null;
        metadata: Record<string, unknown>;
        bid_decisions: { verdict: string }[] | { verdict: string } | null;
      }>
    ) ?? [];

    // Sort runs by created_at desc, pick latest
    const latestRun = runs.filter((run) => !run.archived_at).sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0] ?? null;

    const documentRows: ProcurementDocumentRow[] = docs.map((d) => ({
      originalFilename: d.original_filename,
      parseStatus: d.parse_status,
      parseNote: metadataParseNote(d.metadata),
    }));

    let latestRunPayload: ProcurementLatestRun | null = null;
    if (latestRun) {
      const bd = latestRun.bid_decisions;
      const verdictRow = Array.isArray(bd) ? bd[0] : bd;
      const rawVerdict = verdictRow?.verdict;
      const { decision, needsJudgeReview } = verdictFromBidDecisionRow(rawVerdict);
      const status = latestRun.status as RunStatus;
      const startedAt = latestRun.started_at ?? latestRun.created_at;
      const lifecycle = runLifecycleForDisplay({
        status,
        startedAt: latestRun.started_at,
        createdAt: latestRun.created_at,
        completedAt: null,
        archivedAt: latestRun.archived_at,
        metadata: latestRun.metadata,
      });
      latestRunPayload = {
        id: latestRun.id,
        status,
        isStale: lifecycle.isStale,
        isArchived: lifecycle.isArchived,
        staleAgeMinutes: lifecycle.staleAgeMinutes,
        startedAt,
        stage: lifecycle.stage,
        decision,
        needsJudgeReview,
      };
    }

    return {
      id: t.id as string,
      name: t.title as string,
      uploadedAt: t.created_at as string,
      documentFilenames: docs.map((d) => d.original_filename),
      documents: documentRows,
      documentCount: docs.length,
      latestRun: latestRunPayload,
    };
  });
}

// ---------------------------------------------------------------------------
// Register Procurement
// ---------------------------------------------------------------------------

// Must match SUPABASE_STORAGE_BUCKET in .env
const BUCKET_NAME = "public-procurements";

function slugify(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-");
  return slug || "tender";
}

function safePdfFilename(filename: string): string {
  const stem = filename.replace(/\.pdf$/i, "");
  return `${slugify(stem) || "document"}.pdf`;
}

function buildStoragePath(title: string, checksumHex: string, originalFilename: string): string {
  return `demo/procurements/${slugify(title)}/${checksumHex.slice(0, 12)}-${safePdfFilename(originalFilename)}`;
}

export interface RegisterProcurementInput {
  title: string;
  issuingAuthority: string;
  files: File[];
}

/**
 * Upload PDFs to Supabase Storage and register them as a new tender.
 * Mirrors tender_registration.py — same storage paths, same upsert keys.
 * Returns the tender UUID.
 */
/**
 * Delete a tender and all its documents (cascade on FK).
 * Also removes objects from Storage — DB deletes do not remove bucket files automatically.
 * Requires delete RLS on tenders, documents, and storage.objects for these paths.
 */
export async function deleteProcurement(tenderId: string): Promise<void> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }

  const client = requireSupabase();
  const { data: docRows, error: docListErr } = await client
    .from("documents")
    .select("storage_path")
    .eq("tender_id", tenderId)
    .eq("tenant_key", "demo");
  if (docListErr) throw new Error(`deleteProcurement (list documents): ${docListErr.message}`);

  const paths = (docRows ?? [])
    .map((r) => (r as { storage_path: string }).storage_path)
    .filter((p): p is string => typeof p === "string" && p.length > 0);

  if (paths.length > 0) {
    const { error: storageErr } = await client.storage.from(BUCKET_NAME).remove(paths);
    if (storageErr)
      throw new Error(`deleteProcurement (storage remove): ${storageErr.message}`);
  }

  const { error } = await client
    .from("tenders")
    .delete()
    .eq("id", tenderId)
    .eq("tenant_key", "demo");
  if (error) throw new Error(`deleteProcurement: ${error.message}`);
}

export async function registerProcurement(input: RegisterProcurementInput): Promise<string> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }

  const client = requireSupabase();
  // 1. Fetch demo company ID
  const { data: companyRow, error: companyErr } = await client
    .from("companies")
    .select("id")
    .eq("tenant_key", "demo")
    .limit(1)
    .single();
  if (companyErr) throw new Error(`registerProcurement (company lookup): ${companyErr.message}`);
  const companyId = (companyRow as { id: string }).id;

  // 2. Upsert tender row
  const { data: tenderRows, error: tenderErr } = await client
    .from("tenders")
    .upsert(
      {
        tenant_key: "demo",
        title: input.title,
        issuing_authority: input.issuingAuthority || "Unknown",
        language_policy: { source_document_language: "sv", agent_output_language: "en" },
        metadata: { registered_via: "frontend_ui", demo_company_id: companyId },
      },
      { onConflict: "tenant_key,title,issuing_authority" },
    )
    .select("id");
  if (tenderErr) throw new Error(`registerProcurement (tender upsert): ${tenderErr.message}`);
  const tenderId = (tenderRows as Array<{ id: string }>)[0].id;

  // 3. For each PDF: compute SHA-256 → build path → upload → upsert document row
  for (const file of input.files) {
    const buffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest("SHA-256", buffer);
    const checksum = Array.from(new Uint8Array(hashBuffer))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    const storagePath = buildStoragePath(input.title, checksum, file.name);

    const { error: uploadErr } = await client.storage
      .from(BUCKET_NAME)
      .upload(storagePath, new Blob([buffer], { type: "application/pdf" }), {
        contentType: "application/pdf",
        upsert: true,
      });
    if (uploadErr)
      throw new Error(
        `registerProcurement (storage upload ${file.name}): ${uploadErr.message} [status: ${(uploadErr as { statusCode?: string }).statusCode ?? "?"}]`,
      );

    const { error: docErr } = await client.from("documents").upsert(
      {
        tenant_key: "demo",
        tender_id: tenderId,
        company_id: null,
        storage_path: storagePath,
        checksum_sha256: checksum,
        content_type: "application/pdf",
        document_role: "tender_document",
        parse_status: "pending",
        original_filename: file.name,
        metadata: { registered_via: "frontend_ui", demo_company_id: companyId },
      },
      { onConflict: "storage_path" },
    );
    if (docErr) throw new Error(`registerProcurement (document upsert ${file.name}): ${docErr.message}`);
  }

  return tenderId;
}

// ---------------------------------------------------------------------------
// Agent output mapping helpers
// ---------------------------------------------------------------------------

const EVIDENCE_CAT_MAP: Record<string, EvidenceCategory> = {
  deadline: "Deadlines",
  shall_requirement: "Mandatory Requirements",
  qualification_criterion: "Qualification Criteria",
  evaluation_criterion: "Evaluation Criteria",
  contract_risk: "Contract Risks",
  required_submission_document: "Required Submission Documents",
};

function normalizeVerdictStr(v: string): Verdict {
  return v.toUpperCase() as Verdict;
}

function normalizeComplianceStatus(s: string): ComplianceMatrixRow["status"] {
  if (s === "met") return "Met";
  if (s === "unmet") return "Not Met";
  return "Unknown";
}

function normalizeSeverity(s: string): RiskRow["severity"] {
  const c = s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
  return c as RiskRow["severity"];
}

function extractEvidenceKeys(obj: unknown): string[] {
  if (!obj || typeof obj !== "object") return [];
  if (Array.isArray(obj)) return obj.flatMap(extractEvidenceKeys);
  const o = obj as Record<string, unknown>;
  if (typeof o.evidence_key === "string") return [o.evidence_key];
  return Object.values(o).flatMap(extractEvidenceKeys);
}

function buildReferencedByMap(
  outputs: Array<{ agent_role: string; validated_payload: unknown }>,
): Map<string, AgentName[]> {
  const map = new Map<string, AgentName[]>();
  for (const out of outputs) {
    const label = AGENT_ROLE_LABELS[out.agent_role];
    if (!label) continue;
    for (const key of extractEvidenceKeys(out.validated_payload)) {
      const arr = map.get(key) ?? [];
      if (!arr.includes(label)) arr.push(label);
      map.set(key, arr);
    }
  }
  return map;
}

function mapFinalDecision(
  fd: Record<string, unknown>,
  evidenceIdToKey: Map<string, string>,
): JudgeOutput {
  const vs = (fd.vote_summary as Record<string, number>) ?? {};
  return {
    verdict: normalizeVerdictStr(fd.verdict as string),
    confidence: Math.round(((fd.confidence as number) ?? 0) * 100),
    voteSummary: {
      BID: vs.bid ?? 0,
      NO_BID: vs.no_bid ?? 0,
      CONDITIONAL_BID: vs.conditional_bid ?? 0,
    },
    disagreement: (fd.disagreement_summary as string) ?? "",
    citedMemo: (fd.cited_memo as string) ?? "",
    complianceMatrix: ((fd.compliance_matrix as unknown[]) ?? []).map((r) => {
      const row = r as Record<string, unknown>;
      return {
        requirement: row.requirement as string,
        status: normalizeComplianceStatus(row.status as string),
        evidence: ((row.evidence_refs as unknown[]) ?? []).map(
          (e) => (e as Record<string, unknown>).evidence_key as string,
        ),
      };
    }),
    complianceBlockers: ((fd.compliance_blockers as unknown[]) ?? []).map(
      (b) => (b as Record<string, unknown>).claim as string,
    ),
    potentialBlockers: ((fd.potential_blockers as unknown[]) ?? []).map(
      (b) => (b as Record<string, unknown>).claim as string,
    ),
    riskRegister: ((fd.risk_register as unknown[]) ?? []).map((r) => {
      const row = r as Record<string, unknown>;
      return {
        risk: row.risk as string,
        severity: normalizeSeverity(row.severity as string),
        mitigation: row.mitigation as string,
      };
    }),
    missingInfo: (fd.missing_info as string[]) ?? [],
    recommendedActions: (fd.recommended_actions as string[]) ?? [],
    evidenceIds: ((fd.evidence_ids as string[]) ?? []).map(
      (id) => evidenceIdToKey.get(id) ?? id,
    ),
  };
}

function mapEvidenceRow(
  row: Record<string, unknown>,
  referencedBy: AgentName[],
): Evidence {
  const sm = (row.source_metadata as Record<string, string>) ?? {};
  const sourceLabel = evidenceSourceLabel(sm);
  return {
    id: row.evidence_key as string,
    key: row.evidence_key as string,
    category:
      (EVIDENCE_CAT_MAP[row.category as string] as EvidenceCategory) ??
      (row.category as EvidenceCategory),
    excerpt: row.excerpt as string,
    source: sourceLabel,
    page: (row.page_start as number) ?? 0,
    referencedBy,
    kind: (row.source_type as "tender_document" | "company_profile") ??
      "tender_document",
    companyFieldPath: (row.field_path as string) ?? undefined,
  };
}

const KB_DOCUMENT_TYPE_LABELS: Record<string, string> = {
  certification: "Certification",
  case_study: "Case study",
  cv_profile: "CV/profile",
  capability_statement: "Capability statement",
  policy_process: "Policy/process",
  financial_pricing: "Financial/pricing",
  legal_insurance: "Legal/insurance",
};

function evidenceSourceLabel(sourceMetadata: Record<string, string>): string {
  if (sourceMetadata.kb_document_type) {
    const filename =
      sourceMetadata.original_filename || sourceMetadata.source_label || "Company KB";
    const documentType =
      KB_DOCUMENT_TYPE_LABELS[sourceMetadata.kb_document_type] ??
      sourceMetadata.kb_document_type;
    return `${filename} · ${documentType}`;
  }
  return sourceMetadata.source_label ?? "Unknown";
}

// ---------------------------------------------------------------------------
// Decisions
// ---------------------------------------------------------------------------

export interface DecisionRow extends DecisionSummary {
  id: string;
  status: RunStatus;
}

const DECISION_SUMMARY_SELECT = `
  agent_run_id,
  created_at,
  verdict,
  confidence,
  final_decision,
  agent_runs!inner(
    id,
    tender_id,
    status,
    started_at,
    completed_at,
    archived_at,
    archived_reason,
    tenders!inner(title, created_at, documents(id))
  )
`;

export async function fetchDecisions(): Promise<DecisionRow[]> {
  if (isMockMode()) {
    return mockDecisionRows();
  }

  const client = requireSupabase();
  const { data, error } = await client
    .from("bid_decisions")
    .select(DECISION_SUMMARY_SELECT)
    .eq("tenant_key", "demo")
    .order("created_at", { ascending: false });

  if (error) throw new Error(`fetchDecisions: ${error.message}`);

  return ((data ?? []) as Record<string, unknown>[])
    .map((row) => {
      const decision = mapDecisionRow(row);
      if (!decision) return null;
      const run = Array.isArray(row.agent_runs)
        ? row.agent_runs[0]
        : (row.agent_runs as Record<string, unknown> | null);
      return {
        ...decision,
        id: decision.runId,
        status: (run?.status as RunStatus) ?? "succeeded",
      };
    })
    .filter((row): row is DecisionRow => row !== null);
}

// ---------------------------------------------------------------------------
// Run detail (used by RunDetail and DecisionDetail pages)
// ---------------------------------------------------------------------------

export interface RunDetail {
  id: string;
  tenderName: string;
  tenderId: string;
  company: string;
  status: RunStatus;
  isStale: boolean;
  isArchived: boolean;
  staleAgeMinutes: number | null;
  stage: string;
  startedAt: string;
  completedAt: string | null;
  durationSec: number | null;
  decision: Verdict | null;
  confidence: number | null; // 0–100
  evidence: Evidence[];
  round1: AgentMotion[];
  round2: AgentMotion[];
  judge: JudgeOutput | null;
}

export async function fetchRunDetail(runId: string): Promise<RunDetail | null> {
  if (isMockMode()) {
    return mockRunDetail(runId);
  }

  const client = requireSupabase();
  const { data: runRow, error: runErr } = await client
    .from("agent_runs")
    .select(
      `id, status, created_at, started_at, completed_at, archived_at, archived_reason, metadata, tender_id, company_id,
       tenders!inner(title),
       bid_decisions(verdict, confidence, final_decision, metadata)`,
    )
    .eq("id", runId)
    .single();

  if (runErr) {
    if (runErr.code === "PGRST116") return null;
    throw new Error(`fetchRunDetail (run): ${runErr.message}`);
  }

  const run = runRow as Record<string, unknown>;
  const tender = run.tenders as Record<string, unknown>;
  const decisionRows = run.bid_decisions as Record<string, unknown>[] | null;
  const bd = Array.isArray(decisionRows) ? decisionRows[0] : decisionRows;

  const tenderId = run.tender_id as string;
  const companyId = run.company_id as string;
  const createdAt = run.created_at as string | null;
  const startedAt = run.started_at as string | null;
  const completedAt = run.completed_at as string | null;
  const archivedAt = run.archived_at as string | null;

  const [outputsRes, docsRes] = await Promise.all([
    client
      .from("agent_outputs")
      .select("agent_role, round_name, output_type, validated_payload")
      .eq("agent_run_id", runId)
      .order("created_at"),
    client
      .from("documents")
      .select("id")
      .eq("tender_id", tenderId)
      .eq("tenant_key", "demo"),
  ]);

  if (outputsRes.error)
    throw new Error(`fetchRunDetail (outputs): ${outputsRes.error.message}`);

  const outputs = (outputsRes.data ?? []) as Array<{
    agent_role: string;
    round_name: string;
    output_type: string;
    validated_payload: Record<string, unknown>;
  }>;

  const docIds = ((docsRes.data ?? []) as Array<{ id: string }>).map(
    (d) => d.id,
  );

  let evidenceRows: Record<string, unknown>[] = [];
  if (docIds.length > 0 || companyId) {
    const evQuery = client
      .from("evidence_items")
      .select("*")
      .eq("tenant_key", "demo");

    const { data: evData, error: evErr } =
      docIds.length > 0
        ? await evQuery.or(
            `document_id.in.(${docIds.join(",")}),company_id.eq.${companyId}`,
          )
        : await evQuery.eq("company_id", companyId);

    if (evErr) throw new Error(`fetchRunDetail (evidence): ${evErr.message}`);
    evidenceRows = (evData ?? []) as Record<string, unknown>[];
  }

  const snapshotEvidenceRows = decisionEvidenceSnapshotRows(bd);
  const displayEvidenceRows = mergeEvidenceRows(evidenceRows, snapshotEvidenceRows);

  // Build UUID → evidence_key map for judge output evidence_ids, including
  // decision snapshots for hard-deleted company KB source documents.
  const evidenceIdToKey = new Map<string, string>(
    displayEvidenceRows.flatMap((r) =>
      r.id && r.evidence_key ? [[String(r.id), String(r.evidence_key)]] : [],
    ),
  );

  const referencedByMap = buildReferencedByMap(outputs);

  const evidence: Evidence[] = displayEvidenceRows.map((r) =>
    mapEvidenceRow(r, referencedByMap.get(r.evidence_key as string) ?? []),
  );

  // Group agent outputs by round
  const round1Raw = outputs.filter((o) =>
    o.round_name.includes("round_1") || o.round_name.includes("specialist"),
  );
  const round2Raw = outputs.filter((o) =>
    o.round_name.includes("round_2") || o.round_name.includes("rebuttal"),
  );

  const round1MotionMap = new Map<string, AgentMotion>();
  const round1: AgentMotion[] = [];
  for (const o of round1Raw) {
    const m = mapRound1Output(o.validated_payload);
    if (m) { round1.push(m); round1MotionMap.set(o.agent_role, m); }
  }

  const round2: AgentMotion[] = round2Raw
    .map((o) => mapRound2Output(o.validated_payload, round1MotionMap))
    .filter((m): m is AgentMotion => m !== null);

  const fd = bd
    ? ((bd as Record<string, unknown>).final_decision as Record<
        string,
        unknown
      >)
    : null;
  const judge = fd ? mapFinalDecision(fd, evidenceIdToKey) : null;

  const status = run.status as RunStatus;
  const lifecycle = runLifecycleForDisplay({
    status,
    startedAt,
    createdAt,
    completedAt,
    archivedAt,
    metadata: run.metadata,
  });

  return {
    id: runId,
    tenderName: (tender?.title as string) ?? "Unknown",
    tenderId,
    company: "Demo company",
    status,
    isStale: lifecycle.isStale,
    isArchived: lifecycle.isArchived,
    staleAgeMinutes: lifecycle.staleAgeMinutes,
    stage: lifecycle.stage,
    startedAt: startedAt ?? createdAt ?? "",
    completedAt,
    durationSec:
      startedAt && completedAt
        ? Math.round(
            (new Date(completedAt).getTime() -
              new Date(startedAt).getTime()) /
              1000,
          )
        : null,
    decision:
      bd && (bd as Record<string, unknown>).verdict
        ? normalizeVerdictStr(
            (bd as Record<string, unknown>).verdict as string,
          )
        : null,
    confidence:
      bd && (bd as Record<string, unknown>).confidence != null
        ? Math.round(
            ((bd as Record<string, unknown>).confidence as number) * 100,
          )
        : null,
    evidence,
    round1,
    round2,
    judge,
  };
}

function decisionEvidenceSnapshotRows(
  decisionRow: Record<string, unknown> | null | undefined,
): Record<string, unknown>[] {
  const metadata = decisionRow?.metadata;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return [];
  }
  const snapshot = (metadata as Record<string, unknown>).evidence_snapshot;
  if (!Array.isArray(snapshot)) return [];
  return snapshot.filter(
    (row): row is Record<string, unknown> =>
      Boolean(row && typeof row === "object" && !Array.isArray(row)),
  );
}

function mergeEvidenceRows(
  liveRows: Record<string, unknown>[],
  snapshotRows: Record<string, unknown>[],
): Record<string, unknown>[] {
  const seenIds = new Set(liveRows.map((row) => row.id).filter(Boolean).map(String));
  const seenKeys = new Set(
    liveRows.map((row) => row.evidence_key).filter(Boolean).map(String),
  );
  const merged = [...liveRows];
  for (const snapshotRow of snapshotRows) {
    const id = snapshotRow.id == null ? null : String(snapshotRow.id);
    const key =
      snapshotRow.evidence_key == null ? null : String(snapshotRow.evidence_key);
    if ((id && seenIds.has(id)) || (key && seenKeys.has(key))) continue;
    merged.push(snapshotRow);
    if (id) seenIds.add(id);
    if (key) seenKeys.add(key);
  }
  return merged;
}

// ---------------------------------------------------------------------------
// Evidence board (standalone page, lighter than full run detail)
// ---------------------------------------------------------------------------

export async function fetchEvidenceBoard(runId: string): Promise<Evidence[]> {
  if (isMockMode()) {
    return mockRunDetail(runId)?.evidence ?? [];
  }

  const client = requireSupabase();
  const { data: runRow, error: runErr } = await client
    .from("agent_runs")
    .select("tender_id, company_id")
    .eq("id", runId)
    .single();

  if (runErr) return [];

  const run = runRow as Record<string, unknown>;
  const tenderId = run.tender_id as string;
  const companyId = run.company_id as string;

  const [outputsRes, docsRes] = await Promise.all([
    client
      .from("agent_outputs")
      .select("agent_role, validated_payload")
      .eq("agent_run_id", runId),
    client
      .from("documents")
      .select("id")
      .eq("tender_id", tenderId)
      .eq("tenant_key", "demo"),
  ]);

  const outputs = (outputsRes.data ?? []) as Array<{
    agent_role: string;
    validated_payload: unknown;
  }>;
  const docIds = ((docsRes.data ?? []) as Array<{ id: string }>).map(
    (d) => d.id,
  );

  let evidenceRows: Record<string, unknown>[] = [];
  if (docIds.length > 0 || companyId) {
    const evQuery = client
      .from("evidence_items")
      .select("*")
      .eq("tenant_key", "demo");
    const { data } =
      docIds.length > 0
        ? await evQuery.or(
            `document_id.in.(${docIds.join(",")}),company_id.eq.${companyId}`,
          )
        : await evQuery.eq("company_id", companyId);
    evidenceRows = (data ?? []) as Record<string, unknown>[];
  }

  const referencedByMap = buildReferencedByMap(outputs);
  return evidenceRows.map((r) =>
    mapEvidenceRow(r, referencedByMap.get(r.evidence_key as string) ?? []),
  );
}

// ---------------------------------------------------------------------------
// Tenders with decisions (Compare page)
// ---------------------------------------------------------------------------

export type TenderDecisionRow = DecisionSummary;

export async function fetchCompareRows(): Promise<DecisionSummary[]> {
  if (isMockMode()) {
    return mockDecisionRows();
  }

  const client = requireSupabase();
  const [decisionsRes, bidsRes] = await Promise.all([
    client
      .from("bid_decisions")
      .select(DECISION_SUMMARY_SELECT)
      .eq("tenant_key", "demo")
      .order("created_at", { ascending: false }),
    client
      .from("bids")
      .select("id, agent_run_id, status, updated_at")
      .eq("tenant_key", "demo")
      .order("updated_at", { ascending: false }),
  ]);

  if (decisionsRes.error)
    throw new Error(`fetchCompareRows (decisions): ${decisionsRes.error.message}`);
  if (bidsRes.error)
    throw new Error(`fetchCompareRows (bids): ${bidsRes.error.message}`);

  return mapCompareRows(
    (decisionsRes.data ?? []) as Record<string, unknown>[],
    (bidsRes.data ?? []) as Record<string, unknown>[],
  );
}

export async function fetchTendersWithDecisions(): Promise<TenderDecisionRow[]> {
  return fetchCompareRows();
}

const BID_SELECT = `
  id,
  rate_sek,
  margin_pct,
  hours_estimated,
  status,
  notes,
  updated_at,
  metadata,
  agent_run_id,
  tender_id,
  tenders!inner(title, created_at, documents(id)),
  agent_runs(
    id,
    tender_id,
    status,
    started_at,
    completed_at,
    archived_at,
    archived_reason,
    bid_decisions(created_at, verdict, confidence, final_decision)
  )
`;

// ---------------------------------------------------------------------------
// Bids
// ---------------------------------------------------------------------------

export async function fetchBids(): Promise<Bid[]> {
  if (isMockMode()) {
    return mockBidRows();
  }

  const client = requireSupabase();
  const { data, error } = await client
    .from("bids")
    .select(BID_SELECT)
    .eq("tenant_key", "demo")
    .order("updated_at", { ascending: false });

  if (error) throw new Error(`fetchBids: ${error.message}`);
  return ((data ?? []) as Record<string, unknown>[]).map(mapBidRow);
}

export async function fetchBid(id: string): Promise<Bid | null> {
  if (isMockMode()) {
    return mockBidRows().find((bid) => bid.id === id) ?? null;
  }

  const client = requireSupabase();
  const { data, error } = await client
    .from("bids")
    .select(BID_SELECT)
    .eq("id", id)
    .eq("tenant_key", "demo")
    .single();

  if (error) {
    if (error.code === "PGRST116") return null;
    throw new Error(`fetchBid: ${error.message}`);
  }
  return mapBidRow(data as Record<string, unknown>);
}

export interface CreateBidInput {
  tenderId: string;
  rateSEK: number;
  marginPct: number;
  hoursEstimated: number;
  status: BidStatus;
  notes: string;
  runId?: string;
  sourceDecision?: DecisionSummary | null;
  metadata?: Record<string, unknown>;
}

export async function createBid(input: CreateBidInput): Promise<string> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }

  const client = requireSupabase();
  const { data, error } = await client
    .from("bids")
    .insert({
      tenant_key: "demo",
      tender_id: input.tenderId,
      agent_run_id: input.runId ?? null,
      rate_sek: input.rateSEK,
      margin_pct: input.marginPct,
      hours_estimated: input.hoursEstimated,
      status: input.status,
      notes: input.notes,
      metadata: {
        ...(input.metadata ?? {}),
        ...buildSourceDecisionMetadata(input.sourceDecision),
      },
    })
    .select("id")
    .single();

  if (error) throw new Error(`createBid: ${error.message}`);
  return (data as { id: string }).id;
}

export async function updateBid(
  id: string,
  input: CreateBidInput,
): Promise<void> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }

  const client = requireSupabase();
  const { error } = await client
    .from("bids")
    .update({
      tender_id: input.tenderId,
      agent_run_id: input.runId ?? null,
      rate_sek: input.rateSEK,
      margin_pct: input.marginPct,
      hours_estimated: input.hoursEstimated,
      status: input.status,
      notes: input.notes,
      metadata: {
        ...(input.metadata ?? {}),
        ...buildSourceDecisionMetadata(input.sourceDecision),
      },
    })
    .eq("id", id)
    .eq("tenant_key", "demo");

  if (error) throw new Error(`updateBid: ${error.message}`);
}

export async function updateBidStatus(
  id: string,
  status: BidStatus,
): Promise<void> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }

  const client = requireSupabase();
  const { error } = await client
    .from("bids")
    .update({ status, updated_at: new Date().toISOString() })
    .eq("id", id)
    .eq("tenant_key", "demo");

  if (error) throw new Error(`updateBidStatus: ${error.message}`);
}

export async function deleteBid(id: string): Promise<void> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }

  const client = requireSupabase();
  const { error } = await client
    .from("bids")
    .delete()
    .eq("id", id)
    .eq("tenant_key", "demo");

  if (error) throw new Error(`deleteBid: ${error.message}`);
}

// ---------------------------------------------------------------------------
// Agent API — local FastAPI server (bidded serve)
// ---------------------------------------------------------------------------

const AGENT_API_URL =
  (import.meta.env.VITE_AGENT_API_URL as string | undefined) ?? "http://localhost:8000";

export type CompanyKbDocumentType =
  | "certification"
  | "case_study"
  | "cv_profile"
  | "capability_statement"
  | "policy_process"
  | "financial_pricing"
  | "legal_insurance";

export interface CompanyKbUploadItem {
  file: File;
  kbDocumentType: CompanyKbDocumentType;
}

export interface CompanyKbDocument {
  document_id: string;
  company_id: string;
  original_filename: string;
  storage_path: string;
  content_type: string;
  parse_status: "pending" | "parsing" | "parsed" | "parser_failed";
  kb_document_type: CompanyKbDocumentType;
  extraction_status: "pending" | "parsing" | "extracted" | "fallback" | "failed";
  evidence_count: number;
  warnings: string[];
}

export interface CompanyKbEvidenceItem {
  evidence_key: string;
  excerpt: string;
  normalized_meaning?: string;
  category: string;
  confidence: number;
  source_metadata?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface CompanyKbDocumentsResponse {
  documents: CompanyKbDocument[];
}

export interface CompanyKbEvidenceResponse {
  evidence: CompanyKbEvidenceItem[];
}

export async function uploadCompanyKbDocuments(
  items: CompanyKbUploadItem[],
): Promise<CompanyKbDocumentsResponse> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }
  const token = await requireAccessToken();
  const form = new FormData();
  for (const item of items) {
    form.append("files", item.file);
    form.append("kb_document_types", item.kbDocumentType);
  }
  const res = await fetch(`${AGENT_API_URL}/api/company/kb/documents`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  return parseAgentResponse<CompanyKbDocumentsResponse>(res);
}

export async function fetchCompanyKbDocuments(): Promise<CompanyKbDocumentsResponse> {
  if (isMockMode()) {
    return { documents: [] };
  }
  const token = await requireAccessToken();
  const res = await fetch(`${AGENT_API_URL}/api/company/kb/documents`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseAgentResponse<CompanyKbDocumentsResponse>(res);
}

export async function fetchCompanyKbEvidence(
  documentId: string,
): Promise<CompanyKbEvidenceResponse> {
  if (isMockMode()) {
    return { evidence: [] };
  }
  const token = await requireAccessToken();
  const res = await fetch(
    `${AGENT_API_URL}/api/company/kb/documents/${documentId}/evidence`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  return parseAgentResponse<CompanyKbEvidenceResponse>(res);
}

export async function deleteCompanyKbDocument(documentId: string): Promise<void> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }
  const token = await requireAccessToken();
  const res = await fetch(
    `${AGENT_API_URL}/api/company/kb/documents/${documentId}`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  await parseAgentResponse<{ deleted: boolean }>(res);
}

export async function archiveAgentRun(
  runId: string,
  reason = "operator archived run",
): Promise<void> {
  if (isMockMode()) {
    archiveMockAgentRun(runId);
    return;
  }

  const token = await requireAccessToken();
  const res = await fetch(`${AGENT_API_URL}/api/runs/${encodeURIComponent(runId)}/archive`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
}

export async function startAgentRun(tenderId: string): Promise<string> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }

  const token = await requireAccessToken();
  const res = await fetch(`${AGENT_API_URL}/api/runs/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ tender_id: tenderId }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  const data = (await res.json()) as { run_id: string };
  return data.run_id;
}

export async function fetchLatestBidDraft(runId: string): Promise<BidResponseDraft | null> {
  if (isMockMode()) {
    const generatedDraft = generatedMockBidDrafts.get(runId);
    if (generatedDraft) return generatedDraft;
    return mockBidDrafts.find((draft) => draft.runId === runId) ?? null;
  }

  const token = await requireAccessToken();
  const res = await fetch(
    `${AGENT_API_URL}/api/bid-drafts/latest?run_id=${encodeURIComponent(runId)}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (res.status === 404) return null;
  const payload = await parseAgentResponse<RawBidResponseDraft>(res);
  return mapBidDraftPayload(payload, publicUrlForStoragePath);
}

export async function generateBidDraft(
  runId: string,
  bidId?: string,
): Promise<BidResponseDraft> {
  if (isMockMode()) {
    const draft =
      mockBidDrafts.find((item) => item.runId === runId) ?? {
        ...mockBidDrafts[0],
        runId,
        bidId,
      };
    generatedMockBidDrafts.set(runId, draft);
    return draft;
  }

  const token = await requireAccessToken();
  const res = await fetch(`${AGENT_API_URL}/api/bid-drafts/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ run_id: runId, bid_id: bidId ?? null }),
  });
  const payload = await parseAgentResponse<RawBidResponseDraft>(res);
  return mapBidDraftPayload(payload, publicUrlForStoragePath);
}

async function parseAgentResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

function publicUrlForStoragePath(storagePath: string): string | undefined {
  if (!supabase) return undefined;
  return supabase.storage.from(BUCKET_NAME).getPublicUrl(storagePath).data.publicUrl;
}
