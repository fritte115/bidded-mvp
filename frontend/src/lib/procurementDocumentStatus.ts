import type { DocumentParseStatus, RunStatus } from "@/data/mock";

export type ProcurementDocumentStatusInput = {
  originalFilename: string;
  parseStatus: DocumentParseStatus;
  parseNote: string | null;
};

export type ProcurementDocumentRunStatusInput = {
  status: RunStatus;
  stage?: string | null;
  isStale?: boolean | null;
} | null;

export type ProcurementDocumentStatusSummary = {
  documents: ProcurementDocumentStatusInput[];
  hasIssues: boolean;
  statusLabel: string;
  tooltipLines: string;
};

const NOT_PAST_PARSING_STAGES = new Set([
  "pending",
  "ingest",
  "ingestion",
  "parse",
  "parsing",
  "preflight",
]);

function normalizedStage(stage: string | null | undefined): string {
  return (stage ?? "").trim().toLowerCase().replace(/[_:]+/g, " ");
}

export function runHasPassedDocumentParsing(run: ProcurementDocumentRunStatusInput): boolean {
  if (!run) return false;
  if (run.status === "succeeded" || run.status === "needs_human_review") return true;

  const stage = normalizedStage(run.stage);
  if (!stage) return false;

  return !NOT_PAST_PARSING_STAGES.has(stage);
}

export function documentStatusForDisplay(
  document: ProcurementDocumentStatusInput,
  run: ProcurementDocumentRunStatusInput,
): DocumentParseStatus {
  if (
    (document.parseStatus === "pending" || document.parseStatus === "parsing") &&
    runHasPassedDocumentParsing(run)
  ) {
    return "parsed";
  }

  return document.parseStatus;
}

export function summarizeProcurementDocuments(
  documents: ProcurementDocumentStatusInput[],
  run: ProcurementDocumentRunStatusInput,
): ProcurementDocumentStatusSummary {
  const displayDocuments = documents.map((document) => ({
    ...document,
    parseStatus: documentStatusForDisplay(document, run),
  }));
  const failed = displayDocuments.filter((document) => document.parseStatus === "parser_failed");
  const parsing = displayDocuments.filter(
    (document) => document.parseStatus === "parsing" || document.parseStatus === "pending",
  );

  return {
    documents: displayDocuments,
    hasIssues: failed.length > 0 || parsing.length > 0,
    statusLabel:
      failed.length > 0 ? `${failed.length} failed` : parsing.length > 0 ? "parsing..." : "parsed",
    tooltipLines: displayDocuments
      .map((document) => {
        const icon =
          document.parseStatus === "parsed"
            ? "+"
            : document.parseStatus === "parser_failed"
              ? "x"
              : "...";
        return `${icon} ${document.originalFilename}${
          document.parseNote ? ` - ${document.parseNote}` : ""
        }`;
      })
      .join("\n"),
  };
}
