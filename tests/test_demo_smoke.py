from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

import bidded.demo_smoke as demo_smoke
from bidded.orchestration import AgentRunStatus, RunStatusSnapshot, Verdict

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")


def test_demo_smoke_runs_bounded_flow_with_existing_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "tender.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    client = object()
    calls: list[str] = []

    _patch_successful_smoke_dependencies(
        monkeypatch,
        calls=calls,
        expected_client=client,
        expected_registered_pdf=pdf_path,
    )

    result = demo_smoke.run_demo_smoke(
        client,
        pdf_path=pdf_path,
        bucket_name="procurement-fixtures",
    )

    assert calls == [
        "seed",
        "register",
        "ingest",
        "retrieve",
        "tender_evidence",
        "company_evidence",
        "pending_run",
        "graph_runner",
        "worker",
        "run_status",
        "decision_readback",
    ]
    assert result.pdf_source == "provided"
    assert result.requested_pdf_path == pdf_path
    assert result.resolved_pdf_path == pdf_path
    assert result.llm_mode == "mocked"
    assert result.run_id == RUN_ID
    assert result.terminal_status is AgentRunStatus.SUCCEEDED
    assert result.decision_verdict is Verdict.CONDITIONAL_BID
    assert result.evidence_count == 14
    assert result.failure_reason is None
    assert [step.name for step in result.steps] == [
        "seed_demo_company",
        "register_tender_pdf",
        "ingest_tender_pdf",
        "create_evidence",
        "create_pending_run",
        "run_worker",
        "read_decision",
    ]


def test_demo_smoke_generates_fixture_pdf_when_requested_path_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_pdf_path = tmp_path / "data" / "demo" / "incoming" / "Bilaga Skakrav.pdf"
    client = object()
    calls: list[str] = []
    generated_pdf_paths: list[Path] = []

    _patch_successful_smoke_dependencies(
        monkeypatch,
        calls=calls,
        expected_client=client,
        expected_registered_pdf=None,
        registered_pdf_paths=generated_pdf_paths,
    )

    result = demo_smoke.run_demo_smoke(
        client,
        pdf_path=missing_pdf_path,
        bucket_name="procurement-fixtures",
    )

    assert result.pdf_source == "generated_fixture"
    assert result.requested_pdf_path == missing_pdf_path
    assert generated_pdf_paths
    assert generated_pdf_paths[0] != missing_pdf_path
    assert generated_pdf_paths[0].name == "bidded-smoke-tender.pdf"
    assert generated_pdf_paths[0].suffix == ".pdf"
    assert result.resolved_pdf_path == generated_pdf_paths[0]


def test_demo_smoke_live_llm_flag_builds_live_graph_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "tender.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    client = object()
    anthropic_client = object()
    calls: list[str] = []
    runner = object()
    captured_graph_runner: dict[str, Any] = {}

    _patch_successful_smoke_dependencies(
        monkeypatch,
        calls=calls,
        expected_client=client,
        expected_registered_pdf=pdf_path,
        worker_graph_runner=runner,
    )

    def record_graph_runner(
        *,
        live_llm: bool,
        anthropic_client: object | None,
        anthropic_model: str | None,
    ) -> object:
        calls.append("graph_runner")
        captured_graph_runner.update(
            {
                "live_llm": live_llm,
                "anthropic_client": anthropic_client,
                "anthropic_model": anthropic_model,
            }
        )
        return runner

    monkeypatch.setattr(
        demo_smoke,
        "build_demo_smoke_graph_runner",
        record_graph_runner,
    )

    result = demo_smoke.run_demo_smoke(
        client,
        pdf_path=pdf_path,
        bucket_name="procurement-fixtures",
        live_llm=True,
        anthropic_client=anthropic_client,
        anthropic_model="claude-test-model",
    )

    assert result.llm_mode == "live"
    assert captured_graph_runner == {
        "live_llm": True,
        "anthropic_client": anthropic_client,
        "anthropic_model": "claude-test-model",
    }


def test_demo_smoke_summarizes_failed_worker_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "tender.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    client = object()
    calls: list[str] = []

    _patch_successful_smoke_dependencies(
        monkeypatch,
        calls=calls,
        expected_client=client,
        expected_registered_pdf=pdf_path,
        worker_status=AgentRunStatus.FAILED,
        worker_verdict=None,
        status_error_details={
            "code": "graph_failed",
            "message": "Evidence board is empty.",
            "source": "graph",
        },
        decision_present=False,
        decision_verdict=None,
    )

    result = demo_smoke.run_demo_smoke(
        client,
        pdf_path=pdf_path,
        bucket_name="procurement-fixtures",
    )

    assert result.terminal_status is AgentRunStatus.FAILED
    assert result.decision_verdict is None
    assert result.failure_reason == "graph_failed from graph - Evidence board is empty."
    assert result.steps[-1].status == "failed"
    assert "Evidence board is empty" in result.steps[-1].detail


def _patch_successful_smoke_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    calls: list[str],
    expected_client: object,
    expected_registered_pdf: Path | None,
    registered_pdf_paths: list[Path] | None = None,
    worker_graph_runner: object | None = None,
    worker_status: AgentRunStatus = AgentRunStatus.SUCCEEDED,
    worker_verdict: Verdict | None = Verdict.CONDITIONAL_BID,
    status_error_details: dict[str, Any] | None = None,
    decision_present: bool = True,
    decision_verdict: Verdict | None = Verdict.CONDITIONAL_BID,
) -> None:
    def record_seed(received_client: object) -> SimpleNamespace:
        calls.append("seed")
        assert received_client is expected_client
        return SimpleNamespace(company_name="Nordic Digital Delivery AB")

    def record_registration(received_client: object, **kwargs: Any) -> SimpleNamespace:
        calls.append("register")
        assert received_client is expected_client
        assert kwargs["bucket_name"] == "procurement-fixtures"
        registered_pdf = Path(kwargs["pdf_path"])
        if expected_registered_pdf is not None:
            assert registered_pdf == expected_registered_pdf
        else:
            assert registered_pdf.exists()
            assert registered_pdf.read_bytes().startswith(b"%PDF-")
        if registered_pdf_paths is not None:
            registered_pdf_paths.append(registered_pdf)
        return SimpleNamespace(
            company_id=str(COMPANY_ID),
            tender_id=str(TENDER_ID),
            document_id=str(DOCUMENT_ID),
            storage_path="demo/tenders/smoke/tender.pdf",
        )

    def record_ingestion(received_client: object, **kwargs: Any) -> SimpleNamespace:
        calls.append("ingest")
        assert received_client is expected_client
        assert str(kwargs["document_id"]) == str(DOCUMENT_ID)
        assert kwargs["bucket_name"] == "procurement-fixtures"
        return SimpleNamespace(page_count=1, chunk_count=1)

    def record_retrieval(received_client: object, **kwargs: Any) -> list[object]:
        calls.append("retrieve")
        assert received_client is expected_client
        assert str(kwargs["document_id"]) == str(DOCUMENT_ID)
        assert kwargs["top_k"] >= 1
        return [object()]

    def record_candidates(chunks: list[object]) -> list[object]:
        assert len(chunks) == 1
        return [object(), object()]

    def record_tender_evidence(
        received_client: object,
        candidates: list[object],
    ) -> SimpleNamespace:
        calls.append("tender_evidence")
        assert received_client is expected_client
        assert len(candidates) == 2
        return SimpleNamespace(evidence_count=2)

    def record_company_evidence(
        received_client: object,
        **kwargs: Any,
    ) -> SimpleNamespace:
        calls.append("company_evidence")
        assert received_client is expected_client
        assert kwargs["company_id"] == COMPANY_ID
        assert kwargs["company_profile"]["tenant_key"] == "demo"
        return SimpleNamespace(evidence_count=12)

    def record_pending_run(received_client: object, **kwargs: Any) -> SimpleNamespace:
        calls.append("pending_run")
        assert received_client is expected_client
        assert str(kwargs["tender_id"]) == str(TENDER_ID)
        assert str(kwargs["company_id"]) == str(COMPANY_ID)
        assert str(kwargs["document_id"]) == str(DOCUMENT_ID)
        return SimpleNamespace(run_id=RUN_ID)

    def record_graph_runner(
        *,
        live_llm: bool,
        anthropic_client: object | None,
        anthropic_model: str | None,
    ) -> object | None:
        calls.append("graph_runner")
        assert live_llm is False
        assert anthropic_client is None
        assert anthropic_model is None
        return worker_graph_runner

    def record_worker(received_client: object, **kwargs: Any) -> SimpleNamespace:
        calls.append("worker")
        assert received_client is expected_client
        assert kwargs["run_id"] == RUN_ID
        if worker_graph_runner is None:
            assert "graph_runner" not in kwargs
        else:
            assert kwargs["graph_runner"] is worker_graph_runner
        return SimpleNamespace(
            run_id=RUN_ID,
            terminal_status=worker_status,
            visited_nodes=("preflight", "END"),
            agent_output_count=10 if worker_status is AgentRunStatus.SUCCEEDED else 0,
            decision_verdict=worker_verdict,
            message=(
                "worker finished"
                if worker_status is not AgentRunStatus.FAILED
                else "worker failed"
            ),
        )

    def record_status(received_client: object, **kwargs: Any) -> RunStatusSnapshot:
        calls.append("run_status")
        assert received_client is expected_client
        assert kwargs == {"run_id": RUN_ID}
        return RunStatusSnapshot(
            run_id=RUN_ID,
            status=worker_status,
            created_at=None,
            started_at=None,
            completed_at=None,
            error_details=status_error_details,
            agent_output_count=10 if worker_status is AgentRunStatus.SUCCEEDED else 0,
            decision_present=decision_present,
            last_recorded_step="persist_decision",
        )

    def record_decision_readback(
        received_client: object,
        *,
        run_id: UUID,
    ) -> SimpleNamespace:
        calls.append("decision_readback")
        assert received_client is expected_client
        assert run_id == RUN_ID
        return SimpleNamespace(
            decision_present=decision_present,
            verdict=decision_verdict,
        )

    monkeypatch.setattr(demo_smoke, "seed_demo_company", record_seed)
    monkeypatch.setattr(demo_smoke, "register_demo_tender_pdf", record_registration)
    monkeypatch.setattr(demo_smoke, "ingest_tender_pdf_document", record_ingestion)
    monkeypatch.setattr(demo_smoke, "retrieve_document_chunks", record_retrieval)
    monkeypatch.setattr(
        demo_smoke,
        "build_tender_evidence_candidates",
        record_candidates,
    )
    monkeypatch.setattr(
        demo_smoke,
        "upsert_tender_evidence_items",
        record_tender_evidence,
    )
    monkeypatch.setattr(
        demo_smoke,
        "upsert_company_profile_evidence",
        record_company_evidence,
    )
    monkeypatch.setattr(demo_smoke, "create_pending_run_context", record_pending_run)
    monkeypatch.setattr(
        demo_smoke,
        "build_demo_smoke_graph_runner",
        record_graph_runner,
    )
    monkeypatch.setattr(demo_smoke, "run_worker_once", record_worker)
    monkeypatch.setattr(demo_smoke, "get_run_status", record_status)
    monkeypatch.setattr(
        demo_smoke,
        "read_demo_smoke_decision",
        record_decision_readback,
    )
