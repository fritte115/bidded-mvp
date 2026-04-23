import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import Procurements from "@/pages/Procurements";
import { deleteProcurement, fetchProcurements, startAgentRun } from "@/lib/api";
import type { ProcurementRow } from "@/lib/api";
import { TooltipProvider } from "@/components/ui/tooltip";

vi.mock("@/lib/api", () => ({
  deleteProcurement: vi.fn(),
  fetchProcurements: vi.fn(),
  startAgentRun: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  usePermissions: () => ({
    canStartRuns: true,
    canRegisterProcurements: true,
    canDeleteProcurements: true,
  }),
}));

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
];

function renderProcurements() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Procurements />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("Procurements", () => {
  it("shows sequential run labels and compact status dots", async () => {
    vi.mocked(fetchProcurements).mockResolvedValue(rows);
    vi.mocked(startAgentRun).mockResolvedValue("run-99");
    vi.mocked(deleteProcurement).mockResolvedValue();

    renderProcurements();

    expect(await screen.findByText("Run 2")).toBeInTheDocument();
    expect(screen.getByText("Run 3")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Status" })).not.toBeInTheDocument();
    expect(screen.queryByText("Parsed")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Succeeded").querySelector(".bg-success")).not.toBeNull();
    expect(screen.getByLabelText("Failed").querySelector(".bg-danger")).not.toBeNull();
    expect(screen.getByText("Healthcare Platform").closest("td")).toContainElement(
      screen.getByLabelText("Succeeded"),
    );
  });
});
