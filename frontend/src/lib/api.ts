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

import { supabase } from "@/lib/supabase";
import type { Company, RunStatus, Verdict } from "@/data/mock";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
  const { data, error } = await supabase
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
  const { error } = await supabase
    .from("companies")
    .update(mapCompanyToDbUpdate(c))
    .eq("tenant_key", "demo");

  if (error) throw new Error(`updateCompany: ${error.message}`);
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
  const [tendersRes, docsRes, activeRunsRes] = await Promise.all([
    supabase
      .from("tenders")
      .select("id", { count: "exact", head: true })
      .eq("tenant_key", "demo"),
    supabase
      .from("documents")
      .select("id", { count: "exact", head: true })
      .eq("tenant_key", "demo")
      .eq("document_role", "tender_document"),
    supabase
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
  stage: string | null;
  startedAt: string;
  completedAt: string | null;
  durationSec: number | null;
}

export async function fetchActiveRuns(): Promise<ActiveRun[]> {
  const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

  const { data, error } = await supabase
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

    return {
      id: r.id as string,
      tenderName: tender?.title ?? "Unknown procurement",
      status: (r.status as RunStatus) ?? "pending",
      stage: ((r.metadata as Record<string, unknown>)?.current_step as string) ?? null,
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
  stage: string | null;
  decision: Verdict | null;
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

export async function fetchProcurements(): Promise<ProcurementRow[]> {
  const { data, error } = await supabase
    .from("tenders")
    .select(`
      id,
      title,
      created_at,
      documents(original_filename, parse_status, metadata),
      agent_runs(id, status, started_at, created_at, metadata)
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

    return {
      id: t.id as string,
      name: t.title as string,
      uploadedAt: t.created_at as string,
      documentFilenames: docs.map((d) => d.original_filename),
      documents: documentRows,
      documentCount: docs.length,
      latestRun: latestRun
        ? {
            id: latestRun.id,
            status: latestRun.status as RunStatus,
            startedAt: latestRun.started_at ?? latestRun.created_at,
            stage: (latestRun.metadata?.current_step as string) ?? null,
            decision: null,
          }
        : null,
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
  const { data: docRows, error: docListErr } = await supabase
    .from("documents")
    .select("storage_path")
    .eq("tender_id", tenderId)
    .eq("tenant_key", "demo");
  if (docListErr) throw new Error(`deleteProcurement (list documents): ${docListErr.message}`);

  const paths = (docRows ?? [])
    .map((r) => (r as { storage_path: string }).storage_path)
    .filter((p): p is string => typeof p === "string" && p.length > 0);

  if (paths.length > 0) {
    const { error: storageErr } = await supabase.storage.from(BUCKET_NAME).remove(paths);
    if (storageErr)
      throw new Error(`deleteProcurement (storage remove): ${storageErr.message}`);
  }

  const { error } = await supabase
    .from("tenders")
    .delete()
    .eq("id", tenderId)
    .eq("tenant_key", "demo");
  if (error) throw new Error(`deleteProcurement: ${error.message}`);
}

export async function registerProcurement(input: RegisterProcurementInput): Promise<string> {
  // 1. Fetch demo company ID
  const { data: companyRow, error: companyErr } = await supabase
    .from("companies")
    .select("id")
    .eq("tenant_key", "demo")
    .limit(1)
    .single();
  if (companyErr) throw new Error(`registerProcurement (company lookup): ${companyErr.message}`);
  const companyId = (companyRow as { id: string }).id;

  // 2. Upsert tender row
  const { data: tenderRows, error: tenderErr } = await supabase
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

    const { error: uploadErr } = await supabase.storage
      .from(BUCKET_NAME)
      .upload(storagePath, new Blob([buffer], { type: "application/pdf" }), {
        contentType: "application/pdf",
        upsert: true,
      });
    if (uploadErr)
      throw new Error(
        `registerProcurement (storage upload ${file.name}): ${uploadErr.message} [status: ${(uploadErr as { statusCode?: string }).statusCode ?? "?"}]`,
      );

    const { error: docErr } = await supabase.from("documents").upsert(
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
