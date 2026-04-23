import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const TEST_SUPABASE_URL = "https://example.supabase.co";
const TEST_SUPABASE_ANON_KEY = "test-anon-key";

describe("mock mode fallback", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_SUPABASE_URL", "");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "");
  });

  afterEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_SUPABASE_URL", TEST_SUPABASE_URL);
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", TEST_SUPABASE_ANON_KEY);
  });

  it("does not throw when supabase env is missing", async () => {
    const module = await import("./supabase");

    expect(module.isSupabaseConfigured).toBe(false);
    expect(module.supabase).toBeNull();
  });

  it("returns mock dashboard stats when supabase env is missing", async () => {
    const { fetchDashboardStats } = await import("./api");
    const { procurements, runs } = await import("@/data/mock");

    await expect(fetchDashboardStats()).resolves.toEqual({
      totalProcurements: procurements.length,
      totalPdfDocuments: procurements.reduce((sum, row) => sum + row.documents.length, 0),
      activeRuns: runs.filter((run) => run.status === "running" || run.status === "pending")
        .length,
    });
  });
});
