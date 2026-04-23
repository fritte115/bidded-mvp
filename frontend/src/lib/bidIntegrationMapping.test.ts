import { describe, expect, it } from "vitest";
import {
  buildBidDraftPath,
  mapBidRow,
  mapCompareRows,
  summarizeBidPipeline,
} from "./bidIntegrationMapping";

const tenderA = "33333333-3333-4333-8333-333333333333";
const tenderB = "44444444-4444-4444-8444-444444444444";
const runOld = "11111111-1111-4111-8111-111111111111";
const runNew = "22222222-2222-4222-8222-222222222222";

describe("mapCompareRows", () => {
  it("keeps the latest decision per tender and derives decision summary fields", () => {
    const rows = mapCompareRows(
      [
        {
          agent_run_id: runOld,
          created_at: "2026-04-18T10:00:00Z",
          verdict: "bid",
          confidence: 0.61,
          final_decision: {
            cited_memo: "Older memo.",
            risk_register: [],
            compliance_blockers: [],
            potential_blockers: [],
          },
          agent_runs: {
            id: runOld,
            tender_id: tenderA,
            status: "succeeded",
            started_at: "2026-04-18T09:00:00Z",
            completed_at: "2026-04-18T10:00:00Z",
            tenders: {
              title: "Old decision tender",
              created_at: "2026-04-15T08:00:00Z",
              documents: [{ id: "doc-1" }],
            },
          },
        },
        {
          agent_run_id: runNew,
          created_at: "2026-04-19T12:00:00Z",
          verdict: "conditional_bid",
          confidence: 0.77,
          final_decision: {
            cited_memo: "New memo. Keep this reason.",
            risk_register: [
              { risk: "Staffing", severity: "medium", mitigation: "Confirm CVs" },
              { risk: "Liability", severity: "high", mitigation: "Legal review" },
            ],
            compliance_blockers: [{ claim: "Missing insurance certificate." }],
            potential_blockers: [{ claim: "Named staff not confirmed." }],
            recommended_actions: ["Confirm staffing."],
            missing_info: ["Exact submission appendix list."],
          },
          agent_runs: {
            id: runNew,
            tender_id: tenderA,
            status: "succeeded",
            started_at: "2026-04-19T11:00:00Z",
            completed_at: "2026-04-19T12:00:00Z",
            tenders: {
              title: "New decision tender",
              created_at: "2026-04-15T08:00:00Z",
              documents: [{ id: "doc-1" }, { id: "doc-2" }],
            },
          },
        },
        {
          agent_run_id: "66666666-6666-4666-8666-666666666666",
          created_at: "2026-04-20T12:00:00Z",
          verdict: "no_bid",
          confidence: 0.99,
          final_decision: {
            cited_memo: "Archived decision should stay hidden.",
            risk_register: [],
            compliance_blockers: [],
            potential_blockers: [],
          },
          agent_runs: {
            id: "66666666-6666-4666-8666-666666666666",
            tender_id: tenderA,
            status: "succeeded",
            started_at: "2026-04-20T11:00:00Z",
            completed_at: "2026-04-20T12:00:00Z",
            archived_at: "2026-04-20T12:30:00Z",
            tenders: {
              title: "Archived decision tender",
              created_at: "2026-04-15T08:00:00Z",
              documents: [{ id: "doc-3" }],
            },
          },
        },
        {
          agent_run_id: "55555555-5555-4555-8555-555555555555",
          created_at: "2026-04-18T15:00:00Z",
          verdict: "no_bid",
          confidence: 0.82,
          final_decision: {
            cited_memo: "Formal blocker.",
            risk_register: [{ risk: "Eligibility", severity: "high" }],
            compliance_blockers: [{ claim: "Mandatory certification missing." }],
          },
          agent_runs: {
            id: "55555555-5555-4555-8555-555555555555",
            tender_id: tenderB,
            status: "succeeded",
            started_at: "2026-04-18T14:00:00Z",
            completed_at: "2026-04-18T15:00:00Z",
            tenders: {
              title: "No bid tender",
              created_at: "2026-04-16T08:00:00Z",
              documents: [],
            },
          },
        },
      ],
      [
        {
          id: "bid-1",
          agent_run_id: runNew,
          status: "review",
          updated_at: "2026-04-19T13:00:00Z",
        },
      ],
    );

    expect(rows.map((r) => r.runId)).toEqual([
      runNew,
      "55555555-5555-4555-8555-555555555555",
    ]);
    expect(rows[0]).toMatchObject({
      tenderId: tenderA,
      tenderName: "New decision tender",
      verdict: "CONDITIONAL_BID",
      confidence: 77,
      topReason: "New memo",
      documentCount: 2,
      riskScore: "High",
      riskCount: 2,
      complianceBlockerCount: 1,
      potentialBlockerCount: 1,
      recommendedActions: ["Confirm staffing."],
      missingInfo: ["Exact submission appendix list."],
      isDraftable: true,
      existingBidId: "bid-1",
      existingBidStatus: "review",
    });
    expect(rows[1]).toMatchObject({
      verdict: "NO_BID",
      isDraftable: false,
      riskScore: "High",
    });
  });
});

describe("buildBidDraftPath", () => {
  it("routes existing bids to edit and draftable decisions to a run-linked new bid", () => {
    expect(
      buildBidDraftPath({
        tenderId: tenderA,
        runId: runNew,
        isDraftable: true,
        existingBidId: "bid-1",
      }),
    ).toBe("/bids/bid-1/edit");

    expect(
      buildBidDraftPath({
        tenderId: tenderA,
        runId: runNew,
        isDraftable: true,
      }),
    ).toBe(`/bids/new?procurement=${tenderA}&run=${runNew}`);

    expect(
      buildBidDraftPath({
        tenderId: tenderA,
        runId: runNew,
        isDraftable: false,
      }),
    ).toBeNull();
  });
});

describe("mapBidRow", () => {
  it("maps Supabase bid rows with hours, metadata, tender date, and linked decision", () => {
    const bid = mapBidRow({
      id: "bid-1",
      tender_id: tenderA,
      rate_sek: "1300",
      margin_pct: "13",
      hours_estimated: 720,
      status: "review",
      notes: "Confirm pricing.",
      updated_at: "2026-04-19T13:00:00Z",
      metadata: { sourceDecision: { runId: runNew } },
      agent_run_id: runNew,
      tenders: {
        title: "New decision tender",
        created_at: "2026-04-15T08:00:00Z",
        documents: [{ id: "doc-1" }],
      },
      agent_runs: {
        id: runNew,
        tender_id: tenderA,
        status: "succeeded",
        started_at: "2026-04-19T11:00:00Z",
        completed_at: "2026-04-19T12:00:00Z",
        bid_decisions: [
          {
            created_at: "2026-04-19T12:00:00Z",
            verdict: "bid",
            confidence: 0.7,
            final_decision: { cited_memo: "Bid rationale." },
          },
        ],
      },
    });

    expect(bid).toMatchObject({
      id: "bid-1",
      procurementId: tenderA,
      procurementName: "New decision tender",
      rateSEK: 1300,
      marginPct: 13,
      hoursEstimated: 720,
      tenderUploadedAt: "2026-04-15T08:00:00Z",
      runId: runNew,
      metadata: { sourceDecision: { runId: runNew } },
      decision: {
        runId: runNew,
        verdict: "BID",
        confidence: 70,
        topReason: "Bid rationale",
      },
    });
  });

  it("does not surface linked decisions for archived run rows", () => {
    const bid = mapBidRow({
      id: "bid-archived",
      tender_id: tenderA,
      status: "review",
      agent_run_id: runNew,
      tenders: {
        title: "Archived run tender",
        created_at: "2026-04-15T08:00:00Z",
        documents: [],
      },
      agent_runs: {
        id: runNew,
        tender_id: tenderA,
        status: "succeeded",
        started_at: "2026-04-19T11:00:00Z",
        completed_at: "2026-04-19T12:00:00Z",
        archived_at: "2026-04-20T12:30:00Z",
        bid_decisions: [
          {
            created_at: "2026-04-19T12:00:00Z",
            verdict: "bid",
            confidence: 0.7,
            final_decision: { cited_memo: "Hidden rationale." },
          },
        ],
      },
    });

    expect(bid.decision).toBeUndefined();
  });
});

describe("summarizeBidPipeline", () => {
  it("uses each bid's own estimated hours for pipeline value", () => {
    const summary = summarizeBidPipeline([
      {
        id: "bid-1",
        procurementId: tenderA,
        procurementName: "A",
        rateSEK: 1000,
        marginPct: 12,
        hoursEstimated: 100,
        status: "draft",
        notes: "",
        updatedAt: "2026-04-19T13:00:00Z",
      },
      {
        id: "bid-2",
        procurementId: tenderB,
        procurementName: "B",
        rateSEK: 2000,
        marginPct: 10,
        hoursEstimated: 50,
        status: "lost",
        notes: "",
        updatedAt: "2026-04-19T13:00:00Z",
      },
      {
        id: "bid-3",
        procurementId: tenderB,
        procurementName: "B",
        rateSEK: 1500,
        marginPct: 10,
        hoursEstimated: 200,
        status: "submitted",
        notes: "",
        updatedAt: "2026-04-19T13:00:00Z",
      },
    ]);

    expect(summary.pipelineSEK).toBe(400000);
    expect(summary.pipelineMSEK).toBe("0.4");
  });
});
