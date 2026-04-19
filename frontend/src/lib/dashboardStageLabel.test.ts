import { describe, expect, it } from "vitest";
import {
  dashboardStageLabel,
  resolveMetadataCurrentStep,
} from "./api";

describe("resolveMetadataCurrentStep", () => {
  it("reads top-level current_step", () => {
    expect(resolveMetadataCurrentStep({ current_step: "evidence_scout" })).toBe(
      "evidence_scout",
    );
  });

  it("reads worker.current_step when top-level is missing", () => {
    expect(
      resolveMetadataCurrentStep({
        worker: { current_step: "judge", name: "bidded-worker" },
      }),
    ).toBe("judge");
  });

  it("returns null when absent", () => {
    expect(resolveMetadataCurrentStep({ created_via: "api" })).toBeNull();
    expect(resolveMetadataCurrentStep(null)).toBeNull();
  });
});

describe("dashboardStageLabel", () => {
  it("maps known step via stageDisplayName", () => {
    expect(
      dashboardStageLabel("running", { current_step: "preflight" }),
    ).toBe("Evidence Scout");
  });

  it("shows Finished for terminal runs without current_step", () => {
    expect(dashboardStageLabel("succeeded", {})).toBe("Finished");
    expect(dashboardStageLabel("failed", { created_via: "test" })).toBe("Finished");
    expect(dashboardStageLabel("needs_human_review", null)).toBe("Finished");
  });

  it("shows Running when in flight without step", () => {
    expect(dashboardStageLabel("running", {})).toBe("Running");
  });

  it("shows Pending when queued without step", () => {
    expect(dashboardStageLabel("pending", {})).toBe("Pending");
  });
});
