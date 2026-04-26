import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const TEST_SUPABASE_URL = "https://example.supabase.co";
const TEST_SUPABASE_ANON_KEY = "test-anon-key";

describe("mock mode fallback", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_SUPABASE_URL", "");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "");
    vi.setSystemTime(new Date("2026-04-23T10:00:00Z"));
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.resetModules();
    vi.useRealTimers();
    vi.stubEnv("VITE_SUPABASE_URL", TEST_SUPABASE_URL);
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", TEST_SUPABASE_ANON_KEY);
    window.localStorage.clear();
  });

  it("does not throw when supabase env is missing", async () => {
    const module = await import("./supabase");

    expect(module.isSupabaseConfigured).toBe(false);
    expect(module.supabase).toBeNull();
  });

  it("returns mock dashboard stats when supabase env is missing", async () => {
    const { fetchDashboardStats, runLifecycleForDisplay } = await import("./api");
    const { procurements, runs } = await import("@/data/mock");

    await expect(fetchDashboardStats()).resolves.toEqual({
      totalProcurements: procurements.length,
      totalPdfDocuments: procurements.reduce((sum, row) => sum + row.documents.length, 0),
      activeRuns: runs.filter((run) =>
        runLifecycleForDisplay({
          status: run.status,
          startedAt: run.startedAt,
          createdAt: run.startedAt,
          completedAt: run.completedAt ?? null,
          metadata: {},
        }).isActive,
      ).length,
    });
  });
});
