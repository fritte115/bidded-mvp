from __future__ import annotations

import hashlib
import re
import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from bidded.company.website_import import (
    WebsiteImportError,
    import_company_website,
    resolve_website_profile_extractor,
)
from bidded.config import load_settings
from bidded.documents import (
    PdfIngestionError,
    ensure_tender_evidence_items_for_document,
    ingest_tender_pdf_document,
)
from bidded.evidence.company_profile import upsert_company_profile_evidence
from bidded.llm.factory import resolve_graph_handlers
from bidded.orchestration import (
    PendingRunContextError,
    WorkerLifecycleError,
    create_pending_run_context,
    run_worker_once,
)
from bidded.retrieval import RetrievalError

app = FastAPI(title="Bidded Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartRunRequest(BaseModel):
    tender_id: str


class CompanyWebsiteImportRequest(BaseModel):
    url: str
    max_pages: int = Field(default=5, ge=1, le=5)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/company/import-website")
def import_company_website_route(req: CompanyWebsiteImportRequest) -> dict[str, Any]:
    settings = load_settings()
    try:
        return import_company_website(
            url=req.url,
            max_pages=req.max_pages,
            extractor=resolve_website_profile_extractor(settings),
        )
    except WebsiteImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/company/resync-evidence")
def resync_company_evidence() -> dict[str, Any]:
    """Re-materialize `company_profile` evidence_items from the current
    `companies` row.

    Call this after the frontend edits the company profile so the swarm sees
    the updated values on its next run. Uses the service-role client so the
    upsert can bypass RLS on `evidence_items`.
    """
    settings = load_settings()
    from uuid import UUID  # noqa: PLC0415

    from supabase import create_client  # noqa: PLC0415

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    company_resp = (
        client.table("companies")
        .select("*")
        .eq("tenant_key", "demo")
        .limit(1)
        .execute()
    )
    if not company_resp.data:
        raise HTTPException(
            status_code=400,
            detail="Demo company not seeded.",
        )
    row = company_resp.data[0]
    company_id = UUID(str(row["id"]))

    result = upsert_company_profile_evidence(
        client,
        company_id=company_id,
        company_profile=row,
    )
    return {
        "evidence_count": result.evidence_count,
        "rows_returned": result.rows_returned,
    }


@app.post("/api/runs/start")
def start_run(req: StartRunRequest) -> dict[str, str]:
    settings = load_settings()
    from supabase import create_client  # noqa: PLC0415

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    # Resolve demo company
    company_resp = (
        client.table("companies")
        .select("id")
        .eq("tenant_key", "demo")
        .limit(1)
        .execute()
    )
    if not company_resp.data:
        raise HTTPException(
            status_code=400,
            detail="Demo company not seeded. Run: .venv/bin/bidded seed-demo-company",
        )
    company_id: str = company_resp.data[0]["id"]

    bucket: str = (
        getattr(settings, "supabase_storage_bucket", None) or "public-procurements"
    )

    # Find all registered documents for this tender
    docs_resp = (
        client.table("documents")
        .select("id,parse_status")
        .eq("tender_id", req.tender_id)
        .eq("tenant_key", "demo")
        .execute()
    )

    doc_rows: list[dict[str, Any]] = list(docs_resp.data or [])

    if not doc_rows:
        # Auto-discover and register ALL PDFs from Supabase Storage
        registered_ids = _auto_register_from_storage(
            client, req.tender_id, company_id, settings
        )
        if not registered_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No documents found for this tender. "
                    "Ensure the PDFs are in Supabase Storage under "
                    "demo/procurements/<tender-name>/."
                ),
            )
        doc_rows = [{"id": did, "parse_status": "pending"} for did in registered_ids]

    # Parse each document that isn't already parsed. `parser_failed` docs are
    # retried on every run — a previous failure may have been transient
    # (network blip, storage hiccup) or fixable (user re-uploaded a text-layer
    # version of a scanned PDF). If the retry also fails, we skip that doc
    # for *this* run and continue with whatever else parses.
    #
    # If a run ends up with *zero* parseable documents we abort — there's no
    # material for the swarm to analyse. Otherwise `document_ids` excludes
    # failed docs so downstream evidence materialization and pending-run
    # creation only reference documents that actually parsed.
    skipped_failed: list[str] = []
    for row in doc_rows:
        status = row.get("parse_status")
        if status == "parsed":
            continue
        # `pending`, `parsing`, and `parser_failed` all fall through to a
        # parse attempt. For `parser_failed` this is a retry.
        try:
            ingest_tender_pdf_document(
                client, document_id=row["id"], bucket_name=bucket
            )
        except PdfIngestionError as exc:
            # `_update_document_parse_status` has already flipped the DB row
            # to `parser_failed`; we just skip it for this run and continue.
            skipped_failed.append(row["id"])
            retry_note = " (retry failed)" if status == "parser_failed" else ""
            print(
                f"[runs/start] skipping parser_failed document {row['id']}"
                f"{retry_note}: {exc}"
            )

    document_ids = [row["id"] for row in doc_rows if row["id"] not in skipped_failed]

    if not document_ids:
        raise HTTPException(
            status_code=422,
            detail=(
                "No parseable documents in this tender — all PDFs failed to "
                "parse (likely image-only or scanned). v1 only supports text "
                "PDFs; re-upload text-layer versions and try again."
            ),
        )

    # Tender evidence_items are derived from chunks; ensure rows exist even for
    # documents parsed before this materialization step existed.
    for did in document_ids:
        try:
            ensure_tender_evidence_items_for_document(client, document_id=did)
        except (RetrievalError, ValueError, PdfIngestionError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"tender evidence materialization failed for {did}: {exc}",
            ) from exc

    # Create pending run with all document IDs
    try:
        pending = create_pending_run_context(
            client,
            tender_id=req.tender_id,
            company_id=company_id,
            document_ids=document_ids,
        )
    except PendingRunContextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run_id = str(pending.run_id)

    # Execute worker in a background thread so the request returns immediately
    def _run_worker() -> None:
        worker_settings = load_settings()
        from supabase import create_client as _create  # noqa: PLC0415

        worker_client = _create(
            worker_settings.supabase_url, worker_settings.supabase_service_role_key
        )
        try:
            run_worker_once(
                worker_client,
                run_id=run_id,
                log=print,
                graph_handlers=resolve_graph_handlers(worker_settings),
            )
        except WorkerLifecycleError as exc:
            print(f"[worker] run {run_id} failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] unexpected error for run {run_id}: {exc}")

    threading.Thread(target=_run_worker, daemon=True).start()

    return {"run_id": run_id}


# ---------------------------------------------------------------------------
# Storage-based document auto-discovery
# ---------------------------------------------------------------------------


def _auto_register_from_storage(
    client: Any,
    tender_id: str,
    company_id: str,
    settings: Any,
) -> list[str]:
    """Discover and register all Storage PDFs for this tender. Returns document IDs."""
    tender_resp = (
        client.table("tenders").select("title").eq("id", tender_id).single().execute()
    )
    if not getattr(tender_resp, "data", None):
        return []

    title: str = tender_resp.data["title"]
    bucket: str = (
        getattr(settings, "supabase_storage_bucket", None) or "public-procurements"
    )
    pdf_hits = _find_all_pdfs_in_storage(client, bucket, title)
    if not pdf_hits:
        return []

    registered: list[str] = []
    for storage_path, pdf_bytes in pdf_hits:
        checksum = hashlib.sha256(pdf_bytes).hexdigest()
        original_filename = storage_path.rsplit("/", 1)[-1]
        doc_resp = (
            client.table("documents")
            .upsert(
                {
                    "tenant_key": "demo",
                    "tender_id": tender_id,
                    "company_id": None,
                    "storage_path": storage_path,
                    "checksum_sha256": checksum,
                    "content_type": "application/pdf",
                    "document_role": "tender_document",
                    "parse_status": "pending",
                    "original_filename": original_filename,
                    "metadata": {
                        "registered_via": "api_auto_discover",
                        "demo_company_id": company_id,
                    },
                },
                on_conflict="storage_path",
            )
            .execute()
        )
        data = getattr(doc_resp, "data", None)
        if isinstance(data, list) and data:
            doc_id = data[0].get("id")
            if doc_id:
                registered.append(str(doc_id))

    return registered


def _find_all_pdfs_in_storage(
    client: Any, bucket: str, title: str
) -> list[tuple[str, bytes]]:
    """Return (storage_path, pdf_bytes) for every PDF under the tender's folder."""
    title_slug = _slugify(title)

    # Try canonical paths first
    for folder in [
        f"demo/procurements/{title_slug}",
        f"demo/procurements/{title}",
    ]:
        hits = _collect_pdfs_in_folder(client, bucket, folder)
        if hits:
            return hits

    # Fall back: scan all subfolders and match by slug similarity
    try:
        root_objects = client.storage.from_(bucket).list("demo/procurements")
    except Exception:  # noqa: BLE001
        return []

    for obj in root_objects or []:
        folder_name: str = obj.get("name", "")
        if not folder_name:
            continue
        if _slugify(folder_name) == title_slug or title_slug in _slugify(folder_name):
            hits = _collect_pdfs_in_folder(
                client, bucket, f"demo/procurements/{folder_name}"
            )
            if hits:
                return hits

    return []


def _collect_pdfs_in_folder(
    client: Any, bucket: str, folder: str
) -> list[tuple[str, bytes]]:
    """Download all valid PDFs in a storage folder. Returns list of (path, bytes)."""
    try:
        objects = client.storage.from_(bucket).list(folder)
    except Exception:  # noqa: BLE001
        return []

    results: list[tuple[str, bytes]] = []
    for obj in objects or []:
        name: str = obj.get("name", "")
        if not name.lower().endswith(".pdf"):
            continue
        full_path = f"{folder}/{name}"
        try:
            pdf_bytes = client.storage.from_(bucket).download(full_path)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(pdf_bytes, bytes) and pdf_bytes.startswith(b"%PDF-"):
            results.append((full_path, pdf_bytes))

    return results


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)
