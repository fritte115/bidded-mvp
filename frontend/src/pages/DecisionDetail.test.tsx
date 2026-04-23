import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import DecisionDetail from "@/pages/DecisionDetail";
import { fetchRunDetail, type RunDetail } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchRunDetail: vi.fn(),
}));

const run: RunDetail = {
  id: "run-123",
  runNumber: 3,
  tenderId: "tender-123",
  tenderName: "Healthcare Platform",
  company: "Acme IT Consulting AB",
  startedAt: "2026-04-23T08:00:00Z",
  completedAt: "2026-04-23T08:10:00Z",
  durationSec: 600,
  status: "succeeded",
  isStale: false,
  isArchived: false,
  staleAgeMinutes: null,
  stage: "Judge",
  decision: "CONDITIONAL_BID",
  confidence: 82,
  documents: [],
  evidence: [
    {
      id: "EVD-001",
      key: "TENDER.MANDATORY.ISO27001",
      category: "Mandatory Requirements",
      excerpt: "ISO certificate must be attached.",
      source: "police-modernisation.pdf",
      page: 11,
      referencedBy: ["Compliance Officer"],
      kind: "tender_document",
    },
  ],
  round1: [],
  round2: [],
  judge: {
    verdict: "CONDITIONAL_BID",
    confidence: 82,
    voteSummary: { BID: 1, NO_BID: 0, CONDITIONAL_BID: 3 },
    disagreement: "",
    citedMemo: "Conditional bid.",
    complianceMatrix: [
      {
        requirement: "ISO 27001 certificate",
        status: "Met",
        evidence: ["EVD-001"],
      },
    ],
    complianceBlockers: [],
    potentialBlockers: [],
    riskRegister: [],
    missingInfo: [],
    recommendedActions: [],
    evidenceIds: ["EVD-001"],
  },
};

function renderDecisionDetail() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={["/decisions/run-123"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/decisions/:id" element={<DecisionDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DecisionDetail", () => {
  it("keeps evidence in the compliance matrix without a separate cited-evidence card", async () => {
    vi.mocked(fetchRunDetail).mockResolvedValue(run);

    renderDecisionDetail();

    expect(await screen.findByText("ISO 27001 certificate")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open source for EVD-001" })).toBeInTheDocument();
    expect(screen.queryByText("Cited Evidence")).not.toBeInTheDocument();
  });
});
