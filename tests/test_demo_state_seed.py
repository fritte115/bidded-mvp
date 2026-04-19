from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from bidded.agents.schemas import (
    EvidenceScoutOutput,
    JudgeDecision,
    Round1Motion,
    Round2Rebuttal,
)
from bidded.db.seed_demo_states import (
    DEMO_STATES_FIXTURE_KEY,
    seed_demo_states,
)
from bidded.orchestration import AgentRunStatus, build_bid_run_state_from_supabase


def test_seed_demo_states_creates_replayable_fixture_rows() -> None:
    client = InMemorySupabaseClient()

    result = seed_demo_states(client)

    assert result.tenant_key == "demo"
    assert set(result.run_ids_by_state) == {
        "pending",
        "succeeded",
        "failed",
        "needs_human_review",
    }
    assert result.evidence_items_seeded >= 8
    assert result.agent_outputs_seeded >= 12
    assert result.bid_decisions_seeded == 2

    assert len(client.rows["companies"]) == 1
    assert len(client.rows["tenders"]) == 1
    assert len(client.rows["documents"]) == 1
    assert len(client.rows["document_chunks"]) >= 1
    assert len(client.rows["evidence_items"]) == result.evidence_items_seeded

    run_statuses = {
        row["metadata"]["fixture"]["state"]: row["status"]
        for row in client.rows["agent_runs"]
    }
    assert run_statuses == {
        "pending": AgentRunStatus.PENDING.value,
        "succeeded": AgentRunStatus.SUCCEEDED.value,
        "failed": AgentRunStatus.FAILED.value,
        "needs_human_review": AgentRunStatus.NEEDS_HUMAN_REVIEW.value,
    }

    for table_name in [
        "tenders",
        "documents",
        "document_chunks",
        "evidence_items",
        "agent_runs",
        "agent_outputs",
        "bid_decisions",
    ]:
        assert client.rows[table_name], table_name
        assert all(_fixture(row) for row in client.rows[table_name]), table_name

    failed_run = _run_by_state(client, "failed")
    assert failed_run["error_details"]["code"] == "demo_fixture_failed_run"
    assert "fixture" in failed_run["error_details"]["message"]


def test_seed_demo_states_is_idempotent_and_preserves_manual_rows() -> None:
    client = InMemorySupabaseClient()
    manual_run = {
        "id": str(_stable_uuid("manual-run")),
        "tenant_key": "demo",
        "tender_id": str(_stable_uuid("manual-tender")),
        "company_id": str(_stable_uuid("manual-company")),
        "status": "succeeded",
        "run_config": {"manual": True},
        "metadata": {"created_via": "manual_demo_operator"},
        "error_details": None,
        "started_at": "2026-04-19T09:00:00+00:00",
        "completed_at": "2026-04-19T09:15:00+00:00",
    }
    client.rows["agent_runs"].append(deepcopy(manual_run))

    first = seed_demo_states(client)
    counts_after_first = {table: len(rows) for table, rows in client.rows.items()}
    second = seed_demo_states(client)

    assert second == first
    assert (
        {table: len(rows) for table, rows in client.rows.items()}
        == counts_after_first
    )
    assert client.rows["agent_runs"][0] == manual_run
    assert len({row["id"] for row in client.rows["agent_runs"]}) == 5
    assert len(
        {
            (
                row["agent_run_id"],
                row["agent_role"],
                row["round_name"],
                row["output_type"],
            )
            for row in client.rows["agent_outputs"]
        }
    ) == len(client.rows["agent_outputs"])
    assert len({row["agent_run_id"] for row in client.rows["bid_decisions"]}) == 2


def test_seeded_completed_states_have_valid_payloads_and_evidence_references() -> None:
    client = InMemorySupabaseClient()

    seed_demo_states(client)

    evidence_ids = {str(row["id"]) for row in client.rows["evidence_items"]}
    completed_run_ids = {
        _run_by_state(client, "succeeded")["id"],
        _run_by_state(client, "needs_human_review")["id"],
    }
    outputs = [
        row
        for row in client.rows["agent_outputs"]
        if row["agent_run_id"] in completed_run_ids
    ]
    assert outputs

    for output in outputs:
        payload = output["validated_payload"]
        if output["output_type"] == "scout_output":
            validated = EvidenceScoutOutput.model_validate(payload)
        elif output["output_type"] == "motion":
            validated = Round1Motion.model_validate(payload)
        elif output["output_type"] == "rebuttal":
            validated = Round2Rebuttal.model_validate(payload)
        else:
            validated = JudgeDecision.model_validate(payload)

        for evidence_id in _nested_evidence_ids(validated.model_dump(mode="json")):
            assert evidence_id in evidence_ids

    for decision in client.rows["bid_decisions"]:
        validated = JudgeDecision.model_validate(decision["final_decision"])
        assert str(decision["agent_run_id"]) in completed_run_ids
        assert decision["verdict"] == validated.verdict.value
        assert set(decision["evidence_ids"]).issubset(evidence_ids)
        for evidence_id in _nested_evidence_ids(validated.model_dump(mode="json")):
            assert evidence_id in evidence_ids


def test_seeded_runs_are_readable_by_worker_state_loader() -> None:
    client = InMemorySupabaseClient()

    seed_demo_states(client)

    succeeded_run = _run_by_state(client, "succeeded")
    state = build_bid_run_state_from_supabase(client, run_row=succeeded_run)

    assert state.status is AgentRunStatus.SUCCEEDED
    assert state.run_context["metadata"]["fixture"]["seed_key"] == (
        DEMO_STATES_FIXTURE_KEY
    )
    assert len(state.document_ids) == 1
    assert state.chunks
    assert len(state.evidence_board) >= 8
    assert all(item.evidence_id is not None for item in state.evidence_board)


class InMemorySupabaseClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {
            "companies": [],
            "tenders": [],
            "documents": [],
            "document_chunks": [],
            "evidence_items": [],
            "agent_runs": [],
            "agent_outputs": [],
            "bid_decisions": [],
        }

    def table(self, table_name: str) -> InMemorySupabaseQuery:
        self.rows.setdefault(table_name, [])
        return InMemorySupabaseQuery(self, table_name)

    def assign_id(
        self,
        table_name: str,
        row: dict[str, Any],
        *,
        index: int = 0,
    ) -> dict[str, Any]:
        if row.get("id"):
            return row
        row["id"] = str(_stable_uuid(table_name, _row_identity(row, index=index)))
        return row


class InMemorySupabaseQuery:
    def __init__(self, client: InMemorySupabaseClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.order_column: str | None = None
        self.descending = False
        self.row_limit: int | None = None
        self.insert_payload: Any | None = None
        self.upsert_payload: Any | None = None
        self.on_conflict: str | None = None

    def select(self, _columns: str) -> InMemorySupabaseQuery:
        return self

    def eq(self, column: str, value: object) -> InMemorySupabaseQuery:
        self.filters.append((column, str(value)))
        return self

    def order(self, column: str, *, desc: bool = False) -> InMemorySupabaseQuery:
        self.order_column = column
        self.descending = desc
        return self

    def limit(self, row_limit: int) -> InMemorySupabaseQuery:
        self.row_limit = row_limit
        return self

    def insert(self, payload: Any) -> InMemorySupabaseQuery:
        self.insert_payload = payload
        return self

    def upsert(
        self,
        payload: Any,
        *,
        on_conflict: str | None = None,
    ) -> InMemorySupabaseQuery:
        self.upsert_payload = payload
        self.on_conflict = on_conflict
        return self

    def execute(self) -> object:
        if self.insert_payload is not None:
            payload_rows = _payload_rows(self.insert_payload)
            inserted_rows = []
            for index, payload in enumerate(payload_rows):
                row = self.client.assign_id(
                    self.table_name,
                    dict(payload),
                    index=len(self.client.rows[self.table_name]) + index,
                )
                self.client.rows[self.table_name].append(row)
                inserted_rows.append(row)
            return _response(inserted_rows)

        if self.upsert_payload is not None:
            payload_rows = _payload_rows(self.upsert_payload)
            upserted_rows = [
                self._upsert_one(dict(payload), index=index)
                for index, payload in enumerate(payload_rows)
            ]
            return _response(upserted_rows)

        return _response(self._filtered_rows())

    def _filtered_rows(self) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.client.rows.get(self.table_name, [])
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]
        if self.order_column is not None:
            rows = sorted(
                rows,
                key=lambda row: str(row.get(self.order_column) or ""),
                reverse=self.descending,
            )
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        return rows

    def _upsert_one(self, payload: dict[str, Any], *, index: int) -> dict[str, Any]:
        conflict_columns = _conflict_columns(self.on_conflict)
        existing = None
        if conflict_columns:
            existing = next(
                (
                    row
                    for row in self.client.rows[self.table_name]
                    if all(
                        str(row.get(column)) == str(payload.get(column))
                        for column in conflict_columns
                    )
                ),
                None,
            )

        if existing is not None:
            row_id = existing.get("id")
            existing.update(payload)
            if row_id is not None:
                existing["id"] = row_id
            return existing

        row = self.client.assign_id(self.table_name, payload, index=index)
        self.client.rows[self.table_name].append(row)
        return row


def _run_by_state(client: InMemorySupabaseClient, state: str) -> dict[str, Any]:
    return next(
        row
        for row in client.rows["agent_runs"]
        if row["metadata"].get("fixture", {}).get("state") == state
    )


def _fixture(row: dict[str, Any]) -> bool:
    return row.get("metadata", {}).get("fixture", {}).get("seed_key") == (
        DEMO_STATES_FIXTURE_KEY
    )


def _nested_evidence_ids(value: Any) -> list[str]:
    if isinstance(value, dict):
        evidence_ids: list[str] = []
        if value.get("evidence_id") is not None:
            evidence_ids.append(str(value["evidence_id"]))
        for child in value.values():
            evidence_ids.extend(_nested_evidence_ids(child))
        return evidence_ids
    if isinstance(value, list):
        return [
            evidence_id
            for child in value
            for evidence_id in _nested_evidence_ids(child)
        ]
    return []


def _payload_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload]
    return [dict(payload)]


def _conflict_columns(on_conflict: str | None) -> list[str]:
    if not on_conflict:
        return []
    return [column.strip() for column in on_conflict.split(",") if column.strip()]


def _response(rows: list[dict[str, Any]]) -> object:
    return type("Response", (), {"data": rows})()


def _row_identity(row: dict[str, Any], *, index: int) -> str:
    for key in [
        "evidence_key",
        "storage_path",
        "name",
        "title",
        "agent_run_id",
        "document_id",
    ]:
        if row.get(key) is not None:
            return f"{key}:{row[key]}:{index}"
    return f"row:{index}"


def _stable_uuid(*parts: object) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        "https://bidded.test/demo-state-seed/" + "/".join(map(str, parts)),
    )
