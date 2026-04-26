import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import BidDraft from "@/pages/BidDraft";
import { fetchLatestBidDraft, fetchRunDetail, generateBidDraft } from "@/lib/api";
import type { BidResponseDraft, Run } from "@/data/mock";

vi.mock("@/lib/api", () => ({
  fetchLatestBidDraft: vi.fn(),
  fetchRunDetail: vi.fn(),
  generateBidDraft: vi.fn(),
}));

const run: Run = {
  id: "run-1",
  tenderId: "tender-1",
  tenderName: "Identity Platform",
  company: "Acme IT",
  startedAt: "2026-04-23T08:00:00Z",
  completedAt: "2026-04-23T08:10:00Z",
  durationSec: 600,
  status: "succeeded",
  stage: "Judge",
  decision: "CONDITIONAL_BID",
  confidence: 76,
  evidence: [],
  round1: [],
  round2: [],
  judge: undefined,
};

const draft: BidResponseDraft = {
  schemaVersion: "draft-v1",
  runId: "run-1",
  tenderId: "tender-1",
  language: "sv",
  status: "needs_review",
  verdict: "CONDITIONAL_BID",
  confidence: 76,
  pricing: {
    source: "bid_row",
    rateSEK: 1330,
    marginPct: 14,
    hoursEstimated: 800,
    totalValueSEK: 1_064_000,
  },
  answers: [
    {
      questionId: "TENDER-ISO",
      prompt: "ISO certificate required.",
      answer: "Bifoga ISO-certifikat.",
      status: "drafted",
      evidenceKeys: ["TENDER-ISO", "COMPANY-ISO"],
      requiredAttachmentTypes: ["certificate"],
    },
  ],
  attachments: [
    {
      filename: "iso.pdf",
      storagePath: "demo/company-kb/iso.pdf",
      attachmentType: "certificate",
      requiredByEvidenceKey: "TENDER-ISO",
      status: "attached",
      sourceEvidenceKeys: ["TENDER-ISO", "COMPANY-ISO"],
      publicUrl: "https://storage.example/iso.pdf",
    },
  ],
  missingInfo: ["Confirm project manager."],
  sourceEvidenceKeys: ["TENDER-ISO", "COMPANY-ISO"],
};

function renderDraft() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={["/drafts/run-1"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/drafts/:runId" element={<BidDraft />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BidDraft", () => {
  it("renders answers, price, missing info, and attached PDFs", async () => {
    vi.mocked(fetchRunDetail).mockResolvedValue(run);
    vi.mocked(fetchLatestBidDraft).mockResolvedValue(draft);
    vi.mocked(generateBidDraft).mockResolvedValue(draft);

    renderDraft();

    expect(await screen.findByText("Identity Platform")).toBeInTheDocument();
    expect(screen.getByText("ISO certificate required.")).toBeInTheDocument();
    expect(screen.getByText("Bifoga ISO-certifikat.")).toBeInTheDocument();
    const price = screen.getByText(/SEK\/h/);
    expect(price.textContent).toContain("330");
    expect(price).toBeInTheDocument();
    expect(screen.getByText("iso.pdf")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open PDF/i })).toHaveAttribute(
      "href",
      "https://storage.example/iso.pdf",
    );
    expect(screen.getByText("Confirm project manager.")).toBeInTheDocument();
  });
});
