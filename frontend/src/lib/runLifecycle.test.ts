import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("run lifecycle display", () => {
  beforeEach(() => {
    vi.setSystemTime(new Date("2026-04-23T10:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("marks old running runs as stale instead of active", async () => {
    const { runLifecycleForDisplay, STALE_RUN_STAGE } = await import("./api");

    expect(
      runLifecycleForDisplay({
        status: "running",
        startedAt: "2026-04-23T09:00:00Z",
        createdAt: "2026-04-23T08:58:00Z",
        completedAt: null,
        metadata: {},
      }),
    ).toEqual({
      isActive: false,
      isStale: true,
      staleAgeMinutes: 60,
      stage: STALE_RUN_STAGE,
    });
  });

  it("uses the worker update timestamp when deciding freshness", async () => {
    const { runLifecycleForDisplay } = await import("./api");

    expect(
      runLifecycleForDisplay({
        status: "running",
        startedAt: "2026-04-23T08:00:00Z",
        createdAt: "2026-04-23T07:58:00Z",
        completedAt: null,
        metadata: { worker: { updated_at: "2026-04-23T09:45:00Z" } },
      }),
    ).toMatchObject({
      isActive: true,
      isStale: false,
      stage: "Running",
    });
  });
});

describe("mock-mode run deletion", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_SUPABASE_URL", "");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "");
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    window.localStorage.clear();
  });

  it("hides deleted mock runs instead of throwing the Supabase env error", async () => {
    const { deleteAgentRun, fetchRunDetail } = await import("./api");

    expect(await fetchRunDetail("run_5d9e4a7b")).not.toBeNull();

    await expect(deleteAgentRun("run_5d9e4a7b")).resolves.toBeUndefined();

    expect(await fetchRunDetail("run_5d9e4a7b")).toBeNull();
  });
});
