import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import RunDetail from "@/pages/RunDetail";
import { fetchRunDetail, type RunDetail as RunDetailModel } from "@/lib/api";
import type { Evidence } from "@/data/mock";

vi.mock("@/lib/api", () => ({
  archiveAgentRun: vi.fn(),
  fetchRunDetail: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  usePermissions: () => ({
    canDeleteRuns: true,
  }),
}));

const run: RunDetailModel = {
  id: "run-123",
  runNumber: 2,
  tenderId: "tender-123",
  tenderName: "City CRM Procurement",
  company: "Acme IT Consulting AB",
  startedAt: "2026-04-19T08:00:00Z",
  completedAt: "2026-04-19T08:10:00Z",
  durationSec: 600,
  status: "succeeded",
  isStale: false,
  isArchived: false,
  staleAgeMinutes: null,
  stage: "Judge",
  decision: "BID",
  confidence: 82,
  documents: [
    {
      originalFilename: "city-crm-main.pdf",
      parseStatus: "parsed",
      parseNote: null,
      publicUrl: "https://example.supabase.co/storage/v1/object/public/public-procurements/city-crm-main.pdf",
    },
    {
      originalFilename: "city-crm-appendix.pdf",
      parseStatus: "parsed",
      parseNote: null,
      publicUrl: "https://example.supabase.co/storage/v1/object/public/public-procurements/city-crm-appendix.pdf",
    },
  ],
  evidence: [],
  round1: [],
  round2: [],
  judge: null,
};

const evidenceItem: Evidence = {
  id: "EVD-001",
  key: "TENDER.MANDATORY.ISO27001",
  category: "Mandatory Requirements",
  excerpt: "ISO certificate must be attached.",
  source: "police-modernisation.pdf",
  page: 11,
  referencedBy: ["Compliance Officer"],
  kind: "tender_document",
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
    expect(screen.getByRole("heading", { name: /^Run \d+$/i })).toBeInTheDocument();
    expect(screen.queryByText(/run-123/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Run metadata")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Evidence Board/i })).toHaveAttribute(
      "href",
      "/runs/run-123/evidence",
    );
    expect(screen.getByText("Submitted files")).toBeInTheDocument();
    expect(
      screen.queryByText("The tender documents linked to this run."),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open city-crm-main.pdf" })).toHaveAttribute(
      "href",
      "https://example.supabase.co/storage/v1/object/public/public-procurements/city-crm-main.pdf",
    );
    expect(screen.getByRole("link", { name: "Download city-crm-main.pdf" })).toHaveAttribute(
      "href",
      "https://example.supabase.co/storage/v1/object/public/public-procurements/city-crm-main.pdf",
    );
    expect(screen.getByRole("link", { name: "Open city-crm-appendix.pdf" })).toHaveAttribute(
      "href",
      "https://example.supabase.co/storage/v1/object/public/public-procurements/city-crm-appendix.pdf",
    );
    expect(screen.getAllByLabelText("Parsed")).toHaveLength(2);
    expect(screen.queryByText("Parsed")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Re-run/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Export/i })).toBeInTheDocument();
  });

  it("opens cited evidence in a source sidebar", async () => {
    vi.mocked(fetchRunDetail).mockResolvedValue({
      ...run,
      evidence: [evidenceItem],
      judge: {
        verdict: "BID",
        confidence: 82,
        voteSummary: { BID: 4, NO_BID: 0, CONDITIONAL_BID: 0 },
        disagreement: "",
        citedMemo: "Bid because EVD-001 is satisfied.",
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
        evidenceIds: ["EVD-404"],
      },
    });

    renderRunDetail();

    const citationButtons = await screen.findAllByRole("button", {
      name: "Open source for EVD-001",
    });
    fireEvent.click(citationButtons[0]);

    const sidebar = await screen.findByRole("dialog", { name: "Citation source" });
    expect(within(sidebar).getByText(/ISO certificate must be attached/)).toBeInTheDocument();
    expect(within(sidebar).getByText("police-modernisation.pdf")).toBeInTheDocument();
    expect(within(sidebar).getByText("Page 11")).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: "Open Evidence Board" })).toHaveAttribute(
      "href",
      "/runs/run-123/evidence",
    );
  });

  it("shows an explicit missing-source state for citations outside the evidence board", async () => {
    vi.mocked(fetchRunDetail).mockResolvedValue({
      ...run,
      evidence: [evidenceItem],
      judge: {
        verdict: "BID",
        confidence: 82,
        voteSummary: { BID: 4, NO_BID: 0, CONDITIONAL_BID: 0 },
        disagreement: "",
        citedMemo: "Bid.",
        complianceMatrix: [],
        complianceBlockers: [],
        potentialBlockers: [],
        riskRegister: [],
        missingInfo: [],
        recommendedActions: [],
        evidenceIds: ["EVD-404"],
      },
    });

    renderRunDetail();

    fireEvent.click(await screen.findByText("Cited Evidence"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open source for EVD-404" }),
    );

    const sidebar = await screen.findByRole("dialog", { name: "Citation source" });
    expect(
      within(sidebar).getByText("Source not found in this run's evidence board."),
    ).toBeInTheDocument();
    expect(within(sidebar).getByText("EVD-404")).toBeInTheDocument();
  });

  it("hides judge disagreement when it repeats the verdict memo", async () => {
    vi.mocked(fetchRunDetail).mockResolvedValue({
      ...run,
      judge: {
        verdict: "CONDITIONAL_BID",
        confidence: 82,
        voteSummary: { BID: 1, NO_BID: 0, CONDITIONAL_BID: 3 },
        disagreement: "All four agents unanimously recommend CONDITIONAL_BID.",
        citedMemo: "All four agents unanimously recommend conditional bid.",
        complianceMatrix: [],
        complianceBlockers: [],
        potentialBlockers: [],
        riskRegister: [],
        missingInfo: [],
        recommendedActions: [],
        evidenceIds: [],
      },
    });

    renderRunDetail();

    expect(await screen.findByText("Final verdict")).toBeInTheDocument();
    expect(screen.queryByText("Disagreement")).not.toBeInTheDocument();
  });
});
