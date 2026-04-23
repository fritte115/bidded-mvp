import { useMemo, useState } from "react";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  applyCompanyWebsiteImportPreview,
  fetchCompany,
  importCompanyWebsite,
  updateCompany,
  type CompanyWebsiteImportPreview,
} from "@/lib/api";
import type { Company as CompanyType } from "@/data/mock";
import {
  Pencil, Plus, Trash2, Building2, Globe, Mail, Phone, MapPin, Calendar,
  ShieldCheck, Award, Users, TrendingUp, FileCheck2, Leaf, AlertTriangle,
  CheckCircle2, Clock, Download, ExternalLink, ChevronRight, Loader2,
  Sparkles,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip as ReTooltip, XAxis, YAxis,
} from "recharts";

type Company = CompanyType;

const COMPLETENESS_FIELDS: {
  key: string;
  label: string;
  check: (c: Company) => boolean;
}[] = [
  { key: "description", label: "Company description", check: (c) => !!c.description && c.description.length > 40 },
  { key: "leadership", label: "Leadership team (≥3)", check: (c) => (c.leadership?.length ?? 0) >= 3 },
  { key: "offices", label: "Office locations", check: (c) => (c.offices?.length ?? 0) >= 1 },
  { key: "financials", label: "Financial history (≥2 years)", check: (c) => (c.financials?.length ?? 0) >= 2 },
  { key: "certifications", label: "Certifications (≥1)", check: (c) => c.certifications.length >= 1 },
  { key: "references", label: "Reference assignments (≥3)", check: (c) => c.references.length >= 3 },
  { key: "security", label: "Security posture defined", check: (c) => (c.securityPosture?.length ?? 0) >= 3 },
  { key: "sustainability", label: "Sustainability metrics", check: (c) => !!c.sustainability },
];

export default function CompanyProfile() {
  const queryClient = useQueryClient();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["company"],
    queryFn: fetchCompany,
  });

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<Company | null>(null);
  const [websiteImportUrl, setWebsiteImportUrl] = useState("");
  const [websiteImporting, setWebsiteImporting] = useState(false);
  const [websiteImportPreview, setWebsiteImportPreview] =
    useState<CompanyWebsiteImportPreview | null>(null);

  const company = data?.company;

  const completeness = useMemo(() => {
    if (!company) return { score: 0, present: [], missing: [] as typeof COMPLETENESS_FIELDS };
    const present = COMPLETENESS_FIELDS.filter((f) => f.check(company));
    const missing = COMPLETENESS_FIELDS.filter((f) => !f.check(company));
    const score = Math.round((present.length / COMPLETENESS_FIELDS.length) * 100);
    return { score, present, missing };
  }, [company]);

  function openEditor() {
    if (!company) return;
    // Deep-clone every editable collection so draft mutations don't leak back
    // into live react-query state before save succeeds.
    setDraft({
      ...company,
      capabilities: [...company.capabilities],
      certifications: company.certifications.map((c) => ({ ...c })),
      references: company.references.map((r) => ({ ...r })),
      financialAssumptions: { ...company.financialAssumptions },
      offices: company.offices ? [...company.offices] : [],
      industries: company.industries ? [...company.industries] : [],
      leadership: company.leadership ? company.leadership.map((p) => ({ ...p })) : [],
      financials: company.financials ? company.financials.map((f) => ({ ...f })) : [],
      teamComposition: company.teamComposition
        ? company.teamComposition.map((t) => ({ ...t }))
        : [],
      insurance: company.insurance ? company.insurance.map((i) => ({ ...i })) : [],
      frameworkAgreements: company.frameworkAgreements
        ? company.frameworkAgreements.map((f) => ({ ...f }))
        : [],
      securityPosture: company.securityPosture
        ? company.securityPosture.map((s) => ({ ...s }))
        : [],
      sustainability: company.sustainability
        ? { ...company.sustainability }
        : { co2ReductionPct: 0, renewableEnergyPct: 0, diversityPct: 0, codeOfConductSigned: false },
      bidStats: company.bidStats
        ? { ...company.bidStats }
        : {
            totalBids: 0,
            won: 0,
            lost: 0,
            inProgress: 0,
            winRatePct: 0,
            avgContractMSEK: 0,
          },
      websiteImports: company.websiteImports ? [...company.websiteImports] : [],
    });
    setWebsiteImportUrl(company.website ?? "");
    setWebsiteImportPreview(null);
    setOpen(true);
  }

  async function importWebsiteIntoDraft() {
    if (!draft) return;
    const url = websiteImportUrl.trim() || draft.website?.trim();
    if (!url) {
      toast.error("Website URL required");
      return;
    }
    setWebsiteImporting(true);
    try {
      const preview = await importCompanyWebsite(url);
      setWebsiteImportPreview(preview);
      setWebsiteImportUrl(preview.profile_patch.website ?? preview.source_url);
      toast.success("Website parsed", {
        description: `${preview.pages.length} page${preview.pages.length === 1 ? "" : "s"} ready for review.`,
      });
    } catch (err) {
      toast.error("Website import failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setWebsiteImporting(false);
    }
  }

  function applyWebsiteImportPreview() {
    if (!draft || !websiteImportPreview) return;
    const next = applyCompanyWebsiteImportPreview(draft, websiteImportPreview);
    setDraft(next);
    setWebsiteImportUrl(next.website ?? websiteImportPreview.source_url);
    setWebsiteImportPreview(null);
    toast.success("Import applied to draft", {
      description: "Review the fields, then save changes.",
    });
  }

  async function save() {
    if (!draft || !data) return;
    setSaving(true);
    try {
      await updateCompany(draft, data.raw);
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

  if (isLoading) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
        Loading company profile…
      </div>
    );
  }

  if (error || !company || !data) {
    return (
      <div className="mx-auto mt-10 max-w-md rounded-lg border border-danger/40 bg-danger/5 p-5 text-sm">
        <p className="mb-2 font-semibold text-danger">Couldn’t load company profile</p>
        <p className="mb-3 text-muted-foreground">
          {error instanceof Error ? error.message : "Supabase request failed."}
        </p>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  const initials = company.name
    .split(" ")
    .filter((w) => /^[A-ZÅÄÖ]/.test(w))
    .slice(0, 2)
    .map((w) => w[0])
    .join("");

  const latestFinancial = company.financials?.[company.financials.length - 1];
  const firstFinancial = company.financials?.[0];

  return (
    <>
      <PageHeader
        title="Company Profile"
        description="The single source of truth used by Bidded agents to evaluate every tender."
        actions={
          <div className="flex gap-2">
            <Button variant="outline" size="sm">
              <Download className="h-4 w-4" /> Export PDF
            </Button>
            <Button variant="default" size="sm" onClick={openEditor}>
              <Pencil className="h-4 w-4" /> Edit Profile
            </Button>
          </div>
        }
      />

      <div className="space-y-6">
        {/* Hero / identity card */}
        <Card className="overflow-hidden border-border/60 shadow-sm">
          <div className="h-24 bg-gradient-to-br from-primary/20 via-primary/8 to-transparent" />
          <CardContent className="-mt-12 pb-7">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
              <div className="flex items-end gap-5">
                <div className="flex h-24 w-24 shrink-0 items-center justify-center rounded-2xl border-4 border-background bg-gradient-to-br from-primary to-primary/80 text-3xl font-bold text-primary-foreground shadow-lg ring-1 ring-border/40">
                  {initials || "AC"}
                </div>
                <div className="min-w-0 pb-1.5">
                  <h2 className="truncate text-2xl font-bold tracking-tight">{company.name}</h2>
                  {company.legalName && (
                    <p className="text-sm text-muted-foreground">{company.legalName}</p>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1.5">
                      <Building2 className="h-3.5 w-3.5" />
                      <span className="font-mono">{company.orgNumber}</span>
                    </span>
                    {company.founded && (
                      <span className="inline-flex items-center gap-1.5">
                        <Calendar className="h-3.5 w-3.5" />
                        Founded {company.founded}
                      </span>
                    )}
                    <span className="inline-flex items-center gap-1.5">
                      <MapPin className="h-3.5 w-3.5" />
                      {company.hq}
                    </span>
                    {company.website && (
                      <a
                        href={company.website}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1.5 text-primary hover:underline"
                      >
                        <Globe className="h-3.5 w-3.5" />
                        {company.website.replace(/^https?:\/\//, "")}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Popover>
                  <PopoverTrigger asChild>
                    <button className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-xs hover:bg-muted/40">
                      <div className="relative h-7 w-7">
                        <svg viewBox="0 0 36 36" className="h-7 w-7 -rotate-90">
                          <circle cx="18" cy="18" r="15" fill="none" stroke="hsl(var(--muted))" strokeWidth="3.5" />
                          <circle
                            cx="18" cy="18" r="15" fill="none"
                            stroke={completeness.score >= 80 ? "hsl(var(--success))" : completeness.score >= 50 ? "hsl(var(--warning))" : "hsl(var(--destructive))"}
                            strokeWidth="3.5" strokeLinecap="round"
                            strokeDasharray={`${(completeness.score / 100) * 94.2} 94.2`}
                          />
                        </svg>
                        <span className="absolute inset-0 flex items-center justify-center text-[9px] font-bold tabular-nums">
                          {completeness.score}
                        </span>
                      </div>
                      <span className="font-medium">Profile completeness</span>
                      <ChevronRight className="h-3 w-3 text-muted-foreground" />
                    </button>
                  </PopoverTrigger>
                  <PopoverContent align="end" className="w-72">
                    <div className="space-y-2">
                      <div className="flex items-baseline justify-between">
                        <span className="text-sm font-semibold">{completeness.score}% complete</span>
                        <span className="text-xs text-muted-foreground">
                          {completeness.present.length}/{COMPLETENESS_FIELDS.length}
                        </span>
                      </div>
                      <Progress value={completeness.score} className="h-1.5" />
                      <Separator className="my-2" />
                      <p className="text-xs font-medium text-muted-foreground">Checklist</p>
                      <ul className="space-y-1.5">
                        {COMPLETENESS_FIELDS.map((f) => {
                          const ok = f.check(company);
                          return (
                            <li key={f.key} className="flex items-center gap-2 text-xs">
                              {ok ? (
                                <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                              ) : (
                                <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                              )}
                              <span className={ok ? "text-foreground" : "text-muted-foreground"}>{f.label}</span>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  </PopoverContent>
                </Popover>
                <Badge variant="outline">Last reviewed 2 weeks ago</Badge>
              </div>
            </div>

            {company.description && (
              <p className="mt-5 max-w-4xl text-sm leading-relaxed text-muted-foreground">
                {company.description}
              </p>
            )}
          </CardContent>
        </Card>

        {/* KPI strip */}
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <KpiCard
            icon={<Users className="h-4 w-4" />}
            label="Headcount"
            value={String(company.headcount ?? "—")}
            sub={
              company.headcount && firstFinancial
                ? `+${company.headcount - firstFinancial.headcount} since ${firstFinancial.year}`
                : undefined
            }
          />
          <KpiCard
            icon={<TrendingUp className="h-4 w-4" />}
            label="Revenue (latest FY)"
            value={latestFinancial ? `${latestFinancial.revenueMSEK} MSEK` : "—"}
            sub={latestFinancial ? `${latestFinancial.ebitMarginPct}% EBIT margin` : undefined}
            tone="positive"
          />
          <KpiCard
            icon={<Award className="h-4 w-4" />}
            label="Win rate"
            value={company.bidStats ? `${company.bidStats.winRatePct}%` : "—"}
            sub={company.bidStats ? `${company.bidStats.won} won / ${company.bidStats.totalBids} total` : undefined}
          />
          <KpiCard
            icon={<ShieldCheck className="h-4 w-4" />}
            label="Active certifications"
            value={String(company.certifications.length)}
            sub={company.certifications.slice(0, 4).map((c) => c.name.split(" ")[0]).join(", ") || undefined}
          />
        </div>

        <Tabs defaultValue="overview" className="space-y-5">
          <TabsList className="inline-flex h-auto w-full justify-start gap-1 rounded-lg bg-muted/60 p-1 sm:w-auto">
            <TabsTrigger value="overview" className="px-4 py-1.5">Overview</TabsTrigger>
            <TabsTrigger value="capabilities" className="px-4 py-1.5">Capabilities</TabsTrigger>
            <TabsTrigger value="references" className="px-4 py-1.5">References</TabsTrigger>
            <TabsTrigger value="financials" className="px-4 py-1.5">Financials</TabsTrigger>
            <TabsTrigger value="security" className="px-4 py-1.5">Security & ESG</TabsTrigger>
          </TabsList>

          {/* OVERVIEW */}
          <TabsContent value="overview" className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Leadership & contacts</CardTitle>
              </CardHeader>
              <CardContent>
                {company.leadership && company.leadership.length > 0 ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {company.leadership.map((p) => (
                      <div key={p.name} className="flex items-start gap-3 rounded-md border border-border bg-muted/20 p-3">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                          {p.name.split(" ").map((n) => n[0]).slice(0, 2).join("")}
                        </div>
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium">{p.name}</div>
                          <div className="truncate text-xs text-muted-foreground">{p.title}</div>
                          {p.email && (
                            <a href={`mailto:${p.email}`} className="mt-0.5 block truncate text-xs text-primary hover:underline">
                              {p.email}
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyHint message="No leadership team recorded yet." />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Get in touch</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {company.email && (
                  <ContactRow icon={<Mail className="h-4 w-4" />} label="Bid mailbox" value={company.email} href={`mailto:${company.email}`} />
                )}
                {company.phone && (
                  <ContactRow icon={<Phone className="h-4 w-4" />} label="Switchboard" value={company.phone} href={`tel:${company.phone.replace(/\s/g, "")}`} />
                )}
                {(company.email || company.phone) && <Separator />}
                <div>
                  <div className="mb-1.5 text-xs uppercase tracking-wide text-muted-foreground">Offices</div>
                  {company.offices && company.offices.length > 0 ? (
                    <ul className="space-y-1 text-sm">
                      {company.offices.map((o) => (
                        <li key={o} className="flex items-center gap-2">
                          <MapPin className="h-3.5 w-3.5 text-muted-foreground" /> {o}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted-foreground">—</p>
                  )}
                </div>
                <Separator />
                <div>
                  <div className="mb-1.5 text-xs uppercase tracking-wide text-muted-foreground">Industries served</div>
                  {company.industries && company.industries.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {company.industries.map((i) => (
                        <Badge key={i} variant="secondary" className="font-normal">{i}</Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">—</p>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="lg:col-span-3">
              <CardHeader className="flex-row items-center justify-between pb-3">
                <CardTitle className="text-sm">Bid pipeline performance</CardTitle>
                <Badge variant="outline" className="font-normal">Last 24 months</Badge>
              </CardHeader>
              <CardContent>
                {company.bidStats ? (
                  <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
                    <PipelineStat label="Total bids" value={company.bidStats.totalBids} />
                    <PipelineStat label="Won" value={company.bidStats.won} tone="positive" />
                    <PipelineStat label="Lost" value={company.bidStats.lost} tone="negative" />
                    <PipelineStat label="In progress" value={company.bidStats.inProgress} />
                    <PipelineStat label="Avg. contract" value={`${company.bidStats.avgContractMSEK} MSEK`} />
                  </div>
                ) : (
                  <EmptyHint message="No bid pipeline statistics yet." />
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* CAPABILITIES */}
          <TabsContent value="capabilities" className="grid gap-5 lg:grid-cols-2">
            <Card className="lg:col-span-2">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Core capabilities</CardTitle>
              </CardHeader>
              <CardContent>
                {company.capabilities.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {company.capabilities.map((c) => (
                      <span
                        key={c}
                        className="inline-flex items-center rounded-md border border-border bg-secondary px-2.5 py-1 text-xs font-medium"
                      >
                        {c}
                      </span>
                    ))}
                  </div>
                ) : (
                  <EmptyHint message="No capabilities recorded." />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Team composition</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {company.teamComposition && company.teamComposition.length > 0 ? (
                  company.teamComposition.map((t) => {
                    const max = Math.max(...(company.teamComposition?.map((x) => x.count) ?? [1]));
                    return (
                      <div key={t.role}>
                        <div className="mb-1 flex items-baseline justify-between text-xs">
                          <span className="font-medium">{t.role}</span>
                          <span className="font-mono text-muted-foreground">
                            {t.count} · ⌀ {t.avgYears}y
                          </span>
                        </div>
                        <Progress value={(t.count / max) * 100} className="h-1.5" />
                      </div>
                    );
                  })
                ) : (
                  <EmptyHint message="No team composition recorded." />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Certifications</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {company.certifications.length > 0 ? (
                  company.certifications.map((c) => (
                    <div key={c.name} className="flex items-start gap-3 rounded-md border border-border p-2.5">
                      <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">{c.name}</div>
                        <div className="text-xs text-muted-foreground">
                          Issued by {c.issuer} · valid until <span className="font-mono">{c.validUntil}</span>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <EmptyHint message="No certifications recorded." />
                )}
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Framework agreements</CardTitle>
              </CardHeader>
              <CardContent>
                {company.frameworkAgreements && company.frameworkAgreements.length > 0 ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Agreement</TableHead>
                        <TableHead>Authority</TableHead>
                        <TableHead>Valid until</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {company.frameworkAgreements.map((f) => (
                        <TableRow key={f.name}>
                          <TableCell className="font-medium">{f.name}</TableCell>
                          <TableCell className="text-muted-foreground">{f.authority}</TableCell>
                          <TableCell className="font-mono text-xs">{f.validUntil}</TableCell>
                          <TableCell>
                            <Badge
                              variant={f.status === "Active" ? "secondary" : "outline"}
                              className={
                                f.status === "Active"
                                  ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300"
                                  : f.status === "Expiring"
                                    ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
                                    : ""
                              }
                            >
                              {f.status}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <EmptyHint message="No framework agreements recorded." />
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* REFERENCES */}
          <TabsContent value="references">
            <Card>
              <CardHeader className="flex-row items-center justify-between pb-3">
                <CardTitle className="text-sm">Reference assignments</CardTitle>
                <Badge variant="outline" className="font-normal">{company.references.length} cases</Badge>
              </CardHeader>
              <CardContent>
                {company.references.length > 0 ? (
                  <div className="grid gap-3 md:grid-cols-2">
                    {company.references.map((r) => (
                      <div key={`${r.client}-${r.year}`} className="rounded-md border border-border bg-card p-4 transition-colors hover:bg-muted/30">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold">{r.client}</div>
                            {r.sector && <div className="text-xs text-muted-foreground">{r.sector}</div>}
                          </div>
                          <Badge variant="outline" className="shrink-0 font-mono text-xs">{r.year}</Badge>
                        </div>
                        <p className="mt-2 text-sm">{r.scope}</p>
                        {r.outcome && (
                          <p className="mt-1.5 text-xs italic text-muted-foreground">"{r.outcome}"</p>
                        )}
                        <div className="mt-3 flex items-center justify-between border-t border-border/60 pt-2 text-xs">
                          <span className="inline-flex items-center gap-1 text-muted-foreground">
                            <Clock className="h-3 w-3" /> {r.duration ?? "—"}
                          </span>
                          <span className="font-mono font-semibold tabular-nums">{r.value}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyHint message="No reference assignments recorded." />
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* FINANCIALS */}
          <TabsContent value="financials" className="grid gap-5 lg:grid-cols-2">
            {company.financials && company.financials.length > 0 && (
              <>
                <Card className="lg:col-span-2">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">Revenue & EBIT margin trend</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ResponsiveContainer width="100%" height={220}>
                      <AreaChart data={company.financials} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                        <defs>
                          <linearGradient id="revFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.35} />
                            <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                        <XAxis dataKey="year" stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                        <YAxis yAxisId="left" stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}M`} />
                        <YAxis yAxisId="right" orientation="right" stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} />
                        <ReTooltip
                          contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          labelStyle={{ color: "hsl(var(--foreground))" }}
                        />
                        <Area yAxisId="left" type="monotone" dataKey="revenueMSEK" name="Revenue (MSEK)" stroke="hsl(var(--primary))" strokeWidth={2} fill="url(#revFill)" />
                        <Line yAxisId="right" type="monotone" dataKey="ebitMarginPct" name="EBIT margin (%)" stroke="hsl(var(--success))" strokeWidth={2} dot={{ r: 3 }} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>

                <Card className="lg:col-span-2">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">Headcount growth</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ResponsiveContainer width="100%" height={180}>
                      <LineChart data={company.financials} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                        <XAxis dataKey="year" stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                        <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                        <ReTooltip
                          contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                        />
                        <Line type="monotone" dataKey="headcount" name="Headcount" stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 4 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              </>
            )}

            <Card className="lg:col-span-2">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Financial history</CardTitle>
              </CardHeader>
              <CardContent>
                {company.financials && company.financials.length > 0 ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Fiscal year</TableHead>
                        <TableHead className="text-right">Revenue</TableHead>
                        <TableHead className="text-right">EBIT margin</TableHead>
                        <TableHead className="text-right">Headcount</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {company.financials.map((f) => (
                        <TableRow key={f.year}>
                          <TableCell className="font-mono">{f.year}</TableCell>
                          <TableCell className="text-right font-mono tabular-nums">{f.revenueMSEK} MSEK</TableCell>
                          <TableCell className="text-right font-mono tabular-nums">{f.ebitMarginPct}%</TableCell>
                          <TableCell className="text-right font-mono tabular-nums">{f.headcount}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <EmptyHint message="No financial history recorded." />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Bid economics (assumptions)</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <Row label="Revenue range" value={company.financialAssumptions.revenueRange} />
                <Row label="Target margin" value={company.financialAssumptions.targetMargin} />
                <Row label="Max contract size" value={company.financialAssumptions.maxContractSize} />
                <p className="rounded-md bg-muted/40 p-2.5 text-xs text-muted-foreground">
                  These assumptions feed Delivery/CFO agent reasoning when scoring tenders.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Insurance coverage</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {company.insurance && company.insurance.length > 0 ? (
                  company.insurance.map((i) => (
                    <div key={i.type} className="flex items-start justify-between gap-3 border-b border-border/60 py-2 last:border-0">
                      <div className="min-w-0">
                        <div className="text-sm font-medium">{i.type}</div>
                        <div className="text-xs text-muted-foreground">{i.insurer}</div>
                      </div>
                      <span className="shrink-0 font-mono text-xs">{i.coverage}</span>
                    </div>
                  ))
                ) : (
                  <EmptyHint message="No insurance coverage recorded." />
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* SECURITY & ESG */}
          <TabsContent value="security" className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Security posture</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {company.securityPosture && company.securityPosture.length > 0 ? (
                  company.securityPosture.map((s) => (
                    <div key={s.item} className="flex items-start gap-3 border-b border-border/60 py-2 last:border-0">
                      {s.status === "Implemented" ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                      ) : s.status === "Partial" ? (
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                      ) : (
                        <Clock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium">{s.item}</div>
                        {s.note && <div className="text-xs text-muted-foreground">{s.note}</div>}
                      </div>
                      <Badge variant="outline" className="shrink-0 text-xs">{s.status}</Badge>
                    </div>
                  ))
                ) : (
                  <EmptyHint message="No security posture items recorded." />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-sm">
                  <Leaf className="h-4 w-4 text-emerald-600" /> Sustainability
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {company.sustainability ? (
                  <>
                    <SustainabilityBar label="CO₂ reduction vs. 2019" value={company.sustainability.co2ReductionPct} />
                    <SustainabilityBar label="Renewable energy" value={company.sustainability.renewableEnergyPct} />
                    <SustainabilityBar label="Gender diversity" value={company.sustainability.diversityPct} />
                    {company.sustainability.codeOfConductSigned && (
                      <div className="flex items-center gap-2 rounded-md bg-emerald-50 p-2.5 text-xs text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                        <FileCheck2 className="h-4 w-4" />
                        Code of Conduct signed by all consultants
                      </div>
                    )}
                  </>
                ) : (
                  <EmptyHint message="No sustainability metrics recorded." />
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>

      {draft ? (
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetContent className="flex w-full flex-col overflow-hidden p-0 sm:max-w-3xl">
            <SheetHeader className="shrink-0 border-b border-border/60 px-6 pt-6 pb-4">
              <SheetTitle>Edit Company Profile</SheetTitle>
              <SheetDescription>
                All fields below persist to Supabase on save. JSONB keys not
                represented in this form (rate cards, CV summaries, etc.) pass
                through untouched.
              </SheetDescription>
            </SheetHeader>

            <Tabs
              defaultValue="identity"
              className="flex flex-1 flex-col overflow-hidden"
            >
              <TabsList className="mx-6 mt-4 inline-flex h-auto w-fit justify-start gap-1 rounded-lg bg-muted/60 p-1">
                <TabsTrigger value="identity" className="px-3 py-1.5 text-xs">Identity</TabsTrigger>
                <TabsTrigger value="contact" className="px-3 py-1.5 text-xs">Contact & Team</TabsTrigger>
                <TabsTrigger value="capabilities" className="px-3 py-1.5 text-xs">Capabilities</TabsTrigger>
                <TabsTrigger value="references" className="px-3 py-1.5 text-xs">References</TabsTrigger>
                <TabsTrigger value="financials" className="px-3 py-1.5 text-xs">Financials</TabsTrigger>
                <TabsTrigger value="security" className="px-3 py-1.5 text-xs">Security & ESG</TabsTrigger>
              </TabsList>

              <div className="flex-1 overflow-y-auto px-6 py-5">
                {/* IDENTITY */}
                <TabsContent value="identity" className="mt-0 space-y-6">
                  <Section title="Website import">
                    <div className="space-y-3 rounded-md border border-border bg-muted/10 p-3">
                      <div className="flex flex-col gap-2 sm:flex-row">
                        <div className="relative flex-1">
                          <Globe className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                          <Input
                            className="pl-9"
                            value={websiteImportUrl}
                            placeholder="https://company.com"
                            onChange={(e) => setWebsiteImportUrl(e.target.value)}
                          />
                        </div>
                        <Button
                          variant="outline"
                          onClick={importWebsiteIntoDraft}
                          disabled={websiteImporting}
                        >
                          {websiteImporting ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Sparkles className="h-4 w-4" />
                          )}
                          Import
                        </Button>
                      </div>

                      {websiteImportPreview ? (
                        <WebsiteImportPreviewPanel
                          preview={websiteImportPreview}
                          onApply={applyWebsiteImportPreview}
                          onDiscard={() => setWebsiteImportPreview(null)}
                        />
                      ) : null}
                    </div>
                  </Section>

                  <Separator />

                  <Section title="General info">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field label="Display name">
                        <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                      </Field>
                      <Field label="Legal name">
                        <Input
                          value={draft.legalName ?? ""}
                          onChange={(e) => setDraft({ ...draft, legalName: e.target.value })}
                        />
                      </Field>
                      <Field label="Org. number">
                        <Input value={draft.orgNumber} onChange={(e) => setDraft({ ...draft, orgNumber: e.target.value })} />
                      </Field>
                      <Field label="VAT number">
                        <Input
                          value={draft.vatNumber ?? ""}
                          onChange={(e) => setDraft({ ...draft, vatNumber: e.target.value })}
                        />
                      </Field>
                      <Field label="Founded (year)">
                        <Input
                          type="number"
                          value={draft.founded ?? ""}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              founded: e.target.value ? Number(e.target.value) : undefined,
                            })
                          }
                        />
                      </Field>
                      <Field label="Size label">
                        <Input value={draft.size} onChange={(e) => setDraft({ ...draft, size: e.target.value })} />
                      </Field>
                      <Field label="Headcount">
                        <Input
                          type="number"
                          value={draft.headcount ?? ""}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              headcount: e.target.value ? Number(e.target.value) : undefined,
                            })
                          }
                        />
                      </Field>
                      <Field label="HQ">
                        <Input value={draft.hq} onChange={(e) => setDraft({ ...draft, hq: e.target.value })} />
                      </Field>
                    </div>
                  </Section>

                  <Separator />

                  <Section title="About" hint="Shown in the hero card on the profile page.">
                    <Textarea
                      rows={5}
                      value={draft.description ?? ""}
                      onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                    />
                  </Section>

                  <Separator />

                  <Section title="Industries served" hint="One per line">
                    <Textarea
                      rows={4}
                      value={(draft.industries ?? []).join("\n")}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          industries: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean),
                        })
                      }
                    />
                  </Section>
                </TabsContent>

                {/* CONTACT & TEAM */}
                <TabsContent value="contact" className="mt-0 space-y-6">
                  <Section title="Contact">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field label="Website">
                        <Input
                          value={draft.website ?? ""}
                          placeholder="https://…"
                          onChange={(e) => setDraft({ ...draft, website: e.target.value })}
                        />
                      </Field>
                      <Field label="Bid mailbox">
                        <Input
                          value={draft.email ?? ""}
                          placeholder="tenders@…"
                          onChange={(e) => setDraft({ ...draft, email: e.target.value })}
                        />
                      </Field>
                      <Field label="Phone">
                        <Input
                          value={draft.phone ?? ""}
                          onChange={(e) => setDraft({ ...draft, phone: e.target.value })}
                        />
                      </Field>
                    </div>
                  </Section>

                  <Separator />

                  <Section title="Offices" hint="One per line">
                    <Textarea
                      rows={4}
                      value={(draft.offices ?? []).join("\n")}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          offices: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean),
                        })
                      }
                    />
                  </Section>

                  <Separator />

                  <Section
                    title="Leadership"
                    action={
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            leadership: [
                              ...(draft.leadership ?? []),
                              { name: "", title: "", email: "" },
                            ],
                          })
                        }
                      >
                        <Plus className="h-3.5 w-3.5" /> Add
                      </Button>
                    }
                  >
                    <div className="space-y-2">
                      {(draft.leadership ?? []).map((p, i) => (
                        <div key={i} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2">
                          <Input
                            placeholder="Name"
                            value={p.name}
                            onChange={(e) => {
                              const next = [...(draft.leadership ?? [])];
                              next[i] = { ...next[i], name: e.target.value };
                              setDraft({ ...draft, leadership: next });
                            }}
                          />
                          <Input
                            placeholder="Title"
                            value={p.title}
                            onChange={(e) => {
                              const next = [...(draft.leadership ?? [])];
                              next[i] = { ...next[i], title: e.target.value };
                              setDraft({ ...draft, leadership: next });
                            }}
                          />
                          <Input
                            placeholder="email@…"
                            value={p.email ?? ""}
                            onChange={(e) => {
                              const next = [...(draft.leadership ?? [])];
                              next[i] = { ...next[i], email: e.target.value };
                              setDraft({ ...draft, leadership: next });
                            }}
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() =>
                              setDraft({
                                ...draft,
                                leadership: (draft.leadership ?? []).filter((_, idx) => idx !== i),
                              })
                            }
                          >
                            <Trash2 className="h-4 w-4 text-muted-foreground" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </Section>

                  <Separator />

                  <Section
                    title="Team composition"
                    hint="Feeds the capability breakdown on the Capabilities tab."
                    action={
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            teamComposition: [
                              ...(draft.teamComposition ?? []),
                              { role: "", count: 0, avgYears: 0 },
                            ],
                          })
                        }
                      >
                        <Plus className="h-3.5 w-3.5" /> Add
                      </Button>
                    }
                  >
                    <div className="space-y-2">
                      {(draft.teamComposition ?? []).map((t, i) => (
                        <div key={i} className="grid grid-cols-[1fr_90px_90px_auto] gap-2">
                          <Input
                            placeholder="Role"
                            value={t.role}
                            onChange={(e) => {
                              const next = [...(draft.teamComposition ?? [])];
                              next[i] = { ...next[i], role: e.target.value };
                              setDraft({ ...draft, teamComposition: next });
                            }}
                          />
                          <Input
                            type="number"
                            placeholder="Count"
                            value={t.count}
                            onChange={(e) => {
                              const next = [...(draft.teamComposition ?? [])];
                              next[i] = { ...next[i], count: Number(e.target.value) || 0 };
                              setDraft({ ...draft, teamComposition: next });
                            }}
                          />
                          <Input
                            type="number"
                            placeholder="Avg. yrs"
                            value={t.avgYears}
                            onChange={(e) => {
                              const next = [...(draft.teamComposition ?? [])];
                              next[i] = { ...next[i], avgYears: Number(e.target.value) || 0 };
                              setDraft({ ...draft, teamComposition: next });
                            }}
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() =>
                              setDraft({
                                ...draft,
                                teamComposition: (draft.teamComposition ?? []).filter(
                                  (_, idx) => idx !== i,
                                ),
                              })
                            }
                          >
                            <Trash2 className="h-4 w-4 text-muted-foreground" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </Section>
                </TabsContent>

                {/* CAPABILITIES */}
                <TabsContent value="capabilities" className="mt-0 space-y-6">
                  <Section title="Core capabilities" hint="One per line — shown on the Capabilities tab.">
                    <Textarea
                      rows={6}
                      value={draft.capabilities.join("\n")}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          capabilities: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean),
                        })
                      }
                    />
                  </Section>

                  <Separator />

                  <Section
                    title="Certifications"
                    action={
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            certifications: [
                              ...draft.certifications,
                              { name: "", issuer: "", validUntil: "" },
                            ],
                          })
                        }
                      >
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
                            onClick={() =>
                              setDraft({
                                ...draft,
                                certifications: draft.certifications.filter((_, idx) => idx !== i),
                              })
                            }
                          >
                            <Trash2 className="h-4 w-4 text-muted-foreground" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </Section>

                  <Separator />

                  <Section
                    title="Framework agreements"
                    action={
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            frameworkAgreements: [
                              ...(draft.frameworkAgreements ?? []),
                              { name: "", authority: "", validUntil: "", status: "Active" },
                            ],
                          })
                        }
                      >
                        <Plus className="h-3.5 w-3.5" /> Add
                      </Button>
                    }
                  >
                    <div className="space-y-2">
                      {(draft.frameworkAgreements ?? []).map((f, i) => (
                        <div key={i} className="grid grid-cols-[1.2fr_1fr_110px_110px_auto] gap-2">
                          <Input
                            placeholder="Agreement name"
                            value={f.name}
                            onChange={(e) => {
                              const next = [...(draft.frameworkAgreements ?? [])];
                              next[i] = { ...next[i], name: e.target.value };
                              setDraft({ ...draft, frameworkAgreements: next });
                            }}
                          />
                          <Input
                            placeholder="Authority"
                            value={f.authority}
                            onChange={(e) => {
                              const next = [...(draft.frameworkAgreements ?? [])];
                              next[i] = { ...next[i], authority: e.target.value };
                              setDraft({ ...draft, frameworkAgreements: next });
                            }}
                          />
                          <Input
                            placeholder="YYYY-MM-DD"
                            value={f.validUntil}
                            onChange={(e) => {
                              const next = [...(draft.frameworkAgreements ?? [])];
                              next[i] = { ...next[i], validUntil: e.target.value };
                              setDraft({ ...draft, frameworkAgreements: next });
                            }}
                          />
                          <select
                            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                            value={f.status}
                            onChange={(e) => {
                              const next = [...(draft.frameworkAgreements ?? [])];
                              next[i] = {
                                ...next[i],
                                status: e.target.value as "Active" | "Expiring" | "Expired",
                              };
                              setDraft({ ...draft, frameworkAgreements: next });
                            }}
                          >
                            <option value="Active">Active</option>
                            <option value="Expiring">Expiring</option>
                            <option value="Expired">Expired</option>
                          </select>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() =>
                              setDraft({
                                ...draft,
                                frameworkAgreements: (draft.frameworkAgreements ?? []).filter(
                                  (_, idx) => idx !== i,
                                ),
                              })
                            }
                          >
                            <Trash2 className="h-4 w-4 text-muted-foreground" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </Section>
                </TabsContent>

                {/* REFERENCES */}
                <TabsContent value="references" className="mt-0 space-y-6">
                  <Section
                    title="Reference assignments"
                    hint="Shown as cards on the References tab."
                    action={
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            references: [
                              ...draft.references,
                              {
                                client: "",
                                scope: "",
                                value: "",
                                year: new Date().getFullYear(),
                                sector: "",
                                duration: "",
                                outcome: "",
                              },
                            ],
                          })
                        }
                      >
                        <Plus className="h-3.5 w-3.5" /> Add
                      </Button>
                    }
                  >
                    <div className="space-y-4">
                      {draft.references.map((r, i) => (
                        <div key={i} className="rounded-md border border-border bg-muted/10 p-3">
                          <div className="mb-2 flex items-center justify-between">
                            <span className="text-xs font-semibold text-muted-foreground">
                              #{i + 1}
                            </span>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() =>
                                setDraft({
                                  ...draft,
                                  references: draft.references.filter((_, idx) => idx !== i),
                                })
                              }
                            >
                              <Trash2 className="h-4 w-4 text-muted-foreground" />
                            </Button>
                          </div>
                          <div className="grid gap-2 sm:grid-cols-2">
                            <Field label="Client">
                              <Input
                                value={r.client}
                                onChange={(e) => {
                                  const next = [...draft.references];
                                  next[i] = { ...next[i], client: e.target.value };
                                  setDraft({ ...draft, references: next });
                                }}
                              />
                            </Field>
                            <Field label="Sector">
                              <Input
                                value={r.sector ?? ""}
                                onChange={(e) => {
                                  const next = [...draft.references];
                                  next[i] = { ...next[i], sector: e.target.value };
                                  setDraft({ ...draft, references: next });
                                }}
                              />
                            </Field>
                            <Field label="Value">
                              <Input
                                value={r.value}
                                placeholder="12 MSEK"
                                onChange={(e) => {
                                  const next = [...draft.references];
                                  next[i] = { ...next[i], value: e.target.value };
                                  setDraft({ ...draft, references: next });
                                }}
                              />
                            </Field>
                            <Field label="Year">
                              <Input
                                type="number"
                                value={r.year}
                                onChange={(e) => {
                                  const next = [...draft.references];
                                  next[i] = { ...next[i], year: Number(e.target.value) || 0 };
                                  setDraft({ ...draft, references: next });
                                }}
                              />
                            </Field>
                            <Field label="Duration">
                              <Input
                                value={r.duration ?? ""}
                                placeholder="18 mo"
                                onChange={(e) => {
                                  const next = [...draft.references];
                                  next[i] = { ...next[i], duration: e.target.value };
                                  setDraft({ ...draft, references: next });
                                }}
                              />
                            </Field>
                            <Field label="Outcome">
                              <Input
                                value={r.outcome ?? ""}
                                placeholder="What landed?"
                                onChange={(e) => {
                                  const next = [...draft.references];
                                  next[i] = { ...next[i], outcome: e.target.value };
                                  setDraft({ ...draft, references: next });
                                }}
                              />
                            </Field>
                          </div>
                          <div className="mt-2">
                            <Field label="Scope">
                              <Textarea
                                rows={2}
                                value={r.scope}
                                onChange={(e) => {
                                  const next = [...draft.references];
                                  next[i] = { ...next[i], scope: e.target.value };
                                  setDraft({ ...draft, references: next });
                                }}
                              />
                            </Field>
                          </div>
                        </div>
                      ))}
                    </div>
                  </Section>
                </TabsContent>

                {/* FINANCIALS */}
                <TabsContent value="financials" className="mt-0 space-y-6">
                  <Section title="Bid economics (assumptions)">
                    <div className="grid gap-3 sm:grid-cols-3">
                      <Field label="Revenue range">
                        <Input
                          value={draft.financialAssumptions.revenueRange}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              financialAssumptions: {
                                ...draft.financialAssumptions,
                                revenueRange: e.target.value,
                              },
                            })
                          }
                        />
                      </Field>
                      <Field label="Target margin">
                        <Input
                          value={draft.financialAssumptions.targetMargin}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              financialAssumptions: {
                                ...draft.financialAssumptions,
                                targetMargin: e.target.value,
                              },
                            })
                          }
                        />
                      </Field>
                      <Field label="Max contract size">
                        <Input
                          value={draft.financialAssumptions.maxContractSize}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              financialAssumptions: {
                                ...draft.financialAssumptions,
                                maxContractSize: e.target.value,
                              },
                            })
                          }
                        />
                      </Field>
                    </div>
                  </Section>

                  <Separator />

                  <Section
                    title="Financial history"
                    hint="Drives the revenue / margin / headcount charts."
                    action={
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            financials: [
                              ...(draft.financials ?? []),
                              {
                                year: new Date().getFullYear(),
                                revenueMSEK: 0,
                                ebitMarginPct: 0,
                                headcount: 0,
                              },
                            ],
                          })
                        }
                      >
                        <Plus className="h-3.5 w-3.5" /> Add year
                      </Button>
                    }
                  >
                    <div className="space-y-2">
                      {(draft.financials ?? []).map((f, i) => (
                        <div key={i} className="grid grid-cols-[90px_1fr_1fr_1fr_auto] gap-2">
                          <Input
                            type="number"
                            placeholder="Year"
                            value={f.year}
                            onChange={(e) => {
                              const next = [...(draft.financials ?? [])];
                              next[i] = { ...next[i], year: Number(e.target.value) || 0 };
                              setDraft({ ...draft, financials: next });
                            }}
                          />
                          <Input
                            type="number"
                            placeholder="Revenue (MSEK)"
                            value={f.revenueMSEK}
                            onChange={(e) => {
                              const next = [...(draft.financials ?? [])];
                              next[i] = { ...next[i], revenueMSEK: Number(e.target.value) || 0 };
                              setDraft({ ...draft, financials: next });
                            }}
                          />
                          <Input
                            type="number"
                            step="0.1"
                            placeholder="EBIT %"
                            value={f.ebitMarginPct}
                            onChange={(e) => {
                              const next = [...(draft.financials ?? [])];
                              next[i] = {
                                ...next[i],
                                ebitMarginPct: Number(e.target.value) || 0,
                              };
                              setDraft({ ...draft, financials: next });
                            }}
                          />
                          <Input
                            type="number"
                            placeholder="Headcount"
                            value={f.headcount}
                            onChange={(e) => {
                              const next = [...(draft.financials ?? [])];
                              next[i] = { ...next[i], headcount: Number(e.target.value) || 0 };
                              setDraft({ ...draft, financials: next });
                            }}
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() =>
                              setDraft({
                                ...draft,
                                financials: (draft.financials ?? []).filter((_, idx) => idx !== i),
                              })
                            }
                          >
                            <Trash2 className="h-4 w-4 text-muted-foreground" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </Section>

                  <Separator />

                  <Section
                    title="Insurance"
                    action={
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            insurance: [
                              ...(draft.insurance ?? []),
                              { type: "", insurer: "", coverage: "" },
                            ],
                          })
                        }
                      >
                        <Plus className="h-3.5 w-3.5" /> Add
                      </Button>
                    }
                  >
                    <div className="space-y-2">
                      {(draft.insurance ?? []).map((ins, i) => (
                        <div key={i} className="grid grid-cols-[1.2fr_1fr_1fr_auto] gap-2">
                          <Input
                            placeholder="Type"
                            value={ins.type}
                            onChange={(e) => {
                              const next = [...(draft.insurance ?? [])];
                              next[i] = { ...next[i], type: e.target.value };
                              setDraft({ ...draft, insurance: next });
                            }}
                          />
                          <Input
                            placeholder="Insurer"
                            value={ins.insurer}
                            onChange={(e) => {
                              const next = [...(draft.insurance ?? [])];
                              next[i] = { ...next[i], insurer: e.target.value };
                              setDraft({ ...draft, insurance: next });
                            }}
                          />
                          <Input
                            placeholder="Coverage"
                            value={ins.coverage}
                            onChange={(e) => {
                              const next = [...(draft.insurance ?? [])];
                              next[i] = { ...next[i], coverage: e.target.value };
                              setDraft({ ...draft, insurance: next });
                            }}
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() =>
                              setDraft({
                                ...draft,
                                insurance: (draft.insurance ?? []).filter((_, idx) => idx !== i),
                              })
                            }
                          >
                            <Trash2 className="h-4 w-4 text-muted-foreground" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </Section>

                  <Separator />

                  <Section title="Bid pipeline performance">
                    <div className="grid gap-3 sm:grid-cols-3">
                      <Field label="Total bids">
                        <Input
                          type="number"
                          value={draft.bidStats?.totalBids ?? 0}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              bidStats: {
                                ...(draft.bidStats ?? {
                                  totalBids: 0, won: 0, lost: 0, inProgress: 0,
                                  winRatePct: 0, avgContractMSEK: 0,
                                }),
                                totalBids: Number(e.target.value) || 0,
                              },
                            })
                          }
                        />
                      </Field>
                      <Field label="Won">
                        <Input
                          type="number"
                          value={draft.bidStats?.won ?? 0}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              bidStats: {
                                ...(draft.bidStats ?? {
                                  totalBids: 0, won: 0, lost: 0, inProgress: 0,
                                  winRatePct: 0, avgContractMSEK: 0,
                                }),
                                won: Number(e.target.value) || 0,
                              },
                            })
                          }
                        />
                      </Field>
                      <Field label="Lost">
                        <Input
                          type="number"
                          value={draft.bidStats?.lost ?? 0}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              bidStats: {
                                ...(draft.bidStats ?? {
                                  totalBids: 0, won: 0, lost: 0, inProgress: 0,
                                  winRatePct: 0, avgContractMSEK: 0,
                                }),
                                lost: Number(e.target.value) || 0,
                              },
                            })
                          }
                        />
                      </Field>
                      <Field label="In progress">
                        <Input
                          type="number"
                          value={draft.bidStats?.inProgress ?? 0}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              bidStats: {
                                ...(draft.bidStats ?? {
                                  totalBids: 0, won: 0, lost: 0, inProgress: 0,
                                  winRatePct: 0, avgContractMSEK: 0,
                                }),
                                inProgress: Number(e.target.value) || 0,
                              },
                            })
                          }
                        />
                      </Field>
                      <Field label="Win rate %">
                        <Input
                          type="number"
                          value={draft.bidStats?.winRatePct ?? 0}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              bidStats: {
                                ...(draft.bidStats ?? {
                                  totalBids: 0, won: 0, lost: 0, inProgress: 0,
                                  winRatePct: 0, avgContractMSEK: 0,
                                }),
                                winRatePct: Number(e.target.value) || 0,
                              },
                            })
                          }
                        />
                      </Field>
                      <Field label="Avg. contract (MSEK)">
                        <Input
                          type="number"
                          value={draft.bidStats?.avgContractMSEK ?? 0}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              bidStats: {
                                ...(draft.bidStats ?? {
                                  totalBids: 0, won: 0, lost: 0, inProgress: 0,
                                  winRatePct: 0, avgContractMSEK: 0,
                                }),
                                avgContractMSEK: Number(e.target.value) || 0,
                              },
                            })
                          }
                        />
                      </Field>
                    </div>
                  </Section>
                </TabsContent>

                {/* SECURITY & ESG */}
                <TabsContent value="security" className="mt-0 space-y-6">
                  <Section
                    title="Security posture"
                    action={
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            securityPosture: [
                              ...(draft.securityPosture ?? []),
                              { item: "", status: "Implemented", note: "" },
                            ],
                          })
                        }
                      >
                        <Plus className="h-3.5 w-3.5" /> Add
                      </Button>
                    }
                  >
                    <div className="space-y-2">
                      {(draft.securityPosture ?? []).map((s, i) => (
                        <div key={i} className="grid grid-cols-[1.2fr_1fr_120px_auto] gap-2">
                          <Input
                            placeholder="Item"
                            value={s.item}
                            onChange={(e) => {
                              const next = [...(draft.securityPosture ?? [])];
                              next[i] = { ...next[i], item: e.target.value };
                              setDraft({ ...draft, securityPosture: next });
                            }}
                          />
                          <Input
                            placeholder="Note"
                            value={s.note ?? ""}
                            onChange={(e) => {
                              const next = [...(draft.securityPosture ?? [])];
                              next[i] = { ...next[i], note: e.target.value };
                              setDraft({ ...draft, securityPosture: next });
                            }}
                          />
                          <select
                            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                            value={s.status}
                            onChange={(e) => {
                              const next = [...(draft.securityPosture ?? [])];
                              next[i] = {
                                ...next[i],
                                status: e.target.value as "Implemented" | "Partial" | "Planned",
                              };
                              setDraft({ ...draft, securityPosture: next });
                            }}
                          >
                            <option value="Implemented">Implemented</option>
                            <option value="Partial">Partial</option>
                            <option value="Planned">Planned</option>
                          </select>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() =>
                              setDraft({
                                ...draft,
                                securityPosture: (draft.securityPosture ?? []).filter(
                                  (_, idx) => idx !== i,
                                ),
                              })
                            }
                          >
                            <Trash2 className="h-4 w-4 text-muted-foreground" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </Section>

                  <Separator />

                  <Section title="Sustainability">
                    <div className="grid gap-3 sm:grid-cols-3">
                      <Field label="CO₂ reduction vs. 2019 (%)">
                        <Input
                          type="number"
                          value={draft.sustainability?.co2ReductionPct ?? 0}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              sustainability: {
                                ...(draft.sustainability ?? {
                                  co2ReductionPct: 0, renewableEnergyPct: 0,
                                  diversityPct: 0, codeOfConductSigned: false,
                                }),
                                co2ReductionPct: Number(e.target.value) || 0,
                              },
                            })
                          }
                        />
                      </Field>
                      <Field label="Renewable energy (%)">
                        <Input
                          type="number"
                          value={draft.sustainability?.renewableEnergyPct ?? 0}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              sustainability: {
                                ...(draft.sustainability ?? {
                                  co2ReductionPct: 0, renewableEnergyPct: 0,
                                  diversityPct: 0, codeOfConductSigned: false,
                                }),
                                renewableEnergyPct: Number(e.target.value) || 0,
                              },
                            })
                          }
                        />
                      </Field>
                      <Field label="Gender diversity (%)">
                        <Input
                          type="number"
                          value={draft.sustainability?.diversityPct ?? 0}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              sustainability: {
                                ...(draft.sustainability ?? {
                                  co2ReductionPct: 0, renewableEnergyPct: 0,
                                  diversityPct: 0, codeOfConductSigned: false,
                                }),
                                diversityPct: Number(e.target.value) || 0,
                              },
                            })
                          }
                        />
                      </Field>
                    </div>
                    <label className="mt-3 flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={draft.sustainability?.codeOfConductSigned ?? false}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            sustainability: {
                              ...(draft.sustainability ?? {
                                co2ReductionPct: 0, renewableEnergyPct: 0,
                                diversityPct: 0, codeOfConductSigned: false,
                              }),
                              codeOfConductSigned: e.target.checked,
                            },
                          })
                        }
                      />
                      Code of Conduct signed by all consultants
                    </label>
                  </Section>
                </TabsContent>
              </div>
            </Tabs>

            <SheetFooter className="shrink-0 gap-2 border-t border-border/60 px-6 py-4 sm:gap-2">
              <Button variant="outline" onClick={() => setOpen(false)} disabled={saving}>
                Cancel
              </Button>
              <Button onClick={save} disabled={saving}>
                {saving ? "Saving…" : "Save changes"}
              </Button>
            </SheetFooter>
          </SheetContent>
        </Sheet>
      ) : null}
    </>
  );
}

function WebsiteImportPreviewPanel({
  preview,
  onApply,
  onDiscard,
}: {
  preview: CompanyWebsiteImportPreview;
  onApply: () => void;
  onDiscard: () => void;
}) {
  const patch = preview.profile_patch;
  const summary = [
    patch.description ? "Description" : null,
    patch.email ? "Email" : null,
    patch.phone ? "Phone" : null,
    patch.offices?.length ? `${patch.offices.length} offices` : null,
    patch.industries?.length ? `${patch.industries.length} industries` : null,
    patch.capabilities?.length ? `${patch.capabilities.length} capabilities` : null,
    patch.certifications?.length
      ? `${patch.certifications.length} certifications`
      : null,
    patch.references?.length ? `${patch.references.length} references` : null,
    patch.securityPosture?.length
      ? `${patch.securityPosture.length} security items`
      : null,
  ].filter((item): item is string => item !== null);

  return (
    <div className="rounded-md border border-primary/20 bg-background p-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {summary.length > 0 ? (
              summary.map((item) => (
                <Badge key={item} variant="secondary" className="font-normal">
                  {item}
                </Badge>
              ))
            ) : (
              <Badge variant="outline" className="font-normal">
                Website only
              </Badge>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {preview.pages.map((page) => (
              <a
                key={page.url}
                href={page.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex max-w-full items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-primary"
              >
                <ExternalLink className="h-3 w-3 shrink-0" />
                <span className="truncate">
                  {page.title || page.url.replace(/^https?:\/\//, "")}
                </span>
              </a>
            ))}
          </div>
          {preview.warnings.length > 0 ? (
            <div className="space-y-1">
              {preview.warnings.map((warning) => (
                <div
                  key={warning}
                  className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-300"
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>{warning}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="ghost" size="sm" onClick={onDiscard}>
            Discard
          </Button>
          <Button size="sm" onClick={onApply}>
            <CheckCircle2 className="h-4 w-4" />
            Apply
          </Button>
        </div>
      </div>
    </div>
  );
}

function KpiCard({
  icon, label, value, sub, tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  tone?: "positive" | "negative";
}) {
  return (
    <Card className="border-border/60 transition-shadow hover:shadow-sm">
      <CardContent className="p-5">
        <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-muted/60 text-muted-foreground">
            {icon}
          </span>
          {label}
        </div>
        <div className={`mt-3 text-2xl font-bold leading-none tabular-nums ${
          tone === "positive" ? "text-emerald-600 dark:text-emerald-400" :
          tone === "negative" ? "text-destructive" : ""
        }`}>
          {value}
        </div>
        {sub && <div className="mt-1.5 text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function PipelineStat({ label, value, tone }: { label: string; value: string | number; tone?: "positive" | "negative" }) {
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`mt-1 text-xl font-bold tabular-nums ${
        tone === "positive" ? "text-emerald-600 dark:text-emerald-400" :
        tone === "negative" ? "text-destructive" : ""
      }`}>
        {value}
      </div>
    </div>
  );
}

function ContactRow({ icon, label, value, href }: { icon: React.ReactNode; label: string; value: string; href?: string }) {
  const content = (
    <div className="flex items-center gap-2.5">
      <span className="text-muted-foreground">{icon}</span>
      <div className="min-w-0">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className="truncate text-sm font-medium">{value}</div>
      </div>
    </div>
  );
  return href ? <a href={href} className="block hover:text-primary">{content}</a> : content;
}

function SustainabilityBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="font-medium">{label}</span>
        <span className="font-mono tabular-nums text-muted-foreground">{value}%</span>
      </div>
      <Progress value={value} className="h-1.5" />
    </div>
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

function EmptyHint({ message }: { message: string }) {
  return <p className="text-xs text-muted-foreground">{message}</p>;
}
