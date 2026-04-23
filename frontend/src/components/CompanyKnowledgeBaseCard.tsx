import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FileArchive, FileText, Loader2, UploadCloud, X } from "lucide-react";

import { ParseStatusBadge } from "@/components/ParseStatusBadge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  fetchCompanyKnowledgeBaseDocuments,
  uploadCompanyKnowledgeBaseDocuments,
} from "@/lib/api";
import { normalizeDocumentUploads } from "@/lib/documentUploads";

interface CompanyKnowledgeBaseCardProps {
  companyId: string;
  companyName: string;
}

export function CompanyKnowledgeBaseCard({
  companyId,
  companyName,
}: CompanyKnowledgeBaseCardProps) {
  const queryClient = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);

  const { data: documents = [], isLoading } = useQuery({
    queryKey: ["company-knowledge-base", companyId],
    queryFn: () => fetchCompanyKnowledgeBaseDocuments(companyId),
    enabled: companyId.length > 0,
  });

  async function handleFiles(incoming: FileList | null) {
    if (!incoming) {
      return;
    }

    const result = await normalizeDocumentUploads(Array.from(incoming));
    if (result.accepted.length > 0) {
      setFiles((prev) => {
        const seen = new Set(prev.map((file) => file.name));
        return [
          ...prev,
          ...result.accepted
            .map((item) => item.file)
            .filter((file) => !seen.has(file.name)),
        ];
      });
    }

    if (result.rejected.length > 0) {
      const description = formatRejectionSummary(result.rejected);
      if (result.accepted.length > 0) {
        toast("Some files were skipped", { description });
      } else {
        toast.error("No PDF files were added", { description });
      }
    }
  }

  function removeFile(index: number) {
    setFiles((prev) => prev.filter((_, fileIndex) => fileIndex !== index));
  }

  async function uploadFiles() {
    if (files.length === 0) {
      return;
    }

    setUploading(true);
    try {
      await uploadCompanyKnowledgeBaseDocuments({
        companyId,
        companyName,
        files,
      });
      await queryClient.invalidateQueries({
        queryKey: ["company-knowledge-base", companyId],
      });
      setFiles([]);
      toast.success("Knowledge base updated", {
        description: `${files.length} PDF${files.length === 1 ? "" : "s"} stored for ${companyName}.`,
      });
    } catch (error) {
      toast.error("Knowledge base upload failed", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      setUploading(false);
    }
  }

  return (
    <Card className="border-border/60 shadow-sm">
      <CardHeader className="space-y-2">
        <div className="flex items-center gap-2">
          <FileArchive className="h-4 w-4 text-primary" />
          <CardTitle className="text-lg">Knowledge Base Documents</CardTitle>
        </div>
        <CardDescription>
          Upload PDF files or ZIP bundles from {companyName}. ZIP archives are unpacked
          in the browser and stored as individual PDFs.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <label
          className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-secondary/30 px-6 py-10 text-center hover:border-primary/40"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            void handleFiles(event.dataTransfer.files);
          }}
        >
          <UploadCloud className="mb-3 h-8 w-8 text-muted-foreground" />
          <p className="text-sm font-medium text-foreground">
            Drop PDF or ZIP files here, or click to browse
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            ZIPs may contain multiple PDFs. Non-PDF files inside the archive are skipped.
          </p>
          <input
            type="file"
            accept="application/pdf,.pdf,application/zip,.zip"
            multiple
            className="sr-only"
            onChange={(event) => {
              void handleFiles(event.target.files);
              event.target.value = "";
            }}
          />
        </label>

        {files.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-foreground">
                Ready to upload
              </p>
              <Button
                type="button"
                size="sm"
                disabled={uploading}
                onClick={() => setFiles([])}
                variant="ghost"
              >
                Clear
              </Button>
            </div>
            <ul className="space-y-1.5">
              {files.map((file, index) => (
                <li
                  key={file.name}
                  className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="truncate text-sm text-foreground">{file.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {(file.size / 1024 / 1024).toFixed(1)} MB
                    </span>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-muted-foreground hover:text-foreground"
                    onClick={() => removeFile(index)}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
            <Button
              type="button"
              disabled={uploading}
              onClick={() => {
                void uploadFiles();
              }}
            >
              {uploading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Uploading…
                </>
              ) : (
                "Upload knowledge base"
              )}
            </Button>
          </div>
        )}

        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-900">
          These documents are stored and tracked now, but the current swarm still builds
          `company_profile` evidence from the structured company profile row, not from the
          uploaded PDFs yet.
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-foreground">Stored documents</p>
            <span className="text-xs text-muted-foreground">
              {documents.length} {documents.length === 1 ? "document" : "documents"}
            </span>
          </div>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading knowledge base documents…</p>
          ) : documents.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No knowledge base documents uploaded yet.
            </p>
          ) : (
            <ul className="space-y-2">
              {documents.map((document) => (
                <li
                  key={document.id}
                  className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">
                      {document.originalFilename}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Uploaded {formatDateTime(document.uploadedAt)}
                    </p>
                  </div>
                  <ParseStatusBadge status={document.parseStatus} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function formatDateTime(value: string): string {
  if (!value) {
    return "just now";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("sv-SE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function formatRejectionSummary(
  rejected: Array<{ name: string; reason: string }>,
): string {
  return rejected
    .slice(0, 3)
    .map((entry) => `${entry.name}: ${entry.reason}`)
    .join(" · ");
}
