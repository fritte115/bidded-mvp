import { describe, expect, it } from "vitest";
import {
  mapRound1Output,
  mapRound2Output,
  keysFromEvidenceRefs,
  normalizeVoteToVerdict,
} from "./agentOutputMapping";

describe("keysFromEvidenceRefs", () => {
  it("collects evidence_key from API-shaped refs", () => {
    expect(
      keysFromEvidenceRefs([
        { evidence_key: "EVD-1", source_type: "tender_document", evidence_id: "uuid" },
      ]),
    ).toEqual(["EVD-1"]);
  });
});

describe("normalizeVoteToVerdict", () => {
  it("maps conditional_bid to CONDITIONAL_BID", () => {
    expect(normalizeVoteToVerdict("conditional_bid")).toBe("CONDITIONAL_BID");
  });
});

describe("mapRound1Output", () => {
  it("maps Round1Motion (vote + top_findings with evidence_refs)", () => {
    const m = mapRound1Output({
      agent_role: "compliance_officer",
      vote: "bid",
      confidence: 0.81,
      top_findings: [
        {
          claim: "Deadline is feasible.",
          evidence_refs: [{ evidence_key: "EVD-01", source_type: "tender_document" }],
        },
      ],
      role_specific_risks: [],
      formal_blockers: [],
      potential_blockers: [],
    });
    expect(m?.verdict).toBe("BID");
    expect(m?.confidence).toBe(81);
    expect(m?.findings[0]).toBe("Deadline is feasible.");
    expect(m?.findingsWithEvidence?.[0].evidenceKeys).toEqual(["EVD-01"]);
  });

  it("maps SpecialistMotionState (verdict + findings + evidence_refs)", () => {
    const m = mapRound1Output({
      agent_role: "win_strategist",
      verdict: "conditional_bid",
      confidence: 0.72,
      summary: "Shell motion",
      evidence_refs: [{ evidence_key: "EVD-X", source_type: "tender_document" }],
      findings: ["The evidence board is available for specialist review."],
      risks: [],
      blockers: [],
    });
    expect(m?.verdict).toBe("CONDITIONAL_BID");
    expect(m?.confidence).toBe(72);
    expect(m?.findings[0]).toBe("The evidence board is available for specialist review.");
    expect(m?.findingsWithEvidence?.[0].evidenceKeys).toEqual(["EVD-X"]);
  });

  it("formats delivery_cfo with the UI label", () => {
    const m = mapRound1Output({
      agent_role: "delivery_cfo",
      verdict: "conditional_bid",
      confidence: 0.72,
      summary: "Margin assumptions need review.",
      evidence_refs: [{ evidence_key: "EVD-CFO", source_type: "tender_document" }],
      findings: ["Delivery review is needed."],
      risks: [],
      blockers: [],
    });

    expect(m?.agent).toBe("Delivery CFO");
  });
});

describe("mapRound2Output", () => {
  it("maps Round2Rebuttal (target_roles + targeted_disagreements)", () => {
    const prior = new Map([
      [
        "compliance_officer",
        {
          agent: "Compliance Officer",
          verdict: "BID" as const,
          confidence: 80,
          findings: [],
        },
      ],
    ]);
    const m = mapRound2Output(
      {
        agent_role: "compliance_officer",
        target_roles: ["win_strategist"],
        targeted_disagreements: [
          {
            target_role: "win_strategist",
            disputed_claim: "Price is too low",
            rebuttal: "We can meet evaluation criteria.",
            evidence_refs: [{ evidence_key: "EVD-2", source_type: "tender_document" }],
          },
        ],
        revised_stance: "conditional_bid",
        confidence: 0.62,
      },
      prior,
    );
    expect(m?.verdict).toBe("CONDITIONAL_BID");
    expect(m?.confidence).toBe(62);
    expect(m?.findings[0]).toBe("We can meet evaluation criteria.");
    expect(m?.findingsWithEvidence?.[0].evidenceKeys).toEqual(["EVD-2"]);
    expect(m?.rebuttalFocus).toEqual(["Win Strategist"]);
  });

  it("maps RebuttalState (summary + challenged_claims)", () => {
    const prior = new Map([
      [
        "red_team",
        {
          agent: "Red Team",
          verdict: "BID" as const,
          confidence: 72,
          findings: [],
        },
      ],
    ]);
    const m = mapRound2Output(
      {
        agent_role: "red_team",
        target_motion_role: "win_strategist",
        summary: "Placeholder rebuttal from the routing shell.",
        challenged_claims: [],
        accepted_claims: ["Round 1 artifacts were available for rebuttal."],
        evidence_refs: [{ evidence_key: "EVD-9", source_type: "tender_document" }],
      },
      prior,
    );
    expect(m?.findings[0]).toContain("Placeholder rebuttal");
    expect(m?.findings.some((f) => f.includes("Accepted:"))).toBe(true);
    expect(m?.findingsWithEvidence?.every((f) => f.evidenceKeys.includes("EVD-9"))).toBe(
      true,
    );
    expect(m?.rebuttalFocus).toEqual(["Win Strategist"]);
  });
});
