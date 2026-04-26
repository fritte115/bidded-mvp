from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from bidded.orchestration.procurement_manifest import (
    ProcurementManifestError,
    prepare_procurement_manifest_run,
)


def _write_pdf(path: Path) -> None:
    path.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n")


def _write_manifest(procurement_dir: Path, documents: list[dict[str, str]]) -> Path:
    manifest_path = procurement_dir / "procurement-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "tender_title": "Seven PDF procurement",
                "issuing_authority": "Example Municipality",
                "procurement_reference": "REF-2026-007",
                "procurement_metadata": {"procedure": "open"},
                "documents": documents,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_prepare_procurement_manifest_registers_and_prepares_documents(
    tmp_path: Path,
) -> None:
    procurement_dir = tmp_path / "data" / "demo" / "incoming" / "seven-pdf-demo"
    procurement_dir.mkdir(parents=True)
    roles = [
        "main_tender",
        "qualification_appendix",
        "evaluation_model",
        "requirements_appendix",
        "contract_terms",
        "pricing_appendix",
        "dpa",
    ]
    documents = []
    for index, role in enumerate(roles, start=1):
        suffix = ".docx" if index == 4 else ".pdf"
        filename = f"{index:02d}-{role}{suffix}"
        if suffix == ".pdf":
            _write_pdf(procurement_dir / filename)
        else:
            (procurement_dir / filename).write_bytes(b"docx fixture")
        documents.append(
            {
                "path": filename,
                "source_label": f"Attachment {index}",
                "document_role": role,
            }
        )
    manifest_path = _write_manifest(procurement_dir, documents)
    client = object()
    registrations: list[dict[str, Any]] = []
    prepare_calls: list[dict[str, Any]] = []

    def register_document(supabase_client: object, **kwargs: Any) -> SimpleNamespace:
        registrations.append({"client": supabase_client, **kwargs})
        index = len(registrations)
        return SimpleNamespace(
            company_id="22222222-2222-4222-8222-222222222222",
            tender_id="33333333-3333-4333-8333-333333333333",
            document_id=f"44444444-4444-4444-8444-44444444444{index}",
        )

    def prepare_run(supabase_client: object, **kwargs: Any) -> SimpleNamespace:
        prepare_calls.append({"client": supabase_client, **kwargs})
        return SimpleNamespace(
            agent_run_id="11111111-1111-4111-8111-111111111111",
            document_ids=tuple(kwargs["document_ids"]),
            document_results=(),
            tender_evidence_count=7,
            company_evidence_count=12,
            evidence_count=19,
            warnings=(),
            audit=None,
        )

    result = prepare_procurement_manifest_run(
        client,
        manifest_path=manifest_path,
        bucket_name="procurement-fixtures",
        register_document=register_document,
        prepare_run=prepare_run,
    )

    assert result.agent_run_id == "11111111-1111-4111-8111-111111111111"
    assert result.manifest_path == manifest_path
    assert result.procurement_directory == procurement_dir
    assert result.document_ids == tuple(
        f"44444444-4444-4444-8444-44444444444{index}" for index in range(1, 8)
    )
    assert [call["document_path"] for call in registrations] == [
        procurement_dir / document["path"] for document in documents
    ]
    assert [call["source_label"] for call in registrations] == [
        document["source_label"] for document in documents
    ]
    assert [call["procurement_document_role"] for call in registrations] == roles
    assert {call["tender_title"] for call in registrations} == {"Seven PDF procurement"}
    assert {call["issuing_authority"] for call in registrations} == {
        "Example Municipality"
    }
    assert registrations[0]["procurement_metadata"] == {"procedure": "open"}
    assert prepare_calls == [
        {
            "client": client,
            "tender_id": "33333333-3333-4333-8333-333333333333",
            "company_id": "22222222-2222-4222-8222-222222222222",
            "document_ids": list(result.document_ids),
            "bucket_name": "procurement-fixtures",
            "created_via": "bidded_procurement_manifest",
        }
    ]


def test_prepare_procurement_manifest_requires_exactly_seven_pdfs(
    tmp_path: Path,
) -> None:
    procurement_dir = tmp_path / "data" / "demo" / "incoming" / "too-small"
    procurement_dir.mkdir(parents=True)
    _write_pdf(procurement_dir / "01-main.pdf")
    manifest_path = _write_manifest(
        procurement_dir,
        [
            {
                "path": "01-main.pdf",
                "source_label": "Main tender",
            }
        ],
    )

    try:
        prepare_procurement_manifest_run(
            object(),
            manifest_path=manifest_path,
            bucket_name="procurement-fixtures",
        )
    except ProcurementManifestError as exc:
        assert "exactly 7 documents" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("Manifest with fewer than seven PDFs should fail.")


def test_prepare_procurement_manifest_rejects_paths_outside_directory(
    tmp_path: Path,
) -> None:
    procurement_dir = tmp_path / "data" / "demo" / "incoming" / "unsafe-path"
    procurement_dir.mkdir(parents=True)
    documents = [
        {
            "path": f"{index:02d}-safe.pdf",
            "source_label": f"Attachment {index}",
        }
        for index in range(1, 8)
    ]
    documents[3]["path"] = "../outside.pdf"
    manifest_path = _write_manifest(procurement_dir, documents)

    try:
        prepare_procurement_manifest_run(
            object(),
            manifest_path=manifest_path,
            bucket_name="procurement-fixtures",
        )
    except ProcurementManifestError as exc:
        assert "must stay inside the manifest directory" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("Manifest path traversal should fail.")
