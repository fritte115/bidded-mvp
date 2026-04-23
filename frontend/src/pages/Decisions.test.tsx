import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import Decisions from "@/pages/Decisions";
import { fetchDecisions, type DecisionRow } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchDecisions: vi.fn(),
}));

const rows: DecisionRow[] = [
  {
    id: "run-1",
    runId: "run-1",
    tenderId: "tender-1",
    tenderName: "Healthcare Platform",
    uploadedAt: "2026-04-23T08:00:00Z",
    documentCount: 2,
    verdict: "CONDITIONAL_BID",
    confidence: 82,
    citedMemo:
      "All four agents unanimously recommend conditional bid, but diverge sharply on the severity of key blockers. Have Delivery CFO validate margin assumptions before submission.",
    topReason:
      "All four agents unanimously recommend conditional bid, but diverge sharply on the severity of key blockers.",
    startedAt: "2026-04-23T08:00:00Z",
    completedAt: "2026-04-23T08:15:00Z",
    riskScore: "High",
    riskCount: 2,
    complianceBlockerCount: 1,
    potentialBlockerCount: 1,
    recommendedActions: [],
    missingInfo: [],
    isDraftable: true,
    status: "succeeded",
  },
];

function renderDecisions() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Decisions />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Decisions", () => {
  it("uses the short top reason in the preview card", async () => {
    vi.mocked(fetchDecisions).mockResolvedValue(rows);

    renderDecisions();

    expect(await screen.findByText(rows[0].topReason)).toBeInTheDocument();
    expect(
      screen.queryByText(/Have Delivery CFO validate margin assumptions/i),
    ).not.toBeInTheDocument();
  });
});
