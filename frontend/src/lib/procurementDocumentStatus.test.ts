import { describe, expect, it } from "vitest";

import { summarizeProcurementDocuments } from "./procurementDocumentStatus";

const pendingDocument = {
  originalFilename: "skatteverket-cloud-migration-2026.pdf",
  parseStatus: "pending" as const,
  parseNote: null,
};

describe("summarizeProcurementDocuments", () => {
  it("does not show parsing when the latest run has already reached specialist work", () => {
    const summary = summarizeProcurementDocuments([pendingDocument], {
      status: "running",
      stage: "Round 1: Specialist Motions",
      isStale: true,
    });

    expect(summary.statusLabel).toBe("parsed");
    expect(summary.hasIssues).toBe(false);
    expect(summary.documents[0].parseStatus).toBe("parsed");
  });

  it("keeps parsing visible before a run has passed document parsing", () => {
    const summary = summarizeProcurementDocuments([pendingDocument], {
      status: "running",
      stage: "preflight",
      isStale: false,
    });

    expect(summary.statusLabel).toBe("parsing...");
    expect(summary.hasIssues).toBe(true);
    expect(summary.documents[0].parseStatus).toBe("pending");
  });

  it("keeps parser failures visible even when a run exists", () => {
    const summary = summarizeProcurementDocuments(
      [
        {
          originalFilename: "broken.pdf",
          parseStatus: "parser_failed",
          parseNote: "empty PDF text",
        },
      ],
      {
        status: "failed",
        stage: "Round 1: Specialist Motions",
        isStale: false,
      },
    );

    expect(summary.statusLabel).toBe("1 failed");
    expect(summary.hasIssues).toBe(true);
    expect(summary.documents[0].parseStatus).toBe("parser_failed");
  });
});
