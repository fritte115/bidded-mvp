from __future__ import annotations

import hashlib
import re
import threading
import zipfile
from io import BytesIO
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from bidded.auth import AuthenticatedUser, authenticate_supabase_jwt
from bidded.company.website_import import (
    WebsiteImportError,
    import_company_website,
    resolve_website_profile_extractor,
)
from bidded.config import load_settings
from bidded.documents import (
    DOCX_CONTENT_TYPE,
    PDF_CONTENT_TYPE,
    CompanyKbDocumentType,
    CompanyKbError,
    CompanyKbUploadFile,
    PdfIngestionError,
    delete_company_kb_document,
    ensure_tender_evidence_items_for_document,
    ingest_company_kb_document,
    ingest_tender_document,
    list_company_kb_documents,
    list_company_kb_evidence,
    register_company_kb_documents,
)
from bidded.evidence.company_profile import upsert_company_profile_evidence
from bidded.llm.factory import resolve_graph_handlers
from bidded.orchestration import (
    PendingRunContextError,
    WorkerLifecycleError,
    bid_response_draft_to_payload,
    create_pending_run_context,
    fetch_latest_bid_response_draft,
    generate_bid_response_draft,
    run_worker_once,
)
from bidded.orchestration.run_controls import RunControlError, archive_agent_run
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


class ArchiveRunRequest(BaseModel):
    reason: str = "operator archived run"


class GenerateBidDraftRequest(BaseModel):
    run_id: str
    bid_id: str | None = None


DEMO_ORGANIZATION_ID = "00000000-0000-4000-8000-000000000001"


def require_authenticated_user(
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser:
    return authenticate_supabase_jwt(authorization)


AUTHENTICATED_USER = Depends(require_authenticated_user)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/company/import-website")
def import_company_website_route(
    req: CompanyWebsiteImportRequest,
    user: AuthenticatedUser = AUTHENTICATED_USER,
) -> dict[str, Any]:
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
def resync_company_evidence(
    user: AuthenticatedUser = AUTHENTICATED_USER,
) -> dict[str, Any]:
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
    require_company_admin(client, user, str(company_id))

    result = upsert_company_profile_evidence(
        client,
        company_id=company_id,
        company_profile=row,
    )
    return {
        "evidence_count": result.evidence_count,
        "rows_returned": result.rows_returned,
    }


@app.post("/api/company/kb/documents")
async def upload_company_kb_documents(
    files: Annotated[list[UploadFile], File()],
    kb_document_types: Annotated[list[str], Form()],
    company_id: Annotated[str | None, Form()] = None,
    user: AuthenticatedUser = AUTHENTICATED_USER,
) -> dict[str, Any]:
    settings = load_settings()
    client = _service_role_client(settings)
    resolved_company_id = company_id or _demo_company_id(client)
    require_company_admin(client, user, resolved_company_id)
    if len(files) != len(kb_document_types):
        raise HTTPException(
            status_code=422,
            detail="One kb_document_type is required for each uploaded file.",
        )

    upload_files: list[CompanyKbUploadFile] = []
    for upload, raw_type in zip(files, kb_document_types, strict=True):
        try:
            kb_document_type = CompanyKbDocumentType(raw_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported company KB document type: {raw_type}",
            ) from exc
        upload_files.append(
            CompanyKbUploadFile(
                filename=upload.filename or "document",
                content=await upload.read(),
                content_type=upload.content_type or "application/octet-stream",
                kb_document_type=kb_document_type,
            )
        )

    bucket = _company_kb_bucket(settings)
    try:
        registered = register_company_kb_documents(
            client,
            company_id=resolved_company_id,
            bucket_name=bucket,
            files=upload_files,
        )
    except CompanyKbError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    for document in registered:

        def _ingest(document_id: UUID = document.document_id) -> None:
            try:
                ingest_company_kb_document(
                    client,
                    document_id=document_id,
                    bucket_name=bucket,
                )
            except CompanyKbError as exc:
                print(f"[company-kb] document {document_id} failed: {exc}")

        threading.Thread(target=_ingest, daemon=True).start()

    return {
        "documents": [
            {
                "company_id": str(item.company_id),
                "document_id": str(item.document_id),
                "storage_path": item.storage_path,
                "checksum_sha256": item.checksum_sha256,
                "content_type": item.content_type,
                "original_filename": item.original_filename,
                "kb_document_type": item.kb_document_type.value,
                "parse_status": "pending",
                "extraction_status": "pending",
                "evidence_count": 0,
                "warnings": [],
            }
            for item in registered
        ]
    }


@app.get("/api/company/kb/documents")
def get_company_kb_documents(
    company_id: str | None = None,
    user: AuthenticatedUser = AUTHENTICATED_USER,
) -> dict[str, Any]:
    settings = load_settings()
    client = _service_role_client(settings)
    resolved_company_id = company_id or _demo_company_id(client)
    require_company_member(client, user, resolved_company_id)
    documents = list_company_kb_documents(client, company_id=resolved_company_id)
    return {
        "documents": [
            {
                "document_id": str(item.document_id),
                "company_id": str(item.company_id),
                "original_filename": item.original_filename,
                "storage_path": item.storage_path,
                "content_type": item.content_type,
                "parse_status": item.parse_status,
                "kb_document_type": item.kb_document_type.value,
                "extraction_status": item.extraction_status,
                "evidence_count": item.evidence_count,
                "warnings": list(item.warnings),
            }
            for item in documents
        ]
    }


@app.get("/api/company/kb/documents/{document_id}/evidence")
def get_company_kb_document_evidence(
    document_id: str,
    company_id: str | None = None,
    user: AuthenticatedUser = AUTHENTICATED_USER,
) -> dict[str, Any]:
    settings = load_settings()
    client = _service_role_client(settings)
    resolved_company_id = company_id or _demo_company_id(client)
    require_company_member(client, user, resolved_company_id)
    evidence = list_company_kb_evidence(
        client,
        company_id=resolved_company_id,
        document_id=document_id,
    )
    return {"evidence": evidence}


@app.delete("/api/company/kb/documents/{document_id}")
def delete_company_kb_document_endpoint(
    document_id: str,
    company_id: str | None = None,
    user: AuthenticatedUser = AUTHENTICATED_USER,
) -> dict[str, bool]:
    settings = load_settings()
    client = _service_role_client(settings)
    resolved_company_id = company_id or _demo_company_id(client)
    require_company_admin(client, user, resolved_company_id)
    try:
        delete_company_kb_document(
            client,
            company_id=resolved_company_id,
            document_id=document_id,
            bucket_name=_company_kb_bucket(settings),
        )
    except CompanyKbError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": True}


@app.put("/api/company/profile")
def update_company_profile_endpoint(
    profile_update: dict[str, Any],
    company_id: str | None = None,
    user: AuthenticatedUser = AUTHENTICATED_USER,
) -> dict[str, Any]:
    settings = load_settings()
    client = _service_role_client(settings)
    resolved_company_id = company_id or str(
        profile_update.get("company_id") or _demo_company_id(client)
    )
    require_company_admin(client, user, resolved_company_id)
    try:
        company_profile = update_company_profile_row(
            client,
            company_id=resolved_company_id,
            profile_update=profile_update,
        )
        evidence_result = upsert_company_profile_evidence(
            client,
            company_id=UUID(resolved_company_id),
            company_profile=company_profile,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "company_id": resolved_company_id,
        "evidence_count": evidence_result.evidence_count,
    }


@app.post("/api/runs/start")
def start_run(
    req: StartRunRequest,
    user: AuthenticatedUser = AUTHENTICATED_USER,
) -> dict[str, str]:
    settings = load_settings()
    from supabase import create_client  # noqa: PLC0415

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    require_tender_member(client, user, req.tender_id)

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
        # Auto-discover and register all supported documents from Supabase Storage
        registered_ids = _auto_register_from_storage(
            client, req.tender_id, company_id, settings
        )
        if not registered_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No documents found for this tender. "
                    "Ensure the PDF or DOCX files are in Supabase Storage under "
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
            ingest_tender_document(
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
                "No parseable documents in this tender — all documents failed to "
                "parse (likely image-only/scanned PDFs or DOCX conversion "
                "failures). v1 supports text PDFs and DOCX; re-upload "
                "text-layer versions and try again."
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


@app.post("/api/runs/{run_id}/archive")
def archive_run(
    run_id: str,
    req: ArchiveRunRequest,
    user: AuthenticatedUser = AUTHENTICATED_USER,
) -> dict[str, Any]:
    settings = load_settings()
    from supabase import create_client  # noqa: PLC0415

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    require_agent_run_admin(client, user, run_id)
    try:
        result = archive_agent_run(
            client,
            run_id=run_id,
            reason=req.reason,
        )
    except RunControlError as exc:
        status_code = 404 if "does not exist" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    return {
        "run_id": str(result.run_id),
        "archived_at": result.archived_at,
        "already_archived": result.already_archived,
    }


@app.post("/api/bid-drafts/generate")
def generate_bid_draft(
    req: GenerateBidDraftRequest,
    user: AuthenticatedUser = AUTHENTICATED_USER,
) -> dict[str, Any]:
    settings = load_settings()
    client = _service_role_client(settings)
    require_agent_run_member(client, user, req.run_id)
    try:
        draft = generate_bid_response_draft(
            client,
            run_id=req.run_id,
            bid_id=req.bid_id,
            storage_bucket=(
                getattr(settings, "supabase_storage_bucket", None)
                or "public-procurements"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return bid_response_draft_to_payload(draft)


@app.get("/api/bid-drafts/latest")
def latest_bid_draft(
    run_id: str,
    user: AuthenticatedUser = AUTHENTICATED_USER,
) -> dict[str, Any]:
    settings = load_settings()
    client = _service_role_client(settings)
    require_agent_run_member(client, user, run_id)
    draft = fetch_latest_bid_response_draft(client, run_id=run_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"No draft for run {run_id}.")
    return bid_response_draft_to_payload(draft)


def require_agent_run_admin(
    client: Any,
    user: AuthenticatedUser,
    run_id: str,
) -> str:
    organization_id = _organization_id_for_row(client, "agent_runs", run_id)
    _require_org_role(
        client,
        user,
        organization_id,
        allowed_roles={"admin"},
        action="archive agent runs",
    )
    return organization_id


def require_agent_run_member(
    client: Any,
    user: AuthenticatedUser,
    run_id: str,
) -> str:
    organization_id = _organization_id_for_row(client, "agent_runs", run_id)
    _require_org_role(
        client,
        user,
        organization_id,
        allowed_roles={"admin", "user"},
        action="view bid draft responses",
    )
    return organization_id


def require_tender_member(
    client: Any,
    user: AuthenticatedUser,
    tender_id: str,
) -> str:
    organization_id = _organization_id_for_row(client, "tenders", tender_id)
    _require_org_role(
        client,
        user,
        organization_id,
        allowed_roles={"admin", "user"},
        action="start runs for this procurement",
    )
    return organization_id


def require_company_admin(
    client: Any,
    user: AuthenticatedUser,
    company_id: str,
) -> str:
    organization_id = _organization_id_for_row(client, "companies", company_id)
    _require_org_role(
        client,
        user,
        organization_id,
        allowed_roles={"admin"},
        action="resync company evidence",
    )
    return organization_id


def require_company_member(
    client: Any,
    user: AuthenticatedUser,
    company_id: str,
) -> str:
    organization_id = _organization_id_for_row(client, "companies", company_id)
    _require_org_role(
        client,
        user,
        organization_id,
        allowed_roles={"admin", "user"},
        action="view company knowledge base",
    )
    return organization_id


def update_company_profile_row(
    client: Any,
    *,
    company_id: str,
    profile_update: dict[str, Any],
) -> dict[str, Any]:
    allowed = {
        "name",
        "profile_label",
        "organization_number",
        "headquarters_country",
        "employee_count",
        "annual_revenue_sek",
        "capabilities",
        "certifications",
        "reference_projects",
        "financial_assumptions",
        "profile_details",
        "metadata",
    }
    payload = {
        key: value
        for key, value in profile_update.items()
        if key in allowed and value is not None
    }
    if not payload:
        raise ValueError("No supported company profile fields supplied.")

    updated_rows = _response_rows(
        client.table("companies")
        .update(payload)
        .eq("tenant_key", "demo")
        .eq("id", str(company_id))
        .execute()
    )
    updated_id = updated_rows[0].get("id") if updated_rows else company_id
    full_rows = _response_rows(
        client.table("companies")
        .select(
            "id,tenant_key,name,profile_label,organization_number,"
            "headquarters_country,employee_count,annual_revenue_sek,"
            "capabilities,certifications,reference_projects,"
            "financial_assumptions,profile_details,metadata"
        )
        .eq("tenant_key", "demo")
        .eq("id", str(updated_id))
        .execute()
    )
    if not full_rows:
        raise RuntimeError(f"Demo company does not exist: {company_id}")
    return dict(full_rows[0])


def _organization_id_for_row(client: Any, table_name: str, row_id: str) -> str:
    response = (
        client.table(table_name)
        .select("id,organization_id")
        .eq("id", row_id)
        .limit(1)
        .execute()
    )
    rows = list(getattr(response, "data", None) or [])
    if not rows:
        raise HTTPException(status_code=404, detail=f"{table_name} row not found.")
    return str(rows[0].get("organization_id") or DEMO_ORGANIZATION_ID)


def _require_org_role(
    client: Any,
    user: AuthenticatedUser,
    organization_id: str,
    *,
    allowed_roles: set[str],
    action: str,
) -> None:
    if _user_is_superadmin(client, user.user_id):
        return

    response = (
        client.table("organization_memberships")
        .select("role,status")
        .eq("organization_id", organization_id)
        .eq("user_id", user.user_id)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    rows = list(getattr(response, "data", None) or [])
    role = str(rows[0].get("role")) if rows else ""
    if role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail=f"You do not have permission to {action}.",
        )


def _user_is_superadmin(client: Any, user_id: str) -> bool:
    response = (
        client.table("profiles")
        .select("global_role")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = list(getattr(response, "data", None) or [])
    return bool(rows and rows[0].get("global_role") == "superadmin")


# ---------------------------------------------------------------------------
# Storage-based document auto-discovery
# ---------------------------------------------------------------------------


def _auto_register_from_storage(
    client: Any,
    tender_id: str,
    company_id: str,
    settings: Any,
) -> list[str]:
    """Discover and register supported Storage documents for this tender."""
    tender_resp = (
        client.table("tenders").select("title").eq("id", tender_id).single().execute()
    )
    if not getattr(tender_resp, "data", None):
        return []

    title: str = tender_resp.data["title"]
    bucket: str = (
        getattr(settings, "supabase_storage_bucket", None) or "public-procurements"
    )
    document_hits = _find_all_supported_documents_in_storage(client, bucket, title)
    if not document_hits:
        return []

    registered: list[str] = []
    for storage_path, document_bytes, content_type in document_hits:
        checksum = hashlib.sha256(document_bytes).hexdigest()
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
                    "content_type": content_type,
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


def _find_all_supported_documents_in_storage(
    client: Any, bucket: str, title: str
) -> list[tuple[str, bytes, str]]:
    """Return supported procurement documents under the tender's folder."""
    title_slug = _slugify(title)

    # Try canonical paths first
    for folder in [
        f"demo/procurements/{title_slug}",
        f"demo/procurements/{title}",
    ]:
        hits = _collect_supported_documents_in_folder(client, bucket, folder)
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
            hits = _collect_supported_documents_in_folder(
                client, bucket, f"demo/procurements/{folder_name}"
            )
            if hits:
                return hits

    return []


def _collect_supported_documents_in_folder(
    client: Any, bucket: str, folder: str
) -> list[tuple[str, bytes, str]]:
    """Download all valid PDF/DOCX files in a storage folder."""
    try:
        objects = client.storage.from_(bucket).list(folder)
    except Exception:  # noqa: BLE001
        return []

    results: list[tuple[str, bytes, str]] = []
    for obj in objects or []:
        name: str = obj.get("name", "")
        content_type = _content_type_for_supported_document_name(name)
        if content_type is None:
            continue
        full_path = f"{folder}/{name}"
        try:
            document_bytes = client.storage.from_(bucket).download(full_path)
        except Exception:  # noqa: BLE001
            continue
        if _is_valid_supported_document_bytes(document_bytes, content_type):
            results.append((full_path, document_bytes, content_type))

    return results


def _content_type_for_supported_document_name(name: str) -> str | None:
    lowered = name.lower()
    if lowered.endswith(".pdf"):
        return PDF_CONTENT_TYPE
    if lowered.endswith(".docx"):
        return DOCX_CONTENT_TYPE
    return None


def _is_valid_supported_document_bytes(value: object, content_type: str) -> bool:
    if not isinstance(value, bytes):
        return False
    if content_type == PDF_CONTENT_TYPE:
        return value.startswith(b"%PDF-")
    if content_type == DOCX_CONTENT_TYPE:
        try:
            with zipfile.ZipFile(BytesIO(value)) as archive:
                return "word/document.xml" in archive.namelist()
        except zipfile.BadZipFile:
            return False
    return False


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _service_role_client(settings: Any) -> Any:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(
            status_code=400, detail="Supabase service settings missing."
        )
    from supabase import create_client  # noqa: PLC0415

    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _demo_company_id(client: Any) -> str:
    company_resp = (
        client.table("companies")
        .select("id")
        .eq("tenant_key", "demo")
        .limit(1)
        .execute()
    )
    if not company_resp.data:
        raise RuntimeError(
            "Demo company not seeded. Run: .venv/bin/bidded seed-demo-company"
        )
    return str(company_resp.data[0]["id"])


def _company_kb_bucket(settings: Any) -> str:
    return str(
        getattr(settings, "company_kb_storage_bucket", None) or "company-knowledge"
    )


def _response_rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    return [dict(row) for row in data or [] if isinstance(row, dict)]
