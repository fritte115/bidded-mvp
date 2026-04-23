import { beforeEach, describe, expect, it, vi } from "vitest";

const supabaseState = vi.hoisted(() => ({
  rows: {} as Record<string, unknown[]>,
}));

vi.mock("@/lib/supabase", () => {
  class Query {
    private filters: Array<[string, unknown]> = [];

    constructor(private readonly tableName: string) {}

    select() {
      return this;
    }

    eq(column: string, value: unknown) {
      this.filters.push([column, value]);
      return this;
    }

    order() {
      return this;
    }

    single() {
      const [row] = this.filteredRows();
      return Promise.resolve(row ? { data: row, error: null } : {
        data: null,
        error: { code: "PGRST116", message: "not found" },
      });
    }

    or() {
      return Promise.resolve({ data: this.filteredRows(), error: null });
    }

    then<TResult1 = unknown, TResult2 = never>(
      onfulfilled?: ((value: unknown) => TResult1 | PromiseLike<TResult1>) | null,
      onrejected?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
    ) {
      return Promise.resolve({ data: this.filteredRows(), error: null }).then(
        onfulfilled,
        onrejected,
      );
    }

    private filteredRows() {
      const rows = supabaseState.rows[this.tableName] ?? [];
      return rows.filter((row) => {
        if (!row || typeof row !== "object") return false;
        const record = row as Record<string, unknown>;
        return this.filters.every(([column, value]) => record[column] === value);
      });
    }
  }

  return {
    isSupabaseConfigured: true,
    supabase: {
      from: (tableName: string) => new Query(tableName),
    },
  };
});

describe("fetchRunDetail evidence snapshot fallback", () => {
  beforeEach(() => {
    supabaseState.rows = {
      agent_runs: [
        {
          id: "run-1",
          status: "succeeded",
          started_at: "2026-04-23T10:00:00Z",
          completed_at: "2026-04-23T10:05:00Z",
          metadata: {},
          tender_id: "tender-1",
          company_id: "company-1",
          tenders: { title: "Municipal platform tender" },
          bid_decisions: [
            {
              verdict: "conditional_bid",
              confidence: 0.81,
              final_decision: {
                verdict: "conditional_bid",
                confidence: 0.81,
                vote_summary: {
                  bid: 1,
                  no_bid: 0,
                  conditional_bid: 3,
                },
                cited_memo: "ISO evidence came from the company KB.",
                disagreement_summary: "",
                compliance_matrix: [],
                compliance_blockers: [],
                potential_blockers: [],
                risk_register: [],
                missing_info: [],
                recommended_actions: [],
                evidence_ids: ["ev-1"],
              },
              metadata: {
                evidence_snapshot: [
                  {
                    id: "ev-1",
                    evidence_key: "COMPANY-KB-ISO",
                    source_type: "company_profile",
                    excerpt: "ISO 27001 certification is active.",
                    normalized_meaning: "ISO 27001 is active.",
                    category: "certification",
                    confidence: 0.92,
                    page_start: 1,
                    page_end: 1,
                    company_id: "company-1",
                    field_path: "knowledge_base.certification.doc-1.facts[0]",
                    source_metadata: {
                      source_label: "iso-cert.pdf",
                      original_filename: "iso-cert.pdf",
                      kb_document_type: "certification",
                    },
                  },
                ],
              },
            },
          ],
        },
      ],
      agent_outputs: [],
      documents: [],
      evidence_items: [],
    };
  });

  it("renders hard-deleted cited KB evidence from the decision snapshot", async () => {
    const { fetchRunDetail } = await import("./api");

    const run = await fetchRunDetail("run-1");

    expect(run?.judge?.evidenceIds).toEqual(["COMPANY-KB-ISO"]);
    expect(run?.evidence).toEqual([
      expect.objectContaining({
        key: "COMPANY-KB-ISO",
        excerpt: "ISO 27001 certification is active.",
        source: "iso-cert.pdf · Certification",
        kind: "company_profile",
        companyFieldPath: "knowledge_base.certification.doc-1.facts[0]",
      }),
    ]);
  });
});
