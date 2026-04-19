from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from bidded.agents import (
    EvidenceScoutOutput,
    JudgeDecision,
    Round1Motion,
    Round2Rebuttal,
)
from bidded.db.seed_demo_company import build_demo_company_payload, seed_demo_company
from bidded.documents import ingest_tender_pdf_document, register_demo_tender_pdf
from bidded.evidence.company_profile import upsert_company_profile_evidence
from bidded.evidence.tender_document import (
    build_tender_evidence_candidates,
    upsert_tender_evidence_items,
)
from bidded.orchestration import (
    AgentRunStatus,
    BidRunState,
    GraphRunResult,
    RunStatusSnapshot,
    Verdict,
    create_pending_run_context,
    default_graph_node_handlers,
    get_run_status,
    run_bidded_graph_shell,
    run_worker_once,
)
from bidded.orchestration.evidence_scout import build_evidence_scout_handler
from bidded.orchestration.judge import build_judge_handler
from bidded.orchestration.specialist_motions import build_round_1_specialist_handler
from bidded.orchestration.specialist_rebuttals import (
    build_round_2_rebuttal_handler,
)
from bidded.retrieval import retrieve_document_chunks

DEFAULT_SMOKE_TENDER_TITLE = "Bidded Demo Smoke Procurement"
DEFAULT_SMOKE_ISSUING_AUTHORITY = "Bidded Demo Authority"
DEFAULT_SMOKE_PROCUREMENT_REFERENCE = "BIDDED-SMOKE-2026"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
GENERATED_SMOKE_PDF_FILENAME = "bidded-smoke-tender.pdf"
SMOKE_RETRIEVAL_QUERY = (
    "ISO 27001 security-cleared delivery lead submission deadline award quality "
    "price liability penalties signed data processing agreement bankruptcy "
    "insolvency public sector references financial standing quality management"
)

GraphRunner = Callable[[BidRunState], GraphRunResult]


class DemoSmokeError(RuntimeError):
    """Raised when the opt-in demo smoke flow cannot run."""


@dataclass(frozen=True)
class DemoSmokeStep:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class DemoSmokeDecisionReadback:
    decision_present: bool
    verdict: Verdict | None


@dataclass(frozen=True)
class DemoSmokeResult:
    requested_pdf_path: Path | None
    resolved_pdf_path: Path
    pdf_source: str
    llm_mode: str
    run_id: UUID
    terminal_status: AgentRunStatus
    decision_verdict: Verdict | None
    evidence_count: int
    failure_reason: str | None
    steps: tuple[DemoSmokeStep, ...]


def run_demo_smoke(
    client: Any,
    *,
    pdf_path: Path | None,
    bucket_name: str,
    live_llm: bool = False,
    anthropic_client: Any | None = None,
    anthropic_model: str | None = None,
    tender_title: str = DEFAULT_SMOKE_TENDER_TITLE,
    issuing_authority: str = DEFAULT_SMOKE_ISSUING_AUTHORITY,
    procurement_reference: str = DEFAULT_SMOKE_PROCUREMENT_REFERENCE,
) -> DemoSmokeResult:
    """Run the bounded local demo smoke flow against injected external clients."""

    steps: list[DemoSmokeStep] = []
    requested_pdf_path = Path(pdf_path) if pdf_path is not None else None

    with _resolve_smoke_pdf_path(requested_pdf_path) as (
        resolved_pdf_path,
        pdf_source,
    ):
        seed_result = seed_demo_company(client)
        steps.append(
            DemoSmokeStep(
                name="seed_demo_company",
                status="ok",
                detail=f"seeded {seed_result.company_name}",
            )
        )

        registration = register_demo_tender_pdf(
            client,
            pdf_path=resolved_pdf_path,
            bucket_name=bucket_name,
            tender_title=tender_title,
            issuing_authority=issuing_authority,
            procurement_reference=procurement_reference,
            procurement_metadata={"source": "demo_smoke"},
        )
        steps.append(
            DemoSmokeStep(
                name="register_tender_pdf",
                status="ok",
                detail=(
                    f"document {registration.document_id}; "
                    f"storage {registration.storage_path}"
                ),
            )
        )

        ingestion = ingest_tender_pdf_document(
            client,
            document_id=registration.document_id,
            bucket_name=bucket_name,
        )
        steps.append(
            DemoSmokeStep(
                name="ingest_tender_pdf",
                status="ok",
                detail=(
                    f"pages {ingestion.page_count}; chunks {ingestion.chunk_count}"
                ),
            )
        )

        retrieved_chunks = retrieve_document_chunks(
            client,
            query=SMOKE_RETRIEVAL_QUERY,
            document_id=registration.document_id,
            top_k=12,
        )
        tender_candidates = build_tender_evidence_candidates(retrieved_chunks)
        tender_evidence = upsert_tender_evidence_items(client, tender_candidates)
        company_evidence = upsert_company_profile_evidence(
            client,
            company_id=_normalize_uuid(registration.company_id, "company_id"),
            company_profile=build_demo_company_payload(),
        )
        evidence_count = (
            tender_evidence.evidence_count + company_evidence.evidence_count
        )
        steps.append(
            DemoSmokeStep(
                name="create_evidence",
                status="ok",
                detail=(
                    f"tender evidence {tender_evidence.evidence_count}; "
                    f"company evidence {company_evidence.evidence_count}; "
                    f"retrieved chunks {len(retrieved_chunks)}"
                ),
            )
        )

        pending_run = create_pending_run_context(
            client,
            tender_id=registration.tender_id,
            company_id=registration.company_id,
            document_id=registration.document_id,
            created_via="bidded_demo_smoke",
        )
        steps.append(
            DemoSmokeStep(
                name="create_pending_run",
                status="ok",
                detail=f"run {pending_run.run_id}",
            )
        )

        graph_runner = build_demo_smoke_graph_runner(
            live_llm=live_llm,
            anthropic_client=anthropic_client,
            anthropic_model=anthropic_model,
        )
        worker_kwargs: dict[str, Any] = {"run_id": pending_run.run_id}
        if graph_runner is not None:
            worker_kwargs["graph_runner"] = graph_runner
        worker_result = run_worker_once(client, **worker_kwargs)
        worker_status = worker_result.terminal_status or AgentRunStatus.FAILED
        steps.append(
            DemoSmokeStep(
                name="run_worker",
                status="ok" if worker_status is not AgentRunStatus.FAILED else "failed",
                detail=worker_result.message,
            )
        )

        run_status = get_run_status(client, run_id=pending_run.run_id)
        decision_readback = read_demo_smoke_decision(
            client,
            run_id=pending_run.run_id,
        )
        failure_reason = _failure_reason(run_status, worker_result.message)
        decision_verdict = decision_readback.verdict or worker_result.decision_verdict
        steps.append(
            DemoSmokeStep(
                name="read_decision",
                status="failed" if failure_reason else "ok",
                detail=_readback_detail(
                    run_status=run_status,
                    decision_readback=decision_readback,
                    failure_reason=failure_reason,
                ),
            )
        )

        return DemoSmokeResult(
            requested_pdf_path=requested_pdf_path,
            resolved_pdf_path=resolved_pdf_path,
            pdf_source=pdf_source,
            llm_mode="live" if live_llm else "mocked",
            run_id=pending_run.run_id,
            terminal_status=run_status.status,
            decision_verdict=decision_verdict,
            evidence_count=evidence_count,
            failure_reason=failure_reason,
            steps=tuple(steps),
        )


def build_demo_smoke_graph_runner(
    *,
    live_llm: bool,
    anthropic_client: Any | None,
    anthropic_model: str | None,
) -> GraphRunner | None:
    """Return a live Claude graph runner only when the smoke flag opts in."""

    if not live_llm:
        return None
    if anthropic_client is None:
        raise DemoSmokeError("live LLM smoke requires an Anthropic client.")

    model = AnthropicSmokeAgentModel(
        anthropic_client,
        model_name=anthropic_model or DEFAULT_ANTHROPIC_MODEL,
    )
    handlers = default_graph_node_handlers()
    live_handlers = handlers.__class__(
        evidence_scout=build_evidence_scout_handler(model),
        round_1_specialist=build_round_1_specialist_handler(model),
        round_2_rebuttal=build_round_2_rebuttal_handler(model),
        judge=build_judge_handler(model),
        persist_decision=handlers.persist_decision,
    )

    def graph_runner(state: BidRunState) -> GraphRunResult:
        return run_bidded_graph_shell(state, handlers=live_handlers)

    return graph_runner


def read_demo_smoke_decision(
    client: Any,
    *,
    run_id: UUID,
) -> DemoSmokeDecisionReadback:
    """Read the persisted decision verdict after worker execution."""

    response = (
        client.table("bid_decisions")
        .select("verdict")
        .eq("tenant_key", "demo")
        .eq("agent_run_id", str(run_id))
        .limit(1)
        .execute()
    )
    rows = _response_rows(response)
    if not rows:
        return DemoSmokeDecisionReadback(decision_present=False, verdict=None)
    verdict = rows[0].get("verdict")
    if verdict is None:
        return DemoSmokeDecisionReadback(decision_present=True, verdict=None)
    try:
        normalized_verdict = Verdict(str(verdict))
    except ValueError as exc:
        raise DemoSmokeError(
            f"Persisted decision verdict is invalid: {verdict}"
        ) from exc
    return DemoSmokeDecisionReadback(
        decision_present=True,
        verdict=normalized_verdict,
    )


class AnthropicSmokeAgentModel:
    """Minimal JSON adapter for manual live-LLM smoke rehearsal."""

    def __init__(
        self,
        client: Any,
        *,
        model_name: str,
        max_tokens: int = 8192,
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._max_tokens = max_tokens

    def extract(self, request: Any) -> Mapping[str, Any]:
        return self._complete_json(
            task=(
                "Extract the bounded six-pack tender findings. Use only evidence "
                "items present in request.evidence_board for evidence_refs."
            ),
            request=request,
            output_schema=EvidenceScoutOutput.model_json_schema(),
        )

    def draft_motion(self, request: Any) -> Mapping[str, Any]:
        return self._complete_json(
            task=(
                f"Draft the Round 1 motion for {request.agent_role.value}. Cite "
                "only evidence items present in request.evidence_board."
            ),
            request=request,
            output_schema=Round1Motion.model_json_schema(),
        )

    def draft_rebuttal(self, request: Any) -> Mapping[str, Any]:
        return self._complete_json(
            task=(
                f"Draft the Round 2 rebuttal for {request.agent_role.value}. "
                "Address validated peer motions and cite only shared evidence."
            ),
            request=request,
            output_schema=Round2Rebuttal.model_json_schema(),
        )

    def decide(self, request: Any) -> Mapping[str, Any]:
        return self._complete_json(
            task=(
                "Draft the final Judge decision. The vote_summary must match the "
                "request, formal compliance blockers must be honored, and all "
                "material claims must cite request.evidence_board items."
            ),
            request=request,
            output_schema=JudgeDecision.model_json_schema(),
        )

    def _complete_json(
        self,
        *,
        task: str,
        request: Any,
        output_schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        prompt = {
            "task": task,
            "rules": [
                "Return only a JSON object. Do not use markdown fences.",
                "Do not invent external sources or evidence.",
                "Use evidence_refs with evidence_key, source_type, and evidence_id "
                "copied from the provided evidence_board.",
                "Put unsupported or missing points in missing_info, "
                "potential_evidence_gaps, assumptions, or validation_errors.",
            ],
            "request": request.model_dump(mode="json"),
            "output_schema": output_schema,
        }
        response = self._client.messages.create(
            model=self._model_name,
            max_tokens=self._max_tokens,
            temperature=0,
            system=(
                "You are Bidded's evidence-locked Swedish public procurement "
                "review agent. Follow the JSON schema exactly."
            ),
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(prompt, default=str),
                }
            ],
        )
        return _parse_json_object(_anthropic_response_text(response))


@contextmanager
def _resolve_smoke_pdf_path(
    requested_pdf_path: Path | None,
) -> Generator[tuple[Path, str]]:
    if requested_pdf_path is not None and requested_pdf_path.exists():
        yield requested_pdf_path, "provided"
        return

    with tempfile.TemporaryDirectory(prefix="bidded-smoke-") as temp_dir:
        generated_path = Path(temp_dir) / GENERATED_SMOKE_PDF_FILENAME
        _write_generated_text_pdf(generated_path)
        yield generated_path, "generated_fixture"


def _write_generated_text_pdf(path: Path) -> None:
    import fitz

    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_textbox(
            fitz.Rect(72, 72, 520, 760),
            (
                "Supplier must hold active ISO 27001 certification at submission. "
                "Supplier must name a security-cleared delivery lead in the "
                "submission. Submission deadline is 2026-05-05 at 12:00 CET. "
                "Award evaluation weights quality at 60 percent and price at 40 "
                "percent. The contract includes liability penalties for material "
                "delivery delay. Submission must include a signed data processing "
                "agreement. Supplier must not be bankrupt or subject to insolvency "
                "exclusion grounds. Bidders must provide comparable public sector "
                "references and demonstrate stable financial standing."
            ),
            fontsize=11,
        )
        document.save(path)
    finally:
        document.close()


def _readback_detail(
    *,
    run_status: RunStatusSnapshot,
    decision_readback: DemoSmokeDecisionReadback,
    failure_reason: str | None,
) -> str:
    verdict = (
        decision_readback.verdict.value
        if decision_readback.verdict is not None
        else "none"
    )
    detail = (
        f"status {run_status.status.value}; decision present "
        f"{'yes' if decision_readback.decision_present else 'no'}; verdict {verdict}"
    )
    if failure_reason:
        detail = f"{detail}; failure {failure_reason}"
    return detail


def _failure_reason(
    run_status: RunStatusSnapshot,
    worker_message: str,
) -> str | None:
    if run_status.error_details:
        return _format_error_details(run_status.error_details)
    if run_status.status is AgentRunStatus.FAILED:
        return worker_message
    return None


def _format_error_details(error_details: Mapping[str, Any]) -> str:
    code = error_details.get("code") or "unknown"
    source = error_details.get("source") or "unknown"
    message = error_details.get("message") or "unknown error"
    return f"{code} from {source} - {message}"


def _response_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise DemoSmokeError("Supabase query did not return a row list.")
    return [row for row in data if isinstance(row, Mapping)]


def _normalize_uuid(value: Any, field_name: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise DemoSmokeError(f"{field_name} must be a UUID.") from exc


def _anthropic_response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        parts: list[str] = []
        for block in content:
            if isinstance(block, Mapping):
                text = block.get("text")
            else:
                text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    return str(content)


def _parse_json_object(text: str) -> Mapping[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if match is None:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, Mapping):
        raise DemoSmokeError("Anthropic response did not contain a JSON object.")
    return parsed


__all__ = [
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_SMOKE_ISSUING_AUTHORITY",
    "DEFAULT_SMOKE_PROCUREMENT_REFERENCE",
    "DEFAULT_SMOKE_TENDER_TITLE",
    "DemoSmokeDecisionReadback",
    "DemoSmokeError",
    "DemoSmokeResult",
    "DemoSmokeStep",
    "build_demo_smoke_graph_runner",
    "read_demo_smoke_decision",
    "run_demo_smoke",
]
