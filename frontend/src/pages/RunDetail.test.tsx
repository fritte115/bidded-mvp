import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import RunDetail from "@/pages/RunDetail";
import { fetchRunDetail, type RunDetail as RunDetailModel } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchRunDetail: vi.fn(),
}));

const run: RunDetailModel = {
  id: "run-123",
  tenderId: "tender-123",
  tenderName: "City CRM Procurement",
  company: "Acme IT Consulting AB",
  startedAt: "2026-04-19T08:00:00Z",
  completedAt: "2026-04-19T08:10:00Z",
  durationSec: 600,
  status: "succeeded",
  isStale: false,
  staleAgeMinutes: null,
  stage: "Judge",
  decision: "BID",
  confidence: 82,
  evidence: [],
  round1: [],
  round2: [],
  judge: null,
};

function renderRunDetail() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={["/runs/run-123"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/runs/:id" element={<RunDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RunDetail", () => {
  it("uses header actions instead of the run metadata sidebar card", async () => {
    vi.mocked(fetchRunDetail).mockResolvedValue(run);

    renderRunDetail();

    expect(await screen.findByText("City CRM Procurement")).toBeInTheDocument();
    expect(screen.queryByText("Run metadata")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Evidence Board/i })).toHaveAttribute(
      "href",
      "/runs/run-123/evidence",
    );
    expect(screen.getByRole("button", { name: /Re-run/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Export/i })).toBeInTheDocument();
  });
});
