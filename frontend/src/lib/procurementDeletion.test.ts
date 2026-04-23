import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type QueryResponse = {
  data?: unknown;
  error: { message: string } | null;
  count?: number | null;
};

class QueryBuilder {
  private action: "select" | "delete" = "select";
  private filters: Record<string, unknown> = {};

  constructor(
    private readonly table: string,
    private readonly responses: Record<string, QueryResponse | QueryResponse[]>,
    private readonly calls: Array<Record<string, unknown>>,
  ) {}

  select(columns: string, options?: unknown): QueryBuilder {
    this.action = "select";
    this.calls.push({
      table: this.table,
      action: "select",
      columns,
      options,
    });
    return this;
  }

  delete(): QueryBuilder {
    this.action = "delete";
    this.calls.push({
      table: this.table,
      action: "delete",
    });
    return this;
  }

  eq(column: string, value: unknown): QueryBuilder {
    this.filters[column] = value;
    return this;
  }

  order(column: string, options?: unknown): Promise<QueryResponse> {
    this.calls.push({
      table: this.table,
      action: this.action,
      filters: { ...this.filters },
      order: [column, options],
    });
    return Promise.resolve(this.resolve());
  }

  then<TResult1 = QueryResponse, TResult2 = never>(
    onfulfilled?:
      | ((value: QueryResponse) => TResult1 | PromiseLike<TResult1>)
      | null,
    onrejected?:
      | ((reason: unknown) => TResult2 | PromiseLike<TResult2>)
      | null,
  ): Promise<TResult1 | TResult2> {
    this.calls.push({
      table: this.table,
      action: this.action,
      filters: { ...this.filters },
    });
    return Promise.resolve(this.resolve()).then(onfulfilled, onrejected);
  }

  private resolve(): QueryResponse {
    const key = `${this.table}:${this.action}`;
    const response = this.responses[key];
    if (!response) {
      throw new Error(`Missing mock response for ${key}`);
    }
    if (Array.isArray(response)) {
      const next = response.shift();
      if (!next) {
        throw new Error(`Exhausted mock responses for ${key}`);
      }
      return next;
    }
    return response;
  }
}

function installSupabaseMock(
  responses: Record<string, QueryResponse | QueryResponse[]>,
) {
  const calls: Array<Record<string, unknown>> = [];
  const removeMock = vi.fn(async () => ({ error: null }));
  const client = {
    from: (table: string) => new QueryBuilder(table, responses, calls),
    storage: {
      from: vi.fn(() => ({
        remove: removeMock,
      })),
    },
  };

  vi.doMock("@/lib/supabase", () => ({
    isSupabaseConfigured: true,
    supabase: client,
  }));

  return { calls, client, removeMock };
}

describe("procurement deletion guards", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "test-anon-key");
  });

  afterEach(() => {
    vi.resetModules();
    vi.doUnmock("@/lib/supabase");
    vi.unstubAllEnvs();
  });

  it("refuses to hard-delete procurements that have run history", async () => {
    const { removeMock } = installSupabaseMock({
      "agent_runs:select": {
        data: null,
        error: null,
        count: 2,
      },
    });

    const { deleteProcurement } = await import("./api");

    await expect(deleteProcurement("tender-1")).rejects.toThrow(
      /run history/i,
    );
    expect(removeMock).not.toHaveBeenCalled();
  });

  it("surfaces run history even when every linked run is archived", async () => {
    installSupabaseMock({
      "tenders:select": {
        data: [
          {
            id: "tender-1",
            title: "Archived-only run history",
            created_at: "2026-04-23T08:00:00Z",
            documents: [],
            agent_runs: [
              {
                id: "run-1",
                status: "succeeded",
                started_at: "2026-04-23T08:05:00Z",
                created_at: "2026-04-23T08:01:00Z",
                archived_at: "2026-04-23T09:00:00Z",
                archived_reason: "operator archived run",
                metadata: {},
                bid_decisions: [{ verdict: "bid" }],
              },
            ],
          },
        ],
        error: null,
      },
    });

    const { fetchProcurements } = await import("./api");

    await expect(fetchProcurements()).resolves.toEqual([
      expect.objectContaining({
        id: "tender-1",
        latestRun: null,
        hasRunHistory: true,
      }),
    ]);
  });
});
