import { describe, expect, it } from "vitest";

import { buildRunNumberMap, runDisplayId } from "./mock";

describe("buildRunNumberMap", () => {
  it("assigns ascending run numbers per procurement", () => {
    const runNumbers = buildRunNumberMap([
      {
        id: "run-a2",
        tenderId: "tender-a",
        startedAt: "2026-04-23T10:00:00Z",
        createdAt: "2026-04-23T09:59:00Z",
      },
      {
        id: "run-a1",
        tenderId: "tender-a",
        startedAt: "2026-04-23T08:00:00Z",
        createdAt: "2026-04-23T07:59:00Z",
      },
      {
        id: "run-b1",
        tenderId: "tender-b",
        startedAt: "2026-04-23T09:00:00Z",
        createdAt: "2026-04-23T08:59:00Z",
      },
    ]);

    expect(runNumbers.get("run-a1")).toBe(1);
    expect(runNumbers.get("run-a2")).toBe(2);
    expect(runNumbers.get("run-b1")).toBe(1);
  });
});

describe("runDisplayId", () => {
  it("uses the computed per-procurement run number when available", () => {
    expect(runDisplayId({ id: "run-a2", runNumber: 2 })).toBe("Run 2");
  });
});
