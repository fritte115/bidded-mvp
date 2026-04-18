import { useState } from "react";
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
import { company as mockCompany } from "@/data/mock";
import { fetchCompany, updateCompany } from "@/lib/api";
import { Pencil, Plus, Trash2 } from "lucide-react";

type Company = typeof mockCompany;

export default function CompanyProfile() {
  const queryClient = useQueryClient();
  const { data: liveCompany, isLoading } = useQuery({
    queryKey: ["company"],
    queryFn: fetchCompany,
  });

  // Live data when available, mock as fallback
  const company = liveCompany ?? mockCompany;

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<Company>(mockCompany);

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
      </div>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
          <SheetHeader>
            <SheetTitle>Edit Company Profile</SheetTitle>
            <SheetDescription>
              Changes are kept locally in this session. Wire to a backend later.
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
