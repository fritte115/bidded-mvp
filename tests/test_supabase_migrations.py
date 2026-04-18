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
            f"constraint {table_name}_tenant_key_demo_check "
            "check (tenant_key = 'demo')"
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
