from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

import bidded.cli as cli
from bidded.db.seed_demo_states import seed_demo_states
from bidded.orchestration.decision_export import (
    DecisionExportError,
    export_decision_bundle,
)


def test_export_succeeded_decision_bundle_writes_markdown_and_json(
    tmp_path: Path,
) -> None:
    client = InMemorySupabaseClient()
    seed_demo_states(client)
    succeeded_run = _run_by_state(client, "succeeded")
    decision_row = _decision_by_run(client, succeeded_run["id"])
    decision_row["metadata"]["decision_evidence_audit"] = {
        "schema_version": "2026-04-23.decision-evidence-audit.v1",
        "gate_verdict": "flagged",
        "structural_score": 0.54,
        "judge_confidence": 0.74,
        "unsupported_claim_count": 1,
        "source_unverified_count": 1,
        "source_type_mismatch_count": 1,
        "findings": [
            {
                "kind": "source_type_mismatch",
                "severity": "warning",
                "message": "Company proof is missing.",
                "claim_id": "claim-001",
                "field_path": "compliance_matrix[0]",
                "evidence_keys": ["DEMO-REPLAY-TENDER-ISO-27001"],
            }
        ],
    }

    markdown_path = tmp_path / "decision.md"
    json_path = tmp_path / "decision.json"

    result = export_decision_bundle(
        client,
        run_id=succeeded_run["id"],
        markdown_path=markdown_path,
        json_path=json_path,
    )

    assert result.run_id == UUID(str(succeeded_run["id"]))
    assert result.verdict == "conditional_bid"
    assert result.markdown_path == markdown_path
    assert result.json_path == json_path

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# Bidded Decision Bundle" in markdown
    assert "Verdict: conditional_bid" in markdown
    assert "Confidence: 0.74" in markdown
    assert "## Cited Memo" in markdown
    assert "Conditional bid because ISO proof" in markdown
    assert "## Potential Blockers" in markdown
    assert "Named lead proof remains open before submission." in markdown
    assert "## Risk Register" in markdown
    assert "Delay penalties may reduce delivery margin." in markdown
    assert "## Missing Information" in markdown
    assert "Named security-cleared lead CV." in markdown
    assert "## Recommended Actions" in markdown
    assert "Attach named security-cleared lead CV." in markdown
    assert "## Decision Evidence Audit" in markdown
    assert "Gate verdict: flagged" in markdown
    assert "Source type mismatches: 1" in markdown
    assert "## Evidence" in markdown
    assert "DEMO-REPLAY-TENDER-NAMED-LEAD" in markdown
    assert "Supplier must name a security-cleared delivery lead" in markdown

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert list(payload) == [
        "schema_version",
        "run_id",
        "tenant_key",
        "decision",
        "agent_outputs",
        "evidence",
    ]
    assert payload["decision"]["verdict"] == "conditional_bid"
    assert payload["decision"]["confidence"] == 0.74
    assert payload["decision"]["cited_memo"].startswith("Conditional bid")
    assert payload["decision"]["compliance_blockers"] == []
    assert payload["decision"]["potential_blockers"] == [
        {
            "claim": "Named lead proof remains open before submission.",
            "evidence_keys": ["DEMO-REPLAY-TENDER-NAMED-LEAD"],
            "requirement_type": "qualification_requirement",
        }
    ]
    assert payload["decision"]["risk_register"] == [
        {
            "risk": "Delay penalties may reduce delivery margin.",
            "severity": "medium",
            "mitigation": "Review liability cap and contingency staffing.",
            "evidence_keys": [
                "DEMO-REPLAY-TENDER-LIABILITY",
                "DEMO-REPLAY-COMPANY-CAPACITY",
            ],
            "requirement_type": "contract_obligation",
        }
    ]
    assert payload["decision"]["missing_info"] == ["Named security-cleared lead CV."]
    assert payload["decision"]["recommended_actions"] == [
        "Attach named security-cleared lead CV.",
        "Confirm liability cap before final bid approval.",
    ]
    assert payload["decision"]["decision_evidence_audit"]["gate_verdict"] == "flagged"
    assert payload["decision"]["decision_evidence_audit"]["findings"][0]["kind"] == (
        "source_type_mismatch"
    )
    assert [item["evidence_key"] for item in payload["evidence"]] == sorted(
        item["evidence_key"] for item in payload["evidence"]
    )
    assert payload["agent_outputs"][0] == {
        "agent_role": "evidence_scout",
        "round_name": "evidence",
        "output_type": "scout_output",
        "evidence_keys": [
            "DEMO-REPLAY-TENDER-DEADLINE",
            "DEMO-REPLAY-TENDER-DPA",
            "DEMO-REPLAY-TENDER-EVALUATION",
            "DEMO-REPLAY-TENDER-ISO-27001",
            "DEMO-REPLAY-TENDER-LIABILITY",
            "DEMO-REPLAY-TENDER-NAMED-LEAD",
        ],
    }


def test_export_needs_human_review_decision_preserves_review_context(
    tmp_path: Path,
) -> None:
    client = InMemorySupabaseClient()
    seed_demo_states(client)
    review_run = _run_by_state(client, "needs_human_review")

    export_decision_bundle(
        client,
        run_id=review_run["id"],
        markdown_path=tmp_path / "review.md",
        json_path=tmp_path / "review.json",
    )

    markdown = (tmp_path / "review.md").read_text(encoding="utf-8")
    assert "Verdict: needs_human_review" in markdown
    assert "Needs human review because critical named-lead proof is missing." in (
        markdown
    )
    assert "## Potential Evidence Gaps" in markdown
    assert "Critical named-lead proof is absent from fixture evidence." in markdown

    payload = json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert payload["decision"]["verdict"] == "needs_human_review"
    assert payload["decision"]["confidence"] == 0.42
    assert payload["decision"]["missing_info"] == [
        "Named security-cleared lead CV is critical before a defensible verdict."
    ]
    assert payload["decision"]["potential_evidence_gaps"] == [
        "Critical named-lead proof is absent from fixture evidence."
    ]


def test_export_uses_decision_snapshot_when_cited_evidence_was_deleted(
    tmp_path: Path,
) -> None:
    client = InMemorySupabaseClient()
    seed_demo_states(client)
    succeeded_run = _run_by_state(client, "succeeded")
    decision = next(
        row
        for row in client.rows["bid_decisions"]
        if row["agent_run_id"] == succeeded_run["id"]
    )
    deleted_evidence = next(
        row
        for row in client.rows["evidence_items"]
        if row["evidence_key"] == "DEMO-REPLAY-COMPANY-CAPACITY"
    )
    decision["metadata"] = {
        **decision.get("metadata", {}),
        "evidence_snapshot": [deepcopy(deleted_evidence)],
    }
    client.rows["evidence_items"] = [
        row
        for row in client.rows["evidence_items"]
        if row["evidence_key"] != "DEMO-REPLAY-COMPANY-CAPACITY"
    ]

    export_decision_bundle(
        client,
        run_id=succeeded_run["id"],
        markdown_path=tmp_path / "decision.md",
        json_path=tmp_path / "decision.json",
    )

    markdown = (tmp_path / "decision.md").read_text(encoding="utf-8")
    assert "DEMO-REPLAY-COMPANY-CAPACITY" in markdown
    assert deleted_evidence["excerpt"] in markdown

    payload = json.loads((tmp_path / "decision.json").read_text(encoding="utf-8"))
    assert "DEMO-REPLAY-COMPANY-CAPACITY" in {
        row["evidence_key"] for row in payload["evidence"]
    }
    assert payload["decision"]["risk_register"][0]["evidence_keys"] == [
        "DEMO-REPLAY-TENDER-LIABILITY",
        "DEMO-REPLAY-COMPANY-CAPACITY",
    ]


def test_export_fails_when_run_has_no_persisted_final_decision(
    tmp_path: Path,
) -> None:
    client = InMemorySupabaseClient()
    seed_demo_states(client)
    failed_run = _run_by_state(client, "failed")

    with pytest.raises(DecisionExportError, match="No persisted final decision"):
        export_decision_bundle(
            client,
            run_id=failed_run["id"],
            markdown_path=tmp_path / "failed.md",
            json_path=tmp_path / "failed.json",
        )

    assert not (tmp_path / "failed.md").exists()
    assert not (tmp_path / "failed.json").exists()


def test_cli_export_decision_writes_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = InMemorySupabaseClient()
    seed_demo_states(client)
    succeeded_run = _run_by_state(client, "succeeded")
    markdown_path = tmp_path / "cli-decision.md"
    json_path = tmp_path / "cli-decision.json"
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "supabase_url": "https://example.supabase.co",
                "supabase_service_role_key": "service-role",
            },
        )(),
    )
    monkeypatch.setattr(cli, "_create_supabase_client", lambda _settings: client)

    result = cli.main(
        [
            "export-decision",
            "--run-id",
            succeeded_run["id"],
            "--markdown-path",
            str(markdown_path),
            "--json-path",
            str(json_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert f"Exported decision bundle for {succeeded_run['id']}" in captured.out
    assert "conditional_bid" in captured.out
    assert markdown_path.exists()
    assert json_path.exists()


def test_cli_export_decision_returns_clear_missing_decision_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = InMemorySupabaseClient()
    seed_demo_states(client)
    failed_run = _run_by_state(client, "failed")
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "supabase_url": "https://example.supabase.co",
                "supabase_service_role_key": "service-role",
            },
        )(),
    )
    monkeypatch.setattr(cli, "_create_supabase_client", lambda _settings: client)

    result = cli.main(
        [
            "export-decision",
            "--run-id",
            failed_run["id"],
            "--markdown-path",
            str(tmp_path / "failed.md"),
            "--json-path",
            str(tmp_path / "failed.json"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "No persisted final decision" in captured.err


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
        self.row_limit: int | None = None
        self.insert_payload: Any | None = None
        self.upsert_payload: Any | None = None
        self.on_conflict: str | None = None

    def select(self, _columns: str) -> InMemorySupabaseQuery:
        return self

    def eq(self, column: str, value: object) -> InMemorySupabaseQuery:
        self.filters.append((column, str(value)))
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

        rows = self._filtered_rows()
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        return _response(deepcopy(rows))

    def _filtered_rows(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.client.rows.get(self.table_name, [])
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]

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
            return deepcopy(existing)

        row = self.client.assign_id(self.table_name, payload, index=index)
        self.client.rows[self.table_name].append(row)
        return deepcopy(row)


def _run_by_state(client: InMemorySupabaseClient, state: str) -> dict[str, Any]:
    return next(
        row
        for row in client.rows["agent_runs"]
        if row["metadata"].get("fixture", {}).get("state") == state
    )


def _decision_by_run(client: InMemorySupabaseClient, run_id: str) -> dict[str, Any]:
    return next(
        row for row in client.rows["bid_decisions"] if row["agent_run_id"] == run_id
    )


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
        "https://bidded.test/decision-export/" + "/".join(map(str, parts)),
    )
