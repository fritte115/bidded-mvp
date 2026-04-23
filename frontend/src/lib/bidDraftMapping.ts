import type {
  BidDraftAnswer,
  BidDraftAnswerStatus,
  BidDraftAttachment,
  BidDraftAttachmentStatus,
  BidResponseDraft,
  Verdict,
} from "@/data/mock";

interface RawPricing {
  source?: string;
  rate_sek?: number | string;
  margin_pct?: number | string;
  hours_estimated?: number | string;
  total_value_sek?: number | string;
  bid_id?: string | null;
}

interface RawAnswer {
  question_id?: string;
  prompt?: string;
  answer?: string;
  status?: string;
  evidence_keys?: unknown;
  required_attachment_types?: unknown;
}

interface RawAttachment {
  filename?: string;
  storage_path?: string | null;
  checksum_sha256?: string | null;
  attachment_type?: string;
  required_by_evidence_key?: string;
  status?: string;
  source_evidence_keys?: unknown;
  packet_path?: string | null;
}

export interface RawBidResponseDraft {
  schema_version?: string;
  run_id?: string;
  tender_id?: string;
  bid_id?: string | null;
  language?: string;
  status?: string;
  verdict?: string;
  confidence?: number | string | null;
  pricing?: RawPricing;
  answers?: RawAnswer[];
  attachments?: RawAttachment[];
  missing_info?: unknown;
  source_evidence_keys?: unknown;
}

function numberValue(value: number | string | null | undefined, fallback = 0): number {
  if (value == null) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function normalizeVerdict(value: string | undefined): Verdict {
  const normalized = value?.toUpperCase();
  if (normalized === "BID" || normalized === "NO_BID" || normalized === "CONDITIONAL_BID") {
    return normalized;
  }
  return "CONDITIONAL_BID";
}

function answerStatus(value: string | undefined): BidDraftAnswerStatus {
  if (value === "drafted" || value === "needs_input" || value === "blocked" || value === "not_applicable") {
    return value;
  }
  return "needs_input";
}

function attachmentStatus(value: string | undefined): BidDraftAttachmentStatus {
  if (value === "attached" || value === "suggested" || value === "missing" || value === "needs_review") {
    return value;
  }
  return "needs_review";
}

export function mapBidDraftPayload(
  payload: RawBidResponseDraft,
  publicUrlForStoragePath?: (storagePath: string) => string | undefined,
): BidResponseDraft {
  const pricing = payload.pricing ?? {};
  return {
    schemaVersion: payload.schema_version ?? "",
    runId: payload.run_id ?? "",
    tenderId: payload.tender_id ?? "",
    bidId: payload.bid_id ?? undefined,
    language: payload.language ?? "sv",
    status:
      payload.status === "draft" || payload.status === "blocked"
        ? payload.status
        : "needs_review",
    verdict: normalizeVerdict(payload.verdict),
    confidence:
      payload.confidence == null ? null : Math.round(numberValue(payload.confidence) * 100),
    pricing: {
      source: pricing.source === "bid_row" ? "bid_row" : "estimator",
      rateSEK: numberValue(pricing.rate_sek),
      marginPct: numberValue(pricing.margin_pct),
      hoursEstimated: numberValue(pricing.hours_estimated),
      totalValueSEK: numberValue(pricing.total_value_sek),
      bidId: pricing.bid_id ?? undefined,
    },
    answers: (payload.answers ?? []).map(mapAnswer),
    attachments: (payload.attachments ?? []).map((attachment) =>
      mapAttachment(attachment, publicUrlForStoragePath),
    ),
    missingInfo: stringArray(payload.missing_info),
    sourceEvidenceKeys: stringArray(payload.source_evidence_keys),
  };
}

function mapAnswer(raw: RawAnswer): BidDraftAnswer {
  return {
    questionId: raw.question_id ?? "",
    prompt: raw.prompt ?? "",
    answer: raw.answer ?? "",
    status: answerStatus(raw.status),
    evidenceKeys: stringArray(raw.evidence_keys),
    requiredAttachmentTypes: stringArray(raw.required_attachment_types),
  };
}

function mapAttachment(
  raw: RawAttachment,
  publicUrlForStoragePath?: (storagePath: string) => string | undefined,
): BidDraftAttachment {
  const storagePath = raw.storage_path ?? undefined;
  return {
    filename: raw.filename ?? "attachment.pdf",
    storagePath,
    checksumSha256: raw.checksum_sha256 ?? undefined,
    attachmentType: raw.attachment_type ?? "other",
    requiredByEvidenceKey: raw.required_by_evidence_key ?? "",
    status: attachmentStatus(raw.status),
    sourceEvidenceKeys: stringArray(raw.source_evidence_keys),
    packetPath: raw.packet_path ?? undefined,
    publicUrl: storagePath ? publicUrlForStoragePath?.(storagePath) : undefined,
  };
}
