export type DocumentRegistrationScope = "tender_document" | "company_profile";

interface StorageUploadError {
  message: string;
  statusCode?: string;
}

interface DocumentRegistrationClient {
  storage: {
    from: (bucketName: string) => {
      upload: (
        path: string,
        file: Blob,
        options: { contentType: string; upsert: boolean },
      ) => Promise<{ error: StorageUploadError | null }>;
    };
  };
  from: (tableName: string) => {
    upsert: (
      payload: Record<string, unknown>,
      options: { onConflict: string },
    ) => Promise<{ error: { message: string } | null }>;
  };
}

export interface RegisterUploadedDocumentsInput {
  client: DocumentRegistrationClient;
  bucketName: string;
  ownerName: string;
  companyId: string;
  tenderId: string | null;
  files: File[];
  scope: DocumentRegistrationScope;
  registeredVia: string;
  metadata?: Record<string, unknown>;
}

export async function registerUploadedDocuments(
  input: RegisterUploadedDocumentsInput,
): Promise<void> {
  if (input.scope === "tender_document" && !input.tenderId) {
    throw new Error("registerUploadedDocuments: tenderId is required for tender uploads.");
  }

  for (const file of input.files) {
    const buffer = await readFileBuffer(file);
    const checksum = await sha256Hex(buffer);
    const storagePath = buildStoragePath(
      input.scope,
      input.ownerName,
      checksum,
      file.name,
    );

    const { error: uploadError } = await input.client.storage
      .from(input.bucketName)
      .upload(storagePath, new Blob([buffer], { type: "application/pdf" }), {
        contentType: "application/pdf",
        upsert: true,
      });
    if (uploadError) {
      throw new Error(
        `registerUploadedDocuments (storage upload ${file.name}): ${uploadError.message} [status: ${uploadError.statusCode ?? "?"}]`,
      );
    }

    const { error: documentError } = await input.client.from("documents").upsert(
      {
        tenant_key: "demo",
        tender_id: input.scope === "tender_document" ? input.tenderId : null,
        company_id: input.scope === "company_profile" ? input.companyId : null,
        storage_path: storagePath,
        checksum_sha256: checksum,
        content_type: "application/pdf",
        document_role: input.scope,
        parse_status: "pending",
        original_filename: file.name,
        metadata: {
          registered_via: input.registeredVia,
          ...(input.metadata ?? {}),
        },
      },
      { onConflict: "storage_path" },
    );
    if (documentError) {
      throw new Error(
        `registerUploadedDocuments (document upsert ${file.name}): ${documentError.message}`,
      );
    }
  }
}

async function readFileBuffer(file: File): Promise<ArrayBuffer> {
  if (typeof file.arrayBuffer === "function") {
    return file.arrayBuffer();
  }
  return new Response(file).arrayBuffer();
}

async function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  const hashBuffer = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(hashBuffer))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function buildStoragePath(
  scope: DocumentRegistrationScope,
  ownerName: string,
  checksumHex: string,
  originalFilename: string,
): string {
  const root =
    scope === "tender_document" ? "demo/procurements" : "demo/company-profile";
  return `${root}/${slugify(ownerName)}/${checksumHex.slice(0, 12)}-${safePdfFilename(originalFilename)}`;
}

function safePdfFilename(filename: string): string {
  const stem = filename.replace(/\.pdf$/i, "");
  return `${slugify(stem) || "document"}.pdf`;
}

function slugify(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-");
  return slug || "document";
}
