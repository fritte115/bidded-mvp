import { describe, expect, it } from "vitest";

import { company } from "./mock";

describe("mock company profile", () => {
  it("uses Impact Solution public financial metrics instead of old consultancy placeholders", () => {
    expect(company.name).toBe("Impact Solution Scandinavia AB");
    expect(company.orgNumber).toBe("556925-0516");
    expect(company.headcount).toBe(7);
    expect(company.financialAssumptions.revenueRange).toBe(
      "12.970–24.901 MSEK / year (2020–2024)",
    );
    expect(company.financials).toEqual([
      { year: 2020, revenueMSEK: 12.970, ebitMarginPct: 13.4, headcount: 1 },
      { year: 2021, revenueMSEK: 18.376, ebitMarginPct: 13.2, headcount: 3 },
      { year: 2022, revenueMSEK: 20.093, ebitMarginPct: -4.1, headcount: 5 },
      { year: 2023, revenueMSEK: 22.112, ebitMarginPct: -2.1, headcount: 6 },
      { year: 2024, revenueMSEK: 24.901, ebitMarginPct: 0.1, headcount: 7 },
    ]);
  });
});
