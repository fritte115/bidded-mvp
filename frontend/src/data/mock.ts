// Mock data for the Bidded demo UI. All data is illustrative.

export type RunStatus = "pending" | "running" | "succeeded" | "failed" | "needs_human_review";

export type DocumentParseStatus = "pending" | "parsing" | "parsed" | "parser_failed";

export interface DocumentRef {
  id: string;
  filename: string;
  parseStatus: DocumentParseStatus;
}
export type Verdict = "BID" | "NO_BID" | "CONDITIONAL_BID";
export type TenderStatus = "pending" | "processing" | "done";
export type EvidenceCategory =
  | "Deadlines"
  | "Mandatory Requirements"
  | "Qualification Criteria"
  | "Evaluation Criteria"
  | "Contract Risks"
  | "Required Submission Documents";

export type AgentName = "Compliance Officer" | "Win Strategist" | "Delivery/CFO" | "Red Team";

export interface Evidence {
  id: string; // EVD-012
  key: string; // TENDER.DEADLINE.SUBMISSION
  category: EvidenceCategory;
  excerpt: string;
  source: string; // doc filename OR human company source label
  page: number; // 0 for company_profile evidence
  referencedBy: AgentName[];
  /** Where this excerpt comes from. Defaults to "tender_document" when omitted. */
  kind?: "tender_document" | "company_profile";
  /** For company_profile evidence: dotted path on the seeded Company. */
  companyFieldPath?: string;
}

export interface AgentMotionFinding {
  claim: string;
  evidenceKeys: string[];
}

export interface AgentMotion {
  agent: AgentName;
  verdict: Verdict;
  confidence: number; // 0-100
  findings: string[];
  findingsWithEvidence?: AgentMotionFinding[];
  rebuttalFocus?: string[];
  challenges?: string[]; // disagreements (round 2)
  challengesWithEvidence?: AgentMotionFinding[]; // round 2 rebuttals with evidence keys
  revisedStanceRationale?: string; // round 2 only
}

export interface ComplianceMatrixRow {
  requirement: string;
  status: "Met" | "Partial" | "Not Met" | "Unknown";
  evidence: string[]; // EVD-xxx ids
}

export interface RiskRow {
  risk: string;
  severity: "Low" | "Medium" | "High";
  mitigation: string;
}

export interface JudgeOutput {
  verdict: Verdict;
  confidence: number;
  voteSummary: { BID: number; NO_BID: number; CONDITIONAL_BID: number };
  disagreement: string;
  citedMemo: string;
  complianceMatrix: ComplianceMatrixRow[];
  complianceBlockers: string[];
  potentialBlockers: string[];
  riskRegister: RiskRow[];
  missingInfo: string[];
  recommendedActions: string[];
  evidenceIds: string[];
}

export interface Procurement {
  id: string;
  name: string;
  documents: string[];
  /** Optional richer document refs aligned with Supabase `documents` rows. */
  documentRefs?: DocumentRef[];
  uploadedAt: string;
  chunks: number;
  status: TenderStatus;
  description?: string;
  // Comparison metrics (mock — surfaced on the Compare page)
  estimatedValueMSEK: number;
  winProbability: number; // 0–1
  strategicFit: "Low" | "Medium" | "High";
  riskScore: "Low" | "Medium" | "High";
  topReason: string;
  verdict?: Verdict;
  confidence?: number; // 0–100
}

/** @deprecated use Procurement */
export type Tender = Procurement;

export interface Run {
  id: string;
  tenderId: string;
  tenderName: string;
  company: string;
  startedAt: string;
  completedAt?: string;
  durationSec?: number;
  status: RunStatus;
  stage: string;
  decision?: Verdict;
  confidence?: number;
  evidence: Evidence[];
  round1: AgentMotion[];
  round2: AgentMotion[];
  judge?: JudgeOutput;
}

export interface Company {
  name: string;
  legalName?: string;
  orgNumber: string;
  vatNumber?: string;
  founded?: number;
  size: string;
  headcount?: number;
  hq: string;
  offices?: string[];
  website?: string;
  email?: string;
  phone?: string;
  description?: string;
  leadership?: { name: string; title: string; email?: string }[];
  industries?: string[];
  capabilities: string[];
  certifications: { name: string; issuer: string; validUntil: string }[];
  references: {
    client: string;
    scope: string;
    value: string;
    year: number;
    sector?: string;
    duration?: string;
    outcome?: string;
  }[];
  financialAssumptions: {
    revenueRange: string;
    targetMargin: string;
    maxContractSize: string;
  };
  financials?: {
    year: number;
    revenueMSEK: number;
    ebitMarginPct: number;
    headcount: number;
  }[];
  teamComposition?: { role: string; count: number; avgYears: number }[];
  insurance?: { type: string; insurer: string; coverage: string }[];
  frameworkAgreements?: {
    name: string;
    authority: string;
    validUntil: string;
    status: "Active" | "Expiring" | "Expired";
  }[];
  securityPosture?: {
    item: string;
    status: "Implemented" | "Partial" | "Planned";
    note?: string;
  }[];
  sustainability?: {
    co2ReductionPct: number;
    renewableEnergyPct: number;
    diversityPct: number;
    codeOfConductSigned: boolean;
  };
  bidStats?: {
    totalBids: number;
    won: number;
    lost: number;
    inProgress: number;
    winRatePct: number;
    avgContractMSEK: number;
  };
}

export const company: Company = {
  name: "Acme IT Consulting AB",
  orgNumber: "556677-1122",
  size: "85 employees",
  hq: "Stockholm, Sweden",
  capabilities: [
    "Cloud (AWS, Azure)",
    "Cybersecurity",
    "Agile delivery",
    "DevOps",
    "Identity & Access Management",
    "Public sector integrations",
    "Data engineering",
    "Microsoft 365",
    "Kubernetes",
    "Zero Trust",
  ],
  certifications: [
    { name: "ISO 27001", issuer: "DNV", validUntil: "2026-09-30" },
    { name: "ISO 9001", issuer: "DNV", validUntil: "2026-09-30" },
    { name: "ISO 14001", issuer: "DNV", validUntil: "2027-02-15" },
    { name: "SKL Framework Agreement — IT-konsulttjänster", issuer: "SKL Kommentus", validUntil: "2026-12-31" },
  ],
  references: [
    { client: "Region Skåne", scope: "Cloud migration & IAM", value: "12 MSEK", year: 2024 },
    { client: "Trafikverket", scope: "DevOps platform engineering", value: "8 MSEK", year: 2023 },
    { client: "Försäkringskassan", scope: "Secure file exchange platform", value: "18 MSEK", year: 2024 },
  ],
  financialAssumptions: {
    revenueRange: "120–150 MSEK / year",
    targetMargin: "12%",
    maxContractSize: "40 MSEK",
  },
};

export const procurements: Procurement[] = [
  {
    id: "tender-001",
    name: "National Police IT Modernisation 2026",
    documents: [
      "polismyndigheten-it-modernisation-2026.pdf",
      "polismyndigheten-bilaga-1-kravspec.pdf",
      "polismyndigheten-bilaga-2-avtalsvillkor.pdf",
    ],
    uploadedAt: "2026-03-22T09:14:00Z",
    chunks: 184,
    status: "done",
    description:
      "Multi-year framework for modernising case management, identity and endpoint platforms across the Swedish Police.",
    estimatedValueMSEK: 42,
    winProbability: 0.38,
    strategicFit: "High",
    riskScore: "Medium",
    topReason: "Quality-weighted evaluation favours our delivery profile; liability clause needs clarification.",
    verdict: "CONDITIONAL_BID",
    confidence: 71,
  },
  {
    id: "tender-002",
    name: "Swedish Tax Agency Cloud Migration",
    documents: [
      "skatteverket-cloud-migration-2026.pdf",
      "skatteverket-bilaga-prislista.pdf",
    ],
    uploadedAt: "2026-04-02T11:42:00Z",
    chunks: 142,
    status: "processing",
    description: "Lift-and-shift plus modernisation of selected Skatteverket workloads to a sovereign cloud.",
    estimatedValueMSEK: 65,
    winProbability: 0.55,
    strategicFit: "High",
    riskScore: "Low",
    topReason: "Sovereign cloud expertise + prior Skatteverket integration work create a strong incumbent narrative.",
    verdict: "BID",
    confidence: 82,
  },
  {
    id: "tender-003",
    name: "Region Stockholm EHR Integration Platform",
    documents: ["region-sthlm-ehr-2026.pdf"],
    uploadedAt: "2026-04-10T13:20:00Z",
    chunks: 96,
    status: "done",
    description: "Integration platform tying together regional EHR systems with national health services.",
    estimatedValueMSEK: 18,
    winProbability: 0.22,
    strategicFit: "Low",
    riskScore: "High",
    topReason: "Healthcare domain depth is thin; clinical safety classification adds delivery risk.",
    verdict: "NO_BID",
    confidence: 64,
  },
  {
    id: "tender-004",
    name: "Trafikverket DevOps Platform Renewal",
    documents: [
      "trafikverket-devops-2026.pdf",
      "trafikverket-bilaga-sla.pdf",
    ],
    uploadedAt: "2026-04-12T08:05:00Z",
    chunks: 128,
    status: "done",
    description: "Renewal of the agency-wide DevOps and platform engineering framework agreement.",
    estimatedValueMSEK: 30,
    winProbability: 0.48,
    strategicFit: "Medium",
    riskScore: "Medium",
    topReason: "Strong incumbent position from 2023 contract; pricing pressure on senior rates is the main concern.",
    verdict: "BID",
    confidence: 76,
  },
  {
    id: "tender-005",
    name: "Försäkringskassan Identity Platform 2026",
    documents: [
      "fk-identity-platform-2026.pdf",
      "fk-bilaga-saekerhetskrav.pdf",
    ],
    uploadedAt: "2026-04-18T06:40:00Z",
    chunks: 0,
    status: "pending",
    description: "New federated identity and access management platform for citizen-facing services.",
    estimatedValueMSEK: 22,
    winProbability: 0.5,
    strategicFit: "Medium",
    riskScore: "Medium",
    topReason: "Awaiting analysis — strong domain alignment but security clearance requirements unknown.",
    verdict: "BID",
    confidence: 0,
  },
];

/** @deprecated use procurements */
export const tenders = procurements;

const evidence: Evidence[] = [
  {
    id: "EVD-001",
    key: "TENDER.DEADLINE.SUBMISSION",
    category: "Deadlines",
    excerpt:
      "Anbud ska ha kommit in till den upphandlande myndigheten senast 2026-05-30 kl. 23:59 via TendSign.",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 4,
    referencedBy: ["Compliance Officer", "Win Strategist"],
  },
  {
    id: "EVD-002",
    key: "TENDER.DEADLINE.QUESTIONS",
    category: "Deadlines",
    excerpt: "Frågor på upphandlingsdokumenten ska ställas senast 2026-05-10.",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 4,
    referencedBy: ["Compliance Officer"],
  },
  {
    id: "EVD-003",
    key: "TENDER.MANDATORY.ISO27001",
    category: "Mandatory Requirements",
    excerpt:
      "Anbudsgivaren ska inneha giltig certifiering enligt ISO/IEC 27001 vid anbudslämnandet. Kopia på certifikat ska bifogas.",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 11,
    referencedBy: ["Compliance Officer", "Red Team"],
  },
  {
    id: "EVD-004",
    key: "TENDER.MANDATORY.SECURITY_CLEARANCE",
    category: "Mandatory Requirements",
    excerpt:
      "Personal som arbetar i uppdraget ska kunna säkerhetsprövas enligt säkerhetsskyddslagen (2018:585), placering i säkerhetsklass 2.",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 12,
    referencedBy: ["Compliance Officer", "Delivery/CFO", "Red Team"],
  },
  {
    id: "EVD-005",
    key: "TENDER.QUALIFICATION.TURNOVER",
    category: "Qualification Criteria",
    excerpt: "Anbudsgivaren ska ha en årsomsättning om minst 80 MSEK under vart och ett av de senaste två räkenskapsåren.",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 14,
    referencedBy: ["Delivery/CFO"],
  },
  {
    id: "EVD-006",
    key: "TENDER.QUALIFICATION.REFERENCES",
    category: "Qualification Criteria",
    excerpt:
      "Minst tre (3) referensuppdrag av motsvarande omfattning hos statlig myndighet under de senaste fem åren ska redovisas.",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 15,
    referencedBy: ["Win Strategist", "Delivery/CFO"],
  },
  {
    id: "EVD-007",
    key: "TENDER.EVALUATION.MODEL",
    category: "Evaluation Criteria",
    excerpt:
      "Tilldelning sker enligt bästa förhållande mellan pris och kvalitet. Pris viktas 40%, kvalitet 60% (uppdragsförståelse 25%, leveransorganisation 20%, säkerhet 15%).",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 22,
    referencedBy: ["Win Strategist"],
  },
  {
    id: "EVD-008",
    key: "TENDER.EVALUATION.PRICE_CEILING",
    category: "Evaluation Criteria",
    excerpt: "Takpris för ramavtalet är 1500 SEK/timme exkl. moms för seniora konsulter.",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 23,
    referencedBy: ["Delivery/CFO", "Red Team"],
  },
  {
    id: "EVD-009",
    key: "TENDER.RISK.LIABILITY_CAP",
    category: "Contract Risks",
    excerpt:
      "Leverantörens skadeståndsansvar är begränsat till 200% av årligt avropsvärde. Vid säkerhetsincident gäller obegränsat ansvar.",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 31,
    referencedBy: ["Delivery/CFO", "Red Team"],
  },
  {
    id: "EVD-010",
    key: "TENDER.RISK.PENALTIES",
    category: "Contract Risks",
    excerpt: "Vite om 0,5% av månadsersättning per påbörjad förseningsdag, högst 15% av kontraktsvärdet.",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 32,
    referencedBy: ["Delivery/CFO"],
  },
  {
    id: "EVD-011",
    key: "TENDER.DOCS.REQUIRED",
    category: "Required Submission Documents",
    excerpt:
      "Anbudet ska innehålla: ifyllt anbudsformulär, ESPD, ISO 27001-certifikat, CV för nyckelpersoner, beskrivning av leveransorganisation samt referenslista.",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 9,
    referencedBy: ["Compliance Officer"],
  },
  {
    id: "EVD-012",
    key: "TENDER.MANDATORY.SWEDISH_LANGUAGE",
    category: "Mandatory Requirements",
    excerpt: "All dokumentation och leverans ska ske på svenska. Kommunikation med beställaren sker på svenska.",
    source: "polismyndigheten-it-modernisation-2026.pdf",
    page: 13,
    referencedBy: ["Win Strategist", "Delivery/CFO"],
  },
  // ---- Company profile evidence (seeded from Acme IT Consulting AB) ----
  {
    id: "EVD-013",
    key: "COMPANY.CERTIFICATION.ISO27001",
    category: "Mandatory Requirements",
    excerpt: "ISO 27001 — issued by DNV, valid until 2026-09-30.",
    source: "Acme IT Consulting AB · company profile",
    page: 0,
    referencedBy: ["Compliance Officer"],
    kind: "company_profile",
    companyFieldPath: "certifications[0]",
  },
  {
    id: "EVD-014",
    key: "COMPANY.REFERENCE.FORSAKRINGSKASSAN",
    category: "Qualification Criteria",
    excerpt: "Försäkringskassan — Secure file exchange platform, 18 MSEK, 2024.",
    source: "Acme IT Consulting AB · company profile",
    page: 0,
    referencedBy: ["Win Strategist", "Delivery/CFO"],
    kind: "company_profile",
    companyFieldPath: "references[2]",
  },
  {
    id: "EVD-015",
    key: "COMPANY.FINANCIAL.TURNOVER",
    category: "Qualification Criteria",
    excerpt: "Annual revenue range 120–150 MSEK; clears the 80 MSEK threshold.",
    source: "Acme IT Consulting AB · company profile",
    page: 0,
    referencedBy: ["Delivery/CFO"],
    kind: "company_profile",
    companyFieldPath: "financialAssumptions.revenueRange",
  },
];

const round1: AgentMotion[] = [
  {
    agent: "Compliance Officer",
    verdict: "CONDITIONAL_BID",
    confidence: 72,
    findings: [
      "ISO 27001 certificate is valid until 2026-09-30 — covers submission window (EVD-003).",
      "Security clearance class 2 is feasible; 12 of 18 candidate consultants already cleared (EVD-004).",
      "All mandatory submission documents available except updated ESPD (EVD-011).",
      "Swedish-only delivery requirement is met; all proposed staff are SE-based (EVD-012).",
    ],
  },
  {
    agent: "Win Strategist",
    verdict: "BID",
    confidence: 78,
    findings: [
      "Evaluation model favours quality (60%) — plays to our delivery track record (EVD-007).",
      "Three statlig references readily demonstrable (Trafikverket, Försäkringskassan, Region Skåne) (EVD-006).",
      "Win-themes: sovereign cloud expertise, prior Police domain knowledge.",
      "Estimated win probability: 38% based on competitor scan.",
    ],
  },
  {
    agent: "Delivery/CFO",
    verdict: "CONDITIONAL_BID",
    confidence: 64,
    findings: [
      "Annual turnover (130 MSEK) clears 80 MSEK threshold (EVD-005).",
      "Price ceiling of 1500 SEK/h compresses senior margin to ~9%, below 12% target (EVD-008).",
      "Liability cap 200% with unlimited security incident exposure is a CFO concern (EVD-009).",
      "Estimated bench utilization to deliver: 72% — manageable.",
    ],
  },
  {
    agent: "Red Team",
    verdict: "NO_BID",
    confidence: 58,
    findings: [
      "Unlimited liability for security incidents is incompatible with insurance cover (EVD-009).",
      "Six unscreened consultants must clear class-2 security in 8 weeks — schedule risk (EVD-004).",
      "Penalty exposure up to 15% of contract value with thin margin = negative scenario −4 MSEK (EVD-010).",
      "Recommend NO BID unless liability cap is renegotiated.",
    ],
  },
];

const round2: AgentMotion[] = [
  {
    agent: "Compliance Officer",
    verdict: "CONDITIONAL_BID",
    confidence: 74,
    findings: [
      "Confirms ISO 27001 covers contract first year; renewal plan in place.",
      "Updated ESPD can be produced within 5 business days.",
    ],
    rebuttalFocus: ["Red Team's clearance schedule", "Submission completeness"],
    challenges: [
      "Red Team's 8-week clearance timeline is conservative — Polismyndigheten typically approves cleared profiles in 4–6 weeks.",
    ],
  },
  {
    agent: "Win Strategist",
    verdict: "BID",
    confidence: 76,
    findings: [
      "Quality-weighted evaluation neutralises CFO's price-margin concern at portfolio level.",
      "Strategic value: incumbency in Police domain unlocks 3 follow-on procurements worth ~85 MSEK.",
    ],
    rebuttalFocus: ["CFO margin position", "Red Team risk framing"],
    challenges: [
      "CFO's 9% margin assumes worst-case mix — blended team yields 11.5%.",
      "Risk-weighted NPV remains positive even with Red Team's penalty scenario.",
    ],
  },
  {
    agent: "Delivery/CFO",
    verdict: "CONDITIONAL_BID",
    confidence: 68,
    findings: [
      "Concedes blended margin can reach 11% with offshore-augmented delivery for non-cleared scope.",
      "Insists on contractual liability cap clarification before bid submission.",
    ],
    rebuttalFocus: ["Liability exposure", "Pricing strategy"],
    challenges: [
      "Win Strategist undervalues bench cost during ramp; +2 MSEK ramp investment required.",
    ],
  },
  {
    agent: "Red Team",
    verdict: "CONDITIONAL_BID",
    confidence: 55,
    findings: [
      "Withdraws hard NO BID if liability clarification + insurance rider are secured pre-submission.",
      "Maintains schedule risk on clearances as the highest residual exposure.",
    ],
    rebuttalFocus: ["Compliance optimism", "Insurance assumptions"],
    challenges: [
      "Compliance Officer's 4–6 week clearance baseline does not account for summer holiday slowdown (Q2/Q3).",
    ],
  },
];

const judge: JudgeOutput = {
  verdict: "CONDITIONAL_BID",
  confidence: 71,
  voteSummary: { BID: 1, NO_BID: 0, CONDITIONAL_BID: 3 },
  disagreement:
    "Round 1 surfaced one NO BID (Red Team) on liability and clearance risk. After rebuttals, Red Team converged to CONDITIONAL BID provided liability is clarified, leaving residual disagreement on clearance schedule between Compliance and Red Team.",
  citedMemo:
    "Acme should submit a CONDITIONAL BID. The opportunity is strategically aligned and quality-weighted evaluation favours our delivery profile, but two contractual conditions must be resolved pre-submission: (1) clarification of unlimited liability for security incidents, and (2) a documented clearance plan with the customer. Margins are acceptable under a blended delivery model. Without resolution of (1), the recommendation reverts to NO BID.",
  complianceMatrix: [
    { requirement: "ISO 27001 certification valid at submission", status: "Met", evidence: ["EVD-003"] },
    { requirement: "Personnel can be cleared to security class 2", status: "Partial", evidence: ["EVD-004"] },
    { requirement: "Annual turnover ≥ 80 MSEK (last 2 years)", status: "Met", evidence: ["EVD-005"] },
    { requirement: "≥ 3 statlig references (last 5 years)", status: "Met", evidence: ["EVD-006"] },
    { requirement: "Swedish-language delivery and documentation", status: "Met", evidence: ["EVD-012"] },
    { requirement: "Complete submission package incl. ESPD", status: "Partial", evidence: ["EVD-011"] },
  ],
  complianceBlockers: [
    "ESPD must be regenerated and signed before 2026-05-30 submission deadline.",
  ],
  potentialBlockers: [
    "Six consultants pending class-2 security clearance; risk of late confirmation.",
    "Liability clause for security incidents currently unlimited — incompatible with cyber insurance.",
  ],
  riskRegister: [
    {
      risk: "Unlimited liability for security incidents",
      severity: "High",
      mitigation: "Submit clarification question before 2026-05-10; secure insurance rider conditional on outcome.",
    },
    {
      risk: "Class-2 clearance timeline slips into Q3 holiday period",
      severity: "Medium",
      mitigation: "Front-load 6 candidate clearances in April; identify cleared subcontractor backup pool.",
    },
    {
      risk: "Senior-rate ceiling compresses margin below 12% target",
      severity: "Medium",
      mitigation: "Use blended team mix (offshore for non-cleared scope) to recover 200 bps margin.",
    },
  ],
  missingInfo: [
    "Customer's intended ramp profile (FTE per quarter).",
    "Whether liability cap can be negotiated post-award or only pre-submission.",
    "Number of competing bidders pre-qualified in framework.",
  ],
  recommendedActions: [
    "Submit a clarification question on liability clause (EVD-009) before 2026-05-10.",
    "Initiate class-2 clearance for the six remaining candidates this week.",
    "Regenerate ESPD and assemble submission package by 2026-05-23.",
    "Prepare CONDITIONAL bid narrative; trigger NO BID fallback if liability not clarified by 2026-05-20.",
  ],
  evidenceIds: ["EVD-001", "EVD-003", "EVD-004", "EVD-005", "EVD-006", "EVD-008", "EVD-009", "EVD-011"],
};

export const runs: Run[] = [
  {
    id: "run_8f42b1c3",
    tenderId: "tender-001",
    tenderName: "National Police IT Modernisation 2026",
    company: "Acme IT Consulting AB",
    startedAt: "2026-04-15T08:12:00Z",
    completedAt: "2026-04-15T08:23:42Z",
    durationSec: 702,
    status: "succeeded",
    stage: "Judge",
    decision: "CONDITIONAL_BID",
    confidence: 71,
    evidence,
    round1,
    round2,
    judge,
  },
  {
    id: "run_5d9e4a7b",
    tenderId: "tender-002",
    tenderName: "Swedish Tax Agency Cloud Migration",
    company: "Acme IT Consulting AB",
    startedAt: "2026-04-18T09:02:00Z",
    durationSec: 184,
    status: "running",
    stage: "Round 1: Specialist Motions",
    evidence: evidence.slice(0, 5),
    round1: [
      {
        agent: "Compliance Officer",
        verdict: "BID",
        confidence: 70,
        findings: ["Initial scan complete", "Awaiting cross-check"],
      },
    ],
    round2: [],
  },
  {
    id: "run_a1b2c3d4",
    tenderId: "tender-003",
    tenderName: "Region Stockholm EHR Integration Platform",
    company: "Acme IT Consulting AB",
    startedAt: "2026-04-17T15:10:00Z",
    completedAt: "2026-04-17T15:18:22Z",
    durationSec: 502,
    status: "succeeded",
    stage: "Judge",
    decision: "NO_BID",
    confidence: 64,
    evidence: evidence.slice(0, 6),
    round1,
    round2,
    judge: {
      ...judge,
      verdict: "NO_BID",
      confidence: 64,
      voteSummary: { BID: 0, NO_BID: 3, CONDITIONAL_BID: 1 },
      citedMemo:
        "Acme should NOT bid. Healthcare domain depth is thin and the clinical safety classification adds delivery risk that is not offset by the contract value or strategic fit. Recommend re-evaluating only if a credible clinical partner can be secured.",
    },
  },
  {
    id: "run_e5f6a7b8",
    tenderId: "tender-004",
    tenderName: "Trafikverket DevOps Platform Renewal",
    company: "Acme IT Consulting AB",
    startedAt: "2026-04-17T11:02:00Z",
    completedAt: "2026-04-17T11:14:08Z",
    durationSec: 728,
    status: "succeeded",
    stage: "Judge",
    decision: "BID",
    confidence: 76,
    evidence: evidence.slice(0, 7),
    round1,
    round2,
    judge: {
      ...judge,
      verdict: "BID",
      confidence: 76,
      voteSummary: { BID: 3, NO_BID: 0, CONDITIONAL_BID: 1 },
      citedMemo:
        "Acme should BID. Strong incumbent position from the 2023 contract, well-understood scope, and acceptable margins under the blended delivery model. Pricing pressure on senior rates is the main concern but is manageable with the proposed rate card.",
    },
  },
  {
    id: "run_9d3e2f1a",
    tenderId: "tender-002",
    tenderName: "Swedish Tax Agency Cloud Migration",
    company: "Acme IT Consulting AB",
    startedAt: "2026-04-16T13:45:00Z",
    completedAt: "2026-04-16T13:49:11Z",
    durationSec: 251,
    status: "failed",
    stage: "Round 1: Specialist Motions",
    evidence: evidence.slice(0, 2),
    round1: [
      {
        agent: "Compliance Officer",
        verdict: "BID",
        confidence: 60,
        findings: ["Indexing incomplete — aborted before rebuttal round."],
      },
    ],
    round2: [],
  },
  {
    id: "run_b2e19c3f",
    tenderId: "tender-005",
    tenderName: "Försäkringskassan Identity Platform 2026",
    company: "Acme IT Consulting AB",
    startedAt: "2026-04-18T07:10:00Z",
    completedAt: "2026-04-18T07:18:55Z",
    durationSec: 525,
    status: "needs_human_review",
    stage: "Judge",
    decision: "CONDITIONAL_BID",
    confidence: 52,
    evidence: evidence.slice(0, 8),
    round1,
    round2,
    judge: {
      ...judge,
      verdict: "CONDITIONAL_BID",
      confidence: 52,
      voteSummary: { BID: 1, NO_BID: 1, CONDITIONAL_BID: 2 },
      disagreement:
        "Specialists are evenly split and critical company evidence on security clearance capacity is missing. Judge cannot defensibly resolve without operator input.",
      citedMemo:
        "Decision routed to human review. Two specialists oppose, two support a conditional bid, and the company evidence on cleared-personnel capacity is incomplete. Operator should confirm clearance bench before this run can be finalised.",
      missingInfo: [
        "Up-to-date count of class-2 cleared consultants on bench (company profile field).",
        "Whether security clearance can be subcontracted under FK framework rules.",
      ],
    },
  },
];

export function findRun(id: string) {
  return runs.find((r) => r.id === id);
}

/** Friendly run label, e.g. "Run 1". Stable for a given run id. */
export function runDisplayId(run: Pick<Run, "id"> | string) {
  const id = typeof run === "string" ? run : run.id;
  const knownIndex = runs.findIndex((r) => r.id === id);
  if (knownIndex >= 0) return `Run ${knownIndex + 1}`;

  // Fall back to a small stable number for live ids that are not in mock data.
  let sum = 0;
  for (let i = 0; i < id.length; i++) sum = (sum + id.charCodeAt(i) * (i + 1)) % 99;
  return `Run ${sum + 1}`;
}

/** Latest run for a procurement, by startedAt (desc). */
export function latestRunForProcurement(procurementId: string): Run | undefined {
  return runs
    .filter((r) => r.tenderId === procurementId)
    .sort((a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime())[0];
}

/** Short relative time, e.g. "2h ago", "just now", "3d ago". */
export function formatRelativeTime(iso: string) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const sec = Math.max(1, Math.floor(diffMs / 1000));
  if (sec < 60) return "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  const mo = Math.floor(day / 30);
  return `${mo}mo ago`;
}

export function findProcurement(id: string) {
  return procurements.find((t) => t.id === id);
}

/** @deprecated use findProcurement */
export const findTender = findProcurement;

export const verdictLabel: Record<Verdict, string> = {
  BID: "Bid",
  NO_BID: "No bid",
  CONDITIONAL_BID: "Conditional bid",
};

export const verdictLabelShort: Record<Verdict, string> = {
  BID: "Bid",
  NO_BID: "No bid",
  CONDITIONAL_BID: "Cond.",
};

export function humanizeVerdictText(text: string) {
  const normalized = text
    .replace(/\bNOT\s+BID\b/gi, "not bid")
    .replace(/\bCONDITIONAL[_\s-]+BID\b/gi, "conditional bid")
    .replace(/\bNO[_\s-]+BID\b/gi, "no bid")
    .replace(/\bBID\b/g, "bid");

  return normalized.replace(/^(bid|no bid|conditional bid)\b/, (match) =>
    match.charAt(0).toUpperCase() + match.slice(1),
  );
}

export function formatDate(iso: string) {
  return new Date(iso).toLocaleString("sv-SE", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(sec?: number) {
  if (!sec) return "—";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${s}s`;
}

// ============ Bids ============

export type BidStatus = "draft" | "review" | "submitted" | "won" | "lost";

export interface DecisionSummary {
  runId: string;
  tenderId: string;
  tenderName: string;
  uploadedAt: string;
  documentCount: number;
  verdict: Verdict;
  confidence: number;
  citedMemo: string;
  topReason: string;
  startedAt: string;
  completedAt: string | null;
  riskScore: "Low" | "Medium" | "High";
  riskCount: number;
  complianceBlockerCount: number;
  potentialBlockerCount: number;
  recommendedActions: string[];
  missingInfo: string[];
  isDraftable: boolean;
  existingBidId?: string;
  existingBidStatus?: BidStatus;
  decisionCreatedAt?: string;
}

export interface Bid {
  id: string;
  procurementId: string;
  procurementName: string;
  rateSEK: number;
  marginPct: number;
  hoursEstimated: number;
  status: BidStatus;
  notes: string;
  updatedAt: string;
  tenderUploadedAt?: string;
  decision?: DecisionSummary;
  metadata?: Record<string, unknown>;
  /** Optional decision/run that seeded this bid. */
  runId?: string;
}

export type BidDraftAnswerStatus = "drafted" | "needs_input" | "blocked" | "not_applicable";
export type BidDraftAttachmentStatus = "attached" | "suggested" | "missing" | "needs_review";

export interface BidDraftPricing {
  source: "bid_row" | "estimator";
  rateSEK: number;
  marginPct: number;
  hoursEstimated: number;
  totalValueSEK: number;
  bidId?: string;
}

export interface BidDraftAnswer {
  questionId: string;
  prompt: string;
  answer: string;
  status: BidDraftAnswerStatus;
  evidenceKeys: string[];
  requiredAttachmentTypes: string[];
}

export interface BidDraftAttachment {
  filename: string;
  storagePath?: string;
  checksumSha256?: string;
  attachmentType: string;
  requiredByEvidenceKey: string;
  status: BidDraftAttachmentStatus;
  sourceEvidenceKeys: string[];
  packetPath?: string;
  publicUrl?: string;
}

export interface BidResponseDraft {
  schemaVersion: string;
  runId: string;
  tenderId: string;
  bidId?: string;
  language: string;
  status: "draft" | "needs_review" | "blocked";
  verdict: Verdict;
  confidence: number | null;
  pricing: BidDraftPricing;
  answers: BidDraftAnswer[];
  attachments: BidDraftAttachment[];
  missingInfo: string[];
  sourceEvidenceKeys: string[];
}

export const bidDrafts: BidResponseDraft[] = [
  {
    schemaVersion: "2026-04-23.bid_response_draft.v1",
    runId: "run_8f42b1c3",
    tenderId: "tender-001",
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
        questionId: "TENDER-ISO-CERT",
        prompt: "The tender requires an ISO 27001 certificate.",
        answer: "Bifoga ISO 27001-certifikat. Kravet adresseras med bifogad evidens.",
        status: "drafted",
        evidenceKeys: ["TENDER-ISO-CERT", "COMPANY-KB-ISO-27001"],
        requiredAttachmentTypes: ["certificate"],
      },
    ],
    attachments: [
      {
        filename: "iso-27001.pdf",
        storagePath: "demo/company-kb/iso-27001.pdf",
        checksumSha256: "demo-checksum",
        attachmentType: "certificate",
        requiredByEvidenceKey: "TENDER-ISO-CERT",
        status: "attached",
        sourceEvidenceKeys: ["TENDER-ISO-CERT", "COMPANY-KB-ISO-27001"],
      },
    ],
    missingInfo: ["Confirm named project manager."],
    sourceEvidenceKeys: ["TENDER-ISO-CERT", "COMPANY-KB-ISO-27001"],
  },
];

export const bidStatusOrder: BidStatus[] = ["draft", "review", "submitted", "won", "lost"];

export const bidStatusLabel: Record<BidStatus, string> = {
  draft: "Draft",
  review: "Review",
  submitted: "Submitted",
  won: "Won",
  lost: "Lost",
};

export const bids: Bid[] = [
  {
    id: "bid-001",
    procurementId: "tender-002",
    procurementName: "Swedish Tax Agency Cloud Migration",
    rateSEK: 1295,
    marginPct: 14,
    hoursEstimated: 1600,
    status: "draft",
    notes: "Lean on sovereign cloud incumbency narrative; price aggressive on senior rate.",
    updatedAt: "2026-04-16T10:20:00Z",
    runId: "run_5d9e4a7b",
  },
  {
    id: "bid-002",
    procurementId: "tender-001",
    procurementName: "National Police IT Modernisation 2026",
    rateSEK: 1340,
    marginPct: 11,
    hoursEstimated: 1600,
    status: "review",
    notes: "Pending liability clarification; CFO sign-off needed before submission.",
    updatedAt: "2026-04-17T14:05:00Z",
    runId: "run_8f42b1c3",
  },
  {
    id: "bid-003",
    procurementId: "tender-004",
    procurementName: "Trafikverket DevOps Platform Renewal",
    rateSEK: 1255,
    marginPct: 12,
    hoursEstimated: 1600,
    status: "submitted",
    notes: "Submitted via TendSign 2026-04-14; awaiting evaluation.",
    updatedAt: "2026-04-14T16:42:00Z",
  },
  {
    id: "bid-004",
    procurementId: "tender-003",
    procurementName: "Region Stockholm EHR Integration Platform",
    rateSEK: 1180,
    marginPct: 8,
    hoursEstimated: 1600,
    status: "lost",
    notes: "Lost on quality score (clinical safety). Useful learnings on healthcare framing.",
    updatedAt: "2026-03-28T09:00:00Z",
  },
  {
    id: "bid-005",
    procurementId: "tender-002",
    procurementName: "Swedish Tax Agency Cloud Migration",
    rateSEK: 1310,
    marginPct: 13,
    hoursEstimated: 1600,
    status: "won",
    notes: "Won previous mini-call within framework; reuse pricing model as anchor.",
    updatedAt: "2026-02-11T11:15:00Z",
  },
];

export function findBid(id: string) {
  return bids.find((b) => b.id === id);
}
