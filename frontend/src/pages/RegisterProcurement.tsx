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
import { ArrowLeft, UploadCloud, FileText, X, Loader2 } from "lucide-react";
import { registerProcurement } from "@/lib/api";
import { normalizeDocumentUploads } from "@/lib/documentUploads";

export default function RegisterProcurement() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [title, setTitle] = useState("");
  const [issuingAuthority, setIssuingAuthority] = useState("");
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);

  async function handleFiles(incoming: FileList | null) {
    if (!incoming) return;

    const result = await normalizeDocumentUploads(Array.from(incoming));
    if (result.accepted.length > 0) {
      setFiles((prev) => {
        const existingNames = new Set(prev.map((file) => file.name));
        return [
          ...prev,
          ...result.accepted
            .map((item) => item.file)
            .filter((file) => !existingNames.has(file.name)),
        ];
      });
    }

    if (result.rejected.length > 0) {
      const description = result.rejected
        .slice(0, 3)
        .map((entry) => `${entry.name}: ${entry.reason}`)
        .join(" · ");
      if (result.accepted.length > 0) {
        toast("Some files were skipped", { description });
      } else {
        toast.error("No PDF files were added", { description });
      }
    }
  }

  function removeFile(i: number) {
    setFiles((prev) => prev.filter((_, idx) => idx !== i));
  }

  async function handleSubmit() {
    if (!title.trim() || files.length === 0) return;
    setSubmitting(true);
    try {
      await registerProcurement({ title: title.trim(), issuingAuthority: issuingAuthority.trim(), files });
      await queryClient.invalidateQueries({ queryKey: ["procurements"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success("Procurement registered", {
        description: `${files.length} PDF${files.length === 1 ? "" : "s"} uploaded and indexed.`,
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

  const canSubmit = title.trim().length > 0 && files.length > 0 && !submitting;

  return (
    <>
      <PageHeader
        title="Register New Procurement"
        description="Create a procurement case and attach one or more Swedish procurement PDFs."
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
            <Label>Upload PDFs</Label>
            <label
              className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-secondary/40 px-6 py-12 text-center hover:border-primary/40"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                void handleFiles(e.dataTransfer.files);
              }}
            >
              <UploadCloud className="mb-3 h-8 w-8 text-muted-foreground" />
              <p className="text-sm font-medium text-foreground">Drop PDFs or ZIPs here or click to upload</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Attach multiple files · ZIPs are unpacked into PDFs locally · max 50 MB per PDF
              </p>
              <input
                type="file"
                accept="application/pdf,.pdf,application/zip,.zip"
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
                  {files.map((f, i) => (
                    <li
                      key={f.name}
                      className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="truncate text-sm text-foreground">{f.name}</span>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {(f.size / 1024 / 1024).toFixed(1)} MB
                        </span>
                      </div>
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
                  {files.length} {files.length === 1 ? "file" : "files"} attached · ZIP entries are stored as individual PDFs in Supabase; text extraction and chunking run when the ingest worker is available (PRD backlog).
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
              Documents are uploaded and registered with parse status &quot;pending&quot; until the ingestion pipeline runs.
            </p>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
