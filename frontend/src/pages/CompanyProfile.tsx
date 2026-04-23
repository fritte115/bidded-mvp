import { Fragment, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { company as mockCompany } from "@/data/mock";
import {
  deleteCompanyKbDocument,
  fetchCompany,
  fetchCompanyKbDocuments,
  fetchCompanyKbEvidence,
  type CompanyKbDocument,
  type CompanyKbDocumentType,
  type CompanyKbEvidenceItem,
  updateCompany,
  uploadCompanyKbDocuments,
} from "@/lib/api";
import {
  ChevronDown,
  FileText,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  UploadCloud,
} from "lucide-react";

type Company = typeof mockCompany;
type PendingKbFile = { file: File; kbDocumentType: CompanyKbDocumentType };

const kbDocumentTypes: Array<{ value: CompanyKbDocumentType; label: string }> = [
  { value: "certification", label: "Certification" },
  { value: "case_study", label: "Case study" },
  { value: "cv_profile", label: "CV/profile" },
  { value: "capability_statement", label: "Capability statement" },
  { value: "policy_process", label: "Policy/process" },
  { value: "financial_pricing", label: "Financial/pricing" },
  { value: "legal_insurance", label: "Legal/insurance" },
];

export default function CompanyProfile() {
  const queryClient = useQueryClient();
  const { data: liveCompany, isLoading } = useQuery({
    queryKey: ["company"],
    queryFn: fetchCompany,
  });
  const { data: kbData, isLoading: kbLoading } = useQuery({
    queryKey: ["company-kb-documents"],
    queryFn: fetchCompanyKbDocuments,
    refetchInterval: (query) =>
      query.state.data?.documents.some(
        (doc) => doc.parse_status === "pending" || doc.parse_status === "parsing",
      )
        ? 5_000
        : false,
  });

  // Live data when available, mock as fallback
  const company = liveCompany ?? mockCompany;

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<Company>(mockCompany);
  const [kbFiles, setKbFiles] = useState<PendingKbFile[]>([]);
  const [kbUploading, setKbUploading] = useState(false);
  const [kbDeleting, setKbDeleting] = useState<Set<string>>(new Set());
  const [expandedKb, setExpandedKb] = useState<string | null>(null);
  const [kbEvidence, setKbEvidence] = useState<Record<string, CompanyKbEvidenceItem[]>>({});
  const [kbEvidenceLoading, setKbEvidenceLoading] = useState<string | null>(null);

  function openEditor() {
    // Deep-clone arrays so editing the draft doesn't mutate live state
    setDraft({
      ...company,
      capabilities: [...company.capabilities],
      certifications: company.certifications.map((c) => ({ ...c })),
      references: company.references.map((r) => ({ ...r })),
      financialAssumptions: { ...company.financialAssumptions },
    });
    setOpen(true);
  }

  if (isLoading) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
        Loading company profile…
      </div>
    );
  }

  async function save() {
    setSaving(true);
    try {
      await updateCompany(draft);
      await queryClient.invalidateQueries({ queryKey: ["company"] });
      await queryClient.invalidateQueries({ queryKey: ["company-kb-documents"] });
      setOpen(false);
      toast.success("Profile updated", { description: "Changes saved to database." });
    } catch (err) {
      toast.error("Save failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setSaving(false);
    }
  }

  function handleKbFiles(incoming: FileList | null) {
    if (!incoming) return;
    const allowed = new Set(["pdf", "docx", "pptx", "xlsx", "csv", "txt", "md"]);
    const next = Array.from(incoming)
      .filter((file) => allowed.has(file.name.split(".").pop()?.toLowerCase() ?? ""))
      .map((file) => ({ file, kbDocumentType: "certification" as CompanyKbDocumentType }));
    setKbFiles((prev) => {
      const existing = new Set(prev.map((item) => item.file.name));
      return [...prev, ...next.filter((item) => !existing.has(item.file.name))];
    });
  }

  async function uploadKbFiles() {
    if (kbFiles.length === 0) return;
    setKbUploading(true);
    try {
      await uploadCompanyKbDocuments(kbFiles);
      setKbFiles([]);
      await queryClient.invalidateQueries({ queryKey: ["company-kb-documents"] });
      toast.success("Knowledge base upload started", {
        description: `${kbFiles.length} file${kbFiles.length === 1 ? "" : "s"} queued for extraction.`,
      });
    } catch (err) {
      toast.error("Upload failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setKbUploading(false);
    }
  }

  async function toggleKbEvidence(documentId: string) {
    if (expandedKb === documentId) {
      setExpandedKb(null);
      return;
    }
    setExpandedKb(documentId);
    if (kbEvidence[documentId]) return;
    setKbEvidenceLoading(documentId);
    try {
      const response = await fetchCompanyKbEvidence(documentId);
      setKbEvidence((prev) => ({ ...prev, [documentId]: response.evidence }));
    } catch (err) {
      toast.error("Could not load extracted facts", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setKbEvidenceLoading(null);
    }
  }

  async function removeKbDocument(document: CompanyKbDocument) {
    setKbDeleting((prev) => new Set(prev).add(document.document_id));
    try {
      await deleteCompanyKbDocument(document.document_id);
      await queryClient.invalidateQueries({ queryKey: ["company-kb-documents"] });
      setKbEvidence((prev) => {
        const next = { ...prev };
        delete next[document.document_id];
        return next;
      });
      toast.success("Knowledge base file deleted", {
        description: document.original_filename,
      });
    } catch (err) {
      toast.error("Delete failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setKbDeleting((prev) => {
        const next = new Set(prev);
        next.delete(document.document_id);
        return next;
      });
    }
  }

  return (
    <>
      <PageHeader
        title={`${company.name}`}
        description="Company Profile · Demo Workspace"
        actions={
          <Button variant="outline" onClick={openEditor}>
            <Pencil className="h-4 w-4" /> Edit Profile
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">General Info</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Row label="Company" value={company.name} />
            <Row label="Org. Number" value={<span className="font-mono">{company.orgNumber}</span>} />
            <Row label="Size" value={company.size} />
            <Row label="HQ" value={company.hq} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Financial Assumptions</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Row label="Revenue Range" value={company.financialAssumptions.revenueRange} />
            <Row label="Target Margin" value={company.financialAssumptions.targetMargin} />
            <Row label="Max Contract Size" value={company.financialAssumptions.maxContractSize} />
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Capabilities</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-1.5">
              {company.capabilities.map((c) => (
                <span key={c} className="inline-flex items-center rounded-sm border border-border bg-secondary px-2.5 py-1 text-xs font-medium">
                  {c}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Certifications</CardTitle></CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Certification</TableHead>
                  <TableHead>Issuer</TableHead>
                  <TableHead>Valid Until</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {company.certifications.map((c) => (
                  <TableRow key={c.name}>
                    <TableCell className="font-medium">{c.name}</TableCell>
                    <TableCell className="text-muted-foreground">{c.issuer}</TableCell>
                    <TableCell className="font-mono text-xs">{c.validUntil}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="pb-2"><CardTitle className="text-sm">References</CardTitle></CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Client</TableHead>
                  <TableHead>Scope</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead>Year</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {company.references.map((r) => (
                  <TableRow key={r.client}>
                    <TableCell className="font-medium">{r.client}</TableCell>
                    <TableCell>{r.scope}</TableCell>
                    <TableCell className="font-mono text-xs tabular-nums">{r.value}</TableCell>
                    <TableCell className="font-mono text-xs">{r.year}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Knowledge Base</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <label
              className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-secondary/40 px-6 py-8 text-center hover:border-primary/40"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                handleKbFiles(e.dataTransfer.files);
              }}
            >
              <UploadCloud className="mb-2 h-7 w-7 text-muted-foreground" />
              <p className="text-sm font-medium">Drop company documents or click to upload</p>
              <p className="mt-1 text-xs text-muted-foreground">
                PDF, DOCX, PPTX, XLSX, CSV, TXT, MD
              </p>
              <input
                type="file"
                multiple
                accept=".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md"
                className="sr-only"
                onChange={(e) => handleKbFiles(e.target.files)}
              />
            </label>

            {kbFiles.length > 0 && (
              <div className="space-y-2">
                {kbFiles.map((item, index) => (
                  <div
                    key={`${item.file.name}-${index}`}
                    className="grid gap-2 rounded-md border border-border bg-card p-2 sm:grid-cols-[1fr_220px_auto]"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="truncate text-sm">{item.file.name}</span>
                      <span className="shrink-0 font-mono text-xs text-muted-foreground">
                        {(item.file.size / 1024 / 1024).toFixed(1)} MB
                      </span>
                    </div>
                    <Select
                      value={item.kbDocumentType}
                      onValueChange={(value) => {
                        const next = [...kbFiles];
                        next[index] = {
                          ...next[index],
                          kbDocumentType: value as CompanyKbDocumentType,
                        };
                        setKbFiles(next);
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {kbDocumentTypes.map((type) => (
                          <SelectItem key={type.value} value={type.value}>
                            {type.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove ${item.file.name}`}
                      onClick={() => setKbFiles((prev) => prev.filter((_, i) => i !== index))}
                    >
                      <Trash2 className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  </div>
                ))}
                <Button onClick={uploadKbFiles} disabled={kbUploading}>
                  {kbUploading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Uploading
                    </>
                  ) : (
                    <>
                      <UploadCloud className="h-4 w-4" /> Upload to KB
                    </>
                  )}
                </Button>
              </div>
            )}

            <div className="overflow-hidden rounded-md border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>File</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Facts</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {kbLoading ? (
                    <TableRow>
                      <TableCell colSpan={5} className="text-sm text-muted-foreground">
                        Loading knowledge base…
                      </TableCell>
                    </TableRow>
                  ) : (kbData?.documents ?? []).length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="text-sm text-muted-foreground">
                        No company knowledge base files yet.
                      </TableCell>
                    </TableRow>
                  ) : (
                    (kbData?.documents ?? []).map((document) => {
                      const evidence = kbEvidence[document.document_id] ?? [];
                      const isExpanded = expandedKb === document.document_id;
                      const isDeleting = kbDeleting.has(document.document_id);
                      return (
                        <Fragment key={document.document_id}>
                          <TableRow key={document.document_id}>
                            <TableCell className="font-medium">{document.original_filename}</TableCell>
                            <TableCell className="text-sm text-muted-foreground">
                              {kbTypeLabel(document.kb_document_type)}
                            </TableCell>
                            <TableCell>
                              <KbStatus document={document} />
                            </TableCell>
                            <TableCell className="font-mono text-xs">
                              {document.evidence_count}
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="flex justify-end gap-1">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  aria-expanded={isExpanded}
                                  onClick={() => toggleKbEvidence(document.document_id)}
                                >
                                  {kbEvidenceLoading === document.document_id ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <ChevronDown className="h-3.5 w-3.5" />
                                  )}
                                  Facts
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  aria-label={`Delete ${document.original_filename}`}
                                  disabled={isDeleting}
                                  onClick={() => removeKbDocument(document)}
                                >
                                  {isDeleting ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <Trash2 className="h-4 w-4 text-muted-foreground" />
                                  )}
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                          {isExpanded && (
                            <TableRow key={`${document.document_id}-facts`}>
                              <TableCell colSpan={5} className="bg-secondary/30">
                                {document.warnings.length > 0 && (
                                  <div className="mb-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
                                    {document.warnings.join(" · ")}
                                  </div>
                                )}
                                {evidence.length === 0 ? (
                                  <p className="text-sm text-muted-foreground">
                                    No extracted facts loaded.
                                  </p>
                                ) : (
                                  <ul className="space-y-2">
                                    {evidence.map((item) => (
                                      <li key={item.evidence_key} className="rounded-md border border-border bg-card px-3 py-2">
                                        <div className="mb-1 flex items-center justify-between gap-2">
                                          <span className="font-mono text-[11px] text-muted-foreground">
                                            {item.evidence_key}
                                          </span>
                                          <span className="rounded-sm bg-secondary px-1.5 py-0.5 text-[10px] font-medium uppercase text-secondary-foreground">
                                            {item.category}
                                          </span>
                                        </div>
                                        <p className="text-sm">{item.excerpt}</p>
                                      </li>
                                    ))}
                                  </ul>
                                )}
                              </TableCell>
                            </TableRow>
                          )}
                        </Fragment>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
          <SheetHeader>
            <SheetTitle>Edit Company Profile</SheetTitle>
            <SheetDescription>
              Changes are saved through the backend and refresh company evidence.
            </SheetDescription>
          </SheetHeader>

          <div className="mt-6 space-y-6">
            <Section title="General Info">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Company">
                  <Input
                    value={draft.name}
                    onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  />
                </Field>
                <Field label="Org. Number">
                  <Input
                    value={draft.orgNumber}
                    onChange={(e) => setDraft({ ...draft, orgNumber: e.target.value })}
                  />
                </Field>
                <Field label="Size">
                  <Input
                    value={draft.size}
                    onChange={(e) => setDraft({ ...draft, size: e.target.value })}
                  />
                </Field>
                <Field label="HQ">
                  <Input
                    value={draft.hq}
                    onChange={(e) => setDraft({ ...draft, hq: e.target.value })}
                  />
                </Field>
              </div>
            </Section>

            <Separator />

            <Section title="Financial Assumptions">
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Revenue Range">
                  <Input
                    value={draft.financialAssumptions.revenueRange}
                    onChange={(e) => setDraft({
                      ...draft,
                      financialAssumptions: { ...draft.financialAssumptions, revenueRange: e.target.value },
                    })}
                  />
                </Field>
                <Field label="Target Margin">
                  <Input
                    value={draft.financialAssumptions.targetMargin}
                    onChange={(e) => setDraft({
                      ...draft,
                      financialAssumptions: { ...draft.financialAssumptions, targetMargin: e.target.value },
                    })}
                  />
                </Field>
                <Field label="Max Contract Size">
                  <Input
                    value={draft.financialAssumptions.maxContractSize}
                    onChange={(e) => setDraft({
                      ...draft,
                      financialAssumptions: { ...draft.financialAssumptions, maxContractSize: e.target.value },
                    })}
                  />
                </Field>
              </div>
            </Section>

            <Separator />

            <Section title="Capabilities" hint="One per line">
              <Textarea
                rows={5}
                value={draft.capabilities.join("\n")}
                onChange={(e) => setDraft({
                  ...draft,
                  capabilities: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean),
                })}
              />
            </Section>

            <Separator />

            <Section
              title="Certifications"
              action={
                <Button variant="outline" size="sm" onClick={() => setDraft({
                  ...draft,
                  certifications: [...draft.certifications, { name: "", issuer: "", validUntil: "" }],
                })}>
                  <Plus className="h-3.5 w-3.5" /> Add
                </Button>
              }
            >
              <div className="space-y-2">
                {draft.certifications.map((c, i) => (
                  <div key={i} className="grid grid-cols-[1fr_1fr_120px_auto] gap-2">
                    <Input
                      placeholder="Name"
                      value={c.name}
                      onChange={(e) => {
                        const next = [...draft.certifications];
                        next[i] = { ...next[i], name: e.target.value };
                        setDraft({ ...draft, certifications: next });
                      }}
                    />
                    <Input
                      placeholder="Issuer"
                      value={c.issuer}
                      onChange={(e) => {
                        const next = [...draft.certifications];
                        next[i] = { ...next[i], issuer: e.target.value };
                        setDraft({ ...draft, certifications: next });
                      }}
                    />
                    <Input
                      placeholder="YYYY-MM-DD"
                      value={c.validUntil}
                      onChange={(e) => {
                        const next = [...draft.certifications];
                        next[i] = { ...next[i], validUntil: e.target.value };
                        setDraft({ ...draft, certifications: next });
                      }}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setDraft({
                        ...draft,
                        certifications: draft.certifications.filter((_, idx) => idx !== i),
                      })}
                    >
                      <Trash2 className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  </div>
                ))}
              </div>
            </Section>

            <Separator />

            <Section
              title="References"
                action={
                  <Button variant="outline" size="sm" onClick={() => setDraft({
                    ...draft,
                    references: [...draft.references, { client: "", scope: "", value: "", year: new Date().getFullYear() }],
                  })}>
                    <Plus className="h-3.5 w-3.5" /> Add
                  </Button>
                }
            >
              <div className="space-y-2">
                {draft.references.map((r, i) => (
                  <div key={i} className="grid grid-cols-[1fr_1.5fr_120px_90px_auto] gap-2">
                    <Input
                      placeholder="Client"
                      value={r.client}
                      onChange={(e) => {
                        const next = [...draft.references];
                        next[i] = { ...next[i], client: e.target.value };
                        setDraft({ ...draft, references: next });
                      }}
                    />
                    <Input
                      placeholder="Scope"
                      value={r.scope}
                      onChange={(e) => {
                        const next = [...draft.references];
                        next[i] = { ...next[i], scope: e.target.value };
                        setDraft({ ...draft, references: next });
                      }}
                    />
                    <Input
                      placeholder="Value"
                      value={r.value}
                      onChange={(e) => {
                        const next = [...draft.references];
                        next[i] = { ...next[i], value: e.target.value };
                        setDraft({ ...draft, references: next });
                      }}
                    />
                    <Input
                      placeholder="Year"
                      type="number"
                      value={r.year}
                      onChange={(e) => {
                        const next = [...draft.references];
                        next[i] = { ...next[i], year: Number(e.target.value) || 0 };
                        setDraft({ ...draft, references: next });
                      }}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setDraft({
                        ...draft,
                        references: draft.references.filter((_, idx) => idx !== i),
                      })}
                    >
                      <Trash2 className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  </div>
                ))}
              </div>
            </Section>
          </div>

          <SheetFooter className="mt-6 gap-2 sm:gap-2">
            <Button variant="outline" onClick={() => setOpen(false)} disabled={saving}>Cancel</Button>
            <Button onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-border/60 py-1.5 last:border-0">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  );
}

function Section({
  title, hint, action, children,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs uppercase tracking-wide text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function kbTypeLabel(value: CompanyKbDocumentType): string {
  return kbDocumentTypes.find((type) => type.value === value)?.label ?? value;
}

function KbStatus({ document }: { document: CompanyKbDocument }) {
  const activeStatus =
    document.extraction_status === "fallback"
      ? "fallback"
      : document.extraction_status === "failed"
        ? "failed"
        : document.parse_status;
  const label =
    activeStatus === "parsed" && document.extraction_status === "extracted"
      ? "active"
      : activeStatus.replace("_", " ");
  const tone =
    activeStatus === "parser_failed" || activeStatus === "failed"
      ? "border-danger/30 bg-danger/10 text-danger"
      : activeStatus === "fallback"
        ? "border-warning/30 bg-warning/10 text-warning"
        : activeStatus === "pending" || activeStatus === "parsing"
          ? "border-info/30 bg-info/10 text-info"
          : "border-success/30 bg-success/10 text-success";
  return (
    <span className={`inline-flex items-center rounded-sm border px-2 py-0.5 text-xs font-medium ${tone}`}>
      {label}
    </span>
  );
}
