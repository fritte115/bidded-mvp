import { describe, expect, it } from "vitest";

import {
  registerUploadedDocuments,
  type DocumentRegistrationScope,
} from "./documentRegistration";

function makeFile(name: string, contents = name): File {
  return new File([contents], name, { type: "application/pdf" });
}

class RecordingBucket {
  uploads: Array<{
    path: string;
    size: number;
    contentType: string | undefined;
    upsert: boolean | undefined;
  }> = [];

  async upload(path: string, file: Blob, options: { contentType?: string; upsert?: boolean }) {
    this.uploads.push({
      path,
      size: file.size,
      contentType: options.contentType,
      upsert: options.upsert,
    });
    return { error: null };
  }
}

class RecordingClient {
  bucket = new RecordingBucket();
  documentUpserts: Array<{ payload: Record<string, unknown>; onConflict?: string }> = [];

  storage = {
    from: () => this.bucket,
  };

  from(tableName: string) {
    if (tableName !== "documents") {
      throw new Error(`Unexpected table: ${tableName}`);
    }

    return {
      upsert: async (payload: Record<string, unknown>, options: { onConflict?: string }) => {
        this.documentUpserts.push({ payload, onConflict: options.onConflict });
        return { error: null };
      },
    };
  }
}

async function registerForScope(scope: DocumentRegistrationScope) {
  const client = new RecordingClient();
  await registerUploadedDocuments({
    client,
    bucketName: "public-procurements",
    ownerName: scope === "tender_document" ? "Impact Solutions Tender" : "Impact Solutions",
    companyId: "company-1",
    tenderId: scope === "tender_document" ? "tender-1" : null,
    files: [makeFile("Impact Overview.pdf")],
    scope,
    registeredVia: scope === "tender_document" ? "frontend_ui" : "frontend_company_kb",
  });
  return client;
}

describe("registerUploadedDocuments", () => {
  it("registers tender uploads under the procurement prefix", async () => {
    const client = await registerForScope("tender_document");

    expect(client.bucket.uploads).toHaveLength(1);
    expect(client.bucket.uploads[0]).toMatchObject({
      contentType: "application/pdf",
      upsert: true,
    });
    expect(client.bucket.uploads[0].path).toMatch(
      /^demo\/procurements\/impact-solutions-tender\/[a-f0-9]{12}-impact-overview\.pdf$/,
    );
    expect(client.documentUpserts[0]).toMatchObject({
      onConflict: "storage_path",
      payload: {
        tender_id: "tender-1",
        company_id: null,
        document_role: "tender_document",
        content_type: "application/pdf",
      },
    });
  });

  it("registers company knowledge-base uploads under the company-profile prefix", async () => {
    const client = await registerForScope("company_profile");

    expect(client.bucket.uploads).toHaveLength(1);
    expect(client.bucket.uploads[0].path).toMatch(
      /^demo\/company-profile\/impact-solutions\/[a-f0-9]{12}-impact-overview\.pdf$/,
    );
    expect(client.documentUpserts[0]).toMatchObject({
      onConflict: "storage_path",
      payload: {
        tender_id: null,
        company_id: "company-1",
        document_role: "company_profile",
        content_type: "application/pdf",
      },
    });
  });
});
