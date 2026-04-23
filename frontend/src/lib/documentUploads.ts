import JSZip from "jszip";

export interface ZipArchiveEntry {
  name: string;
  data: Uint8Array;
}

export interface NormalizedDocumentUpload {
  file: File;
  source: "direct" | "zip";
  sourceName: string;
  archiveEntryName: string | null;
}

export interface DocumentUploadRejection {
  name: string;
  reason: string;
}

export interface NormalizeDocumentUploadsResult {
  accepted: NormalizedDocumentUpload[];
  rejected: DocumentUploadRejection[];
}

export type ZipArchiveLoader = (file: File) => Promise<ZipArchiveEntry[]>;

const DIRECT_UPLOAD_REJECTION = "Only PDF or ZIP uploads are supported.";
const ZIP_ENTRY_REJECTION = "Only PDF files inside ZIP archives are supported.";
const ZIP_EMPTY_REJECTION = "ZIP archive does not contain any PDF files.";

export async function normalizeDocumentUploads(
  files: Iterable<File>,
  loadZipEntries: ZipArchiveLoader = readZipArchiveEntries,
): Promise<NormalizeDocumentUploadsResult> {
  const accepted: NormalizedDocumentUpload[] = [];
  const rejected: DocumentUploadRejection[] = [];
  const seenNames = new Map<string, number>();

  for (const file of files) {
    if (isPdfUpload(file)) {
      accepted.push({
        file: renameFile(file, nextFilename(file.name, seenNames)),
        source: "direct",
        sourceName: file.name,
        archiveEntryName: null,
      });
      continue;
    }

    if (!isZipUpload(file)) {
      rejected.push({ name: file.name, reason: DIRECT_UPLOAD_REJECTION });
      continue;
    }

    let zipAccepted = 0;
    const zipEntries = await loadZipEntries(file);
    for (const entry of zipEntries) {
      if (!isPdfFilename(entry.name)) {
        rejected.push({ name: entry.name, reason: ZIP_ENTRY_REJECTION });
        continue;
      }

      const entryFilename = nextFilename(
        normalizeArchiveEntryFilename(entry.name),
        seenNames,
      );
      accepted.push({
        file: new File([entry.data], entryFilename, { type: "application/pdf" }),
        source: "zip",
        sourceName: file.name,
        archiveEntryName: entry.name,
      });
      zipAccepted += 1;
    }

    if (zipAccepted === 0) {
      rejected.push({ name: file.name, reason: ZIP_EMPTY_REJECTION });
    }
  }

  return { accepted, rejected };
}

async function readZipArchiveEntries(file: File): Promise<ZipArchiveEntry[]> {
  const archive = await JSZip.loadAsync(await file.arrayBuffer());
  const entries = Object.values(archive.files);
  const results: ZipArchiveEntry[] = [];

  for (const entry of entries) {
    if (entry.dir) {
      continue;
    }
    results.push({
      name: entry.name,
      data: await entry.async("uint8array"),
    });
  }

  return results;
}

function isPdfUpload(file: File): boolean {
  return file.type === "application/pdf" || isPdfFilename(file.name);
}

function isZipUpload(file: File): boolean {
  return (
    file.type === "application/zip" ||
    file.type === "application/x-zip-compressed" ||
    file.type === "multipart/x-zip" ||
    file.name.toLowerCase().endsWith(".zip")
  );
}

function isPdfFilename(filename: string): boolean {
  return filename.toLowerCase().endsWith(".pdf");
}

function normalizeArchiveEntryFilename(filename: string): string {
  const segments = filename
    .split(/[\\/]+/)
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0 && segment !== "." && segment !== "..")
    .map((segment) => segment.replace(/[:*?"<>|]/g, "-"));
  const joined = segments.join("__").replace(/\.pdf$/i, "");
  return `${joined || "document"}.pdf`;
}

function nextFilename(filename: string, seenNames: Map<string, number>): string {
  const normalized = filename.trim() || "document.pdf";
  const currentCount = seenNames.get(normalized) ?? 0;
  seenNames.set(normalized, currentCount + 1);
  if (currentCount === 0) {
    return normalized;
  }

  const stem = normalized.replace(/\.pdf$/i, "");
  return `${stem}-${currentCount + 1}.pdf`;
}

function renameFile(file: File, nextName: string): File {
  if (file.name === nextName) {
    return file;
  }
  return new File([file], nextName, { type: file.type || "application/pdf" });
}
