import { describe, expect, it } from "vitest";

import { isDuplicateJudgeDisagreement } from "./judgeMemo";

describe("isDuplicateJudgeDisagreement", () => {
  it("treats equivalent memo and disagreement text as duplicates", () => {
    expect(
      isDuplicateJudgeDisagreement(
        "All four agents unanimously recommend conditional bid, but diverge sharply on the severity of key blockers.",
        "All four agents unanimously recommend CONDITIONAL_BID, but diverge sharply on the severity of key blockers.",
      ),
    ).toBe(true);
  });

  it("keeps disagreement when it adds distinct information", () => {
    expect(
      isDuplicateJudgeDisagreement(
        "Residual disagreement remains on staffing risk.",
        "All four agents unanimously recommend conditional bid.",
      ),
    ).toBe(false);
  });
});
