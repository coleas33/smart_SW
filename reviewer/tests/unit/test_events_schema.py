"""The event stream against its contract, end to end (T024).

`tests/unit/test_provider_protocol.py` (T008) validates *hand-written* bodies: it proves
the schema says what the Python literals say. This module validates the bodies the code
actually produces - every line `agent/runner.py`'s `EventSink` writes while a scripted
provider drives the real tool registry - so a body that drifts from the contract fails
here even when the literal table in T008 is still in step with the schema.

Three things it pins down:

1. **Every event type in the contract** is produced by a real run and validated, so
   `NOT_YET_EMITTED` is empty: the last type without a producer, `disposition`, is now
   written by `chat/sessions.py`'s `record_disposition`, which is what the chat server's
   disposition endpoint calls. A type that loses its producer fails here rather than
   quietly disappearing from the stream.
2. **`events.jsonl` round-trips.** Each line parses back into an `AgentEvent` and
   re-serializes to the identical bytes, `seq` is contiguous from 1 across every turn of
   the session, and the file is appended to rather than rewritten - the pane replays it
   after a crash, so a line that only survives in memory is no line at all.
3. **Resolution is by `$id`, never by file path.** `chat-events.schema.json` refs the
   feature 001 review-session contract by absolute `$id`, and that contract refs
   `ir.schema.json` relatively against the same base. `tests.support.contracts`
   registers all of them in one `referencing.Registry`; the test below shows the same
   body is *unresolvable* without that registry, which is what proves the refs are
   really being followed and the validation is not vacuous.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, get_args

import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaValidationError
from referencing.exceptions import Unresolvable

from swreview.agent import runner
from swreview.agent.providers import AgentEvent, EventType
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.chat.sessions import record_disposition
from swreview.findings import build_finding
from swreview.ir.models import SourceRef
from tests.support.contracts import (
    CONTRACT_DIRS,
    contract_registry,
    contract_validator,
    load_any_contract,
)
from tests.support.packages import build_package

MODEL = "fake-1"
EVENTS_CONTRACT = "chat-events.schema.json"
EVENTS_SCHEMA = load_any_contract(EVENTS_CONTRACT)
SCHEMA_EVENT_TYPES: set[str] = set(EVENTS_SCHEMA["properties"]["type"]["enum"])

NOT_YET_EMITTED: frozenset[str] = frozenset()
"""Event types the contract carries that no producer emits yet. There are none left.

`finding`, `evidence.requested` and `coverage` are emitted by the tool layer as it writes
them (`ToolContext.record_finding` and its two siblings). `disposition` is an engineer's
judgement on a finding rather than the model's, so it has no place in a turn: it is written
by `record_disposition`, which the chat server's disposition endpoint calls and the run
below calls directly. The constant stays, empty, because it is the thing that would have to
be edited to let a type go unproduced again.
"""

EVIDENCE_ARGUMENTS: dict[str, Any] = {
    "what": "The usable thread depth of hole:1",
    "why": "fastener.engagement needs it; re-run that check once it is answered",
    "entity_ids": ["hole:1", "cmp:0001"],
}
REQUEST_ID = "ER-001"
UNKNOWN_COMPONENT = "cmp:9999"

DRAWING_FINDING_ARGUMENTS: dict[str, Any] = {
    "document_id": "doc:2",
    "sheet": "Sheet1",
    "observed": "The tapped hole is called out without a thread depth",
    "requirement": "A tapped hole callout states the usable thread depth",
    "source_refs": [{"document_id": "doc:2", "sheet": "Sheet1"}],
    "status": "suspected",
    "recommended_action": "Add the tapped depth to the hole callout",
}


def call(name: str, **arguments: Any) -> ScriptedToolCall:
    return ScriptedToolCall(name=name, arguments=arguments)


def turn(text: str, *calls: ScriptedToolCall, end_reason: str = "end") -> ScriptedTurn:
    return ScriptedTurn(text=text, tool_calls=calls, end_reason=end_reason)  # type: ignore[arg-type]


@pytest.fixture
def start(tmp_package_dir: Path, tmp_path: Path) -> Callable[..., runner.ReviewRun]:
    """`start_review` over the fixture package with a scripted provider, not yet played."""

    def begin(script: Sequence[ScriptedTurn], **kwargs: Any) -> runner.ReviewRun:
        return runner.start_review(
            tmp_package_dir,
            tmp_path / "out",
            provider=FakeProvider(script=script, model=MODEL),
            effort="high",
            **kwargs,
        )

    return begin


def events_of(run: runner.ReviewRun) -> list[dict[str, Any]]:
    """Every line of `events.jsonl`, parsed."""
    return [
        json.loads(line)
        for line in run.events_path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def lines_of(run: runner.ReviewRun) -> list[str]:
    """Every line of `events.jsonl`, exactly as written."""
    return [line for line in run.events_path.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture
def full_run(start: Callable[..., runner.ReviewRun]) -> runner.ReviewRun:
    """One session that emits every event type the runner and the tools can emit today.

    The opening turn reads the package, opens an evidence request, and makes a call that
    fails (an id the package does not hold) so `tool.finished` is exercised on both
    branches. Answering the request runs a second turn, which records coverage and a
    drawing finding, so the three types the tool layer emits are all in the stream. The
    engineer then dispositions that finding, which is the only producer of `disposition`.
    The third turn is asked for after the script has run out, which is a provider failure:
    the runner reports `error`, ends the turn and finalizes before re-raising (data-model
    section 3, rule 5).
    """
    run = start(
        [
            turn(
                "Opened one evidence request.",
                call("get_package_summary"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
                call("get_component", component_id=UNKNOWN_COMPONENT),
            ),
            turn(
                "Thread depth is enough; the joint is fine.",
                call(
                    "mark_coverage",
                    check="fastener.engagement",
                    bucket="checked",
                    scope={"component_ids": ["cmp:0001"]},
                    reason="the answered thread depth clears the joint",
                ),
                call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS),
            ),
        ]
    )
    run.start()
    run.answer_evidence(REQUEST_ID, "Tapped 12 mm deep, per the shop drawing.")
    record_disposition(
        run,
        run.session.findings[0].id,
        decision="accepted",
        note="the callout is being fixed in the next revision",
        by="a.engineer",
    )
    with pytest.raises(ValueError, match="the script has 2 turn"):
        run.continue_session("Anything else?")
    return run


# --- the shared contract loader ----------------------------------------------------------


def test_the_registry_holds_every_committed_schema_keyed_by_its_id() -> None:
    """Both features' contracts, registered under the `$id` their refs actually name."""
    registry = contract_registry()
    for directory in CONTRACT_DIRS:
        for path in sorted(directory.glob("*.schema.json")):
            schema_id = json.loads(path.read_text(encoding="utf-8"))["$id"]
            assert registry.contents(schema_id) is not None, f"{path.name} not registered"
    for name in ("ir.schema.json", "review-session.schema.json", EVENTS_CONTRACT):
        assert registry.contents(f"https://smart-sw.local/contracts/{name}") is not None


def test_a_cross_feature_ref_resolves_only_through_the_registry() -> None:
    """A `finding` body reaches review-session by `$id` and `ir.schema.json` from there.

    `jsonschema` resolves lazily, so the proof that the refs are followed is that the
    same body is *unresolvable* against the bare schema: nothing on disk is consulted,
    and `https://smart-sw.local/...` is not a real host.
    """
    event = {
        "seq": 1,
        "at": "2026-09-13T12:00:00Z",
        "type": "finding",
        "body": _finding_body(),
    }
    contract_validator(EVENTS_CONTRACT).validate(event)
    with pytest.raises(Unresolvable):
        Draft202012Validator(EVENTS_SCHEMA).validate(event)


def _finding_body() -> dict[str, Any]:
    """A finding whose `drawing_locations` force the transitive `ir.schema.json` ref."""
    finding = build_finding(
        finding_id="F-001",
        check="drawing.manufacturing_inputs",
        title="Tapped hole callout has no thread depth",
        status="suspected",
        severity="medium",
        package=build_package(),
        configuration="Default",
        observed="The callout states M6x1.0 with no usable thread depth",
        requirement="A tapped hole callout states the usable thread depth",
        recommended_action="Add the tapped depth to the callout",
        drawing_locations=[SourceRef(document_id="doc:2", sheet="Sheet1")],
        tool_result_ids=[0],
        numeric=False,
    )
    return finding.model_dump(mode="json")


# --- every emitted event validates -------------------------------------------------------


def test_every_event_of_a_full_run_validates_against_the_contract(
    full_run: runner.ReviewRun,
) -> None:
    validator = contract_validator(EVENTS_CONTRACT)
    for event in events_of(full_run):
        validator.validate(event)


def test_a_full_run_emits_every_event_type_the_runner_and_tools_can_emit(
    full_run: runner.ReviewRun,
) -> None:
    emitted = {event["type"] for event in events_of(full_run)}
    assert NOT_YET_EMITTED <= SCHEMA_EVENT_TYPES
    assert emitted == SCHEMA_EVENT_TYPES - NOT_YET_EMITTED
    assert emitted <= set(get_args(EventType))


def test_tool_finished_validates_on_both_the_ok_and_the_error_branch(
    full_run: runner.ReviewRun,
) -> None:
    """The failing call is a result, not a raise: `status: error` with a non-null `error`."""
    finished = [event for event in events_of(full_run) if event["type"] == "tool.finished"]
    started = [event for event in events_of(full_run) if event["type"] == "tool.started"]
    assert [event["body"]["tool"] for event in started] == [
        "get_package_summary",
        "request_evidence",
        "get_component",
        "mark_coverage",
        "record_drawing_finding",
    ]
    statuses = [event["body"]["status"] for event in finished]
    assert statuses == ["ok", "ok", "error", "ok", "ok"]
    failed = finished[2]["body"]
    assert failed["error"] is not None
    assert UNKNOWN_COMPONENT in failed["error"]
    assert all(event["body"]["error"] is None for event in finished if event is not finished[2])
    assert [event["body"]["step_index"] for event in finished] == [0, 1, 2, 3, 4]


def test_the_error_event_of_a_failed_turn_names_the_exception(
    full_run: runner.ReviewRun,
) -> None:
    errors = [event for event in events_of(full_run) if event["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["body"]["error_class"] == "ValueError"
    assert errors[0]["body"]["retryable"] is True
    ended = [event for event in events_of(full_run) if event["type"] == "turn.ended"]
    assert [event["body"]["reason"] for event in ended] == ["end", "end", "error"]


@pytest.mark.parametrize(
    ("reason", "script", "options"),
    [
        ("end", [turn("done")], {}),
        ("truncated", [turn("cut off", end_reason="truncated")], {}),
        ("stopped", [turn("", end_reason="stopped")], {}),
        (
            "max_steps",
            [turn("never reached", call("get_package_summary"), call("list_gaps"))],
            {"max_steps": 1},
        ),
    ],
)
def test_every_turn_end_reason_the_runner_can_emit_validates(
    start: Callable[..., runner.ReviewRun],
    reason: str,
    script: list[ScriptedTurn],
    options: dict[str, Any],
) -> None:
    """All five `turn.ended` reasons; `error` is covered by the failed-turn test above."""
    run = start(script, **options)
    run.start()

    validator = contract_validator(EVENTS_CONTRACT)
    events = events_of(run)
    for event in events:
        validator.validate(event)
    ended = [event for event in events if event["type"] == "turn.ended"]
    assert [event["body"]["reason"] for event in ended] == [reason]


# --- events.jsonl round-trips -------------------------------------------------------------


def test_each_line_parses_back_into_an_agent_event_and_reserializes_identically(
    full_run: runner.ReviewRun,
) -> None:
    """The file is the model's own serialization, so the round trip is byte-exact."""
    lines = lines_of(full_run)
    assert lines
    for line in lines:
        event = AgentEvent.model_validate_json(line)
        assert event.model_dump_json() == line


def test_the_round_tripped_events_carry_the_same_bodies_as_the_json(
    full_run: runner.ReviewRun,
) -> None:
    parsed = [AgentEvent.model_validate_json(line) for line in lines_of(full_run)]
    raw = events_of(full_run)
    assert [event.type for event in parsed] == [item["type"] for item in raw]
    assert [event.body for event in parsed] == [item["body"] for item in raw]


def test_seq_is_contiguous_from_one_across_every_turn_of_the_session(
    full_run: runner.ReviewRun,
) -> None:
    """`seq` is per session, not per turn: the answered-evidence turn continues the count."""
    events = events_of(full_run)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert events[0]["type"] == "session.started"
    assert full_run.sink.seq == len(events)


def test_timestamps_never_go_backwards(full_run: runner.ReviewRun) -> None:
    stamps = [AgentEvent.model_validate_json(line).at for line in lines_of(full_run)]
    assert stamps == sorted(stamps)
    assert all(stamp.tzinfo is not None for stamp in stamps)


def test_the_file_is_appended_to_rather_than_rewritten(
    start: Callable[..., runner.ReviewRun],
) -> None:
    """The pane replays the file after a crash; a later turn must not truncate it."""
    run = start([turn("first"), turn("second")])
    run.start()
    after_first = lines_of(run)
    run.continue_session("keep going")
    after_second = lines_of(run)

    assert len(after_second) > len(after_first)
    assert after_second[: len(after_first)] == after_first


def test_a_body_the_contract_forbids_fails_validation(full_run: runner.ReviewRun) -> None:
    """A negative control: the validator rejects what the schema says it must reject."""
    validator = contract_validator(EVENTS_CONTRACT)
    started = next(event for event in events_of(full_run) if event["type"] == "tool.started")
    tampered = {**started, "body": {**started["body"], "unexpected": 1}}
    with pytest.raises(SchemaValidationError):
        validator.validate(tampered)
    with pytest.raises(SchemaValidationError):
        validator.validate({**started, "seq": 0})
