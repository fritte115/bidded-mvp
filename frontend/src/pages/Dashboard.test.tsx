import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import Dashboard from "@/pages/Dashboard";
import {
  fetchActiveRuns,
  fetchDashboardStats,
  fetchDecisions,
  type DecisionRow,
} from "@/lib/api";

vi.mock("@/lib/api", () => ({
  archiveAgentRun: vi.fn(),
  deleteAgentRun: vi.fn(),
  fetchActiveRuns: vi.fn(),
  fetchDashboardStats: vi.fn(),
  fetchDecisions: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  usePermissions: () => ({
    canDeleteRuns: true,
  }),
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
  {
    id: "run-2",
    runId: "run-2",
    tenderId: "tender-2",
    tenderName: "Municipal App",
    uploadedAt: "2026-04-22T08:00:00Z",
    documentCount: 1,
    verdict: "BID",
    confidence: 91,
    citedMemo: "Strong match.",
    topReason: "Strong match.",
    startedAt: "2026-04-22T08:00:00Z",
    completedAt: "2026-04-22T08:12:00Z",
    riskScore: "Low",
    riskCount: 0,
    complianceBlockerCount: 0,
    potentialBlockerCount: 0,
    recommendedActions: [],
    missingInfo: [],
    isDraftable: true,
    status: "succeeded",
  },
  {
    id: "run-3",
    runId: "run-3",
    tenderId: "tender-3",
    tenderName: "Analytics Hub",
    uploadedAt: "2026-04-21T08:00:00Z",
    documentCount: 1,
    verdict: "NO_BID",
    confidence: 74,
    citedMemo: "Formal blocker.",
    topReason: "Formal blocker.",
    startedAt: "2026-04-21T08:00:00Z",
    completedAt: "2026-04-21T08:10:00Z",
    riskScore: "High",
    riskCount: 3,
    complianceBlockerCount: 1,
    potentialBlockerCount: 0,
    recommendedActions: [],
    missingInfo: [],
    isDraftable: false,
    status: "succeeded",
  },
  {
    id: "run-4",
    runId: "run-4",
    tenderId: "tender-4",
    tenderName: "Legacy CRM Migration",
    uploadedAt: "2026-04-20T08:00:00Z",
    documentCount: 3,
    verdict: "CONDITIONAL_BID",
    confidence: 68,
    citedMemo:
      "Delivery risk is manageable if staffing is confirmed. Long memo detail should stay out of the compact dashboard preview.",
    topReason: "Delivery risk is manageable if staffing is confirmed.",
    startedAt: "2026-04-20T08:00:00Z",
    completedAt: "2026-04-20T08:20:00Z",
    riskScore: "Medium",
    riskCount: 2,
    complianceBlockerCount: 0,
    potentialBlockerCount: 1,
    recommendedActions: [],
    missingInfo: [],
    isDraftable: true,
    status: "succeeded",
  },
];

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Dashboard", () => {
  it("puts the full decisions list in an inline dropdown below Latest Verdicts", async () => {
    vi.mocked(fetchDashboardStats).mockResolvedValue({
      totalProcurements: 4,
      totalPdfDocuments: 7,
      activeRuns: 0,
    });
    vi.mocked(fetchActiveRuns).mockResolvedValue([]);
    vi.mocked(fetchDecisions).mockResolvedValue(rows);

    renderDashboard();

    expect(await screen.findByRole("heading", { name: /latest verdicts/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /view all decisions/i })).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: /all decisions/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText(/all decisions list/i)).not.toBeInTheDocument();

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const list = await screen.findByLabelText(/all decisions list/i);
    expect(within(list).getByText("Legacy CRM Migration")).toBeInTheDocument();
    expect(within(list).getByText(rows[3].topReason)).toBeInTheDocument();
    expect(
      within(list).queryByText(/Long memo detail should stay out/i),
    ).not.toBeInTheDocument();
  });
});
