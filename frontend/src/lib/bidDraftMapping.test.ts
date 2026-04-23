import { describe, expect, it } from "vitest";

import { mapBidDraftPayload } from "./bidDraftMapping";

describe("mapBidDraftPayload", () => {
  it("maps evidence-locked answers, pricing, and attachment links", () => {
    const draft = mapBidDraftPayload(
      {
        schema_version: "draft-v1",
        run_id: "run-1",
        tender_id: "tender-1",
        language: "sv",
        status: "needs_review",
        verdict: "conditional_bid",
        confidence: 0.76,
        pricing: {
          source: "bid_row",
          rate_sek: "1330",
          margin_pct: "14",
          hours_estimated: 800,
          total_value_sek: 1_064_000,
        },
        answers: [
          {
            question_id: "TENDER-ISO",
            prompt: "ISO certificate required.",
            answer: "Bifoga ISO-certifikat.",
            status: "drafted",
            evidence_keys: ["TENDER-ISO", "COMPANY-ISO"],
            required_attachment_types: ["certificate"],
          },
        ],
        attachments: [
          {
            filename: "iso.pdf",
            storage_path: "demo/company-kb/iso.pdf",
            checksum_sha256: "abc",
            attachment_type: "certificate",
            required_by_evidence_key: "TENDER-ISO",
            status: "attached",
            source_evidence_keys: ["TENDER-ISO", "COMPANY-ISO"],
          },
        ],
        missing_info: ["Confirm project manager."],
        source_evidence_keys: ["TENDER-ISO", "COMPANY-ISO"],
      },
      (path) => `https://storage.example/${path}`,
    );

    expect(draft).toMatchObject({
      runId: "run-1",
      tenderId: "tender-1",
      verdict: "CONDITIONAL_BID",
      confidence: 76,
      pricing: {
        source: "bid_row",
        rateSEK: 1330,
        totalValueSEK: 1_064_000,
      },
      answers: [
        {
          questionId: "TENDER-ISO",
          status: "drafted",
          evidenceKeys: ["TENDER-ISO", "COMPANY-ISO"],
        },
      ],
      attachments: [
        {
          filename: "iso.pdf",
          status: "attached",
          publicUrl: "https://storage.example/demo/company-kb/iso.pdf",
        },
      ],
    });
  });
});
