from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from operator import add
from typing import Annotated, Any, TypedDict
from uuid import UUID

from langgraph.graph import END as LANGGRAPH_END
from langgraph.graph import START, StateGraph

from bidded.orchestration.state import (
    AgentOutputState,
    AgentRunStatus,
    BidRunState,
    EvidenceItemState,
    EvidenceRef,
    FinalDecisionState,
    GraphNodeName,
    RebuttalState,
    RuntimeErrorState,
    ScoutFindingState,
    ScoutOutputState,
    SpecialistMotionState,
    SpecialistRole,
    ValidationIssueState,
    Verdict,
)


class GraphRouteNode(StrEnum):
    """Fixed route nodes used by the Bidded graph shell."""

    PREFLIGHT = GraphNodeName.PREFLIGHT.value
    EVIDENCE_SCOUT = GraphNodeName.EVIDENCE_SCOUT.value
    ROUND_1_COMPLIANCE = "round_1_compliance"
    ROUND_1_WIN_STRATEGIST = "round_1_win_strategist"
    ROUND_1_DELIVERY_CFO = "round_1_delivery_cfo"
    ROUND_1_RED_TEAM = "round_1_red_team"
    ROUND_1_JOIN = "round_1_join"
    ROUND_2_COMPLIANCE = "round_2_compliance"
    ROUND_2_WIN_STRATEGIST = "round_2_win_strategist"
    ROUND_2_DELIVERY_CFO = "round_2_delivery_cfo"
    ROUND_2_RED_TEAM = "round_2_red_team"
    ROUND_2_JOIN = "round_2_join"
    JUDGE = GraphNodeName.JUDGE.value
    PERSIST_DECISION = GraphNodeName.PERSIST_DECISION.value
    RETRY_HANDLER = "retry_handler"
    FAILED = "failed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    END = "END"


@dataclass(frozen=True)
class GraphEdgeSpec:
    """Human-readable edge table entry for the orchestrator-owned graph routes."""

    source: GraphRouteNode
    condition: str
    destinations: tuple[GraphRouteNode, ...]
    description: str
    orchestrator_controlled: bool = True


@dataclass(frozen=True)
class InvalidGraphOutput:
    """Invalid mocked node output that must be routed to retry handling."""

    source: str
    message: str
    field_path: str | None = None
    retryable: bool = True


@dataclass(frozen=True)
class GraphRunResult:
    """Result returned by the deterministic graph shell runner."""

    state: BidRunState
    visited_nodes: tuple[GraphRouteNode, ...]


_MAX_LLM_RETRIES = 2


@dataclass(frozen=True)
class _RetryAttempt:
    source: str
    message: str
    field_path: str | None = None


@dataclass(frozen=True)
class _RetryPolicyResult:
    output: Any | None
    invalid_output: InvalidGraphOutput | None
    retry_attempts: tuple[_RetryAttempt, ...]


@dataclass(frozen=True)
class Round1MotionResult:
    """Validated Round 1 motion plus its immutable audit row."""

    motion: SpecialistMotionState
    agent_output: AgentOutputState | None = None


@dataclass(frozen=True)
class Round2RebuttalResult:
    """Validated Round 2 rebuttal plus its immutable audit row."""

    rebuttal: RebuttalState
    agent_output: AgentOutputState | None = None


@dataclass(frozen=True)
class JudgeDecisionResult:
    """Validated Judge decision plus its immutable audit row."""

    decision: FinalDecisionState
    agent_output: AgentOutputState | None = None


ScoutHandler = Callable[[BidRunState], ScoutOutputState | InvalidGraphOutput]
Round1Handler = Callable[
    [BidRunState, SpecialistRole],
    SpecialistMotionState | Round1MotionResult | InvalidGraphOutput,
]
Round2Handler = Callable[
    [BidRunState, SpecialistRole],
    RebuttalState | Round2RebuttalResult | InvalidGraphOutput,
]
JudgeHandler = Callable[
    [BidRunState],
    FinalDecisionState | JudgeDecisionResult | InvalidGraphOutput,
]
PersistHandler = Callable[[BidRunState], InvalidGraphOutput | None]


@dataclass(frozen=True)
class GraphNodeHandlers:
    """Injectable deterministic handlers for graph shell tests and later nodes."""

    evidence_scout: ScoutHandler
    round_1_specialist: Round1Handler
    round_2_rebuttal: Round2Handler
    judge: JudgeHandler
    persist_decision: PersistHandler


class _GraphExecutionState(TypedDict, total=False):
    bid_state: BidRunState
    trace: Annotated[list[GraphRouteNode], add]
    round_1_motion_updates: Annotated[list[Round1MotionResult], add]
    round_2_rebuttal_updates: Annotated[list[Round2RebuttalResult], add]
    round_1_retry_attempts: Annotated[list[_RetryAttempt], add]
    round_2_retry_attempts: Annotated[list[_RetryAttempt], add]
    invalid_outputs: Annotated[list[InvalidGraphOutput], add]


_ROUND_1_ROLE_NODES: dict[SpecialistRole, GraphRouteNode] = {
    SpecialistRole.COMPLIANCE: GraphRouteNode.ROUND_1_COMPLIANCE,
    SpecialistRole.WIN_STRATEGIST: GraphRouteNode.ROUND_1_WIN_STRATEGIST,
    SpecialistRole.DELIVERY_CFO: GraphRouteNode.ROUND_1_DELIVERY_CFO,
    SpecialistRole.RED_TEAM: GraphRouteNode.ROUND_1_RED_TEAM,
}
_ROUND_2_ROLE_NODES: dict[SpecialistRole, GraphRouteNode] = {
    SpecialistRole.COMPLIANCE: GraphRouteNode.ROUND_2_COMPLIANCE,
    SpecialistRole.WIN_STRATEGIST: GraphRouteNode.ROUND_2_WIN_STRATEGIST,
    SpecialistRole.DELIVERY_CFO: GraphRouteNode.ROUND_2_DELIVERY_CFO,
    SpecialistRole.RED_TEAM: GraphRouteNode.ROUND_2_RED_TEAM,
}
_REBUTTAL_TARGETS: dict[SpecialistRole, SpecialistRole] = {
    SpecialistRole.COMPLIANCE: SpecialistRole.RED_TEAM,
    SpecialistRole.WIN_STRATEGIST: SpecialistRole.COMPLIANCE,
    SpecialistRole.DELIVERY_CFO: SpecialistRole.WIN_STRATEGIST,
    SpecialistRole.RED_TEAM: SpecialistRole.WIN_STRATEGIST,
}

_ROUTING_EDGE_TABLE: tuple[GraphEdgeSpec, ...] = (
    GraphEdgeSpec(
        source=GraphRouteNode.PREFLIGHT,
        condition="missing input, unparsed document, parser_failed document, "
        "missing chunks, or empty evidence board",
        destinations=(GraphRouteNode.FAILED,),
        description="Preflight only verifies prerequisites prepared before the graph.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.PREFLIGHT,
        condition="prerequisites valid",
        destinations=(GraphRouteNode.EVIDENCE_SCOUT,),
        description="The swarm starts only after registered, parsed, evidenced inputs.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.EVIDENCE_SCOUT,
        condition="invalid scout artifact before retry exhaustion",
        destinations=(GraphRouteNode.RETRY_HANDLER, GraphRouteNode.FAILED),
        description=(
            "Schema or evidence validation failures are retried up to policy limit."
        ),
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.EVIDENCE_SCOUT,
        condition="valid scout artifact",
        destinations=tuple(_ROUND_1_ROLE_NODES.values()),
        description="Round 1 specialists start independently from the same evidence.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.ROUND_1_JOIN,
        condition="invalid or missing Round 1 artifact before retry exhaustion",
        destinations=(GraphRouteNode.RETRY_HANDLER, GraphRouteNode.FAILED),
        description="Round 1 join validates all specialist motions before continuing.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.ROUND_1_JOIN,
        condition="all Round 1 motions valid",
        destinations=tuple(_ROUND_2_ROLE_NODES.values()),
        description="Round 2 is the first point where specialists can read motions.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.ROUND_2_JOIN,
        condition="invalid or missing Round 2 artifact before retry exhaustion",
        destinations=(GraphRouteNode.RETRY_HANDLER, GraphRouteNode.FAILED),
        description="Round 2 join validates all rebuttals before Judge routing.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.ROUND_2_JOIN,
        condition="all Round 2 rebuttals valid",
        destinations=(GraphRouteNode.JUDGE,),
        description="Judge runs only after validated motions and rebuttals.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.JUDGE,
        condition="invalid Judge artifact before retry exhaustion",
        destinations=(GraphRouteNode.RETRY_HANDLER, GraphRouteNode.FAILED),
        description="Invalid final decisions are retried by orchestrator policy.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.JUDGE,
        condition="valid Judge artifact",
        destinations=(GraphRouteNode.PERSIST_DECISION,),
        description="Persistence is a separate orchestrator-owned step.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.PERSIST_DECISION,
        condition="persistence failure",
        destinations=(GraphRouteNode.FAILED,),
        description="Persistence failures terminate the run as failed.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.PERSIST_DECISION,
        condition="persisted needs_human_review decision",
        destinations=(GraphRouteNode.NEEDS_HUMAN_REVIEW,),
        description=(
            "Technically valid but indefensible decisions get a terminal status."
        ),
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.PERSIST_DECISION,
        condition="persisted bid, no_bid, or conditional_bid decision",
        destinations=(GraphRouteNode.END,),
        description="Successful persisted decisions terminate at END.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.RETRY_HANDLER,
        condition="unexpected retryable error fallback",
        destinations=(GraphRouteNode.FAILED,),
        description="Bounded node retries should normally fail before this fallback.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.FAILED,
        condition="terminal failed status",
        destinations=(GraphRouteNode.END,),
        description="Failed runs terminate without agent-selected handoffs.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.NEEDS_HUMAN_REVIEW,
        condition="terminal needs_human_review status",
        destinations=(GraphRouteNode.END,),
        description="Human-review runs terminate after the status is persisted.",
    ),
    GraphEdgeSpec(
        source=GraphRouteNode.END,
        condition="terminal",
        destinations=(),
        description="LangGraph END.",
    ),
)


def graph_routing_edge_table() -> tuple[GraphEdgeSpec, ...]:
    """Return the documented orchestrator-owned graph routing table."""

    return _ROUTING_EDGE_TABLE


def default_graph_node_handlers() -> GraphNodeHandlers:
    """Return deterministic placeholder handlers for the routing shell."""

    return GraphNodeHandlers(
        evidence_scout=_default_evidence_scout,
        round_1_specialist=_default_round_1_specialist,
        round_2_rebuttal=_default_round_2_rebuttal,
        judge=_default_judge,
        persist_decision=_default_persist_decision,
    )


def build_bidded_graph_shell(
    handlers: GraphNodeHandlers | None = None,
) -> Any:
    """Build the fixed LangGraph routing shell without live agent side effects."""

    graph_handlers = handlers or default_graph_node_handlers()
    graph = StateGraph(_GraphExecutionState)

    graph.add_node(GraphRouteNode.PREFLIGHT, _preflight_node)
    graph.add_node(
        GraphRouteNode.EVIDENCE_SCOUT,
        _evidence_scout_node(graph_handlers),
    )
    for role, route_node in _ROUND_1_ROLE_NODES.items():
        graph.add_node(route_node, _round_1_specialist_node(graph_handlers, role))
    graph.add_node(GraphRouteNode.ROUND_1_JOIN, _round_1_join_node)
    for role, route_node in _ROUND_2_ROLE_NODES.items():
        graph.add_node(route_node, _round_2_rebuttal_node(graph_handlers, role))
    graph.add_node(GraphRouteNode.ROUND_2_JOIN, _round_2_join_node)
    graph.add_node(GraphRouteNode.JUDGE, _judge_node(graph_handlers))
    graph.add_node(
        GraphRouteNode.PERSIST_DECISION,
        _persist_decision_node(graph_handlers),
    )
    graph.add_node(GraphRouteNode.RETRY_HANDLER, _retry_handler_node)
    graph.add_node(GraphRouteNode.FAILED, _terminal_node(GraphRouteNode.FAILED))
    graph.add_node(
        GraphRouteNode.NEEDS_HUMAN_REVIEW,
        _terminal_node(GraphRouteNode.NEEDS_HUMAN_REVIEW),
    )

    graph.add_edge(START, GraphRouteNode.PREFLIGHT)
    graph.add_conditional_edges(
        GraphRouteNode.PREFLIGHT,
        _route_after_preflight,
        {
            GraphRouteNode.EVIDENCE_SCOUT: GraphRouteNode.EVIDENCE_SCOUT,
            GraphRouteNode.FAILED: GraphRouteNode.FAILED,
        },
    )
    graph.add_conditional_edges(
        GraphRouteNode.EVIDENCE_SCOUT,
        _route_after_evidence_scout,
        {
            GraphRouteNode.RETRY_HANDLER: GraphRouteNode.RETRY_HANDLER,
            GraphRouteNode.FAILED: GraphRouteNode.FAILED,
            **{node: node for node in _ROUND_1_ROLE_NODES.values()},
        },
    )
    graph.add_edge(list(_ROUND_1_ROLE_NODES.values()), GraphRouteNode.ROUND_1_JOIN)
    graph.add_conditional_edges(
        GraphRouteNode.ROUND_1_JOIN,
        _route_after_round_1_join,
        {
            GraphRouteNode.RETRY_HANDLER: GraphRouteNode.RETRY_HANDLER,
            GraphRouteNode.FAILED: GraphRouteNode.FAILED,
            **{node: node for node in _ROUND_2_ROLE_NODES.values()},
        },
    )
    graph.add_edge(list(_ROUND_2_ROLE_NODES.values()), GraphRouteNode.ROUND_2_JOIN)
    graph.add_conditional_edges(
        GraphRouteNode.ROUND_2_JOIN,
        _route_after_round_2_join,
        {
            GraphRouteNode.RETRY_HANDLER: GraphRouteNode.RETRY_HANDLER,
            GraphRouteNode.FAILED: GraphRouteNode.FAILED,
            GraphRouteNode.JUDGE: GraphRouteNode.JUDGE,
        },
    )
    graph.add_conditional_edges(
        GraphRouteNode.JUDGE,
        _route_after_judge,
        {
            GraphRouteNode.RETRY_HANDLER: GraphRouteNode.RETRY_HANDLER,
            GraphRouteNode.FAILED: GraphRouteNode.FAILED,
            GraphRouteNode.PERSIST_DECISION: GraphRouteNode.PERSIST_DECISION,
        },
    )
    graph.add_conditional_edges(
        GraphRouteNode.PERSIST_DECISION,
        _route_after_persist_decision,
        {
            GraphRouteNode.FAILED: GraphRouteNode.FAILED,
            GraphRouteNode.NEEDS_HUMAN_REVIEW: GraphRouteNode.NEEDS_HUMAN_REVIEW,
            GraphRouteNode.END: LANGGRAPH_END,
        },
    )
    graph.add_edge(GraphRouteNode.RETRY_HANDLER, GraphRouteNode.FAILED)
    graph.add_edge(GraphRouteNode.FAILED, LANGGRAPH_END)
    graph.add_edge(GraphRouteNode.NEEDS_HUMAN_REVIEW, LANGGRAPH_END)

    return graph.compile()


def run_bidded_graph_shell(
    state: BidRunState,
    *,
    handlers: GraphNodeHandlers | None = None,
) -> GraphRunResult:
    """Run the deterministic routing shell and return the final typed state."""

    compiled = build_bidded_graph_shell(handlers)
    output = compiled.invoke(
        {
            "bid_state": state,
            "trace": [],
            "round_1_motion_updates": [],
            "round_2_rebuttal_updates": [],
            "round_1_retry_attempts": [],
            "round_2_retry_attempts": [],
            "invalid_outputs": [],
        }
    )
    final_state = _coerce_bid_state(output["bid_state"])
    trace = tuple(GraphRouteNode(node) for node in output.get("trace", []))
    return GraphRunResult(state=final_state, visited_nodes=(*trace, GraphRouteNode.END))


def _preflight_node(execution_state: _GraphExecutionState) -> _GraphExecutionState:
    state = _state_from_execution(execution_state)
    failures = _preflight_failures(state)
    if failures:
        updated = state.apply_node_update(
            GraphNodeName.PREFLIGHT,
            {
                "status": AgentRunStatus.FAILED,
                "current_step": GraphRouteNode.FAILED,
                "last_error": RuntimeErrorState(
                    source=GraphRouteNode.PREFLIGHT,
                    message="; ".join(failures),
                    retryable=False,
                ),
                "validation_errors": [
                    ValidationIssueState(
                        source=GraphRouteNode.PREFLIGHT,
                        message=failure,
                    )
                    for failure in failures
                ],
            },
        )
    else:
        updated = state.apply_node_update(
            GraphNodeName.PREFLIGHT,
            {
                "status": AgentRunStatus.RUNNING,
                "current_step": GraphRouteNode.PREFLIGHT,
                "last_error": None,
            },
        )
    return {"bid_state": updated, "trace": [GraphRouteNode.PREFLIGHT]}


def _evidence_scout_node(
    handlers: GraphNodeHandlers,
) -> Callable[[_GraphExecutionState], _GraphExecutionState]:
    def node(execution_state: _GraphExecutionState) -> _GraphExecutionState:
        state = _state_from_execution(execution_state)

        def run_once() -> ScoutOutputState | InvalidGraphOutput:
            output = handlers.evidence_scout(state)
            if isinstance(output, InvalidGraphOutput):
                return output

            invalid_output = _validate_scout_output_state(output, state)
            if invalid_output is not None:
                return invalid_output
            return output

        retry_result = _run_with_retry_policy(
            GraphRouteNode.EVIDENCE_SCOUT,
            run_once,
        )
        updated = _apply_retry_attempts(
            state,
            GraphNodeName.EVIDENCE_SCOUT,
            retry_result.retry_attempts,
        )
        if retry_result.invalid_output is not None:
            updated = _apply_invalid_output(
                updated,
                GraphNodeName.EVIDENCE_SCOUT,
                retry_result.invalid_output,
            )
        else:
            output = retry_result.output
            updated = updated.apply_node_update(
                GraphNodeName.EVIDENCE_SCOUT,
                {
                    "scout_output": output,
                    "agent_outputs": [_agent_output_from_scout_output(output)],
                    "current_step": GraphRouteNode.EVIDENCE_SCOUT,
                    "last_error": None,
                },
            )
        return {"bid_state": updated, "trace": [GraphRouteNode.EVIDENCE_SCOUT]}

    return node


def _round_1_specialist_node(
    handlers: GraphNodeHandlers,
    role: SpecialistRole,
) -> Callable[[_GraphExecutionState], _GraphExecutionState]:
    route_node = _ROUND_1_ROLE_NODES[role]

    def node(execution_state: _GraphExecutionState) -> _GraphExecutionState:
        state = _state_from_execution(execution_state)
        retry_result = _run_with_retry_policy(
            route_node,
            lambda: handlers.round_1_specialist(state, role),
        )
        updates: _GraphExecutionState = {
            "trace": [route_node],
        }
        if retry_result.retry_attempts:
            updates["round_1_retry_attempts"] = list(retry_result.retry_attempts)
        if retry_result.invalid_output is not None:
            updates["invalid_outputs"] = [retry_result.invalid_output]
        else:
            updates["round_1_motion_updates"] = [
                _coerce_round_1_motion_result(retry_result.output)
            ]
        return updates

    return node


def _round_1_join_node(execution_state: _GraphExecutionState) -> _GraphExecutionState:
    state = _apply_retry_attempts(
        _state_from_execution(execution_state),
        GraphNodeName.ROUND_1_SPECIALIST,
        execution_state.get("round_1_retry_attempts", []),
    )
    invalid_outputs = execution_state.get("invalid_outputs", [])
    if invalid_outputs:
        updated = _apply_join_invalid_outputs(
            state,
            GraphNodeName.ROUND_1_SPECIALIST,
            invalid_outputs,
            GraphRouteNode.ROUND_1_JOIN,
        )
    else:
        motion_results = execution_state.get("round_1_motion_updates", [])
        motions = [result.motion for result in motion_results]
        invalid = _validate_role_outputs(
            outputs=motions,
            field_name="motions",
            join_node=GraphRouteNode.ROUND_1_JOIN,
        )
        if invalid is not None:
            updated = _apply_invalid_output(
                state,
                GraphNodeName.ROUND_1_SPECIALIST,
                invalid,
            )
        else:
            agent_outputs = [
                result.agent_output
                for result in motion_results
                if result.agent_output is not None
            ]
            updated = state.apply_node_update(
                GraphNodeName.ROUND_1_SPECIALIST,
                {
                    "motions": {motion.agent_role: motion for motion in motions},
                    "agent_outputs": agent_outputs,
                    "current_step": GraphRouteNode.ROUND_1_JOIN,
                    "last_error": None,
                },
            )
    return {"bid_state": updated, "trace": [GraphRouteNode.ROUND_1_JOIN]}


def _round_2_rebuttal_node(
    handlers: GraphNodeHandlers,
    role: SpecialistRole,
) -> Callable[[_GraphExecutionState], _GraphExecutionState]:
    route_node = _ROUND_2_ROLE_NODES[role]

    def node(execution_state: _GraphExecutionState) -> _GraphExecutionState:
        state = _state_from_execution(execution_state)
        retry_result = _run_with_retry_policy(
            route_node,
            lambda: handlers.round_2_rebuttal(state, role),
        )
        updates: _GraphExecutionState = {
            "trace": [route_node],
        }
        if retry_result.retry_attempts:
            updates["round_2_retry_attempts"] = list(retry_result.retry_attempts)
        if retry_result.invalid_output is not None:
            updates["invalid_outputs"] = [retry_result.invalid_output]
        else:
            updates["round_2_rebuttal_updates"] = [
                _coerce_round_2_rebuttal_result(retry_result.output)
            ]
        return updates

    return node


def _round_2_join_node(execution_state: _GraphExecutionState) -> _GraphExecutionState:
    state = _apply_retry_attempts(
        _state_from_execution(execution_state),
        GraphNodeName.ROUND_2_REBUTTAL,
        execution_state.get("round_2_retry_attempts", []),
    )
    invalid_outputs = execution_state.get("invalid_outputs", [])
    if invalid_outputs:
        updated = _apply_join_invalid_outputs(
            state,
            GraphNodeName.ROUND_2_REBUTTAL,
            invalid_outputs,
            GraphRouteNode.ROUND_2_JOIN,
        )
    else:
        rebuttal_results = execution_state.get("round_2_rebuttal_updates", [])
        rebuttals = [result.rebuttal for result in rebuttal_results]
        invalid = _validate_role_outputs(
            outputs=rebuttals,
            field_name="rebuttals",
            join_node=GraphRouteNode.ROUND_2_JOIN,
        )
        if invalid is not None:
            updated = _apply_invalid_output(
                state,
                GraphNodeName.ROUND_2_REBUTTAL,
                invalid,
            )
        else:
            updated = state.apply_node_update(
                GraphNodeName.ROUND_2_REBUTTAL,
                {
                    "rebuttals": {
                        rebuttal.agent_role: rebuttal for rebuttal in rebuttals
                    },
                    "agent_outputs": [
                        result.agent_output
                        for result in rebuttal_results
                        if result.agent_output is not None
                    ],
                    "current_step": GraphRouteNode.ROUND_2_JOIN,
                    "last_error": None,
                },
            )
    return {"bid_state": updated, "trace": [GraphRouteNode.ROUND_2_JOIN]}


def _judge_node(
    handlers: GraphNodeHandlers,
) -> Callable[[_GraphExecutionState], _GraphExecutionState]:
    def node(execution_state: _GraphExecutionState) -> _GraphExecutionState:
        state = _state_from_execution(execution_state)
        retry_result = _run_with_retry_policy(
            GraphRouteNode.JUDGE,
            lambda: handlers.judge(state),
        )
        updated = _apply_retry_attempts(
            state,
            GraphNodeName.JUDGE,
            retry_result.retry_attempts,
        )
        if retry_result.invalid_output is not None:
            updated = _apply_invalid_output(
                updated,
                GraphNodeName.JUDGE,
                retry_result.invalid_output,
            )
        else:
            result = _coerce_judge_decision_result(retry_result.output)
            agent_outputs = (
                [result.agent_output] if result.agent_output is not None else []
            )
            updated = updated.apply_node_update(
                GraphNodeName.JUDGE,
                {
                    "final_decision": result.decision,
                    "agent_outputs": agent_outputs,
                    "current_step": GraphRouteNode.JUDGE,
                    "last_error": None,
                },
            )
        return {"bid_state": updated, "trace": [GraphRouteNode.JUDGE]}

    return node


def _persist_decision_node(
    handlers: GraphNodeHandlers,
) -> Callable[[_GraphExecutionState], _GraphExecutionState]:
    def node(execution_state: _GraphExecutionState) -> _GraphExecutionState:
        state = _state_from_execution(execution_state)
        if state.final_decision is None:
            updated = state.apply_node_update(
                GraphNodeName.PERSIST_DECISION,
                {
                    "status": AgentRunStatus.FAILED,
                    "current_step": GraphRouteNode.FAILED,
                    "last_error": RuntimeErrorState(
                        source=GraphRouteNode.PERSIST_DECISION,
                        message="Cannot persist a missing Judge decision.",
                        retryable=False,
                    ),
                },
            )
        elif _invalid_needs_human_review_decision(state.final_decision):
            updated = state.apply_node_update(
                GraphNodeName.PERSIST_DECISION,
                {
                    "status": AgentRunStatus.FAILED,
                    "current_step": GraphRouteNode.FAILED,
                    "last_error": RuntimeErrorState(
                        source=GraphRouteNode.PERSIST_DECISION,
                        message=(
                            "needs_human_review requires critical missing "
                            "information or evidence gaps."
                        ),
                        retryable=False,
                    ),
                },
            )
        else:
            invalid_output = handlers.persist_decision(state)
            if invalid_output is not None:
                updated = state.apply_node_update(
                    GraphNodeName.PERSIST_DECISION,
                    {
                        "status": AgentRunStatus.FAILED,
                        "current_step": GraphRouteNode.FAILED,
                        "last_error": RuntimeErrorState(
                            source=invalid_output.source,
                            message=invalid_output.message,
                            retryable=False,
                        ),
                    },
                )
            else:
                status = (
                    AgentRunStatus.NEEDS_HUMAN_REVIEW
                    if state.final_decision.verdict is Verdict.NEEDS_HUMAN_REVIEW
                    else AgentRunStatus.SUCCEEDED
                )
                updated = state.apply_node_update(
                    GraphNodeName.PERSIST_DECISION,
                    {
                        "status": status,
                        "current_step": GraphRouteNode.PERSIST_DECISION,
                        "last_error": None,
                    },
                )
        return {"bid_state": updated, "trace": [GraphRouteNode.PERSIST_DECISION]}

    return node


def _retry_handler_node(execution_state: _GraphExecutionState) -> _GraphExecutionState:
    state = _state_from_execution(execution_state)
    source = state.last_error.source if state.last_error is not None else "unknown"
    message = state.last_error.message if state.last_error is not None else (
        "Retry handling reached without a recorded error."
    )
    retry_counts = dict(state.retry_counts)
    retry_counts[source] = retry_counts.get(source, 0) + 1
    updated = _replace_runtime_state(
        state,
        status=AgentRunStatus.FAILED,
        current_step=GraphRouteNode.FAILED,
        retry_counts=retry_counts,
        last_error=RuntimeErrorState(
            source=source,
            message=f"Retry handling reached in routing shell: {message}",
            retryable=False,
        ),
    )
    return {"bid_state": updated, "trace": [GraphRouteNode.RETRY_HANDLER]}


def _terminal_node(
    route_node: GraphRouteNode,
) -> Callable[[_GraphExecutionState], _GraphExecutionState]:
    def node(_: _GraphExecutionState) -> _GraphExecutionState:
        return {"trace": [route_node]}

    return node


def _route_after_preflight(state: _GraphExecutionState) -> GraphRouteNode:
    if _state_from_execution(state).status is AgentRunStatus.FAILED:
        return GraphRouteNode.FAILED
    return GraphRouteNode.EVIDENCE_SCOUT


def _route_after_evidence_scout(
    state: _GraphExecutionState,
) -> Sequence[GraphRouteNode]:
    bid_state = _state_from_execution(state)
    if bid_state.status is AgentRunStatus.FAILED:
        return (GraphRouteNode.FAILED,)
    if _has_retryable_error(bid_state):
        return (GraphRouteNode.RETRY_HANDLER,)
    return tuple(_ROUND_1_ROLE_NODES.values())


def _route_after_round_1_join(state: _GraphExecutionState) -> Sequence[GraphRouteNode]:
    bid_state = _state_from_execution(state)
    if bid_state.status is AgentRunStatus.FAILED:
        return (GraphRouteNode.FAILED,)
    if _has_retryable_error(bid_state):
        return (GraphRouteNode.RETRY_HANDLER,)
    return tuple(_ROUND_2_ROLE_NODES.values())


def _route_after_round_2_join(state: _GraphExecutionState) -> GraphRouteNode:
    bid_state = _state_from_execution(state)
    if bid_state.status is AgentRunStatus.FAILED:
        return GraphRouteNode.FAILED
    if _has_retryable_error(bid_state):
        return GraphRouteNode.RETRY_HANDLER
    return GraphRouteNode.JUDGE


def _route_after_judge(state: _GraphExecutionState) -> GraphRouteNode:
    bid_state = _state_from_execution(state)
    if bid_state.status is AgentRunStatus.FAILED:
        return GraphRouteNode.FAILED
    if _has_retryable_error(bid_state):
        return GraphRouteNode.RETRY_HANDLER
    return GraphRouteNode.PERSIST_DECISION


def _route_after_persist_decision(state: _GraphExecutionState) -> GraphRouteNode:
    bid_state = _state_from_execution(state)
    if bid_state.status is AgentRunStatus.FAILED:
        return GraphRouteNode.FAILED
    if bid_state.status is AgentRunStatus.NEEDS_HUMAN_REVIEW:
        return GraphRouteNode.NEEDS_HUMAN_REVIEW
    return GraphRouteNode.END


def _preflight_failures(state: BidRunState) -> list[str]:
    failures: list[str] = []
    if not state.document_ids:
        failures.append("At least one tender document must be registered.")

    parse_statuses = _document_parse_statuses(state)
    for document_id in state.document_ids:
        status = parse_statuses.get(str(document_id))
        if status is None:
            failures.append(f"Tender document {document_id} has no parse_status.")
        elif status == "parser_failed":
            failures.append(f"Tender document {document_id} has parser_failed status.")
        elif status != "parsed":
            failures.append(f"Tender document {document_id} is not parsed: {status}.")

    chunk_document_ids = {chunk.document_id for chunk in state.chunks}
    if not state.chunks:
        failures.append("Parsed tender chunks are required before graph execution.")
    for document_id in state.document_ids:
        if document_id not in chunk_document_ids:
            failures.append(f"Tender document {document_id} has no parsed chunks.")

    if not state.evidence_board:
        failures.append("Evidence board is empty.")

    return failures


def _document_parse_statuses(state: BidRunState) -> dict[str, str]:
    statuses: dict[str, str] = {}
    raw_statuses = state.run_context.get("document_parse_statuses", {})
    if isinstance(raw_statuses, dict):
        statuses.update({str(key): str(value) for key, value in raw_statuses.items()})

    raw_documents = state.run_context.get("documents", [])
    if isinstance(raw_documents, list):
        for raw_document in raw_documents:
            if isinstance(raw_document, dict):
                document_id = raw_document.get("id")
                parse_status = raw_document.get("parse_status")
                if document_id is not None and parse_status is not None:
                    statuses[str(document_id)] = str(parse_status)

    return statuses


def _default_evidence_scout(state: BidRunState) -> ScoutOutputState:
    evidence = state.evidence_board[0]
    return ScoutOutputState(
        findings=[
            ScoutFindingState(
                category=evidence.category,
                requirement_type=evidence.requirement_type,
                claim=evidence.normalized_meaning,
                evidence_refs=[_evidence_ref_from_item(evidence)],
            )
        ],
        missing_info=[],
        potential_blockers=[],
    )


def _default_round_1_specialist(
    state: BidRunState,
    role: SpecialistRole,
) -> SpecialistMotionState:
    evidence_ref = _first_evidence_ref(state)
    return SpecialistMotionState(
        agent_role=role,
        verdict=Verdict.CONDITIONAL_BID,
        confidence=0.72,
        summary=f"{role.value} placeholder motion from the routing shell.",
        evidence_refs=[evidence_ref],
        findings=["The evidence board is available for specialist review."],
        recommended_actions=["Replace routing-shell handler with real agent node."],
    )


def _default_round_2_rebuttal(
    state: BidRunState,
    role: SpecialistRole,
) -> RebuttalState:
    return RebuttalState(
        agent_role=role,
        target_motion_role=_REBUTTAL_TARGETS[role],
        summary=f"{role.value} placeholder rebuttal from the routing shell.",
        accepted_claims=["Round 1 artifacts were available for rebuttal."],
        evidence_refs=[_first_evidence_ref(state)],
    )


def _default_judge(state: BidRunState) -> FinalDecisionState:
    evidence_ref = _first_evidence_ref(state)
    evidence_ids = [
        evidence_id
        for evidence_id in [evidence_ref.evidence_id]
        if isinstance(evidence_id, UUID)
    ]
    return FinalDecisionState(
        verdict=Verdict.CONDITIONAL_BID,
        confidence=0.7,
        rationale="Routing-shell placeholder decision after validated mock artifacts.",
        vote_summary={Verdict.CONDITIONAL_BID.value: len(state.motions)},
        cited_memo="Replace the mocked Judge handler with a real evidence-backed node.",
        evidence_ids=evidence_ids,
        evidence_refs=[evidence_ref],
        recommended_actions=["Implement the real Judge node in a later story."],
    )


def _default_persist_decision(_: BidRunState) -> InvalidGraphOutput | None:
    return None


def _first_evidence_ref(state: BidRunState) -> EvidenceRef:
    return _evidence_ref_from_item(state.evidence_board[0])


def _evidence_ref_from_item(evidence: EvidenceItemState) -> EvidenceRef:
    return EvidenceRef(
        evidence_key=evidence.evidence_key,
        source_type=evidence.source_type,
        evidence_id=evidence.evidence_id,
    )


def _validate_scout_output_state(
    output: ScoutOutputState,
    state: BidRunState,
) -> InvalidGraphOutput | None:
    for finding_index, finding in enumerate(output.findings):
        field_path = f"findings[{finding_index}].evidence_refs"
        if not finding.evidence_refs:
            return InvalidGraphOutput(
                source=GraphRouteNode.EVIDENCE_SCOUT,
                message="Every scout finding must cite at least one evidence ref.",
                field_path=field_path,
            )

        for evidence_ref in finding.evidence_refs:
            if evidence_ref.evidence_id is None:
                return InvalidGraphOutput(
                    source=GraphRouteNode.EVIDENCE_SCOUT,
                    message=(
                        f"{evidence_ref.evidence_key} must include a resolved "
                        "evidence_id."
                    ),
                    field_path=field_path,
                )

            if (
                _matching_state_evidence_item(evidence_ref, state.evidence_board)
                is None
            ):
                return InvalidGraphOutput(
                    source=GraphRouteNode.EVIDENCE_SCOUT,
                    message=(
                        f"{evidence_ref.evidence_key} with evidence_id "
                        f"{evidence_ref.evidence_id} is not present in "
                        "evidence_board."
                    ),
                    field_path=field_path,
                )

    return None


def _agent_output_from_scout_output(output: ScoutOutputState) -> AgentOutputState:
    return AgentOutputState(
        agent_role=GraphNodeName.EVIDENCE_SCOUT.value,
        round_name="evidence",
        output_type="scout_output",
        payload=output.model_dump(mode="json"),
        evidence_refs=_dedupe_evidence_refs(
            evidence_ref
            for finding in output.findings
            for evidence_ref in finding.evidence_refs
        ),
    )


def _coerce_round_1_motion_result(
    output: SpecialistMotionState | Round1MotionResult,
) -> Round1MotionResult:
    if isinstance(output, Round1MotionResult):
        return output
    return Round1MotionResult(
        motion=output,
        agent_output=_agent_output_from_motion_state(output),
    )


def _agent_output_from_motion_state(motion: SpecialistMotionState) -> AgentOutputState:
    return AgentOutputState(
        agent_role=motion.agent_role.value,
        round_name="round_1_motion",
        output_type="motion",
        payload=motion.model_dump(mode="json"),
        evidence_refs=_dedupe_evidence_refs(motion.evidence_refs),
    )


def _coerce_round_2_rebuttal_result(
    output: RebuttalState | Round2RebuttalResult,
) -> Round2RebuttalResult:
    if isinstance(output, Round2RebuttalResult):
        return output
    return Round2RebuttalResult(
        rebuttal=output,
        agent_output=_agent_output_from_rebuttal_state(output),
    )


def _agent_output_from_rebuttal_state(rebuttal: RebuttalState) -> AgentOutputState:
    return AgentOutputState(
        agent_role=rebuttal.agent_role.value,
        round_name="round_2_rebuttal",
        output_type="rebuttal",
        payload=rebuttal.model_dump(mode="json"),
        evidence_refs=_dedupe_evidence_refs(rebuttal.evidence_refs),
    )


def _coerce_judge_decision_result(
    output: FinalDecisionState | JudgeDecisionResult,
) -> JudgeDecisionResult:
    if isinstance(output, JudgeDecisionResult):
        return output
    return JudgeDecisionResult(
        decision=output,
        agent_output=_agent_output_from_final_decision_state(output),
    )


def _agent_output_from_final_decision_state(
    decision: FinalDecisionState,
) -> AgentOutputState:
    return AgentOutputState(
        agent_role=GraphNodeName.JUDGE.value,
        round_name="final_decision",
        output_type="decision",
        payload=decision.model_dump(mode="json"),
        evidence_refs=_dedupe_evidence_refs(decision.evidence_refs),
    )


def _matching_state_evidence_item(
    evidence_ref: EvidenceRef,
    evidence_board: Sequence[EvidenceItemState],
) -> EvidenceItemState | None:
    return next(
        (
            evidence
            for evidence in evidence_board
            if evidence.evidence_key == evidence_ref.evidence_key
            and evidence.source_type is evidence_ref.source_type
            and evidence.evidence_id == evidence_ref.evidence_id
        ),
        None,
    )


def _dedupe_evidence_refs(evidence_refs: Iterable[EvidenceRef]) -> list[EvidenceRef]:
    deduped: list[EvidenceRef] = []
    seen: set[tuple[str, str, UUID | None]] = set()
    for evidence_ref in evidence_refs:
        key = (
            evidence_ref.evidence_key,
            evidence_ref.source_type.value,
            evidence_ref.evidence_id,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(evidence_ref)
    return deduped


def _validate_role_outputs(
    *,
    outputs: Sequence[SpecialistMotionState] | Sequence[RebuttalState],
    field_name: str,
    join_node: GraphRouteNode,
) -> InvalidGraphOutput | None:
    roles = [output.agent_role for output in outputs]
    expected_roles = set(SpecialistRole)
    missing_roles = expected_roles - set(roles)
    duplicate_roles = {role for role in roles if roles.count(role) > 1}
    if missing_roles or duplicate_roles:
        details = []
        if missing_roles:
            details.append(
                "missing "
                + ", ".join(sorted(role.value for role in missing_roles))
            )
        if duplicate_roles:
            details.append(
                "duplicate "
                + ", ".join(sorted(role.value for role in duplicate_roles))
            )
        return InvalidGraphOutput(
            source=join_node,
            message=f"Invalid {field_name}: {'; '.join(details)}.",
            field_path=field_name,
            retryable=False,
        )
    return None


def _apply_join_invalid_outputs(
    state: BidRunState,
    node: GraphNodeName,
    invalid_outputs: Sequence[InvalidGraphOutput],
    join_node: GraphRouteNode,
) -> BidRunState:
    if len(invalid_outputs) == 1:
        return _apply_invalid_output(state, node, invalid_outputs[0])

    message = "; ".join(output.message for output in invalid_outputs)
    invalid = InvalidGraphOutput(source=join_node, message=message, retryable=False)
    return _apply_invalid_output(state, node, invalid)


def _run_with_retry_policy(
    source: GraphRouteNode,
    run_once: Callable[[], Any],
) -> _RetryPolicyResult:
    retry_attempts: list[_RetryAttempt] = []
    while True:
        output = run_once()
        if not isinstance(output, InvalidGraphOutput):
            return _RetryPolicyResult(
                output=output,
                invalid_output=None,
                retry_attempts=tuple(retry_attempts),
            )

        invalid_output = _invalid_output_for_source(output, source)
        if not invalid_output.retryable:
            return _RetryPolicyResult(
                output=None,
                invalid_output=invalid_output,
                retry_attempts=tuple(retry_attempts),
            )

        if len(retry_attempts) >= _MAX_LLM_RETRIES:
            return _RetryPolicyResult(
                output=None,
                invalid_output=InvalidGraphOutput(
                    source=invalid_output.source,
                    message=(
                        f"{invalid_output.message} Retry limit reached after "
                        f"{_MAX_LLM_RETRIES} retries."
                    ),
                    field_path=invalid_output.field_path,
                    retryable=False,
                ),
                retry_attempts=tuple(retry_attempts),
            )

        retry_attempts.append(
            _RetryAttempt(
                source=_source_key(invalid_output.source),
                message=invalid_output.message,
                field_path=invalid_output.field_path,
            )
        )


def _invalid_output_for_source(
    invalid_output: InvalidGraphOutput,
    source: GraphRouteNode,
) -> InvalidGraphOutput:
    return InvalidGraphOutput(
        source=_source_key(source),
        message=invalid_output.message,
        field_path=invalid_output.field_path,
        retryable=invalid_output.retryable,
    )


def _apply_retry_attempts(
    state: BidRunState,
    node: GraphNodeName,
    retry_attempts: Sequence[_RetryAttempt],
) -> BidRunState:
    if not retry_attempts:
        return state

    retry_counts = dict(state.retry_counts)
    for attempt in retry_attempts:
        retry_counts[attempt.source] = retry_counts.get(attempt.source, 0) + 1

    return state.apply_node_update(
        node,
        {
            "retry_counts": retry_counts,
            "validation_errors": [
                ValidationIssueState(
                    source=attempt.source,
                    message=attempt.message,
                    field_path=attempt.field_path,
                )
                for attempt in retry_attempts
            ],
        },
    )


def _apply_invalid_output(
    state: BidRunState,
    node: GraphNodeName,
    invalid_output: InvalidGraphOutput,
) -> BidRunState:
    source = _source_key(invalid_output.source)
    failed = not invalid_output.retryable
    updates: dict[str, Any] = {
        "status": AgentRunStatus.FAILED if failed else AgentRunStatus.RUNNING,
        "current_step": GraphRouteNode.FAILED if failed else source,
        "last_error": RuntimeErrorState(
            source=source,
            message=invalid_output.message,
            retryable=invalid_output.retryable,
        ),
    }
    if "validation_errors" in BidRunState.node_contract(node).owned_write_fields:
        updates["validation_errors"] = [
            ValidationIssueState(
                source=source,
                message=invalid_output.message,
                field_path=invalid_output.field_path,
            )
        ]
    return state.apply_node_update(node, updates)


def _invalid_needs_human_review_decision(decision: FinalDecisionState) -> bool:
    return decision.verdict is Verdict.NEEDS_HUMAN_REVIEW and not (
        decision.missing_info or decision.potential_evidence_gaps
    )


def _replace_runtime_state(
    state: BidRunState,
    *,
    status: AgentRunStatus,
    current_step: str,
    retry_counts: dict[str, int],
    last_error: RuntimeErrorState | None,
) -> BidRunState:
    payload = state.model_dump()
    payload.update(
        {
            "status": status,
            "current_step": current_step,
            "retry_counts": retry_counts,
            "last_error": last_error,
        }
    )
    return BidRunState.model_validate(payload)


def _has_retryable_error(state: BidRunState) -> bool:
    return state.last_error is not None and state.last_error.retryable


def _source_key(source: str | GraphRouteNode) -> str:
    return source.value if isinstance(source, GraphRouteNode) else str(source)


def _state_from_execution(execution_state: _GraphExecutionState) -> BidRunState:
    return _coerce_bid_state(execution_state["bid_state"])


def _coerce_bid_state(value: BidRunState | dict[str, Any]) -> BidRunState:
    if isinstance(value, BidRunState):
        return value
    return BidRunState.model_validate(value)


__all__ = [
    "GraphEdgeSpec",
    "GraphNodeHandlers",
    "GraphRouteNode",
    "GraphRunResult",
    "InvalidGraphOutput",
    "JudgeDecisionResult",
    "Round1MotionResult",
    "Round2RebuttalResult",
    "build_bidded_graph_shell",
    "default_graph_node_handlers",
    "graph_routing_edge_table",
    "run_bidded_graph_shell",
]
