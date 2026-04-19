from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _core_schema_sql() -> str:
    migration_files = sorted(
        (PROJECT_ROOT / "supabase" / "migrations").glob("*_create_core_domain.sql")
    )

    assert [path.name for path in migration_files] == [
        "20260418180000_create_core_domain.sql"
    ]
    return migration_files[0].read_text()


def _agent_audit_sql() -> str:
    migration_files = sorted(
        (PROJECT_ROOT / "supabase" / "migrations").glob("*_create_agent_audit.sql")
    )

    assert [path.name for path in migration_files] == [
        "20260418181000_create_agent_audit.sql"
    ]
    return migration_files[0].read_text()


def _chunk_evidence_sql() -> str:
    migration_files = sorted(
        (PROJECT_ROOT / "supabase" / "migrations").glob("*_create_chunk_evidence.sql")
    )

    assert [path.name for path in migration_files] == [
        "20260418182000_create_chunk_evidence.sql"
    ]
    return migration_files[0].read_text()


def _requirement_type_sql() -> str:
    migration_files = sorted(
        (PROJECT_ROOT / "supabase" / "migrations").glob(
            "*_add_evidence_requirement_type.sql"
        )
    )

    assert [path.name for path in migration_files] == [
        "20260418213000_add_evidence_requirement_type.sql"
    ]
    return migration_files[0].read_text()


def _pgvector_search_sql() -> str:
    migration_files = sorted(
        (PROJECT_ROOT / "supabase" / "migrations").glob("*_add_pgvector_search.sql")
    )

    assert [path.name for path in migration_files] == [
        "20260419013000_add_pgvector_search.sql"
    ]
    return migration_files[0].read_text()


def _table_body(sql: str, table_name: str) -> str:
    match = re.search(
        rf"create table if not exists public\.{table_name}\s*\((?P<body>.*?)\);",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )

    assert match, f"Missing create table statement for public.{table_name}"
    return re.sub(r"\s+", " ", match.group("body").lower())


def test_core_domain_migration_creates_demo_scoped_tables() -> None:
    sql = _core_schema_sql().lower()

    assert "create extension if not exists pgcrypto;" in sql
    assert "enable row level security" not in sql
    assert "create policy" not in sql
    assert "auth.uid" not in sql

    for table_name in ["companies", "tenders", "documents"]:
        table_body = _table_body(sql, table_name)

        assert "id uuid primary key default gen_random_uuid()" in table_body
        assert "created_at timestamptz not null default now()" in table_body
        assert "tenant_key text not null default 'demo'" in table_body
        assert (
            f"constraint {table_name}_tenant_key_demo_check check (tenant_key = 'demo')"
        ) in table_body


def test_documents_store_upload_state_and_tender_or_company_linkage() -> None:
    table_body = _table_body(_core_schema_sql(), "documents")

    for required_fragment in [
        "tender_id uuid references public.tenders(id) on delete cascade",
        "company_id uuid references public.companies(id) on delete cascade",
        "storage_path text not null",
        "checksum_sha256 text not null",
        "content_type text not null",
        "document_role text not null",
        "parse_status text not null",
        "original_filename text not null",
        "metadata jsonb not null default '{}'::jsonb",
        "constraint documents_storage_path_key unique (storage_path)",
        (
            "constraint documents_checksum_sha256_check "
            "check (checksum_sha256 ~ '^[a-f0-9]{64}$')"
        ),
        (
            "constraint documents_document_role_check "
            "check (document_role in ('tender_document', 'company_profile'))"
        ),
        (
            "constraint documents_parse_status_check "
            "check (parse_status in ('pending', 'parsing', 'parsed', "
            "'parser_failed'))"
        ),
    ]:
        assert required_fragment in table_body

    assert "constraint documents_role_link_check check" in table_body
    assert (
        "document_role = 'tender_document' and tender_id is not null and "
        "company_id is null"
    ) in table_body
    assert (
        "document_role = 'company_profile' and company_id is not null and "
        "tender_id is null"
    ) in table_body


def test_tenders_store_procurement_context_and_language_policy() -> None:
    table_body = _table_body(_core_schema_sql(), "tenders")

    for required_fragment in [
        "title text not null",
        "issuing_authority text not null",
        "procurement_reference text",
        "procurement_context jsonb not null default '{}'::jsonb",
        "language_policy jsonb not null default '{}'::jsonb",
        "metadata jsonb not null default '{}'::jsonb",
        (
            "constraint tenders_tenant_title_authority_key "
            "unique (tenant_key, title, issuing_authority)"
        ),
    ]:
        assert required_fragment in table_body


def test_companies_store_seeded_it_consultancy_profile_contract() -> None:
    table_body = _table_body(_core_schema_sql(), "companies")

    for required_fragment in [
        "name text not null",
        "profile_label text not null default 'seeded_it_consultancy'",
        "organization_number text",
        "headquarters_country text not null default 'se'",
        "employee_count integer",
        "annual_revenue_sek numeric",
        "capabilities jsonb not null default '{}'::jsonb",
        "certifications jsonb not null default '[]'::jsonb",
        "reference_projects jsonb not null default '[]'::jsonb",
        "financial_assumptions jsonb not null default '{}'::jsonb",
        "profile_details jsonb not null default '{}'::jsonb",
        "metadata jsonb not null default '{}'::jsonb",
        "constraint companies_tenant_name_key unique (tenant_key, name)",
        (
            "constraint companies_employee_count_check "
            "check (employee_count is null or employee_count > 0)"
        ),
        (
            "constraint companies_annual_revenue_sek_check "
            "check (annual_revenue_sek is null or annual_revenue_sek >= 0)"
        ),
    ]:
        assert required_fragment in table_body


def test_agent_audit_migration_creates_demo_scoped_audit_tables() -> None:
    sql = _agent_audit_sql().lower()

    assert "enable row level security" not in sql
    assert "create policy" not in sql
    assert "auth.uid" not in sql

    for table_name in ["agent_runs", "agent_outputs", "bid_decisions"]:
        table_body = _table_body(sql, table_name)

        assert "id uuid primary key default gen_random_uuid()" in table_body
        assert "created_at timestamptz not null default now()" in table_body
        assert "tenant_key text not null default 'demo'" in table_body
        assert (
            f"constraint {table_name}_tenant_key_demo_check check (tenant_key = 'demo')"
        ) in table_body


def test_agent_runs_track_lifecycle_targets_and_runtime_metadata() -> None:
    table_body = _table_body(_agent_audit_sql(), "agent_runs")

    for required_fragment in [
        "tender_id uuid not null references public.tenders(id)",
        "company_id uuid not null references public.companies(id)",
        "status text not null default 'pending'",
        "run_config jsonb not null default '{}'::jsonb",
        "error_details jsonb",
        "started_at timestamptz",
        "completed_at timestamptz",
        (
            "constraint agent_runs_status_check "
            "check (status in ('pending', 'running', 'succeeded', 'failed', "
            "'needs_human_review'))"
        ),
        (
            "constraint agent_runs_completion_time_check "
            "check (completed_at is null or started_at is not null)"
        ),
    ]:
        assert required_fragment in table_body


def test_agent_outputs_are_validated_immutable_agent_round_artifacts() -> None:
    sql = _agent_audit_sql().lower()
    table_body = _table_body(sql, "agent_outputs")

    for required_fragment in [
        "agent_run_id uuid not null references public.agent_runs(id)",
        "agent_role text not null",
        "round_name text not null",
        "output_type text not null",
        "validated_payload jsonb not null",
        "model_metadata jsonb not null default '{}'::jsonb",
        "started_at timestamptz",
        "completed_at timestamptz",
        "duration_ms integer",
        "input_tokens integer",
        "output_tokens integer",
        "estimated_cost_usd numeric",
        "validation_errors jsonb not null default '[]'::jsonb",
        (
            "constraint agent_outputs_run_role_round_output_key "
            "unique (agent_run_id, agent_role, round_name, output_type)"
        ),
        "constraint agent_outputs_agent_role_check check (agent_role <> '')",
        "constraint agent_outputs_round_name_check check (round_name <> '')",
    ]:
        assert required_fragment in table_body

    assert "create or replace function public.reject_agent_output_mutation()" in sql
    assert "create trigger agent_outputs_immutable_before_update" in sql
    assert "before update or delete on public.agent_outputs" in sql


def test_bid_decisions_store_final_verdict_and_evidence_links() -> None:
    table_body = _table_body(_agent_audit_sql(), "bid_decisions")

    for required_fragment in [
        "agent_run_id uuid not null references public.agent_runs(id)",
        "final_decision jsonb not null",
        "verdict text not null",
        "confidence numeric not null",
        "evidence_ids uuid[] not null default '{}'::uuid[]",
        "constraint bid_decisions_agent_run_id_key unique (agent_run_id)",
        (
            "constraint bid_decisions_verdict_check "
            "check (verdict in ('bid', 'no_bid', 'conditional_bid', "
            "'needs_human_review'))"
        ),
        (
            "constraint bid_decisions_confidence_check "
            "check (confidence >= 0 and confidence <= 1)"
        ),
    ]:
        assert required_fragment in table_body


def test_chunk_evidence_migration_creates_demo_scoped_evidence_tables() -> None:
    sql = _chunk_evidence_sql().lower()

    assert "enable row level security" not in sql
    assert "create policy" not in sql
    assert "auth.uid" not in sql

    for table_name in ["document_chunks", "evidence_items"]:
        table_body = _table_body(sql, table_name)

        assert "id uuid primary key default gen_random_uuid()" in table_body
        assert "created_at timestamptz not null default now()" in table_body
        assert "tenant_key text not null default 'demo'" in table_body
        assert (
            f"constraint {table_name}_tenant_key_demo_check check (tenant_key = 'demo')"
        ) in table_body


def test_document_chunks_store_page_text_and_nullable_embedding_support() -> None:
    table_body = _table_body(_chunk_evidence_sql(), "document_chunks")

    for required_fragment in [
        "document_id uuid not null references public.documents(id) on delete cascade",
        "page_start integer not null",
        "page_end integer not null",
        "chunk_index integer not null",
        "text text not null",
        "metadata jsonb not null default '{}'::jsonb",
        "embedding vector(1536)",
        (
            "constraint document_chunks_document_chunk_index_key "
            "unique (document_id, chunk_index)"
        ),
        "constraint document_chunks_page_start_check check (page_start > 0)",
        ("constraint document_chunks_page_end_check check (page_end >= page_start)"),
        "constraint document_chunks_chunk_index_check check (chunk_index >= 0)",
        "constraint document_chunks_text_check check (text <> '')",
    ]:
        assert required_fragment in table_body

    assert "embedding vector(1536) not null" not in table_body


def test_evidence_items_store_stable_excerpt_claims() -> None:
    table_body = _table_body(_chunk_evidence_sql(), "evidence_items")

    for required_fragment in [
        "evidence_key text not null",
        "source_type text not null",
        "excerpt text not null",
        "normalized_meaning text not null",
        "category text not null",
        "confidence numeric not null",
        "source_metadata jsonb not null default '{}'::jsonb",
        "document_id uuid references public.documents(id) on delete cascade",
        "chunk_id uuid references public.document_chunks(id) on delete cascade",
        "page_start integer",
        "page_end integer",
        "company_id uuid references public.companies(id) on delete cascade",
        "field_path text",
        (
            "constraint evidence_items_tenant_evidence_key_key "
            "unique (tenant_key, evidence_key)"
        ),
        (
            "constraint evidence_items_source_type_check "
            "check (source_type in ('tender_document', 'company_profile'))"
        ),
        (
            "constraint evidence_items_confidence_check "
            "check (confidence >= 0 and confidence <= 1)"
        ),
        "constraint evidence_items_excerpt_check check (excerpt <> '')",
        (
            "constraint evidence_items_normalized_meaning_check "
            "check (normalized_meaning <> '')"
        ),
    ]:
        assert required_fragment in table_body


def test_evidence_items_require_tender_and_company_provenance() -> None:
    table_body = _table_body(_chunk_evidence_sql(), "evidence_items")

    for required_fragment in [
        (
            "constraint evidence_items_source_metadata_object_check "
            "check (jsonb_typeof(source_metadata) = 'object')"
        ),
        (
            "constraint evidence_items_source_label_check "
            "check (source_metadata ? 'source_label')"
        ),
        "constraint evidence_items_tender_document_source_check check",
        "source_type <> 'tender_document'",
        "document_id is not null",
        "chunk_id is not null",
        "page_start is not null",
        "page_end is not null",
        "constraint evidence_items_company_profile_source_check check",
        "source_type <> 'company_profile'",
        "company_id is not null",
        "field_path is not null",
    ]:
        assert required_fragment in table_body


def test_evidence_items_requirement_type_migration_contract() -> None:
    sql = re.sub(r"\s+", " ", _requirement_type_sql().lower())

    assert (
        "alter table if exists public.evidence_items "
        "add column if not exists requirement_type text"
    ) in sql
    assert "constraint_name = 'evidence_items_requirement_type_check'" in sql
    assert "add constraint evidence_items_requirement_type_check check" in sql
    assert "requirement_type is null" in sql
    for requirement_type in [
        "shall_requirement",
        "qualification_requirement",
        "exclusion_ground",
        "financial_standing",
        "legal_or_regulatory_reference",
        "quality_management",
        "submission_document",
        "contract_obligation",
    ]:
        assert f"'{requirement_type}'" in sql


def test_pgvector_search_migration_adds_index_and_rpc_contract() -> None:
    sql = re.sub(r"\s+", " ", _pgvector_search_sql().lower())

    assert "create extension if not exists vector;" in sql
    assert "create index if not exists document_chunks_embedding_hnsw_idx" in sql
    assert "using hnsw (embedding vector_cosine_ops)" in sql
    assert "where embedding is not null" in sql
    assert "create or replace function public.match_document_chunks(" in sql
    for required_fragment in [
        "query_embedding vector(1536)",
        "match_count integer default 5",
        "match_threshold double precision default 0",
        "tenant_key text default 'demo'",
        "document_id uuid default null",
        "returns table (",
        "chunk_id uuid",
        "chunk_document_id uuid",
        "page_start integer",
        "page_end integer",
        "chunk_index integer",
        "text text",
        "metadata jsonb",
        "similarity double precision",
    ]:
        assert required_fragment in sql

    assert "dc.embedding is not null" in sql
    assert "dc.tenant_key = match_document_chunks.tenant_key" in sql
    assert (
        "match_document_chunks.document_id is null "
        "or dc.document_id = match_document_chunks.document_id"
    ) in sql
    assert "dc.embedding <=> query_embedding" in sql
    assert "least(greatest(match_count, 1), 50)" in sql
