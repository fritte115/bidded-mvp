export type ExternalSource = "TED" | "Clira" | "Mercell" | "Visma";

export interface ExternalAttachment {
  filename: string;
  sizeKB: number;
}

export interface ExternalTender {
  id: string;
  source: ExternalSource;
  title: string;
  buyer: string;
  country: string;
  nutsCode: string;
  cpvCodes: string[];
  procedureType: "Open" | "Restricted" | "Negotiated" | "Competitive Dialogue";
  contractType: "Services" | "Supplies" | "Works";
  estimatedValueMSEK: number;
  currency: "SEK" | "EUR";
  publishedAt: string;
  deadline: string;
  summary: string;
  requirements: string[];
  sourceUrl: string;
  attachments: ExternalAttachment[];

  publicationNumber?: string;
  contractStart?: string;
  contractDurationMonths?: number;
  extensionOptions?: string;
  languages?: string[];
  submissionLanguage?: string;
  certifications?: string[];
  securityClearance?: string;
  evaluationCriteria?: { name: string; weight: number }[];
  eligibility?: string[];
  lots?: number;
  framework?: boolean;
  contactName?: string;
  contactEmail?: string;
}

export function enrichTender(t: ExternalTender): Required<
  Pick<
    ExternalTender,
    | "contractStart"
    | "contractDurationMonths"
    | "extensionOptions"
    | "languages"
    | "submissionLanguage"
    | "certifications"
    | "securityClearance"
    | "evaluationCriteria"
    | "eligibility"
    | "lots"
    | "framework"
    | "contactName"
    | "contactEmail"
  >
> {
  const isSE = t.country === "SE";
  const isDefence = /försvar|polis|säkerhet|cyber|defence|police|defense/i.test(`${t.buyer} ${t.title}`);
  const isHealth = /region|karolinska|sjukhus|health|ehr|patient/i.test(`${t.buyer} ${t.title}`);
  const isCloud = /cloud|hosting|kubernetes|devops|platform|saas/i.test(`${t.title}`);
  const baseCerts = ["ISO/IEC 27001:2022", "ISO 9001:2015"];
  if (isCloud) baseCerts.push("ISO/IEC 27017", "ISO/IEC 27018");
  if (isHealth) baseCerts.push("ISO 13485", "ISO/IEC 27799");
  if (isDefence) baseCerts.push("ISO/IEC 27001 + Annex A.18");

  const securityClearance =
    t.securityClearance ??
    (isDefence
      ? /försvarsmakten/i.test(t.buyer)
        ? "SUA Nivå 1 (Top Secret)"
        : "SUA Nivå 2 (Secret)"
      : isSE
      ? "Säkerhetsskyddad upphandling — ej tillämplig"
      : "Not required");

  const evaluation = t.evaluationCriteria ?? [
    { name: "Technical solution", weight: 40 },
    { name: "Team competence & references", weight: 25 },
    { name: "Price", weight: 25 },
    { name: "Sustainability & ESG", weight: 10 },
  ];

  const eligibility = t.eligibility ?? [
    "Registered for F-skatt and VAT in country of operation",
    "No tax debts or bankruptcy proceedings (verified via Skatteverket / equivalent)",
    "No exclusion grounds under LOU 13 kap. / EU Directive 2014/24 art. 57",
    "Minimum annual turnover of 2× contract value over last 3 years",
    "Professional liability insurance ≥ 10 MSEK",
  ];

  return {
    contractStart: t.contractStart ?? (t.deadline
      ? new Date(new Date(t.deadline).getTime() + 60 * 24 * 60 * 60 * 1000).toISOString()
      : new Date(Date.now() + 90 * 24 * 60 * 60 * 1000).toISOString()),
    contractDurationMonths: t.contractDurationMonths ?? (isCloud ? 48 : isDefence ? 36 : 24),
    extensionOptions: t.extensionOptions ?? "2 × 12 months at the buyer's discretion",
    languages: t.languages ?? (isSE ? ["Swedish", "English"] : ["English"]),
    submissionLanguage: t.submissionLanguage ?? (isSE ? "Swedish" : "English"),
    certifications: t.certifications ?? baseCerts,
    securityClearance,
    evaluationCriteria: evaluation,
    eligibility,
    lots: t.lots ?? (isCloud ? 3 : 1),
    framework: t.framework ?? /framework|ramavtal/i.test(t.title),
    contactName: t.contactName ?? "Procurement officer",
    contactEmail:
      t.contactEmail ??
      `procurement@${t.buyer.toLowerCase().replace(/[^a-z0-9]+/g, "").slice(0, 18)}.se`,
  };
}

const SOURCE_META: Record<ExternalSource, { label: string; bg: string; text: string; ring: string }> = {
  TED: { label: "TED", bg: "bg-info/10", text: "text-info", ring: "ring-info/20" },
  Clira: { label: "Clira", bg: "bg-primary/10", text: "text-primary", ring: "ring-primary/20" },
  Mercell: { label: "Mercell", bg: "bg-success/10", text: "text-success", ring: "ring-success/20" },
  Visma: { label: "Visma Opic", bg: "bg-warning/10", text: "text-warning", ring: "ring-warning/20" },
};

export function sourceMeta(source: ExternalSource) {
  return SOURCE_META[source];
}

export function daysUntil(iso: string): number {
  if (!iso) return -999;
  const ms = new Date(iso).getTime() - Date.now();
  if (isNaN(ms)) return -999;
  return Math.ceil(ms / (1000 * 60 * 60 * 24));
}

const NOW = Date.now();
const DAY = 1000 * 60 * 60 * 24;
const iso = (offsetDays: number) => new Date(NOW + offsetDays * DAY).toISOString();

export const externalTenders: ExternalTender[] = [
  {
    id: "ted-2026-001",
    source: "TED",
    title: "Cloud Hosting & Managed Services Framework 2026–2030",
    buyer: "European Commission — DG DIGIT",
    country: "EU",
    nutsCode: "BE100",
    cpvCodes: ["72415000", "72222300"],
    procedureType: "Open",
    contractType: "Services",
    estimatedValueMSEK: 850,
    currency: "EUR",
    publishedAt: iso(-3),
    deadline: iso(42),
    summary:
      "Multi-lot framework for hosting EU institution workloads in sovereign cloud environments across Member States. Lots cover IaaS, PaaS, and managed Kubernetes.",
    requirements: [
      "ISO/IEC 27001 and 27017 certification",
      "EU data residency with sovereign cloud control plane",
      "Minimum 50 MEUR turnover in last 3 years",
      "Three references for public-sector hosting >10 MEUR",
    ],
    sourceUrl: "https://ted.europa.eu/notice/2026-001",
    attachments: [
      { filename: "tender-notice.pdf", sizeKB: 412 },
      { filename: "annex-1-technical-spec.pdf", sizeKB: 1280 },
      { filename: "annex-2-pricing-template.xlsx", sizeKB: 64 },
    ],
  },
  {
    id: "ted-2026-002",
    source: "TED",
    title: "Identity & Access Management Platform — Renewal",
    buyer: "Polismyndigheten",
    country: "SE",
    nutsCode: "SE110",
    cpvCodes: ["48732000", "72253000"],
    procedureType: "Restricted",
    contractType: "Services",
    estimatedValueMSEK: 96,
    currency: "SEK",
    publishedAt: iso(-1),
    deadline: iso(5),
    summary:
      "Renewal of the national police IAM platform with federation, MFA, and privileged access controls. Strict security clearance applies (SUA Nivå 2).",
    requirements: [
      "Security clearance for all consultants (SUA Nivå 2)",
      "ISO 27001 certification",
      "Two references with Swedish authorities",
      "Swedish-speaking architect available on-site Stockholm",
    ],
    sourceUrl: "https://ted.europa.eu/notice/2026-002",
    attachments: [
      { filename: "förfrågningsunderlag.pdf", sizeKB: 624 },
      { filename: "bilaga-1-säkerhetskrav.pdf", sizeKB: 312 },
    ],
  },
  {
    id: "clira-2026-014",
    source: "Clira",
    title: "DevOps Platform Engineering — Trafikverket",
    buyer: "Trafikverket",
    country: "SE",
    nutsCode: "SE121",
    cpvCodes: ["72500000", "72200000"],
    procedureType: "Open",
    contractType: "Services",
    estimatedValueMSEK: 38,
    currency: "SEK",
    publishedAt: iso(-2),
    deadline: iso(18),
    summary:
      "Senior DevOps and platform engineers for the agency-wide internal developer platform. Kubernetes, GitOps, and observability stack.",
    requirements: [
      "Three references on Kubernetes platforms in regulated sectors",
      "Argo CD and Crossplane experience",
      "Hourly cap 1 450 SEK for senior consultants",
    ],
    sourceUrl: "https://clira.se/tender/2026-014",
    attachments: [
      { filename: "uppdragsbeskrivning.pdf", sizeKB: 240 },
      { filename: "bilaga-prislista.xlsx", sizeKB: 32 },
    ],
  },
  {
    id: "clira-2026-022",
    source: "Clira",
    title: "Microsoft 365 Rollout — Region Skåne",
    buyer: "Region Skåne",
    country: "SE",
    nutsCode: "SE224",
    cpvCodes: ["48214000", "80533100"],
    procedureType: "Open",
    contractType: "Services",
    estimatedValueMSEK: 22,
    currency: "SEK",
    publishedAt: iso(-5),
    deadline: iso(28),
    summary:
      "Rollout of Microsoft 365 to ~18 000 healthcare staff including change management, training, and Teams telephony.",
    requirements: [
      "Demonstrated M365 rollouts for >10 000 users",
      "GDPR/Patientdatalagen compliance plan",
      "Swedish-speaking trainers",
    ],
    sourceUrl: "https://clira.se/tender/2026-022",
    attachments: [{ filename: "anbudsinbjudan.pdf", sizeKB: 380 }],
  },
  {
    id: "mercell-2026-103",
    source: "Mercell",
    title: "Cybersecurity Operations Centre — Försvarsmakten",
    buyer: "Försvarsmakten",
    country: "SE",
    nutsCode: "SE110",
    cpvCodes: ["72212732", "79714000"],
    procedureType: "Negotiated",
    contractType: "Services",
    estimatedValueMSEK: 240,
    currency: "SEK",
    publishedAt: iso(-7),
    deadline: iso(2),
    summary:
      "Build and operate a 24/7 cyber SOC for the Swedish Armed Forces. Requires top-tier security clearance (SUA Nivå 1) and Swedish-only data residency.",
    requirements: [
      "SUA Nivå 1 clearance for all personnel",
      "Swedish citizenship for analysts",
      "Existing SOC-CMM Level 4 maturity",
      "Annual revenue > 200 MSEK",
    ],
    sourceUrl: "https://mercell.com/notice/2026-103",
    attachments: [
      { filename: "request-for-tender.pdf", sizeKB: 920 },
      { filename: "security-annex.pdf", sizeKB: 540 },
    ],
  },
  {
    id: "mercell-2026-118",
    source: "Mercell",
    title: "EHR Integration Platform — Region Stockholm",
    buyer: "Region Stockholm",
    country: "SE",
    nutsCode: "SE110",
    cpvCodes: ["72263000", "48180000"],
    procedureType: "Competitive Dialogue",
    contractType: "Services",
    estimatedValueMSEK: 145,
    currency: "SEK",
    publishedAt: iso(-10),
    deadline: iso(56),
    summary:
      "Integration backbone connecting regional EHR systems with national health services (1177, NPÖ) and labs.",
    requirements: [
      "HL7 FHIR R4 expertise",
      "Two references with Swedish regions",
      "Patientdatalagen and IVO classification",
    ],
    sourceUrl: "https://mercell.com/notice/2026-118",
    attachments: [
      { filename: "rfp.pdf", sizeKB: 510 },
      { filename: "integration-catalog.xlsx", sizeKB: 128 },
    ],
  },
  {
    id: "visma-2026-451",
    source: "Visma",
    title: "Citizen Portal Modernisation — Stockholms stad",
    buyer: "Stockholms stad",
    country: "SE",
    nutsCode: "SE110",
    cpvCodes: ["72413000", "72212222"],
    procedureType: "Open",
    contractType: "Services",
    estimatedValueMSEK: 54,
    currency: "SEK",
    publishedAt: iso(-4),
    deadline: iso(11),
    summary:
      "Redesign and rebuild of the central citizen-facing services portal. Accessibility (WCAG 2.2 AA) and multilingual support required.",
    requirements: [
      "WCAG 2.2 AA compliance evidence",
      "BankID and Freja eID integration",
      "Two municipal reference projects",
    ],
    sourceUrl: "https://opic.com/notice/2026-451",
    attachments: [
      { filename: "anbudsförfrågan.pdf", sizeKB: 290 },
      { filename: "designprinciper.pdf", sizeKB: 1100 },
    ],
  },
  {
    id: "visma-2026-462",
    source: "Visma",
    title: "Data Warehouse Modernisation — SCB",
    buyer: "Statistiska Centralbyrån",
    country: "SE",
    nutsCode: "SE125",
    cpvCodes: ["72319000", "72330000"],
    procedureType: "Open",
    contractType: "Services",
    estimatedValueMSEK: 31,
    currency: "SEK",
    publishedAt: iso(-6),
    deadline: iso(33),
    summary:
      "Modernise statistical production pipelines onto a lakehouse architecture (Delta/Iceberg) with strong lineage and reproducibility.",
    requirements: [
      "Databricks or Snowflake reference deliveries",
      "DataOps and dbt experience",
      "Statistician domain knowledge advantageous",
    ],
    sourceUrl: "https://opic.com/notice/2026-462",
    attachments: [{ filename: "uppdrag.pdf", sizeKB: 180 }],
  },
  {
    id: "ted-2026-009",
    source: "TED",
    title: "Cybersecurity Advisory Framework — ENISA",
    buyer: "ENISA — EU Cybersecurity Agency",
    country: "EU",
    nutsCode: "GR300",
    cpvCodes: ["79417000", "72212732"],
    procedureType: "Open",
    contractType: "Services",
    estimatedValueMSEK: 165,
    currency: "EUR",
    publishedAt: iso(-12),
    deadline: iso(70),
    summary:
      "Advisory framework for NIS2 implementation guidance, threat intelligence, and incident response support across EU Member States.",
    requirements: [
      "Multilingual delivery team (EN + 2 EU languages)",
      "ISO 27001 and demonstrable NIS2 advisory experience",
      "Five references on national-level cybersecurity advisory",
    ],
    sourceUrl: "https://ted.europa.eu/notice/2026-009",
    attachments: [
      { filename: "tender-spec-en.pdf", sizeKB: 720 },
      { filename: "annex-pricing.xlsx", sizeKB: 88 },
    ],
  },
  {
    id: "clira-2026-031",
    source: "Clira",
    title: "Application Modernisation — Skatteverket",
    buyer: "Skatteverket",
    country: "SE",
    nutsCode: "SE110",
    cpvCodes: ["72262000", "72240000"],
    procedureType: "Restricted",
    contractType: "Services",
    estimatedValueMSEK: 78,
    currency: "SEK",
    publishedAt: iso(0),
    deadline: iso(45),
    summary:
      "Replatforming of legacy COBOL/JCL workloads onto Java microservices with phased decommissioning of mainframe.",
    requirements: [
      "Mainframe-to-cloud migration references",
      "Java 21, Spring Boot, OpenShift",
      "Sovereign cloud residency",
    ],
    sourceUrl: "https://clira.se/tender/2026-031",
    attachments: [
      { filename: "förfrågan.pdf", sizeKB: 410 },
      { filename: "teknisk-bilaga.pdf", sizeKB: 880 },
    ],
  },
  {
    id: "mercell-2026-129",
    source: "Mercell",
    title: "Network Infrastructure Refresh — Karolinska",
    buyer: "Karolinska Universitetssjukhuset",
    country: "SE",
    nutsCode: "SE110",
    cpvCodes: ["32420000", "72710000"],
    procedureType: "Open",
    contractType: "Supplies",
    estimatedValueMSEK: 64,
    currency: "SEK",
    publishedAt: iso(-8),
    deadline: iso(21),
    summary:
      "Hospital-wide network refresh including Wi-Fi 7, segmentation, and zero-trust microsegmentation.",
    requirements: [
      "Cisco or Aruba certified delivery partner",
      "Healthcare references",
      "24/7 support with 1h response SLA",
    ],
    sourceUrl: "https://mercell.com/notice/2026-129",
    attachments: [{ filename: "rfp-network.pdf", sizeKB: 615 }],
  },
  {
    id: "visma-2026-477",
    source: "Visma",
    title: "GIS Platform — Lantmäteriet",
    buyer: "Lantmäteriet",
    country: "SE",
    nutsCode: "SE125",
    cpvCodes: ["72212000", "38221000"],
    procedureType: "Open",
    contractType: "Services",
    estimatedValueMSEK: 42,
    currency: "SEK",
    publishedAt: iso(-15),
    deadline: iso(8),
    summary:
      "Modernisation of the national geospatial platform with vector tiles, OGC APIs, and large-scale raster processing.",
    requirements: [
      "PostGIS and GeoServer experience",
      "OGC API Features compliance",
      "References with national mapping agencies",
    ],
    sourceUrl: "https://opic.com/notice/2026-477",
    attachments: [{ filename: "uppdragsbeskrivning.pdf", sizeKB: 350 }],
  },
  {
    id: "ted-2026-014",
    source: "TED",
    title: "AI/ML Model Validation Services",
    buyer: "European Banking Authority",
    country: "EU",
    nutsCode: "FR101",
    cpvCodes: ["72316000", "73100000"],
    procedureType: "Open",
    contractType: "Services",
    estimatedValueMSEK: 58,
    currency: "EUR",
    publishedAt: iso(-2),
    deadline: iso(38),
    summary:
      "Independent validation services for ML models used in supervisory analytics. EU AI Act compliance focus.",
    requirements: [
      "PhD-level statistical expertise on team",
      "EU AI Act high-risk validation experience",
      "Two references in financial supervision",
    ],
    sourceUrl: "https://ted.europa.eu/notice/2026-014",
    attachments: [
      { filename: "tor.pdf", sizeKB: 220 },
      { filename: "annex-methodology.pdf", sizeKB: 440 },
    ],
  },
  {
    id: "clira-2026-040",
    source: "Clira",
    title: "Bid Management Platform — Adda",
    buyer: "Adda Inköpscentral",
    country: "SE",
    nutsCode: "SE110",
    cpvCodes: ["72212222", "48000000"],
    procedureType: "Open",
    contractType: "Services",
    estimatedValueMSEK: 19,
    currency: "SEK",
    publishedAt: iso(-1),
    deadline: iso(14),
    summary:
      "SaaS platform for managing the central purchasing body's framework agreement portfolio and supplier engagement.",
    requirements: [
      "GDPR and OSL compliance",
      "Open API and SCB statistics integration",
      "Swedish-language UI and support",
    ],
    sourceUrl: "https://clira.se/tender/2026-040",
    attachments: [{ filename: "förfrågningsunderlag.pdf", sizeKB: 285 }],
  },
  {
    id: "mercell-2026-141",
    source: "Mercell",
    title: "Identity Federation — Försäkringskassan",
    buyer: "Försäkringskassan",
    country: "SE",
    nutsCode: "SE110",
    cpvCodes: ["48732000", "72200000"],
    procedureType: "Restricted",
    contractType: "Services",
    estimatedValueMSEK: 88,
    currency: "SEK",
    publishedAt: iso(-9),
    deadline: iso(50),
    summary:
      "Federated identity for citizen-facing services with eIDAS cross-border support and BankID integration.",
    requirements: [
      "eIDAS node implementation experience",
      "BankID and Freja eID integration",
      "Three references in social insurance or tax",
    ],
    sourceUrl: "https://mercell.com/notice/2026-141",
    attachments: [
      { filename: "rfp-identity.pdf", sizeKB: 480 },
      { filename: "bilaga-säkerhet.pdf", sizeKB: 290 },
    ],
  },
  {
    id: "visma-2026-489",
    source: "Visma",
    title: "Procurement Analytics Dashboard — Upphandlingsmyndigheten",
    buyer: "Upphandlingsmyndigheten",
    country: "SE",
    nutsCode: "SE110",
    cpvCodes: ["72319000", "72416000"],
    procedureType: "Open",
    contractType: "Services",
    estimatedValueMSEK: 12,
    currency: "SEK",
    publishedAt: iso(-3),
    deadline: iso(25),
    summary:
      "Self-service analytics dashboard exposing public procurement data to authorities and suppliers.",
    requirements: [
      "Power BI or Tableau certified",
      "Open data publication experience",
      "WCAG 2.2 AA compliance",
    ],
    sourceUrl: "https://opic.com/notice/2026-489",
    attachments: [{ filename: "uppdrag.pdf", sizeKB: 195 }],
  },
];
