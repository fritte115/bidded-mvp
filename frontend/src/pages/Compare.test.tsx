import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { DecisionSummary } from "@/data/mock";
import { fetchCompareRows } from "@/lib/api";
import Compare from "@/pages/Compare";

vi.mock("@/lib/api", () => ({
  fetchCompareRows: vi.fn(),
}));

vi.mock("@/components/BidRecommendation", () => ({
  BidRecommendation: ({ heading }: { heading?: string }) => (
    <div data-testid="bid-recommendation">{heading}</div>
  ),
}));

const rows: DecisionSummary[] = [
  {
    runId: "run-1",
    tenderId: "tender-1",
    tenderName: "Healthcare Platform",
    uploadedAt: "2026-04-23T08:00:00Z",
    documentCount: 3,
    verdict: "NO_BID",
    confidence: 88,
    citedMemo: "Do not bid.",
    topReason: "Insufficient healthcare delivery evidence for this scope.",
    startedAt: "2026-04-23T08:00:00Z",
    completedAt: "2026-04-23T08:12:00Z",
    riskScore: "High",
    riskCount: 2,
    complianceBlockerCount: 1,
    potentialBlockerCount: 0,
    recommendedActions: [],
    missingInfo: [],
    isDraftable: false,
  },
];

function renderCompare() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Compare />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Compare", () => {
  it("omits the redundant risk column from the comparison table", async () => {
    vi.mocked(fetchCompareRows).mockResolvedValue(rows);

    renderCompare();

    expect(await screen.findByRole("link", { name: "Open run" })).toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "Risk" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("High")).not.toBeInTheDocument();
  });
});
