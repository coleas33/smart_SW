"""Unit tests for the agent runner (T030).

The loop is driven by a fake Anthropic client: a scripted list of turns, each naming the
tools that turn calls. Nothing here touches the network, and no API key is needed - the
point of injecting `client` into `run_review` is that the whole loop, including the parts
that only happen when something goes wrong, is reachable from a unit test.

The fake mirrors the two pieces of the SDK contract the runner depends on: iterating it
yields one message per turn with a `stop_reason`, and `generate_tool_call_response()`
runs that turn's tool calls once and returns the tool-result message.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from anthropic.lib.tools import ToolError
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from swreview.agent import runner
from swreview.agent.checklist import load_checklist
from swreview.report.session import ReviewSession
from tests.support.contracts import load_contract

ToolCall = tuple[str, dict[str, Any]]


@dataclass(frozen=True)
class Turn:
    """One assistant turn: why it stopped, and what it asked the tools to do."""

    stop_reason: str
    calls: tuple[ToolCall, ...] = ()


class FakeMessage:
    """The only part of `BetaMessage` the runner reads."""

    role = "assistant"

    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason


@dataclass
class FakeToolRunner:
    tools: dict[str, Any]
    script: list[Turn]
    results: list[dict[str, Any]] = field(default_factory=list)
    pending: list[ToolCall] = field(default_factory=list)

    def __iter__(self) -> Iterator[FakeMessage]:
        for turn in self.script:
            self.pending = list(turn.calls)
            yield FakeMessage(turn.stop_reason)

    def generate_tool_call_response(self) -> dict[str, Any] | None:
        """Run this turn's calls once, the way the SDK runner does, and cache the result."""
        if not self.pending:
            return None
        blocks: list[dict[str, Any]] = []
        for name, arguments in self.pending:
            try:
                content = self.tools[name].call(arguments)
                blocks.append({"type": "tool_result", "content": content, "is_error": False})
            except ToolError as exc:
                blocks.append({"type": "tool_result", "content": exc.content, "is_error": True})
        self.pending = []
        self.results.extend(blocks)
        return {"role": "user", "content": blocks}


class FakeMessages:
    def __init__(self, script: Sequence[Turn]) -> None:
        self.script = list(script)
        self.kwargs: dict[str, Any] = {}
        self.runner: FakeToolRunner | None = None

    def tool_runner(self, **kwargs: Any) -> FakeToolRunner:
        self.kwargs = kwargs
        self.runner = FakeToolRunner(
            tools={tool.name: tool for tool in kwargs["tools"]},
            script=self.script,
        )
        return self.runner


class FakeBeta:
    def __init__(self, script: Sequence[Turn]) -> None:
        self.messages = FakeMessages(script)


class FakeClient:
    """`client.beta.messages.tool_runner(...)`, and nothing else."""

    def __init__(self, script: Sequence[Turn]) -> None:
        self.beta = FakeBeta(script)


@dataclass(frozen=True)
class Run:
    """One finished review plus the fake client it ran against."""

    session: ReviewSession
    client: FakeClient

    @property
    def kwargs(self) -> dict[str, Any]:
        """What `tool_runner` was called with."""
        return self.client.beta.messages.kwargs

    @property
    def results(self) -> list[dict[str, Any]]:
        """The tool_result blocks the fake runner produced, in order."""
        assert self.client.beta.messages.runner is not None
        return self.client.beta.messages.runner.results


@pytest.fixture
def review(tmp_package_dir: Path, tmp_path: Path) -> Callable[..., Run]:
    """Run `run_review` over the `make_package` package with a scripted fake client."""

    def run(script: Sequence[Turn], **kwargs: Any) -> Run:
        client = FakeClient(script)
        session = runner.run_review(tmp_package_dir, tmp_path / "out", client=client, **kwargs)
        return Run(session=session, client=client)

    return run


def session_validator() -> Draft202012Validator:
    ir_schema = Resource.from_contents(load_contract("ir.schema.json"))
    registry: Registry = ir_schema @ Registry()
    return Draft202012Validator(
        load_contract("review-session.schema.json"),
        registry=registry,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


DRAWING_FINDING: ToolCall = (
    "record_drawing_finding",
    {
        "document_id": "doc:2",
        "sheet": "Sheet1",
        "observed": "The tapped hole is called out without a thread depth",
        "requirement": "A tapped hole callout states the usable thread depth",
        "source_refs": [{"document_id": "doc:2", "sheet": "Sheet1"}],
        "status": "suspected",
        "recommended_action": "Add the tapped depth to the hole callout",
    },
)


# --- the trace -------------------------------------------------------------------


def test_every_tool_call_becomes_an_investigation_step(
    review: Callable[..., Run],
) -> None:
    run = review(
        [
            Turn("tool_use", (("get_package_summary", {}), ("get_review_checklist", {}))),
            Turn("tool_use", (("list_holes", {"component_id": "cmp:0001"}),)),
            Turn("end_turn"),
        ]
    )
    assert [step.tool for step in run.session.steps] == [
        "get_package_summary",
        "get_review_checklist",
        "list_holes",
    ]
    assert [step.index for step in run.session.steps] == [0, 1, 2]
    assert {step.status for step in run.session.steps} == {"ok"}
    assert all(step.error is None for step in run.session.steps)
    assert all(step.elapsed_s >= 0 for step in run.session.steps)
    assert all(len(step.result_summary) <= 200 for step in run.session.steps)
    assert run.session.steps[2].arguments == {"component_id": "cmp:0001"}
    assert run.session.steps[2].result_summary.startswith("1 items: ")
    holes = json.loads(run.results[2]["content"])
    assert holes[0]["thread_depth_note"] == "unknown"


def test_a_tool_result_is_json_the_model_can_read(
    review: Callable[..., Run],
) -> None:
    run = review([Turn("tool_use", (("list_gaps", {}),)), Turn("end_turn")])
    block = run.results[0]
    assert block["is_error"] is False
    gaps = json.loads(block["content"])
    assert gaps[0]["entity_id"] == "hole:1"


def test_the_runner_is_started_with_the_contracted_parameters(
    review: Callable[..., Run],
) -> None:
    run = review([Turn("end_turn")], effort="medium")
    kwargs = run.kwargs
    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["max_tokens"] == runner.MAX_TOKENS
    assert kwargs["output_config"] == {"effort": "medium"}
    assert kwargs["messages"] == [{"role": "user", "content": runner.OPENING_MESSAGE}]
    assert [tool.name for tool in kwargs["tools"]][0] == "get_package_summary"
    assert all(tool.to_dict()["strict"] is True for tool in kwargs["tools"])

    system = kwargs["system"]
    assert "You are a mechanical design reviewer" in system
    assert "coverage.closeout" in system
    assert "cover-assy" in system


# --- failures stay visible -------------------------------------------------------


def test_a_failing_tool_is_an_error_result_and_failed_coverage(
    review: Callable[..., Run],
) -> None:
    run = review(
        [Turn("tool_use", (("list_gaps", {}),)), Turn("end_turn")],
        fail_tool=("list_gaps",),
    )
    step = run.session.steps[0]
    assert step.status == "error"
    assert "--fail-tool" in (step.error or "")
    failed = run.session.coverage.failed
    assert [item.check for item in failed] == ["tool.list_gaps"]
    assert failed[0].error == step.error
    block = run.results[0]
    assert block["is_error"] is True
    assert "--fail-tool" in json.loads(block["content"])["error"]


def test_an_unknown_id_is_an_error_result_not_a_crash(
    review: Callable[..., Run],
) -> None:
    run = review(
        [
            Turn("tool_use", (("get_component", {"component_id": "cmp:9999"}),)),
            Turn("tool_use", (("get_component", {"component_id": "cmp:0001"}),)),
            Turn("end_turn"),
        ]
    )
    assert [step.status for step in run.session.steps] == ["error", "ok"]
    assert run.session.steps[0].error == "unknown component id 'cmp:9999'"
    assert [item.check for item in run.session.coverage.failed] == ["tool.get_component"]


def test_fail_tool_rejects_a_name_that_is_not_a_tool(
    review: Callable[..., Run],
) -> None:
    with pytest.raises(ValueError, match="fail_tool names no such tool"):
        review([Turn("end_turn")], fail_tool=("list_everything",))


# --- budgets ---------------------------------------------------------------------


def test_max_steps_stops_the_loop_and_records_closeout(
    review: Callable[..., Run],
) -> None:
    run = review(
        [
            Turn("tool_use", (("list_gaps", {}), ("list_holes", {}))),
            Turn("tool_use", (("list_fasteners", {}),)),
            Turn("end_turn"),
        ],
        max_steps=2,
    )
    assert [step.tool for step in run.session.steps] == ["list_gaps", "list_holes"]
    closeout = [
        item for item in run.session.coverage.unresolved if item.check == runner.CLOSEOUT_CHECK
    ]
    assert len(closeout) == 1
    assert "max_steps reached (2 tool calls)" in closeout[0].reason


def test_repeated_pause_turns_are_capped(review: Callable[..., Run]) -> None:
    script = [Turn("pause_turn") for _ in range(runner.MAX_PAUSE_RESTARTS + 1)]
    run = review([*script, Turn("tool_use", (("list_gaps", {}),)), Turn("end_turn")])
    assert run.session.steps == []
    closeout = [
        item for item in run.session.coverage.unresolved if item.check == runner.CLOSEOUT_CHECK
    ]
    assert len(closeout) == 1
    assert "paused turns" in closeout[0].reason


def test_pause_turns_under_the_cap_do_not_stop_the_review(
    review: Callable[..., Run],
) -> None:
    run = review(
        [
            Turn("pause_turn"),
            Turn("pause_turn"),
            Turn("tool_use", (("list_gaps", {}),)),
            Turn("end_turn"),
        ]
    )
    assert [step.tool for step in run.session.steps] == ["list_gaps"]
    assert not [
        item for item in run.session.coverage.unresolved if "paused turns" in item.reason
    ]


def test_the_bridge_is_not_available_in_this_build(
    review: Callable[..., Run],
) -> None:
    with pytest.raises(NotImplementedError, match="US3"):
        review([Turn("end_turn")], bridge=True)


# --- finalization ----------------------------------------------------------------


def test_open_evidence_requests_become_unresolved_coverage(
    review: Callable[..., Run],
) -> None:
    run = review(
        [
            Turn(
                "tool_use",
                (
                    (
                        "request_evidence",
                        {
                            "what": "The usable thread depth of hole:1",
                            "why": "fastener.engagement needs it",
                            "entity_ids": ["hole:1", "cmp:0001"],
                        },
                    ),
                ),
            ),
            Turn("end_turn"),
        ]
    )
    assert [request.status for request in run.session.evidence_requests] == ["open"]
    opened = [
        item for item in run.session.coverage.unresolved if item.check == runner.EVIDENCE_CHECK
    ]
    assert len(opened) == 1
    assert "ER-001 is still open" in opened[0].reason
    assert opened[0].scope.component_ids == ["cmp:0001"]


def test_checklist_items_left_open_become_unresolved_coverage(
    review: Callable[..., Run],
) -> None:
    run = review(
        [
            Turn(
                "tool_use",
                (
                    DRAWING_FINDING,
                    (
                        "mark_coverage",
                        {
                            "check": "interference",
                            "bucket": "skipped",
                            "scope": {},
                            "reason": "no interference results in this package",
                        },
                    ),
                ),
            ),
            Turn("end_turn"),
        ]
    )
    closed_in_run = {"drawing.manufacturing_inputs", "interference"}
    expected = [item.id for item in load_checklist().items if item.id not in closed_in_run]
    left_open = [
        item.check
        for item in run.session.coverage.unresolved
        if item.check != runner.EVIDENCE_CHECK
    ]
    assert left_open == expected


def test_the_session_is_timed_and_written(
    review: Callable[..., Run], tmp_path: Path
) -> None:
    run = review([Turn("tool_use", (("list_gaps", {}),)), Turn("end_turn")])
    assert run.session.ended_at is not None
    assert run.session.ended_at >= run.session.started_at
    assert run.session.timing.unattended_runtime_minutes >= 0
    assert run.session.timing.baseline_minutes is None
    assert run.session.timing.net_saved_minutes is None

    written = tmp_path / "out" / runner.SESSION_FILE_NAME
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["design_id"] == "dsn:1"


def test_the_saved_session_validates_against_the_contract(
    review: Callable[..., Run], tmp_path: Path
) -> None:
    run = review(
        [
            Turn(
                "tool_use",
                (
                    ("get_package_summary", {}),
                    ("get_component", {"component_id": "cmp:9999"}),
                    DRAWING_FINDING,
                    (
                        "request_evidence",
                        {
                            "what": "The usable thread depth of hole:1",
                            "why": "fastener.engagement needs it",
                            "entity_ids": ["hole:1"],
                        },
                    ),
                ),
            ),
            Turn("end_turn"),
        ]
    )
    assert run.session.findings and run.session.coverage.failed and run.session.coverage.unresolved
    written = json.loads(
        (tmp_path / "out" / runner.SESSION_FILE_NAME).read_text(encoding="utf-8")
    )
    session_validator().validate(written)
