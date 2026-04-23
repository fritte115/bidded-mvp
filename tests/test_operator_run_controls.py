from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from bidded.orchestration import AgentRunStatus
from bidded.orchestration.run_controls import (
    DemoTraceEntry,
    RunControlError,
    archive_agent_run,
    get_run_status,
    reset_stale_runs,
    retry_agent_run,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_RUN_ID = UUID("99999999-9999-4999-8999-999999999999")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")


class RecordingRunControlQuery:
    def __init__(self, client: RecordingRunControlClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.row_limit: int | None = None
        self.insert_payload: dict[str, Any] | list[dict[str, Any]] | None = None
        self.update_payload: dict[str, Any] | None = None

    def select(self, _columns: str) -> RecordingRunControlQuery:
        return self

    def eq(self, column: str, value: object) -> RecordingRunControlQuery:
        self.filters.append((column, str(value)))
        return self

    def limit(self, row_limit: int) -> RecordingRunControlQuery:
        self.row_limit = row_limit
        return self

    def insert(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
    ) -> RecordingRunControlQuery:
        self.insert_payload = payload
        return self

    def update(self, payload: dict[str, Any]) -> RecordingRunControlQuery:
        self.update_payload = payload
        return self

    def execute(self) -> object:
        if self.update_payload is not None:
            if self.client.next_update_returns_no_rows:
                self.client.next_update_returns_no_rows = False
                return type("Response", (), {"data": []})()
            self.client.updates.setdefault(self.table_name, []).append(
                (self.update_payload, self.filters)
            )
            rows = self._filtered_rows()
            for row in rows:
                row.update(self.update_payload)
            return type("Response", (), {"data": rows})()

        if self.insert_payload is not None:
            if self.client.next_insert_returns_no_rows:
                self.client.next_insert_returns_no_rows = False
                return type("Response", (), {"data": []})()
            self.client.inserts.setdefault(self.table_name, []).append(
                self.insert_payload
            )
            payload_rows = (
                self.insert_payload
                if isinstance(self.insert_payload, list)
                else [self.insert_payload]
            )
            rows: list[dict[str, Any]] = []
            for payload in payload_rows:
                inserted = dict(payload)
                inserted.setdefault("id", str(self.client.next_insert_id))
                self.client.rows.setdefault(self.table_name, []).append(inserted)
                rows.append(inserted)
            return type("Response", (), {"data": rows})()

        rows = self._filtered_rows()
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        return type("Response", (), {"data": rows})()

    def _filtered_rows(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.client.rows.get(self.table_name, [])
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]


class RecordingRunControlClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {
            "agent_runs": [_agent_run()],
            "agent_outputs": [
                {
                    "id": "output-1",
                    "tenant_key": "demo",
                    "agent_run_id": str(RUN_ID),
                },
                {
                    "id": "output-2",
                    "tenant_key": "demo",
                    "agent_run_id": str(RUN_ID),
                },
                {
                    "id": "output-3",
                    "tenant_key": "demo",
                    "agent_run_id": str(OTHER_RUN_ID),
                },
            ],
            "bid_decisions": [
                {
                    "id": "decision-1",
                    "tenant_key": "demo",
                    "agent_run_id": str(RUN_ID),
                },
            ],
        }
        self.inserts: dict[str, list[dict[str, Any] | list[dict[str, Any]]]] = {}
        self.updates: dict[
            str,
            list[tuple[dict[str, Any], list[tuple[str, str]]]],
        ] = {}
        self.table_names: list[str] = []
        self.next_insert_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        self.next_insert_returns_no_rows = False
        self.next_update_returns_no_rows = False

    def table(self, table_name: str) -> RecordingRunControlQuery:
        self.table_names.append(table_name)
        return RecordingRunControlQuery(self, table_name)


def test_run_status_reports_lifecycle_audit_snapshot() -> None:
    client = RecordingRunControlClient()

    status = get_run_status(client, run_id=RUN_ID)

    assert status.run_id == RUN_ID
    assert status.status is AgentRunStatus.FAILED
    assert status.created_at == "2026-04-18T17:00:00+00:00"
    assert status.started_at == "2026-04-18T17:30:00+00:00"
    assert status.completed_at == "2026-04-18T17:45:00+00:00"
    assert status.error_details == {
        "code": "graph_failed",
        "message": "Evidence board is empty.",
        "source": "graph",
    }
    assert status.agent_output_count == 2
    assert status.decision_present is True
    assert status.last_recorded_step == "judge"
    assert client.table_names == ["agent_runs", "agent_outputs", "bid_decisions"]


def test_run_status_reports_compact_demo_trace_entries() -> None:
    client = RecordingRunControlClient()
    client.rows["agent_runs"][0]["metadata"]["demo_trace"] = [
        {
            "step": "claim_run",
            "status": "completed",
            "started_at": "2026-04-18T17:30:00+00:00",
            "completed_at": "2026-04-18T17:30:00+00:00",
            "duration_ms": 0,
            "raw_prompt": "must not be surfaced",
        },
        {
            "step": "run_graph",
            "status": "failed",
            "started_at": "2026-04-18T17:31:00+00:00",
            "completed_at": "2026-04-18T17:32:00+00:00",
            "duration_ms": 60_000,
            "error_code": "graph_failed",
            "private_context": "must not be surfaced",
        },
    ]

    status = get_run_status(client, run_id=RUN_ID)

    assert status.demo_trace == (
        DemoTraceEntry(
            step="claim_run",
            status="completed",
            started_at="2026-04-18T17:30:00+00:00",
            completed_at="2026-04-18T17:30:00+00:00",
            duration_ms=0,
            error_code=None,
        ),
        DemoTraceEntry(
            step="run_graph",
            status="failed",
            started_at="2026-04-18T17:31:00+00:00",
            completed_at="2026-04-18T17:32:00+00:00",
            duration_ms=60_000,
            error_code="graph_failed",
        ),
    )
    assert "raw_prompt" not in repr(status.demo_trace)
    assert "private_context" not in repr(status.demo_trace)


def test_retry_creates_new_pending_run_with_source_lineage() -> None:
    client = RecordingRunControlClient()

    retry = retry_agent_run(
        client,
        run_id=RUN_ID,
        reason="retry after replacing demo PDF",
        now_factory=lambda: datetime(2026, 4, 19, 10, 15, tzinfo=UTC),
    )

    assert retry.source_run_id == RUN_ID
    assert retry.new_run_id == client.next_insert_id
    assert retry.source_status is AgentRunStatus.FAILED
    payload = client.inserts["agent_runs"][0]
    assert isinstance(payload, dict)
    assert payload["status"] == "pending"
    assert payload["tender_id"] == str(TENDER_ID)
    assert payload["company_id"] == str(COMPANY_ID)
    assert payload["run_config"] == {
        "document_ids": ["44444444-4444-4444-8444-444444444444"]
    }
    assert payload["metadata"]["retry"] == {
        "source_run_id": str(RUN_ID),
        "source_status": "failed",
        "requested_at": "2026-04-19T10:15:00+00:00",
        "reason": "retry after replacing demo PDF",
        "force": False,
    }
    assert "agent_outputs" not in client.inserts


def test_retry_refuses_succeeded_without_force_and_records_force_usage() -> None:
    client = RecordingRunControlClient()
    client.rows["agent_runs"] = [_agent_run(status="succeeded")]

    with pytest.raises(RunControlError, match="force=True"):
        retry_agent_run(
            client,
            run_id=RUN_ID,
            reason="operator requested rerun",
            now_factory=lambda: datetime(2026, 4, 19, 10, 15, tzinfo=UTC),
        )

    assert "agent_runs" not in client.inserts

    retry_agent_run(
        client,
        run_id=RUN_ID,
        reason="operator approved rerun",
        force=True,
        now_factory=lambda: datetime(2026, 4, 19, 10, 20, tzinfo=UTC),
    )

    payload = client.inserts["agent_runs"][0]
    assert isinstance(payload, dict)
    assert payload["metadata"]["retry"]["source_status"] == "succeeded"
    assert payload["metadata"]["retry"]["force"] is True
    assert payload["metadata"]["retry"]["reason"] == "operator approved rerun"


def test_reset_stale_marks_only_old_running_runs_failed_with_reason() -> None:
    stale_run_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    fresh_run_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    succeeded_run_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    client = RecordingRunControlClient()
    client.rows["agent_runs"] = [
        _agent_run(
            id=str(stale_run_id),
            status="running",
            started_at="2026-04-19T09:00:00+00:00",
            completed_at=None,
        ),
        _agent_run(
            id=str(fresh_run_id),
            status="running",
            started_at="2026-04-19T09:50:00+00:00",
            completed_at=None,
        ),
        _agent_run(
            id=str(succeeded_run_id),
            status="succeeded",
            started_at="2026-04-19T08:00:00+00:00",
            completed_at="2026-04-19T08:30:00+00:00",
        ),
    ]

    result = reset_stale_runs(
        client,
        max_age_minutes=30,
        reason="operator confirmed worker heartbeat is stale",
        now_factory=lambda: datetime(2026, 4, 19, 10, 0, tzinfo=UTC),
    )

    assert result.reset_count == 1
    assert result.reset_run_ids == [stale_run_id]
    assert client.rows["agent_runs"][0]["status"] == "failed"
    assert client.rows["agent_runs"][1]["status"] == "running"
    assert client.rows["agent_runs"][2]["status"] == "succeeded"

    update_payload, update_filters = client.updates["agent_runs"][0]
    assert ("status", "running") in update_filters
    assert update_payload["completed_at"] == "2026-04-19T10:00:00+00:00"
    assert update_payload["error_details"] == {
        "code": "operator_stale_reset",
        "message": "operator confirmed worker heartbeat is stale",
        "source": "operator",
        "stale_age_minutes": 60,
    }
    assert update_payload["metadata"]["operator_control"] == {
        "action": "reset_stale",
        "reason": "operator confirmed worker heartbeat is stale",
        "requested_at": "2026-04-19T10:00:00+00:00",
        "max_age_minutes": 30,
        "stale_age_minutes": 60,
    }


def test_archive_agent_run_marks_run_archived_without_touching_audit_rows() -> None:
    client = RecordingRunControlClient()

    result = archive_agent_run(
        client,
        run_id=RUN_ID,
        reason="clear stale run from operator dashboard",
        now_factory=lambda: datetime(2026, 4, 19, 10, 30, tzinfo=UTC),
    )

    assert result.run_id == RUN_ID
    assert result.archived_at == "2026-04-19T10:30:00+00:00"
    assert result.already_archived is False
    assert client.rows["agent_runs"][0]["archived_at"] == "2026-04-19T10:30:00+00:00"
    assert client.rows["agent_runs"][0]["archived_reason"] == (
        "clear stale run from operator dashboard"
    )

    update_payload, update_filters = client.updates["agent_runs"][0]
    assert ("id", str(RUN_ID)) in update_filters
    assert update_payload["archived_at"] == "2026-04-19T10:30:00+00:00"
    assert update_payload["archived_reason"] == (
        "clear stale run from operator dashboard"
    )
    assert update_payload["metadata"]["operator_control"] == {
        "action": "archive_run",
        "reason": "clear stale run from operator dashboard",
        "requested_at": "2026-04-19T10:30:00+00:00",
    }
    assert "agent_outputs" not in client.updates
    assert "bid_decisions" not in client.updates


def test_archive_agent_run_is_idempotent_for_already_archived_runs() -> None:
    client = RecordingRunControlClient()
    client.rows["agent_runs"][0]["archived_at"] = "2026-04-18T10:00:00+00:00"
    client.rows["agent_runs"][0]["archived_reason"] = "already hidden"

    result = archive_agent_run(
        client,
        run_id=RUN_ID,
        reason="clear stale run from operator dashboard",
        now_factory=lambda: datetime(2026, 4, 19, 10, 30, tzinfo=UTC),
    )

    assert result.run_id == RUN_ID
    assert result.archived_at == "2026-04-18T10:00:00+00:00"
    assert result.already_archived is True
    assert "agent_runs" not in client.updates


def test_archive_agent_run_requires_reason() -> None:
    client = RecordingRunControlClient()

    with pytest.raises(RunControlError, match="reason"):
        archive_agent_run(client, run_id=RUN_ID, reason=" ")


def test_retry_reports_insert_persistence_failure() -> None:
    client = RecordingRunControlClient()
    client.next_insert_returns_no_rows = True

    with pytest.raises(RunControlError, match="insert did not return"):
        retry_agent_run(
            client,
            run_id=RUN_ID,
            reason="retry failed run",
            now_factory=lambda: datetime(2026, 4, 19, 10, 15, tzinfo=UTC),
        )

    assert "agent_outputs" not in client.inserts


def test_reset_stale_reports_compare_and_swap_failure() -> None:
    client = RecordingRunControlClient()
    client.next_update_returns_no_rows = True
    client.rows["agent_runs"] = [
        _agent_run(
            status="running",
            started_at="2026-04-19T09:00:00+00:00",
            completed_at=None,
        )
    ]

    with pytest.raises(RunControlError, match="changed"):
        reset_stale_runs(
            client,
            max_age_minutes=30,
            reason="operator confirmed worker heartbeat is stale",
            now_factory=lambda: datetime(2026, 4, 19, 10, 0, tzinfo=UTC),
        )


def _agent_run(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": str(RUN_ID),
        "created_at": "2026-04-18T17:00:00+00:00",
        "tenant_key": "demo",
        "tender_id": str(TENDER_ID),
        "company_id": str(COMPANY_ID),
        "status": "failed",
        "run_config": {"document_ids": ["44444444-4444-4444-8444-444444444444"]},
        "metadata": {
            "worker": {
                "last_status": "failed",
                "visited_nodes": ["preflight", "evidence_scout", "judge"],
            }
        },
        "error_details": {
            "code": "graph_failed",
            "message": "Evidence board is empty.",
            "source": "graph",
        },
        "started_at": "2026-04-18T17:30:00+00:00",
        "completed_at": "2026-04-18T17:45:00+00:00",
    }
    row.update(overrides)
    return row
