import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import Bids from "@/pages/Bids";
import {
  fetchBids,
  fetchCompany,
  fetchProcurements,
  updateBidStatus,
} from "@/lib/api";
import type { Bid } from "@/data/mock";

vi.mock("@/lib/api", () => ({
  fetchBids: vi.fn(),
  fetchCompany: vi.fn(),
  fetchProcurements: vi.fn(),
  updateBidStatus: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

const draftBid: Bid = {
  id: "bid-123",
  procurementId: "tender-123",
  procurementName: "City CRM Procurement",
  rateSEK: 1250,
  marginPct: 12,
  hoursEstimated: 400,
  status: "draft",
  notes: "Ready for review.",
  updatedAt: "2026-04-17T14:05:00Z",
};

function renderBids() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Bids />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function createDataTransfer() {
  const store = new Map<string, string>();
  return {
    dropEffect: "move",
    effectAllowed: "move",
    getData: vi.fn((type: string) => store.get(type) ?? ""),
    setData: vi.fn((type: string, value: string) => {
      store.set(type, value);
    }),
  };
}

describe("Bids", () => {
  it("moves a bid when the card is dropped onto another status column", async () => {
    vi.mocked(fetchBids).mockResolvedValue([draftBid]);
    vi.mocked(fetchProcurements).mockResolvedValue([]);
    vi.mocked(fetchCompany).mockResolvedValue(null);
    vi.mocked(updateBidStatus).mockResolvedValue();

    renderBids();

    const card = await screen.findByRole("article", { name: /Bid City CRM Procurement/i });
    const reviewColumn = screen.getByRole("region", { name: /Review bids/i });
    const dataTransfer = createDataTransfer();

    fireEvent.dragStart(card, { dataTransfer });
    fireEvent.dragOver(reviewColumn, { dataTransfer });
    fireEvent.drop(reviewColumn, { dataTransfer });

    await waitFor(() => {
      expect(updateBidStatus).toHaveBeenCalledWith("bid-123", "review");
    });
  });
});
