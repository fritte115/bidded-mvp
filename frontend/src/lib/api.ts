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
  bids as mockBids,
  findRun as findMockRun,
  latestRunForProcurement,
  procurements as mockProcurements,
  runs as mockRuns,
  type AgentMotion,
  type AgentName,
  type Bid,
  type BidStatus,
  type Company,
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MOCK_MODE_WRITE_MESSAGE =
  "Frontend is running in mock mode because the public Supabase env vars are missing. Copy frontend/.env.example to frontend/.env to enable live writes.";

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

function mockParseStatus(procurement: Procurement): ProcurementDocumentRow["parseStatus"] {
  if (procurement.status === "done") return "parsed";
  if (procurement.status === "processing") return "parsing";
  return "pending";
}

function mockDashboardStats(): DashboardStats {
  return {
    totalProcurements: mockProcurements.length,
    totalPdfDocuments: mockProcurements.reduce(
      (sum, procurement) => sum + procurement.documents.length,
      0,
    ),
    activeRuns: mockRuns.filter(
      (run) => run.status === "running" || run.status === "pending",
    ).length,
  };
}

function mockActiveRuns(): ActiveRun[] {
  return mockRuns
    .filter((run) => run.status === "running" || run.status === "pending")
    .map((run) => ({
      id: run.id,
      tenderName: run.tenderName,
      status: run.status,
      stage: run.stage,
      startedAt: run.startedAt,
      completedAt: run.completedAt ?? null,
      durationSec: run.durationSec ?? null,
    }))
    .sort(
      (left, right) =>
        new Date(right.startedAt).getTime() - new Date(left.startedAt).getTime(),
    );
}

function mockProcurementLatestRun(
  procurementId: string,
): ProcurementLatestRun | null {
  const latestRun = latestRunForProcurement(procurementId);
  if (!latestRun) return null;

  return {
    id: latestRun.id,
    status: latestRun.status,
    startedAt: latestRun.startedAt,
    stage: latestRun.stage,
    decision:
      latestRun.status === "needs_human_review"
        ? null
        : (latestRun.decision ?? null),
    needsJudgeReview: latestRun.status === "needs_human_review",
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
  return mockRuns
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
  const run = findMockRun(runId);
  if (!run) return null;

  return {
    id: run.id,
    tenderName: run.tenderName,
    tenderId: run.tenderId,
    company: run.company,
    status: run.status,
    stage: run.stage,
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
  return mockBids
    .map((bid) => {
      const procurement = mockProcurements.find(
        (row) => row.id === bid.procurementId,
      );
      const run = bid.runId
        ? findMockRun(bid.runId)
        : mockRuns.find((candidate) => candidate.tenderId === bid.procurementId);
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

// ---------------------------------------------------------------------------
// Company
// ---------------------------------------------------------------------------

/** Raw shape returned by Supabase for the companies table */
interface DbCompany {
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
  }>;
  reference_projects: Array<{
    customer_type?: string;
    case_study_summary?: string;
    contract_value_band_sek?: string;
    delivery_years?: string;
  }>;
  financial_assumptions: {
    revenue_band_sek?: { min: number; max: number };
    target_gross_margin_percent?: number;
    minimum_acceptable_margin_percent?: number;
  };
  profile_details: {
    company_size?: string;
  };
}

function mapDbCompany(row: DbCompany): Company {
  // Flatten service_lines into a single capabilities array
  const serviceLines = row.capabilities?.service_lines ?? {};
  const capabilities = Object.values(serviceLines).flat() as string[];

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

  return {
    name: row.name,
    orgNumber: row.organization_number ?? "—",
    size: row.employee_count != null
      ? `${row.employee_count.toLocaleString("sv-SE")} employees`
      : (row.profile_details?.company_size ?? "—"),
    hq: countryName(row.headquarters_country),
    capabilities,
    certifications,
    references,
    financialAssumptions: { revenueRange, targetMargin, maxContractSize },
  };
}

/**
 * Map a frontend Company back to the DB columns we can safely update.
 * Scalars are exact; JSONB fields preserve the DB keys Ralph's seed created.
 */
function mapCompanyToDbUpdate(c: Company): Record<string, unknown> {
  // Reverse country name → code ("Sweden" → "SE")
  const COUNTRY_CODES = Object.fromEntries(
    Object.entries(COUNTRY_NAMES).map(([k, v]) => [v, k])
  );

  // Parse "1 850 employees" → 1850  (sv-SE locale uses non-breaking space)
  const empMatch = c.size.replace(/\s/g, "").match(/\d+/);
  const employeeCount = empMatch ? parseInt(empMatch[0], 10) : null;

  // Capabilities: store flat list under service_lines.all
  const capabilities = {
    service_lines: { all: c.capabilities },
  };

  // Certifications: scope = issuer description, status inferred from validUntil
  const certifications = c.certifications.map((cert) => ({
    name: cert.name,
    scope: cert.issuer !== "—" ? cert.issuer : "",
    status: cert.validUntil === "Active" ? "active" : "active",
    source_label: "user_edit",
  }));

  // Reference projects: map back from frontend fields
  const reference_projects = c.references.map((ref, i) => ({
    reference_id: `ref-user-${i + 1}`,
    sector: "public_sector",
    customer_type: ref.client,
    delivery_years: String(ref.year),
    contract_value_band_sek: ref.value.replace(/\s?SEK$/i, "").trim(),
    case_study_summary: ref.scope,
    capabilities_used: [],
    source_label: "user_edit",
  }));

  // Financial assumptions: parse percentage strings back to numbers
  const marginMatch = c.financialAssumptions.targetMargin.match(/\d+/);
  const financial_assumptions = {
    target_gross_margin_percent: marginMatch ? parseInt(marginMatch[0], 10) : null,
    pricing_notes: [c.financialAssumptions.revenueRange, c.financialAssumptions.maxContractSize],
  };

  return {
    name: c.name,
    organization_number: c.orgNumber !== "—" ? c.orgNumber : null,
    headquarters_country: COUNTRY_CODES[c.hq] ?? c.hq,
    employee_count: employeeCount && !isNaN(employeeCount) ? employeeCount : null,
    capabilities,
    certifications,
    reference_projects,
    financial_assumptions,
  };
}

/**
 * Fetch the single demo company from Supabase.
 * Falls back gracefully — callers should handle null (use mock data as fallback).
 */
export async function fetchCompany(): Promise<Company> {
  if (isMockMode()) {
    return mockCompany;
  }

  const client = requireSupabase();
  const { data, error } = await client
    .from("companies")
    .select("*")
    .eq("tenant_key", "demo")
    .limit(1)
    .single();

  if (error) throw new Error(`fetchCompany: ${error.message}`);
  return mapDbCompany(data as DbCompany);
}

/**
 * Persist edited company data back to Supabase.
 * Requires the "demo update" RLS policy to be enabled on the companies table.
 */
export async function updateCompany(c: Company): Promise<void> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }

  const res = await fetch(`${AGENT_API_URL}/api/company/profile`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mapCompanyToDbUpdate(c)),
  });
  await parseAgentResponse<{ company_id: string; evidence_count: number }>(res);
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
      .select("id", { count: "exact", head: true })
      .eq("tenant_key", "demo")
      .in("status", ["running", "pending"]),
  ]);

  return {
    totalProcurements: tendersRes.count ?? 0,
    totalPdfDocuments: docsRes.count ?? 0,
    activeRuns: activeRunsRes.count ?? 0,
  };
}

// Lightweight run shape for the Dashboard active-analyses table
export interface ActiveRun {
  id: string;
  tenderName: string;
  status: RunStatus;
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
    .select("id, status, started_at, completed_at, metadata, tenders(title)")
    .eq("tenant_key", "demo")
    .or(
      `status.in.(running,pending),and(status.in.(succeeded,failed,needs_human_review),completed_at.gte.${yesterday})`,
    )
    .order("created_at", { ascending: false })
    .limit(20);

  if (error) throw new Error(`fetchActiveRuns: ${error.message}`);

  return (data ?? []).map((r: Record<string, unknown>) => {
    const tender = r.tenders as { title: string } | null;
    const startedAt = r.started_at as string | null;
    const completedAt = r.completed_at as string | null;
    const durationSec =
      startedAt && completedAt
        ? Math.round(
            (new Date(completedAt).getTime() - new Date(startedAt).getTime()) / 1000,
          )
        : null;

    const status = (r.status as RunStatus) ?? "pending";
    return {
      id: r.id as string,
      tenderName: tender?.title ?? "Unknown procurement",
      status,
      stage: dashboardStageLabel(status, r.metadata),
      startedAt: startedAt ?? (r as Record<string, unknown>).created_at as string,
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
        metadata: Record<string, unknown>;
        bid_decisions: { verdict: string }[] | { verdict: string } | null;
      }>
    ) ?? [];

    // Sort runs by created_at desc, pick latest
    const latestRun = runs.sort(
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
      latestRunPayload = {
        id: latestRun.id,
        status: latestRun.status as RunStatus,
        startedAt: latestRun.started_at ?? latestRun.created_at,
        stage: dashboardStageLabel(
          latestRun.status as RunStatus,
          latestRun.metadata,
        ),
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
      `id, status, started_at, completed_at, metadata, tender_id, company_id,
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
  const startedAt = run.started_at as string | null;
  const completedAt = run.completed_at as string | null;

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
  const step = resolveMetadataCurrentStep(run.metadata);
  const stage =
    step != null ? stageDisplayName(step) : dashboardStageLabel(status, run.metadata);

  return {
    id: runId,
    tenderName: (tender?.title as string) ?? "Unknown",
    tenderId,
    company: "Demo company",
    status,
    stage,
    startedAt: startedAt ?? (run.created_at as string) ?? "",
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

export async function deleteAgentRun(runId: string): Promise<void> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }

  const client = requireSupabase();
  const { error } = await client
    .from("agent_runs")
    .delete()
    .eq("id", runId)
    .eq("tenant_key", "demo");
  if (error) throw new Error(`deleteAgentRun: ${error.message}`);
}

export async function startAgentRun(tenderId: string): Promise<string> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }

  const res = await fetch(`${AGENT_API_URL}/api/runs/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tender_id: tenderId }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  const data = (await res.json()) as { run_id: string };
  return data.run_id;
}

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
  const form = new FormData();
  for (const item of items) {
    form.append("files", item.file);
    form.append("kb_document_types", item.kbDocumentType);
  }
  const res = await fetch(`${AGENT_API_URL}/api/company/kb/documents`, {
    method: "POST",
    body: form,
  });
  return parseAgentResponse<CompanyKbDocumentsResponse>(res);
}

export async function fetchCompanyKbDocuments(): Promise<CompanyKbDocumentsResponse> {
  if (isMockMode()) {
    return { documents: [] };
  }
  const res = await fetch(`${AGENT_API_URL}/api/company/kb/documents`);
  return parseAgentResponse<CompanyKbDocumentsResponse>(res);
}

export async function fetchCompanyKbEvidence(
  documentId: string,
): Promise<CompanyKbEvidenceResponse> {
  if (isMockMode()) {
    return { evidence: [] };
  }
  const res = await fetch(
    `${AGENT_API_URL}/api/company/kb/documents/${documentId}/evidence`,
  );
  return parseAgentResponse<CompanyKbEvidenceResponse>(res);
}

export async function deleteCompanyKbDocument(documentId: string): Promise<void> {
  if (isMockMode()) {
    throw new Error(MOCK_MODE_WRITE_MESSAGE);
  }
  const res = await fetch(
    `${AGENT_API_URL}/api/company/kb/documents/${documentId}`,
    { method: "DELETE" },
  );
  await parseAgentResponse<{ deleted: boolean }>(res);
}

async function parseAgentResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}
