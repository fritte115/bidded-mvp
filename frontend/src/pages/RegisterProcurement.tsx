import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ArrowLeft, UploadCloud, FileText, X, Loader2 } from "lucide-react";
import {
  isSupportedProcurementDocument,
  registerProcurement,
} from "@/lib/api";
import { normalizeDocumentUploads } from "@/lib/documentUploads";
import {
  inferProcurementDocumentRole,
  PROCUREMENT_DOCUMENT_ROLE_OPTIONS,
  type ProcurementDocumentRole,
} from "@/lib/procurementDocumentRoles";

type PendingProcurementFile = {
  file: File;
  procurementDocumentRole: ProcurementDocumentRole | null;
};

export default function RegisterProcurement() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [title, setTitle] = useState("");
  const [issuingAuthority, setIssuingAuthority] = useState("");
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<PendingProcurementFile[]>([]);
  const [submitting, setSubmitting] = useState(false);

  async function handleFiles(incoming: FileList | null) {
    if (!incoming) return;

    const allFiles = Array.from(incoming);
    const directFiles = allFiles.filter(isSupportedProcurementDocument);
    const zippedPdfFiles = await normalizeDocumentUploads(
      allFiles.filter((file) => !isSupportedProcurementDocument(file)),
    );
    const next = [
      ...directFiles,
      ...zippedPdfFiles.accepted.map((item) => item.file),
    ];

    setFiles((prev) => {
      const existingNames = new Set(prev.map((item) => item.file.name));
      const nextFiles = next.filter((file) => !existingNames.has(file.name));
      return [
        ...prev,
        ...nextFiles.map((file, index) => ({
          file,
          procurementDocumentRole: inferProcurementDocumentRole(file.name, {
            isFirstDocument: prev.length === 0 && index === 0,
          }),
        })),
      ];
    });

    if (zippedPdfFiles.rejected.length > 0) {
      const description = zippedPdfFiles.rejected
        .slice(0, 3)
        .map((entry) => `${entry.name}: ${entry.reason}`)
        .join(" · ");
      if (next.length > 0) {
        toast("Some files were skipped", { description });
      } else {
        toast.error("No supported files were added", { description });
      }
    }
  }

  function removeFile(i: number) {
    setFiles((prev) => prev.filter((_, idx) => idx !== i));
  }

  function updateFileRole(index: number, procurementDocumentRole: ProcurementDocumentRole) {
    setFiles((prev) =>
      prev.map((item, itemIndex) =>
        itemIndex === index ? { ...item, procurementDocumentRole } : item,
      ),
    );
  }

  async function handleSubmit() {
    if (!title.trim() || files.length === 0) return;
    setSubmitting(true);
    try {
      await registerProcurement({
        title: title.trim(),
        issuingAuthority: issuingAuthority.trim(),
        documents: files,
      });
      await queryClient.invalidateQueries({ queryKey: ["procurements"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success("Procurement registered", {
        description: `${files.length} document${files.length === 1 ? "" : "s"} uploaded and indexed.`,
      });
      navigate("/procurements");
    } catch (err) {
      toast.error("Registration failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit =
    title.trim().length > 0 &&
    files.length > 0 &&
    files.every((item) => item.procurementDocumentRole !== null) &&
    !submitting;

  return (
    <>
      <PageHeader
        title="Register New Procurement"
        description="Create a procurement case and attach one or more Swedish procurement documents."
        actions={
          <Button asChild variant="outline">
            <Link to="/procurements">
              <ArrowLeft className="h-4 w-4" /> Back to procurements
            </Link>
          </Button>
        }
      />

      <Card className="max-w-3xl">
        <CardContent className="space-y-5 p-6">
          <div className="space-y-2">
            <Label htmlFor="name">Procurement Name</Label>
            <Input
              id="name"
              placeholder="e.g. Skatteverket Cloud Migration 2026"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="authority">
              Issuing Authority <span className="text-muted-foreground">(optional)</span>
            </Label>
            <Input
              id="authority"
              placeholder="e.g. Skatteverket"
              value={issuingAuthority}
              onChange={(e) => setIssuingAuthority(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="desc">
              Description <span className="text-muted-foreground">(optional)</span>
            </Label>
            <Textarea
              id="desc"
              rows={3}
              placeholder="Short context to help the agents understand scope."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label>Upload documents</Label>
            <label
              className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-secondary/40 px-6 py-12 text-center hover:border-primary/40"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                void handleFiles(e.dataTransfer.files);
              }}
            >
              <UploadCloud className="mb-3 h-8 w-8 text-muted-foreground" />
              <p className="text-sm font-medium text-foreground">Drop PDF, DOCX, or ZIP files here</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Attach multiple files · ZIPs are unpacked into PDFs locally · max 50 MB each
              </p>
              <input
                type="file"
                accept="application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.pdf,.docx,application/zip,.zip"
                multiple
                className="sr-only"
                onChange={(e) => {
                  void handleFiles(e.target.files);
                  e.target.value = "";
                }}
              />
            </label>

            {files.length > 0 && (
              <>
                <ul className="mt-3 space-y-1.5">
                  {files.map((item, i) => (
                    <li
                      key={item.file.name}
                      className="grid gap-2 rounded-md border border-border bg-card px-3 py-2 sm:grid-cols-[1fr_220px_auto]"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="truncate text-sm text-foreground">{item.file.name}</span>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {(item.file.size / 1024 / 1024).toFixed(1)} MB
                        </span>
                      </div>
                      <Select
                        value={item.procurementDocumentRole ?? undefined}
                        onValueChange={(value) =>
                          updateFileRole(i, value as ProcurementDocumentRole)
                        }
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Choose document role" />
                        </SelectTrigger>
                        <SelectContent>
                          {PROCUREMENT_DOCUMENT_ROLE_OPTIONS.map((role) => (
                            <SelectItem key={role.value} value={role.value}>
                              {role.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-foreground"
                        onClick={() => removeFile(i)}
                        type="button"
                      >
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-muted-foreground">
                  {files.length} {files.length === 1 ? "file" : "files"} attached · assign a role for each file so pricing, contract, DPA, and requirements attachments are analysed separately.
                </p>
              </>
            )}
          </div>

          <div className="border-t border-border pt-5">
            <Button size="lg" className="w-full sm:w-auto" disabled={!canSubmit} onClick={handleSubmit}>
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Uploading…
                </>
              ) : (
                "Register procurement"
              )}
            </Button>
            <p className="mt-2 text-xs text-muted-foreground">
              Documents are uploaded with parse status &quot;pending&quot;. Procurement roles are stored with each file and follow the evidence pipeline.
            </p>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
