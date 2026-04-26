import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.fn();
const getSessionMock = vi.fn();

describe("company knowledge base API", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "test-anon-key");
    vi.stubEnv("VITE_AGENT_API_URL", "https://agent.example");
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
    getSessionMock.mockResolvedValue({
      data: { session: { access_token: "token-123" } },
      error: null,
    });
    vi.doMock("@/lib/supabase", () => ({
      isSupabaseConfigured: true,
      supabase: { auth: { getSession: getSessionMock } },
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.doUnmock("@/lib/supabase");
  });

  it("uploads company KB files as multipart form data with per-file types", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ documents: [{ document_id: "doc-1" }] }),
    });
    const { uploadCompanyKbDocuments } = await import("./api");
    const file = new File(["ISO 27001"], "iso.txt", { type: "text/plain" });

    const result = await uploadCompanyKbDocuments([
      { file, kbDocumentType: "certification" },
    ]);

    expect(result).toEqual({ documents: [{ document_id: "doc-1" }] });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://agent.example/api/company/kb/documents",
      expect.objectContaining({
        method: "POST",
        headers: { Authorization: "Bearer token-123" },
      }),
    );
    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get("files")).toBe(file);
    expect(body.get("kb_document_types")).toBe("certification");
  });

  it("updates company profile through the backend so evidence can regenerate", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ company_id: "company-1", evidence_count: 3 }),
    });
    const { updateCompany } = await import("./api");

    await updateCompany(
      {
        name: "Nordic Digital Delivery AB",
        orgNumber: "559900-0417",
        size: "1850 employees",
        hq: "Sweden",
        capabilities: ["Azure"],
        certifications: [],
        references: [],
        financialAssumptions: {
          revenueRange: "2,000 MSEK / year",
          targetMargin: "32%",
          maxContractSize: "Min. margin 22%",
        },
      },
      {
        id: "company-1",
        name: "Old name",
        organization_number: "559900-0417",
        headquarters_country: "SE",
        employee_count: 100,
        annual_revenue_sek: null,
        capabilities: { service_lines: {} },
        certifications: [],
        reference_projects: [],
        financial_assumptions: {},
        profile_details: {},
      },
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "https://agent.example/api/company/profile?company_id=company-1",
      expect.objectContaining({
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer token-123",
        },
      }),
    );
    const payload = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(payload.name).toBe("Nordic Digital Delivery AB");
    expect(payload.certifications).toEqual([]);
  });

  it("imports company website through the authenticated agent API", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        source_url: "https://impactsolution.se/",
        imported_at: "2026-04-24T18:00:00Z",
        pages: [],
        profile_patch: { website: "https://impactsolution.se/" },
        field_sources: {},
        warnings: [],
      }),
    });
    const { importCompanyWebsite } = await import("./api");

    await expect(importCompanyWebsite("https://impactsolution.se/")).resolves
      .toEqual(expect.objectContaining({
        source_url: "https://impactsolution.se/",
      }));

    expect(fetchMock).toHaveBeenCalledWith(
      "https://agent.example/api/company/import-website",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer token-123",
        },
        body: JSON.stringify({
          url: "https://impactsolution.se/",
          max_pages: 5,
        }),
      },
    );
  });

  it("normalizes email-like website import input before calling the agent API", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        source_url: "https://impactsolution.se/",
        pages: [],
        profile_patch: { website: "https://impactsolution.se/" },
        field_sources: {},
        warnings: [],
      }),
    });
    const { importCompanyWebsite } = await import("./api");

    await importCompanyWebsite("https://info@impactsolution.se/");

    const payload = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(payload.url).toBe("https://impactsolution.se/");
  });

  it("reads and deletes company KB documents through the backend", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ documents: [{ document_id: "doc-1" }] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ evidence: [{ evidence_key: "COMPANY-KB-1" }] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ deleted: true }),
      });
    const {
      deleteCompanyKbDocument,
      fetchCompanyKbDocuments,
      fetchCompanyKbEvidence,
    } = await import("./api");

    await expect(fetchCompanyKbDocuments()).resolves.toEqual({
      documents: [{ document_id: "doc-1" }],
    });
    await expect(fetchCompanyKbEvidence("doc-1")).resolves.toEqual({
      evidence: [{ evidence_key: "COMPANY-KB-1" }],
    });
    await expect(deleteCompanyKbDocument("doc-1")).resolves.toBeUndefined();

    expect(fetchMock.mock.calls[0][0]).toBe(
      "https://agent.example/api/company/kb/documents",
    );
    expect(fetchMock.mock.calls[0][1].headers).toEqual({
      Authorization: "Bearer token-123",
    });
    expect(fetchMock.mock.calls[1][0]).toBe(
      "https://agent.example/api/company/kb/documents/doc-1/evidence",
    );
    expect(fetchMock.mock.calls[1][1].headers).toEqual({
      Authorization: "Bearer token-123",
    });
    expect(fetchMock.mock.calls[2][0]).toBe(
      "https://agent.example/api/company/kb/documents/doc-1",
    );
    expect(fetchMock.mock.calls[2][1].method).toBe("DELETE");
    expect(fetchMock.mock.calls[2][1].headers).toEqual({
      Authorization: "Bearer token-123",
    });
  });
});
