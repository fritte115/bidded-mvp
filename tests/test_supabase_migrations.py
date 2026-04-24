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


def _agent_run_archive_sql() -> str:
    migration_files = sorted(
        (PROJECT_ROOT / "supabase" / "migrations").glob(
            "*_add_agent_run_archive.sql"
        )
    )

    assert [path.name for path in migration_files] == [
        "20260423113000_add_agent_run_archive.sql"
    ]
    return migration_files[0].read_text()


def _auth_rbac_sql() -> str:
    migration_files = sorted(
        (PROJECT_ROOT / "supabase" / "migrations").glob("*_add_auth_rbac.sql")
    )

    assert [path.name for path in migration_files] == [
        "20260423120000_add_auth_rbac.sql"
    ]
    return migration_files[0].read_text()


def _company_kb_sql() -> str:
    migration_files = sorted(
        (PROJECT_ROOT / "supabase" / "migrations").glob(
            "*_company_knowledge_base.sql"
        )
    )

    assert [path.name for path in migration_files] == [
        "20260423121000_company_knowledge_base.sql"
    ]
    return migration_files[0].read_text()


def _impact_solution_financials_sql() -> str:
    migration_files = sorted(
        (PROJECT_ROOT / "supabase" / "migrations").glob(
            "*_realign_impact_solution_financials.sql"
        )
    )

    assert [path.name for path in migration_files] == [
        "20260424173000_realign_impact_solution_financials.sql"
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


def test_agent_run_archive_migration_adds_soft_archive_contract() -> None:
    sql = _agent_run_archive_sql().lower()
    normalized_sql = re.sub(r"\s+", " ", sql)

    for required_fragment in [
        "alter table if exists public.agent_runs",
        "add column if not exists archived_at timestamptz",
        "add column if not exists archived_reason text",
        "to_regclass('public.agent_runs') is not null",
        (
            "constraint agent_runs_archived_reason_check "
            "check (archived_reason is null or archived_reason <> '')"
        ),
        (
            "create index if not exists agent_runs_unarchived_status_idx "
            "on public.agent_runs (status, created_at desc) where archived_at is null"
        ),
    ]:
        assert required_fragment in normalized_sql

    assert "delete from public.agent_runs" not in sql
    assert "drop trigger agent_outputs_immutable_before_update" not in sql


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


def test_company_kb_migration_adds_private_bucket_and_relaxes_provenance() -> None:
    sql = re.sub(r"\s+", " ", _company_kb_sql().lower())

    assert "insert into storage.buckets" in sql
    assert "'company-knowledge'" in sql
    assert "public = false" in sql
    assert (
        "drop constraint if exists evidence_items_company_profile_source_check" in sql
    )
    assert "add constraint evidence_items_company_profile_source_check check" in sql
    assert "source_type <> 'company_profile'" in sql
    assert "document_id is null" in sql
    assert "document_id is not null" in sql
    assert "chunk_id is not null" in sql
    assert "page_start is not null" in sql
    assert "page_end is not null" in sql
    assert "create index if not exists documents_company_profile_idx" in sql
    assert "create index if not exists evidence_items_company_document_idx" in sql


def test_impact_solution_financials_reseed_uses_public_2024_company_data() -> None:
    sql = re.sub(r"\s+", " ", _impact_solution_financials_sql().lower())

    for required_fragment in [
        "update public.companies",
        "name = 'impact solution scandinavia ab'",
        "organization_number = '556925-0516'",
        "employee_count = 7",
        "annual_revenue_sek = 24901000",
        "'latest_public_financial_year', 2024",
        "'latest_public_revenue_sek', 24901000",
        "'latest_public_result_after_financial_items_sek', -104000",
        "'latest_public_ebitda_sek', 580000",
        "'latest_public_assets_sek', 11187000",
        "'latest_public_equity_sek', 1511000",
        "'latest_public_equity_ratio_percent', 14.9",
        "jsonb_build_object('year', 2024, 'revenue_msek', 24.901",
        "'ebit_margin_pct', 0.1, 'headcount', 7",
        "'source_label', 'allabolag/uc, bolagsfakta and vainu public company data'",
    ]:
        assert required_fragment in sql

    assert "559247-8112" not in sql
    assert "fadi zemzemi" not in sql


def test_auth_rbac_migration_adds_membership_model_and_helpers() -> None:
    sql = re.sub(r"\s+", " ", _auth_rbac_sql().lower())

    for required_fragment in [
        "create table if not exists public.organizations",
        "create table if not exists public.profiles",
        "references auth.users(id) on delete cascade",
        "create table if not exists public.organization_memberships",
        (
            "constraint organization_memberships_role_check "
            "check (role in ('admin', 'user'))"
        ),
        (
            "constraint organization_memberships_status_check "
            "check (status in ('active', 'invited', 'disabled'))"
        ),
        "create or replace function public.is_superadmin()",
        "create or replace function public.has_org_role(",
        "create or replace function public.is_org_member(",
        "create or replace function public.has_any_org_membership()",
        "create or replace function public.has_any_org_role(",
        "create or replace function public.shares_organization_with(",
    ]:
        assert required_fragment in sql


def test_auth_rbac_migration_backfills_organization_id() -> None:
    sql = re.sub(r"\s+", " ", _auth_rbac_sql().lower())

    for required_fragment in [
        "alter table if exists public.%i add column if not exists organization_id uuid",
        "alter table if exists public.%i alter column organization_id set not null",
        "create index if not exists %i on public.%i (organization_id)",
    ]:
        assert required_fragment in sql

    for table_name in [
        "companies",
        "tenders",
        "documents",
        "document_chunks",
        "evidence_items",
        "agent_runs",
        "agent_outputs",
        "bid_decisions",
        "bids",
    ]:
        assert f"'{table_name}'" in sql


def test_auth_rbac_migration_replaces_anon_policies_with_role_policies() -> None:
    sql = re.sub(r"\s+", " ", _auth_rbac_sql().lower())

    for old_policy in [
        '"anon can read demo companies"',
        '"anon can update demo companies"',
        '"anon can insert demo bids"',
        '"anon can update demo bids"',
        '"anon can delete demo bids"',
        '"anon can delete demo agent runs"',
        '"anon can delete demo agent outputs"',
    ]:
        assert f"drop policy if exists {old_policy}" in sql

    assert "update storage.buckets set public = false" in sql

    for required_fragment in [
        "alter table public.companies enable row level security",
        "create policy \"members can read companies\"",
        "create policy \"admins can update companies\"",
        "create policy \"members can read tenders\"",
        "create policy \"members can create tenders\"",
        "create policy \"admins can delete tenders\"",
        "create policy \"members can read documents\"",
        "create policy \"members can create documents\"",
        "create policy \"admins can delete documents\"",
        "create policy \"members can read agent runs\"",
        "create policy \"admins can delete agent runs\"",
        "create policy \"members can read evidence items\"",
        "create policy \"members can read bid decisions\"",
        "create policy \"admins can manage bids\"",
        "to authenticated",
    ]:
        assert required_fragment in sql

    assert "to anon" not in sql
