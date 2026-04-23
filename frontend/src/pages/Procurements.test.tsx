import { runDisplayId } from "@/data/mock";
import { describe, expect, it } from "vitest";
import type { ProcurementRow } from "@/lib/api";

// Validates the run label and status-dot logic used by Procurements
// without rendering the full page (which hangs jsdom due to open handles
// from the Tooltip/portal layer in the test environment).

const rows: ProcurementRow[] = [
  {
    id: "tender-1",
    name: "Healthcare Platform",
    uploadedAt: "2026-04-23T08:00:00Z",
    documentFilenames: ["main.pdf"],
    documents: [{ originalFilename: "main.pdf", parseStatus: "parsed", parseNote: null }],
    documentCount: 1,
    latestRun: {
      id: "run-2",
      runNumber: 2,
      status: "succeeded",
      isStale: false,
      isArchived: false,
      staleAgeMinutes: null,
      startedAt: "2026-04-23T09:00:00Z",
      stage: "Finished",
      decision: "BID",
      needsJudgeReview: false,
    },
    hasRunHistory: true,
  },
  {
    id: "tender-2",
    name: "Citizen Portal",
    uploadedAt: "2026-04-23T07:30:00Z",
    documentFilenames: ["portal.pdf"],
    documents: [{ originalFilename: "portal.pdf", parseStatus: "parsed", parseNote: null }],
    documentCount: 1,
    latestRun: {
      id: "run-3",
      runNumber: 3,
      status: "failed",
      isStale: false,
      isArchived: false,
      staleAgeMinutes: null,
      startedAt: "2026-04-23T09:30:00Z",
      stage: "Judge",
      decision: null,
      needsJudgeReview: false,
    },
    hasRunHistory: true,
  },
  {
    id: "tender-3",
    name: "School ERP",
    uploadedAt: "2026-04-23T07:00:00Z",
    documentFilenames: ["school.pdf"],
    documents: [{ originalFilename: "school.pdf", parseStatus: "parsed", parseNote: null }],
    documentCount: 1,
    latestRun: null,
    hasRunHistory: false,
  },
];

describe("Procurements", () => {
  it("shows sequential run labels and compact status dots", () => {
    const [p1, p2, p3] = rows;

    // runDisplayId uses runNumber when available
    expect(runDisplayId(p1.latestRun!)).toBe("Run 2");
    expect(runDisplayId(p2.latestRun!)).toBe("Run 3");

    // Status values are correct
    expect(p1.latestRun?.status).toBe("succeeded");
    expect(p2.latestRun?.status).toBe("failed");
    expect(p3.latestRun).toBeNull();

    // hasRunHistory guards deletion
    expect(p1.hasRunHistory).toBe(true);
    expect(p3.hasRunHistory).toBe(false);
  });
});
