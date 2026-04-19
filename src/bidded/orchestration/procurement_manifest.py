from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bidded.documents import register_demo_tender_pdf
from bidded.orchestration.prepare_run import PrepareRunResult, prepare_procurement_run

DEFAULT_MANIFEST_CREATED_VIA = "bidded_procurement_manifest"
EXPECTED_MANIFEST_DOCUMENT_COUNT = 7


class ProcurementManifestError(RuntimeError):
    """Raised when a local procurement manifest cannot be used."""


class ProcurementManifestDocument(BaseModel):
    """One local procurement PDF described by a manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    document_role: str | None = Field(default=None, min_length=1)

    @field_validator("path")
    @classmethod
    def validate_relative_pdf_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("document path must stay inside the manifest directory")
        if path.suffix.lower() != ".pdf":
            raise ValueError("document path must point to a PDF")
        return value


class ProcurementManifest(BaseModel):
    """Versioned local manifest for replayable multi-PDF procurement fixtures."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: int = Field(default=1)
    tender_title: str = Field(min_length=1)
    issuing_authority: str = Field(min_length=1)
    procurement_reference: str | None = None
    procurement_metadata: dict[str, Any] = Field(default_factory=dict)
    documents: tuple[ProcurementManifestDocument, ...]

    @model_validator(mode="after")
    def validate_document_count(self) -> ProcurementManifest:
        if len(self.documents) != EXPECTED_MANIFEST_DOCUMENT_COUNT:
            raise ValueError(
                "procurement manifest must list exactly "
                f"{EXPECTED_MANIFEST_DOCUMENT_COUNT} PDFs"
            )
        return self


@dataclass(frozen=True)
class RegisteredManifestDocument:
    path: Path
    source_label: str
    document_role: str | None
    document_id: str


@dataclass(frozen=True)
class ProcurementManifestRunResult:
    manifest_path: Path
    procurement_directory: Path
    tender_id: str
    company_id: str
    document_ids: tuple[str, ...]
    registered_documents: tuple[RegisteredManifestDocument, ...]
    prepare_result: Any

    @property
    def agent_run_id(self) -> Any:
        return self.prepare_result.agent_run_id

    @property
    def document_results(self) -> Any:
        return self.prepare_result.document_results

    @property
    def tender_evidence_count(self) -> Any:
        return self.prepare_result.tender_evidence_count

    @property
    def company_evidence_count(self) -> Any:
        return self.prepare_result.company_evidence_count

    @property
    def evidence_count(self) -> Any:
        return self.prepare_result.evidence_count

    @property
    def warnings(self) -> Any:
        return self.prepare_result.warnings

    @property
    def audit(self) -> Any:
        return self.prepare_result.audit


def load_procurement_manifest(manifest_path: Path) -> ProcurementManifest:
    """Load and validate a local JSON procurement manifest."""

    path = Path(manifest_path)
    if not path.exists():
        raise ProcurementManifestError(f"Procurement manifest does not exist: {path}")
    if not path.is_file():
        raise ProcurementManifestError(f"Procurement manifest is not a file: {path}")

    try:
        raw_manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProcurementManifestError(
            f"Procurement manifest is not valid JSON: {path}"
        ) from exc
    if not isinstance(raw_manifest, Mapping):
        raise ProcurementManifestError(
            f"Procurement manifest must contain a JSON object: {path}"
        )
    try:
        return ProcurementManifest.model_validate(raw_manifest)
    except ValueError as exc:
        raise ProcurementManifestError(str(exc)) from exc


def prepare_procurement_manifest_run(
    client: Any,
    *,
    manifest_path: Path,
    bucket_name: str,
    register_document: Callable[..., Any] = register_demo_tender_pdf,
    prepare_run: Callable[..., PrepareRunResult] = prepare_procurement_run,
    created_via: str = DEFAULT_MANIFEST_CREATED_VIA,
) -> ProcurementManifestRunResult:
    """Register a seven-PDF local procurement fixture and prepare one agent run."""

    normalized_manifest_path = Path(manifest_path)
    procurement_directory = normalized_manifest_path.parent
    manifest = load_procurement_manifest(normalized_manifest_path)
    _validate_manifest_files(procurement_directory, manifest.documents)

    registered_documents: list[RegisteredManifestDocument] = []
    tender_id: str | None = None
    company_id: str | None = None
    for manifest_document in manifest.documents:
        pdf_path = procurement_directory / manifest_document.path
        registration = register_document(
            client,
            pdf_path=pdf_path,
            bucket_name=bucket_name,
            tender_title=manifest.tender_title,
            issuing_authority=manifest.issuing_authority,
            procurement_reference=manifest.procurement_reference,
            procurement_metadata=manifest.procurement_metadata,
            source_label=manifest_document.source_label,
            procurement_document_role=manifest_document.document_role,
            created_via=created_via,
        )
        if tender_id is None:
            tender_id = str(registration.tender_id)
        elif tender_id != str(registration.tender_id):
            raise ProcurementManifestError(
                "Manifest document registration returned mixed tender IDs."
            )
        if company_id is None:
            company_id = str(registration.company_id)
        elif company_id != str(registration.company_id):
            raise ProcurementManifestError(
                "Manifest document registration returned mixed company IDs."
            )

        registered_documents.append(
            RegisteredManifestDocument(
                path=pdf_path,
                source_label=manifest_document.source_label,
                document_role=manifest_document.document_role,
                document_id=str(registration.document_id),
            )
        )

    if tender_id is None or company_id is None:
        raise ProcurementManifestError("Procurement manifest has no documents.")

    document_ids = tuple(document.document_id for document in registered_documents)
    prepare_result = prepare_run(
        client,
        tender_id=tender_id,
        company_id=company_id,
        document_ids=list(document_ids),
        bucket_name=bucket_name,
        created_via=created_via,
    )
    return ProcurementManifestRunResult(
        manifest_path=normalized_manifest_path,
        procurement_directory=procurement_directory,
        tender_id=tender_id,
        company_id=company_id,
        document_ids=document_ids,
        registered_documents=tuple(registered_documents),
        prepare_result=prepare_result,
    )


def _validate_manifest_files(
    procurement_directory: Path,
    documents: Sequence[ProcurementManifestDocument],
) -> None:
    for document in documents:
        pdf_path = procurement_directory / document.path
        if not pdf_path.exists():
            raise ProcurementManifestError(f"Manifest PDF does not exist: {pdf_path}")
        if not pdf_path.is_file():
            raise ProcurementManifestError(f"Manifest PDF is not a file: {pdf_path}")
