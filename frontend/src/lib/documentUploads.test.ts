import { describe, expect, it } from "vitest";

import {
  normalizeDocumentUploads,
  type ZipArchiveEntry,
} from "./documentUploads";

function makeFile(name: string, type: string, contents = name): File {
  return new File([contents], name, { type });
}

describe("normalizeDocumentUploads", () => {
  it("keeps direct PDFs and expands PDF entries from ZIP files", async () => {
    const directPdf = makeFile("impact-capabilities.pdf", "application/pdf");
    const zipFile = makeFile("impact-solutions-kb.zip", "application/zip");

    const result = await normalizeDocumentUploads(
      [directPdf, zipFile],
      async () => [
        {
          name: "sales/impact-reference.pdf",
          data: new Uint8Array([1, 2, 3]),
        },
        {
          name: "sales/notes.txt",
          data: new Uint8Array([4, 5, 6]),
        },
      ],
    );

    expect(result.accepted.map((item) => item.file.name)).toEqual([
      "impact-capabilities.pdf",
      "sales__impact-reference.pdf",
    ]);
    expect(result.accepted.map((item) => item.source)).toEqual(["direct", "zip"]);
    expect(result.rejected).toEqual([
      {
        name: "sales/notes.txt",
        reason: "Only PDF files inside ZIP archives are supported.",
      },
    ]);
  });

  it("rejects unsupported direct uploads and ZIP archives without PDFs", async () => {
    const textFile = makeFile("notes.txt", "text/plain");
    const zipFile = makeFile("empty.zip", "application/zip");

    const result = await normalizeDocumentUploads(
      [textFile, zipFile],
      async () => [{ name: "readme.md", data: new Uint8Array([7, 8, 9]) }],
    );

    expect(result.accepted).toEqual([]);
    expect(result.rejected).toEqual([
      {
        name: "notes.txt",
        reason: "Only PDF or ZIP uploads are supported.",
      },
      {
        name: "readme.md",
        reason: "Only PDF files inside ZIP archives are supported.",
      },
      {
        name: "empty.zip",
        reason: "ZIP archive does not contain any PDF files.",
      },
    ]);
  });

  it("deduplicates extracted filenames while preserving the PDF extension", async () => {
    const zipFile = makeFile("tender-set.zip", "application/zip");
    const entries: ZipArchiveEntry[] = [
      { name: "main/specification.pdf", data: new Uint8Array([1]) },
      { name: "annex/specification.pdf", data: new Uint8Array([2]) },
    ];

    const result = await normalizeDocumentUploads([zipFile], async () => entries);

    expect(result.accepted.map((item) => item.file.name)).toEqual([
      "main__specification.pdf",
      "annex__specification.pdf",
    ]);
  });
});
