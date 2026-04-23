import { describe, expect, it } from "vitest";
import {
  DOCX_CONTENT_TYPE,
  PDF_CONTENT_TYPE,
  contentTypeForProcurementDocument,
  isSupportedProcurementDocument,
  safeDocumentFilename,
} from "./api";

describe("procurement document upload helpers", () => {
  it("accepts PDF and DOCX files by MIME type or extension", () => {
    expect(
      isSupportedProcurementDocument(
        new File(["pdf"], "requirements.pdf", { type: PDF_CONTENT_TYPE }),
      ),
    ).toBe(true);
    expect(
      isSupportedProcurementDocument(new File(["docx"], "requirements.docx")),
    ).toBe(true);
    expect(
      isSupportedProcurementDocument(new File(["txt"], "requirements.txt")),
    ).toBe(false);
  });

  it("preserves the safe supported extension in storage filenames", () => {
    expect(safeDocumentFilename("Bilaga Kravspec.docx")).toBe(
      "bilaga-kravspec.docx",
    );
    expect(safeDocumentFilename("Bilaga Skakrav.pdf")).toBe("bilaga-skakrav.pdf");
  });

  it("uses DOCX content type when browser File.type is empty", () => {
    expect(
      contentTypeForProcurementDocument(new File(["docx"], "requirements.docx")),
    ).toBe(DOCX_CONTENT_TYPE);
  });
});
