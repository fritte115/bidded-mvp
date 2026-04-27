import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { company as mockCompany } from "@/data/mock";
import {
  deleteCompanyKbDocument,
  fetchCompany,
  fetchCompanyKbDocuments,
  fetchCompanyKbEvidence,
  updateCompany,
  uploadCompanyKbDocuments,
} from "@/lib/api";
import CompanyProfile from "@/pages/CompanyProfile";

vi.mock("@/lib/api", () => ({
  deleteCompanyKbDocument: vi.fn(),
  fetchCompany: vi.fn(),
  fetchCompanyKbDocuments: vi.fn(),
  fetchCompanyKbEvidence: vi.fn(),
  updateCompany: vi.fn(),
  uploadCompanyKbDocuments: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  usePermissions: () => ({ canManageCompany: true }),
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

const kbDocument = {
  document_id: "doc-1",
  company_id: "company-1",
  original_filename: "iso-cert.pdf",
  storage_path: "company/company-1/iso-cert.pdf",
  content_type: "application/pdf",
  parse_status: "parsed" as const,
  kb_document_type: "certification" as const,
  extraction_status: "extracted" as const,
  evidence_count: 2,
  warnings: [],
};

function renderCompanyProfile() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <CompanyProfile />
    </QueryClientProvider>,
  );
}

describe("CompanyProfile Knowledge Base", () => {
  beforeEach(() => {
    vi.mocked(fetchCompany).mockResolvedValue({
      company: mockCompany,
      raw: {
        id: "company-1",
        name: mockCompany.name,
        organization_number: mockCompany.orgNumber,
        headquarters_country: "SE",
        employee_count: 100,
        annual_revenue_sek: null,
        capabilities: { service_lines: {} },
        certifications: [],
        reference_projects: [],
        financial_assumptions: {},
        profile_details: {},
      },
    });
    vi.mocked(fetchCompanyKbDocuments).mockResolvedValue({
      documents: [kbDocument],
    });
    vi.mocked(fetchCompanyKbEvidence).mockResolvedValue({
      evidence: [
        {
          evidence_key: "COMPANY-KB-ISO",
          excerpt: "ISO 27001 certification is active.",
          category: "certification",
          confidence: 0.92,
        },
      ],
    });
    vi.mocked(uploadCompanyKbDocuments).mockResolvedValue({
      documents: [kbDocument],
    });
    vi.mocked(deleteCompanyKbDocument).mockResolvedValue();
    vi.mocked(updateCompany).mockResolvedValue();
  });

  it("does not duplicate the company name or stale review metadata in the identity header", async () => {
    renderCompanyProfile();

    expect(
      await screen.findByRole("heading", { name: mockCompany.name }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Last reviewed 2 weeks ago")).not.toBeInTheDocument();
    expect(screen.getAllByText(mockCompany.name)).toHaveLength(1);
  });

  it("renders KB document status, evidence preview, and delete action", async () => {
    renderCompanyProfile();

    fireEvent.mouseDown(await screen.findByRole("tab", { name: "Knowledge Base" }));
    const row = screen.getByText("iso-cert.pdf").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLTableRowElement).getByText("Certification"))
      .toBeInTheDocument();
    expect(within(row as HTMLTableRowElement).getByText("active"))
      .toBeInTheDocument();
    expect(within(row as HTMLTableRowElement).getByText("2")).toBeInTheDocument();

    fireEvent.click(
      within(row as HTMLTableRowElement).getByRole("button", { name: /Facts/i }),
    );
    expect(
      await screen.findByText("ISO 27001 certification is active."),
    ).toBeInTheDocument();
    expect(fetchCompanyKbEvidence).toHaveBeenCalledWith("doc-1");

    fireEvent.click(screen.getByRole("button", { name: /Delete iso-cert.pdf/i }));
    await waitFor(() =>
      expect(deleteCompanyKbDocument).toHaveBeenCalledWith("doc-1"),
    );
  });

  it("queues uploaded files with inferred per-file document types", async () => {
    vi.mocked(fetchCompanyKbDocuments).mockResolvedValue({ documents: [] });
    const { container } = renderCompanyProfile();

    fireEvent.mouseDown(await screen.findByRole("tab", { name: "Knowledge Base" }));
    expect(await screen.findByText("No company knowledge base files yet."))
      .toBeInTheDocument();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["ISO 27001"], "iso.txt", { type: "text/plain" });
    const referenceFile = new File(
      ["Reference assignment"],
      "Referensuppdrag.docx",
      { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" },
    );
    const capacityFile = new File(
      ["Capacity"],
      "1.5 Andra företags kapacitet.pdf",
      { type: "application/pdf" },
    );
    const creditFile = new File(
      ["UC riskklass 4"],
      "UC upphandlingsintyg.pdf",
      { type: "application/pdf" },
    );
    fireEvent.change(input, {
      target: { files: [file, referenceFile, capacityFile, creditFile] },
    });

    expect(await screen.findByText("iso.txt")).toBeInTheDocument();
    expect(await screen.findByText("Referensuppdrag.docx")).toBeInTheDocument();
    expect(await screen.findByText("1.5 Andra företags kapacitet.pdf"))
      .toBeInTheDocument();
    expect(await screen.findByText("UC upphandlingsintyg.pdf")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Upload to KB/i }));

    await waitFor(() =>
      expect(uploadCompanyKbDocuments).toHaveBeenCalledWith([
        { file, kbDocumentType: "certification" },
        { file: referenceFile, kbDocumentType: "case_study" },
        { file: capacityFile, kbDocumentType: "capability_statement" },
        { file: creditFile, kbDocumentType: "credit_certificate" },
      ]),
    );
  });
});
