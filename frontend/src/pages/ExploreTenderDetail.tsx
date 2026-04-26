import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowLeft,
  Bookmark,
  BookmarkCheck,
  Building2,
  Calendar,
  Clock,
  Download,
  ExternalLink,
  FileText,
  Globe,
  Hourglass,
  Inbox,
  Landmark,
  Loader2,
  MapPin,
  Scale,
  ShieldCheck,
  Tag,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { fetchExploreTenders, fetchNoticeDetail } from "@/lib/api";
import {
  daysUntil,
  externalTenders as mockTenders,
  sourceMeta,
  type ExternalSource,
  type ExternalTender,
} from "@/data/exploreMock";
import {
  getSavedTenderIds,
  importExternalTender,
  isTenderImported,
  toggleSavedTender,
} from "@/lib/explore";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

function SourceBadge({ source }: { source: ExternalSource }) {
  const meta = sourceMeta(source);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1",
        meta.bg,
        meta.text,
        meta.ring,
      )}
    >
      {meta.label}
    </span>
  );
}

function ClosingPill({ deadline }: { deadline: string }) {
  const days = daysUntil(deadline);
  if (days <= -2) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
        {days === -999 ? "—" : "Closed"}
      </span>
    );
  }
  const tone =
    days <= 3
      ? "bg-danger/10 text-danger ring-danger/20"
      : days <= 10
      ? "bg-warning/10 text-warning ring-warning/20"
      : "bg-muted text-muted-foreground ring-border";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium tabular-nums ring-1",
        tone,
      )}
    >
      <Hourglass className="h-3 w-3" />
      {days === 0 ? "Closes today" : `Closes in ${days}d`}
    </span>
  );
}

function formatValue(value: number, currency: "SEK" | "EUR") {
  if (!value || !isFinite(value) || value <= 0) return "Not disclosed";
  return `${value.toLocaleString("sv-SE")} M${currency}`;
}

function safeFormatDate(iso: string | undefined): string {
  if (!iso) return "Not specified";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? "Not specified"
    : d.toLocaleDateString("sv-SE", { year: "numeric", month: "short", day: "numeric" });
}

function Fact({
  icon: Icon,
  label,
  value,
  tone = "default",
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  tone?: "default" | "warning" | "danger";
}) {
  const valueTone = {
    default: "text-foreground",
    warning: "text-warning",
    danger: "text-danger",
  }[tone];
  return (
    <div className="min-w-0">
      <p className="inline-flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <Icon className="h-3 w-3" />
        {label}
      </p>
      <p className={cn("mt-1 truncate text-sm font-semibold tabular-nums", valueTone)}>{value}</p>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className={cn("text-right text-foreground", mono && "font-mono text-xs tabular-nums")}>
        {value}
      </dd>
    </div>
  );
}

export default function ExploreTenderDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const [savedIds, setSavedIds] = useState<string[]>(() => getSavedTenderIds());

  // Tender may be passed via router state (from sheet "View full details") — renders instantly.
  const stateTender = (location.state as { tender?: ExternalTender } | null)?.tender ?? null;

  const { data: tenders = [], isLoading } = useQuery({
    queryKey: ["explore-tenders"],
    queryFn: fetchExploreTenders,
    staleTime: 30_000,
  });

  const decodedId = id ? decodeURIComponent(id) : null;
  const tender: ExternalTender | null = useMemo(() => {
    if (!decodedId) return stateTender;
    return (
      tenders.find((t) => t.id === decodedId) ??
      mockTenders.find((t) => t.id === decodedId) ??
      (stateTender?.id === decodedId ? stateTender : null)
    );
  }, [decodedId, tenders, stateTender]);

  // Fetch full XML detail from TED when we have a publication number.
  // This runs in parallel — the page renders with search data immediately,
  // then enriches once the XML parse comes back.
  const pubNumber = tender?.publicationNumber ?? null;
  const { data: xmlDetail } = useQuery({
    queryKey: ["notice-detail", pubNumber],
    queryFn: () => fetchNoticeDetail(pubNumber!),
    enabled: !!pubNumber,
    staleTime: 5 * 60_000,
  });

  // Merge: XML data wins over search data for richer fields, but never replaces
  // the core identity fields (id, title, buyer, etc.) from the search result.
  const enriched: ExternalTender | null = useMemo(() => {
    if (!tender) return null;
    if (!xmlDetail) return tender;
    return {
      ...tender,
      summary: xmlDetail.summary || tender.summary,
      requirements: xmlDetail.requirements?.length ? xmlDetail.requirements : tender.requirements,
      evaluationCriteria: xmlDetail.evaluationCriteria?.length ? xmlDetail.evaluationCriteria : tender.evaluationCriteria,
      contractDurationMonths: xmlDetail.contractDurationMonths ?? tender.contractDurationMonths,
      contactName: xmlDetail.contactName ?? tender.contactName,
      contactEmail: xmlDetail.contactEmail ?? tender.contactEmail,
      submissionLanguage: xmlDetail.submissionLanguage ?? tender.submissionLanguage,
      languages: xmlDetail.languages ?? tender.languages,
      lots: xmlDetail.lots ?? tender.lots,
      framework: xmlDetail.framework ?? tender.framework,
      certifications: xmlDetail.certifications ?? tender.certifications,
    };
  }, [tender, xmlDetail]);

  if (isLoading && !tender) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!enriched) {
    return (
      <div className="mx-auto max-w-2xl py-16 text-center">
        <p className="text-sm text-muted-foreground">Tender not found.</p>
        <Button asChild variant="outline" className="mt-4">
          <Link to="/procurements/explore">
            <ArrowLeft className="h-4 w-4" />
            Back to Explore
          </Link>
        </Button>
      </div>
    );
  }

  const saved = savedIds.includes(enriched.id);
  const imported = user?.companyId ? isTenderImported(enriched.id, user.companyId) : false;
  const daysRaw = daysUntil(enriched.deadline);
  const days = daysRaw === -999 ? -1 : daysRaw;

  const handleToggleSave = () => {
    const nowSaved = toggleSavedTender(enriched.id);
    setSavedIds(getSavedTenderIds());
    toast(nowSaved ? "Saved for later" : "Removed from saved", { description: enriched.title });
  };

  const handleImport = () => {
    if (!user?.companyId) {
      toast.error("Cannot import", { description: "No company context — please log in." });
      return;
    }
    if (imported) {
      navigate("/procurements");
      return;
    }
    importExternalTender(enriched, user.companyId);
    toast.success("Imported — opening in My Procurements", { description: enriched.title });
    setTimeout(() => navigate("/procurements"), 250);
  };

  // Generate a base description from available fields if the XML didn't provide one
  const description =
    enriched.summary ||
    [
      `${enriched.buyer} is procuring a ${enriched.contractType.toLowerCase()} contract in ${enriched.country}.`,
      enriched.procedureType && `Procedure: ${enriched.procedureType}.`,
      enriched.cpvCodes.length > 0 && `CPV: ${enriched.cpvCodes.slice(0, 3).join(", ")}${enriched.cpvCodes.length > 3 ? ` +${enriched.cpvCodes.length - 3} more` : ""}.`,
      enriched.estimatedValueMSEK > 0 && `Estimated value: ${enriched.estimatedValueMSEK} M${enriched.currency}.`,
      enriched.deadline && `Submission deadline: ${safeFormatDate(enriched.deadline)}.`,
    ]
      .filter(Boolean)
      .join(" ");

  const loadingXml = !!pubNumber && !xmlDetail;

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link
          to="/procurements/explore"
          className="inline-flex items-center gap-1 hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Explore Procurements
        </Link>
        <span className="text-muted-foreground/50">/</span>
        <span className="truncate text-foreground">{enriched.title}</span>
      </div>

      {/* Hero */}
      <Card className="overflow-hidden">
        <div className="border-b border-border bg-gradient-to-br from-muted/40 via-card to-card p-6">
          <div className="flex flex-wrap items-center gap-2">
            <SourceBadge source={enriched.source} />
            <ClosingPill deadline={enriched.deadline} />
            <Badge variant="secondary" className="font-normal">{enriched.procedureType}</Badge>
            <Badge variant="secondary" className="font-normal">{enriched.contractType}</Badge>
            {enriched.framework && <Badge variant="secondary" className="font-normal">Framework</Badge>}
            {(enriched.lots ?? 1) > 1 && <Badge variant="secondary" className="font-normal">{enriched.lots} lots</Badge>}
            {imported && (
              <Badge className="bg-success/10 text-success ring-1 ring-success/20 hover:bg-success/10">
                <Inbox className="h-3 w-3" />
                Imported
              </Badge>
            )}
          </div>

          <h1 className="mt-3 text-2xl font-semibold leading-tight tracking-tight text-foreground sm:text-3xl">
            {enriched.title}
          </h1>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <Building2 className="h-3.5 w-3.5" />
              {enriched.buyer}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5" />
              {enriched.country}{enriched.nutsCode ? ` · ${enriched.nutsCode}` : ""}
            </span>
            {enriched.sourceUrl && (
              <a
                href={enriched.sourceUrl}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Original notice
              </a>
            )}
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-2">
            <Button size="lg" onClick={handleImport} disabled={imported} className="shadow-sm">
              <Download className="h-4 w-4" />
              {imported ? "Already imported" : "Import to my procurements"}
            </Button>
            <Button variant="outline" size="lg" onClick={handleToggleSave}>
              {saved ? (
                <><BookmarkCheck className="h-4 w-4" /> Saved</>
              ) : (
                <><Bookmark className="h-4 w-4" /> Save for later</>
              )}
            </Button>
            {enriched.sourceUrl && (
              <Button variant="ghost" size="lg" asChild>
                <a href={enriched.sourceUrl} target="_blank" rel="noreferrer noopener">
                  <Globe className="h-4 w-4" />
                  Open on TED
                </a>
              </Button>
            )}
          </div>
        </div>

        {/* Key facts */}
        <CardContent className="grid grid-cols-2 gap-x-6 gap-y-4 p-6 sm:grid-cols-3 lg:grid-cols-5">
          <Fact icon={Scale} label="Estimated value" value={formatValue(enriched.estimatedValueMSEK, enriched.currency)} />
          <Fact icon={Calendar} label="Published" value={safeFormatDate(enriched.publishedAt)} />
          <Fact
            icon={Hourglass}
            label="Deadline"
            value={safeFormatDate(enriched.deadline)}
            tone={days >= 0 && days <= 3 ? "danger" : days >= 0 && days <= 10 ? "warning" : "default"}
          />
          <Fact icon={Clock} label="Time remaining" value={days < 0 ? "Closed" : `${days} days`} />
          <Fact icon={Landmark} label="Procedure" value={enriched.procedureType} />
        </CardContent>
      </Card>

      {/* Body */}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {/* Description */}
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold text-foreground">About this tender</h2>
                {loadingXml && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
              </div>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{description}</p>
              {!enriched.summary && !loadingXml && (
                <p className="mt-2 text-xs italic text-muted-foreground/60">
                  Full notice text available on TED — use "Open on TED" above.
                </p>
              )}
            </CardContent>
          </Card>

          {/* Requirements — only shown when present */}
          {enriched.requirements.length > 0 && (
            <Card>
              <CardContent className="p-6">
                <h2 className="text-base font-semibold text-foreground">Selection criteria</h2>
                <ul className="mt-3 space-y-2.5">
                  {enriched.requirements.map((r, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-3 rounded-md border border-border bg-muted/20 px-3 py-2.5 text-sm text-foreground"
                    >
                      <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold tabular-nums text-primary">
                        {i + 1}
                      </span>
                      <span className="leading-snug">{r}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {/* Evaluation criteria — only shown when present */}
          {enriched.evaluationCriteria && enriched.evaluationCriteria.length > 0 && (
            <Card>
              <CardContent className="p-6">
                <h2 className="text-base font-semibold text-foreground">Award criteria</h2>
                <ul className="mt-3 space-y-2">
                  {enriched.evaluationCriteria.map((c, i) => (
                    <li key={i} className="flex items-start justify-between gap-3 text-sm text-foreground">
                      <span className="leading-snug">{c.name}</span>
                      {c.weight > 0 && (
                        <span className="shrink-0 font-mono tabular-nums text-muted-foreground">{c.weight}%</span>
                      )}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {/* Attachments — only shown when present */}
          {enriched.attachments.length > 0 && (
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <h2 className="text-base font-semibold text-foreground">Source documents</h2>
                  <span className="text-xs text-muted-foreground">{enriched.attachments.length} files</span>
                </div>
                <div className="mt-3 space-y-2">
                  {enriched.attachments.map((a) => (
                    <div
                      key={a.filename}
                      className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2.5 text-sm"
                    >
                      <span className="flex items-center gap-2 truncate text-foreground">
                        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">{a.filename}</span>
                      </span>
                      <span className="ml-2 shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                        {a.sizeKB} KB
                      </span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* CPV codes */}
          {enriched.cpvCodes.length > 0 && (
            <Card>
              <CardContent className="p-6">
                <h2 className="text-base font-semibold text-foreground">CPV classification</h2>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {enriched.cpvCodes.map((code) => (
                    <Badge key={code} variant="secondary" className="font-mono">
                      <Tag className="h-3 w-3" />
                      {code}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Notice details */}
          <Card>
            <CardContent className="p-6">
              <h2 className="inline-flex items-center gap-2 text-base font-semibold text-foreground">
                <ShieldCheck className="h-4 w-4 text-primary" />
                Notice details
              </h2>
              <dl className="mt-3 space-y-2 text-sm">
                <Row label="Source" value={sourceMeta(enriched.source).label} />
                <Row label="Country" value={enriched.country} />
                {enriched.nutsCode && <Row label="NUTS region" value={enriched.nutsCode} />}
                <Row label="Contract type" value={enriched.contractType} />
                <Row label="Procedure" value={enriched.procedureType} />
                <Row label="Currency" value={enriched.currency} />
                {enriched.contractDurationMonths && (
                  <Row label="Duration" value={`${enriched.contractDurationMonths} months`} />
                )}
                {(enriched.lots ?? 1) > 1 && <Row label="Lots" value={String(enriched.lots)} />}
                {enriched.framework && <Row label="Framework" value="Yes" />}
                {enriched.submissionLanguage && <Row label="Submission language" value={enriched.submissionLanguage} />}
                <Row label="Reference" value={enriched.id} mono />
              </dl>
              {enriched.sourceUrl && (
                <>
                  <Separator className="my-4" />
                  <a
                    href={enriched.sourceUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    View on TED
                  </a>
                </>
              )}
            </CardContent>
          </Card>

          {/* Contracting authority */}
          <Card>
            <CardContent className="p-6">
              <h2 className="text-base font-semibold text-foreground">Contracting authority</h2>
              <div className="mt-3 space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-foreground">{enriched.buyer}</span>
                </div>
                <div className="flex items-center gap-2">
                  <MapPin className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-foreground">{enriched.country}{enriched.nutsCode ? ` · ${enriched.nutsCode}` : ""}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* CTA */}
          <Card className="border-primary/30 bg-primary/5">
            <CardContent className="p-6">
              <h2 className="text-base font-semibold text-foreground">Ready to bid?</h2>
              <p className="mt-1.5 text-sm text-muted-foreground">
                Import this tender to start the AI analysis pipeline and generate a bid recommendation.
              </p>
              <Button onClick={handleImport} disabled={imported} className="mt-4 w-full">
                <Download className="h-4 w-4" />
                {imported ? "Already imported" : "Import to my procurements"}
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
