import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("procurement registration", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "test-anon-key");
    vi.stubGlobal("crypto", {
      subtle: {
        digest: vi.fn(async () => new Uint8Array([1, 2, 3, 4]).buffer),
      },
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.doUnmock("@/lib/supabase");
  });

  it("persists procurement document roles in document metadata", async () => {
    const uploadMock = vi.fn(async () => ({ error: null }));
    const documentUpsertMock = vi.fn(async () => ({ error: null }));
    const tenderSelectMock = vi.fn(async () => ({
      data: [{ id: "tender-1" }],
      error: null,
    }));
    const companySingleMock = vi.fn(async () => ({
      data: { id: "company-1" },
      error: null,
    }));

    const supabaseMock = {
      from: vi.fn((table: string) => {
        if (table === "companies") {
          return {
            select: vi.fn(() => ({
              eq: vi.fn(() => ({
                limit: vi.fn(() => ({
                  single: companySingleMock,
                })),
              })),
            })),
          };
        }
        if (table === "tenders") {
          return {
            upsert: vi.fn(() => ({
              select: tenderSelectMock,
            })),
          };
        }
        if (table === "documents") {
          return {
            upsert: documentUpsertMock,
          };
        }
        throw new Error(`Unexpected table ${table}`);
      }),
      storage: {
        from: vi.fn(() => ({
          upload: uploadMock,
        })),
      },
    };

    vi.doMock("@/lib/supabase", () => ({
      isSupabaseConfigured: true,
      supabase: supabaseMock,
    }));

    const { PDF_CONTENT_TYPE, registerProcurement } = await import("./api");
    const file = new File(["pricing"], "pricing.pdf", { type: PDF_CONTENT_TYPE });
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => new TextEncoder().encode("pricing").buffer,
    });

    await registerProcurement({
      title: "Impact procurement",
      issuingAuthority: "Impact Municipality",
      documents: [
        {
          file,
          procurementDocumentRole: "pricing_appendix",
        },
      ],
    });

    expect(uploadMock).toHaveBeenCalledTimes(1);
    expect(documentUpsertMock).toHaveBeenCalledWith(
      expect.objectContaining({
        document_role: "tender_document",
        metadata: expect.objectContaining({
          registered_via: "frontend_ui",
          demo_company_id: "company-1",
          procurement_document_role: "pricing_appendix",
        }),
      }),
      { onConflict: "storage_path" },
    );
  });
});
