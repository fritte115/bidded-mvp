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
      isArchived: false,
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
      isArchived: false,
      stage: "Running",
    });
  });

  it("marks archived runs as inactive and non-stale", async () => {
    const { ARCHIVED_RUN_STAGE, runLifecycleForDisplay } = await import("./api");

    expect(
      runLifecycleForDisplay({
        status: "running",
        startedAt: "2026-04-23T08:00:00Z",
        createdAt: "2026-04-23T07:58:00Z",
        completedAt: null,
        archivedAt: "2026-04-23T09:00:00Z",
        metadata: {},
      }),
    ).toEqual({
      isActive: false,
      isStale: false,
      isArchived: true,
      staleAgeMinutes: null,
      stage: ARCHIVED_RUN_STAGE,
    });
  });
});

describe("run archiving", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("hides archived mock runs instead of throwing the Supabase env error", async () => {
    vi.stubEnv("VITE_SUPABASE_URL", "");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "");
    const { archiveAgentRun, fetchRunDetail } = await import("./api");

    expect(await fetchRunDetail("run_5d9e4a7b")).not.toBeNull();

    await expect(archiveAgentRun("run_5d9e4a7b")).resolves.toBeUndefined();

    expect(await fetchRunDetail("run_5d9e4a7b")).toBeNull();
  });

  it("archives live runs through the agent API instead of deleting Supabase rows", async () => {
    vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "test-anon-key");
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          run_id: "11111111-1111-4111-8111-111111111111",
          archived_at: "2026-04-19T10:30:00+00:00",
          already_archived: false,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { archiveAgentRun } = await import("./api");

    await archiveAgentRun(
      "11111111-1111-4111-8111-111111111111",
      "clear stale run",
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/runs/11111111-1111-4111-8111-111111111111/archive",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "clear stale run" }),
      },
    );
  });
});
