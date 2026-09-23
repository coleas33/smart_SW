"""Unit tests for the provider-driven agent runner (T014).

The runner no longer owns a vendor SDK's tool loop: it drives an `AgentProvider` turn by
turn and owns everything around it - the step budget, the event stream, the session, and
the resume rules in `specs/002-task-pane-assistant/data-model.md` section 3. The scripted
`FakeProvider` stands in for a real adapter, so every path below is reachable without a
network call, a key, or a recorded exchange.

One test per resume rule, named after the rule it pins down:

- (a) a second finalization produces the same coverage, not duplicates;
- (b) an answered evidence request stops being unresolved coverage;
- (c) a check re-run after its blocking request is answered yields one verdict;
- (d) `max_steps` is a per-turn budget and the cumulative count is kept separately;
- (e) a turn the provider truncated is `turn.ended {reason: "truncated"}` plus unresolved
  coverage;
- (f) a provider exception still finalizes and still writes `session.json`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
from swreview.agent.package_brief import package_brief
from swreview.agent.providers import (
    AgentEvent,
    EffortLevel,
    EffortMapping,
    EventCallback,
    ProviderName,
    ProviderTool,
    TurnResult,
)
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.report.session import ReviewSession
from tests.support.contracts import contract_validator

MODEL = "fake-1"
EFFORT: EffortLevel = "high"


# --- scripts the tests share -----------------------------------------------------------

DRAWING_FINDING_ARGUMENTS: dict[str, Any] = {
    "document_id": "doc:2",
    "sheet": "Sheet1",
    "observed": "The tapped hole is called out without a thread depth",
    "requirement": "A tapped hole callout states the usable thread depth",
    "source_refs": [{"document_id": "doc:2", "sheet": "Sheet1"}],
    "recommended_action": "Add the tapped depth to the hole callout",
}

EVIDENCE_ARGUMENTS: dict[str, Any] = {
    "what": "The usable thread depth of hole:1",
    "why": "fastener.engagement needs it",
    "entity_ids": ["hole:1", "cmp:0001"],
}

COVERAGE_ARGUMENTS: dict[str, Any] = {
    "check": "fasteners",
    "bucket": "checked",
    "scope": {"component_ids": ["cmp:0001"]},
    "reason": "every joint on the cover was checked",
}


def drawing_finding(status: str) -> ScriptedToolCall:
    """The same drawing finding twice over, differing only in its status."""
    return ScriptedToolCall(
        name="record_drawing_finding",
        arguments={**DRAWING_FINDING_ARGUMENTS, "status": status},
    )


def call(name: str, **arguments: Any) -> ScriptedToolCall:
    return ScriptedToolCall(name=name, arguments=arguments)


def turn(text: str, *calls: ScriptedToolCall, end_reason: str = "end") -> ScriptedTurn:
    return ScriptedTurn(text=text, tool_calls=calls, end_reason=end_reason)  # type: ignore[arg-type]


# --- the harness -----------------------------------------------------------------------


class RaisingProvider:
    """An adapter whose turn blows up. The failure path is not a tool error (case f)."""

    name = ProviderName.FAKE

    def __init__(self, model: str = MODEL) -> None:
        self.model = model

    def effort_mapping(self, effort: EffortLevel) -> EffortMapping:
        return EffortMapping(requested=effort, provider_param="fake.effort", provider_value=effort)

    def run(
        self,
        *,
        system: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[ProviderTool],
        effort: EffortLevel,
        max_steps: int,
        on_event: EventCallback,
    ) -> TurnResult:
        raise RuntimeError("the provider connection dropped")


@pytest.fixture
def start(tmp_package_dir: Path, tmp_path: Path) -> Callable[..., runner.ReviewRun]:
    """`start_review` over the fixture package with a scripted provider, not yet run."""

    def begin(script: Sequence[ScriptedTurn], **kwargs: Any) -> runner.ReviewRun:
        provider = kwargs.pop("provider", None)
        if provider is None:
            provider = FakeProvider(script=script, model=MODEL)
        return runner.start_review(
            tmp_package_dir,
            tmp_path / "out",
            provider=provider,
            effort=kwargs.pop("effort", EFFORT),
            **kwargs,
        )

    return begin


@pytest.fixture
def review(start: Callable[..., runner.ReviewRun]) -> Callable[..., runner.ReviewRun]:
    """A started run whose opening turn has already been played."""

    def run(script: Sequence[ScriptedTurn], **kwargs: Any) -> runner.ReviewRun:
        started = start(script, **kwargs)
        started.start()
        return started

    return run


def events_of(run: runner.ReviewRun) -> list[dict[str, Any]]:
    """Every line of `events.jsonl`, parsed."""
    text = run.events_path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def written_session(run: runner.ReviewRun) -> dict[str, Any]:
    return json.loads(run.session_path.read_text(encoding="utf-8"))


# --- the runner drives a provider --------------------------------------------------------


def test_every_scripted_tool_call_becomes_an_investigation_step(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review(
        [
            turn(
                "done",
                call("get_package_summary"),
                call("get_review_checklist"),
                call("list_holes", component_id="cmp:0001"),
            )
        ]
    )

    session = run.session
    assert [step.tool for step in session.steps] == [
        "get_package_summary",
        "get_review_checklist",
        "list_holes",
    ]
    assert [step.index for step in session.steps] == [0, 1, 2]
    assert {step.status for step in session.steps} == {"ok"}
    assert session.steps[2].arguments == {"component_id": "cmp:0001"}
    assert all(len(step.result_summary) <= 200 for step in session.steps)


def test_the_provider_is_given_the_system_prompt_the_tools_and_the_opening_message(
    start: Callable[..., runner.ReviewRun],
) -> None:
    seen: dict[str, Any] = {}

    class Recorder(RaisingProvider):
        def run(self, **kwargs: Any) -> TurnResult:  # type: ignore[override]
            seen.update(kwargs)
            return TurnResult(reason="end", text="", steps=0, messages=list(kwargs["messages"]))

    run = start([], provider=Recorder())
    run.start()

    assert "You are a mechanical design reviewer" in seen["system"]
    assert "coverage.closeout" in seen["system"]
    assert "cover-assy" in seen["system"]
    assert seen["messages"] == [
        {
            "role": "user",
            "content": f"{package_brief(run.context.ir)}\n\n{runner.OPENING_MESSAGE}",
        }
    ]
    assert seen["effort"] == EFFORT
    assert seen["max_steps"] == runner.DEFAULT_MAX_STEPS
    assert [tool.name for tool in seen["tools"]][0] == "get_package_summary"


def test_the_session_records_the_provider_and_the_effort_mapping(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("done")])

    info = run.session.provider_info
    assert info is not None
    assert info.provider == "fake"
    assert info.model == MODEL
    assert info.effort_mapping.requested == EFFORT
    assert info.effort_mapping.provider_param == "fake.effort"
    assert info.key_source == "none"
    assert run.session.model == MODEL


def test_retry_of_links_a_rerun_to_the_session_it_replaces(
    review: Callable[..., runner.ReviewRun],
) -> None:
    failed = "6f1d1d6a-6c8a-4f29-9f3f-0b0f6f5b9e11"

    run = review([turn("done")], retry_of=failed)

    assert str(run.session.retry_of) == failed


# --- failures stay visible ----------------------------------------------------------------


def test_a_failing_tool_is_an_error_result_and_failed_coverage(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("done", call("list_gaps"))], fail_tool=("list_gaps",))

    step = run.session.steps[0]
    assert step.status == "error"
    assert "--fail-tool" in (step.error or "")
    failed = run.session.coverage.failed
    assert [item.check for item in failed] == ["tool.list_gaps"]
    assert failed[0].error == step.error


def test_fail_tool_rejects_a_name_that_is_not_a_tool(
    start: Callable[..., runner.ReviewRun],
) -> None:
    with pytest.raises(ValueError, match="fail_tool names no such tool"):
        start([turn("done")], fail_tool=("list_everything",))


def test_a_tool_name_the_model_invented_is_an_error_step_and_failed_coverage(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """A hallucinated name goes through the registry's dispatch, not past it.

    The runner hands the provider a `ToolDispatch`, so the unknown name is recorded like
    any other failed call - an `InvestigationStep` with `status: error` and a `failed`
    coverage item - instead of being a result the adapter invented and nobody wrote down.
    """
    run = review([turn("done", call("check_everything"))])

    assert [step.tool for step in run.session.steps] == ["check_everything"]
    step = run.session.steps[0]
    assert step.status == "error"
    assert "no tool named 'check_everything'" in (step.error or "")
    assert [item.check for item in run.session.coverage.failed] == ["tool.check_everything"]
    finished = [event for event in events_of(run) if event["type"] == "tool.finished"]
    assert [event["body"]["status"] for event in finished] == ["error"]


# --- the event stream ----------------------------------------------------------------------


def test_events_are_written_in_order_with_a_monotonic_seq(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("all done", call("list_gaps"))])

    events = events_of(run)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert [event["type"] for event in events][:5] == [
        "session.started",
        "usage",
        "tool.started",
        "tool.finished",
        "text.delta",
    ]
    assert [event["type"] for event in events][-3:] == [
        "text.done",
        "turn.ended",
        "session.ended",
    ]


def test_every_event_validates_against_the_chat_event_contract(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """Including the three the tool layer emits, whose bodies are feature 001 `$ref`s."""
    run = review(
        [
            turn(
                "all done",
                call("list_gaps"),
                call("get_component", component_id="x"),
                drawing_finding("suspected"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
                call("mark_coverage", **COVERAGE_ARGUMENTS),
            )
        ]
    )

    validator = contract_validator("chat-events.schema.json")
    for event in events_of(run):
        validator.validate(event)
    assert {"finding", "evidence.requested", "coverage"} <= {
        event["type"] for event in events_of(run)
    }


def test_session_started_carries_the_flat_fields_the_event_schema_names(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("done")])

    started = events_of(run)[0]
    assert started["type"] == "session.started"
    assert started["body"] == {
        "session_id": str(run.session.session_id),
        "package_id": str(run.session.package_id),
        "provider": "fake",
        "model": MODEL,
        "effort_mapping": {
            "requested": EFFORT,
            "provider_param": "fake.effort",
            "provider_value": EFFORT,
        },
    }


def test_callbacks_see_every_event_that_reaches_the_file(
    review: Callable[..., runner.ReviewRun],
) -> None:
    seen: list[AgentEvent] = []

    run = review([turn("done", call("list_gaps"))], callbacks=(seen.append,))

    assert [event.seq for event in seen] == [event["seq"] for event in events_of(run)]
    assert [event.type for event in seen] == [event["type"] for event in events_of(run)]


def test_session_ended_carries_the_end_time_and_the_timing(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("done")])

    ended = events_of(run)[-1]
    assert ended["type"] == "session.ended"
    assert ended["body"]["ended_at"] == run.session.ended_at.isoformat()  # type: ignore[union-attr]
    assert ended["body"]["timing"]["unattended_runtime_minutes"] >= 0


# --- what the tools write reaches the stream while the turn runs (FR-013) ------------------


def bodies_of(run: runner.ReviewRun, event_type: str) -> list[dict[str, Any]]:
    return [event["body"] for event in events_of(run) if event["type"] == event_type]


def test_a_finding_the_model_records_is_announced_as_it_is_written(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("done", drawing_finding("suspected"))])

    announced = bodies_of(run, "finding")
    assert announced == [run.session.findings[0].model_dump(mode="json")]
    assert announced[0]["id"] == "F-001"


def test_an_evidence_request_is_announced_as_it_is_opened(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("asking", call("request_evidence", **EVIDENCE_ARGUMENTS))])

    announced = bodies_of(run, "evidence.requested")
    assert [body["id"] for body in announced] == ["ER-001"]
    assert announced[0]["status"] == "open"
    assert announced[0]["what"] == EVIDENCE_ARGUMENTS["what"]


def test_coverage_the_model_records_is_announced_with_the_bucket_it_went_into(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("done", call("mark_coverage", **COVERAGE_ARGUMENTS))])

    announced = bodies_of(run, "coverage")
    assert [body["bucket"] for body in announced] == ["checked"]
    assert announced[0]["item"] == run.session.coverage.checked[0].model_dump(mode="json")


def test_a_failed_tool_call_announces_the_failed_coverage_it_wrote(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """The bucket the model cannot write itself reaches the pane the same way."""
    run = review([turn("done", call("list_gaps"))], fail_tool=("list_gaps",))

    announced = bodies_of(run, "coverage")
    assert [body["bucket"] for body in announced] == ["failed"]
    assert announced[0]["item"]["check"] == "tool.list_gaps"
    assert announced[0]["item"]["error"] == run.session.coverage.failed[0].error


def test_a_turn_cut_short_announces_the_unresolved_item_it_wrote(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("cut short", call("list_gaps"), call("list_gaps"))], max_steps=1)

    announced = bodies_of(run, "coverage")
    assert [body["bucket"] for body in announced] == ["unresolved"]
    assert announced[0]["item"]["check"] == runner.CLOSEOUT_CHECK


def test_a_rerun_folded_onto_an_earlier_finding_is_reannounced_under_that_id(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """Resume rule (c) reuses the earlier id, so the stream has to say so.

    The re-run's finding is announced under the id it was allocated, and the fold is
    announced again under the id it was folded onto - a client keyed by finding id then
    ends on the same verdict `session.json` holds.
    """
    run = review(
        [
            turn(
                "blocked",
                drawing_finding("unresolved"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
            ),
            turn("resolved", drawing_finding("suspected")),
        ]
    )

    run.answer_evidence("ER-001", "The usable thread depth is 12 mm.")

    announced = bodies_of(run, "finding")
    assert [body["id"] for body in announced] == ["F-001", "F-002", "F-001"]
    assert [body["status"] for body in announced] == ["unresolved", "suspected", "suspected"]
    assert announced[-1] == run.session.findings[0].model_dump(mode="json")


# --- multi-turn ------------------------------------------------------------------------------


def test_continue_session_appends_a_user_turn_and_runs_it(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review(
        [
            turn("first", call("list_gaps")),
            turn("second", call("list_holes")),
        ]
    )

    run.continue_session("Also check the holes on cmp:0001, please.")

    assert run.messages[0] == {
        "role": "user",
        "content": f"{package_brief(run.context.ir)}\n\n{runner.OPENING_MESSAGE}",
    }
    follow_ups = [
        message
        for message in run.messages
        if message["role"] == "user" and message["content"].startswith("Also check")
    ]
    assert len(follow_ups) == 1
    assert [step.tool for step in run.session.steps] == ["list_gaps", "list_holes"]
    assert run.turns == 2


def test_a_follow_up_runs_on_a_session_that_already_ended(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("first"), turn("second", call("list_gaps"))])
    first_ended_at = run.session.ended_at
    assert first_ended_at is not None

    session = run.continue_session("One more thing.")

    assert session.ended_at is not None
    assert session.ended_at >= first_ended_at
    assert [step.tool for step in session.steps] == ["list_gaps"]
    assert [event["type"] for event in events_of(run)].count("session.ended") == 2


def test_answering_an_evidence_request_marks_it_and_resumes(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review(
        [
            turn("asking", call("request_evidence", **EVIDENCE_ARGUMENTS)),
            turn("thanks", call("list_holes", component_id="cmp:0001")),
        ]
    )
    assert [request.status for request in run.session.evidence_requests] == ["open"]

    session = run.answer_evidence("ER-001", "The usable thread depth is 12 mm.")

    request = session.evidence_requests[0]
    assert request.status == "answered"
    assert request.answer == "The usable thread depth is 12 mm."
    assert request.answered_at is not None
    assert [step.tool for step in session.steps][-1] == "list_holes"
    answered = [event for event in events_of(run) if event["type"] == "evidence.answered"]
    assert answered[0]["body"] == {
        "request_id": "ER-001",
        "answer": "The usable thread depth is 12 mm.",
    }


def test_answering_an_unknown_request_is_refused(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("done")])

    with pytest.raises(ValueError, match="ER-404"):
        run.answer_evidence("ER-404", "anything")


def test_answering_a_request_twice_is_refused(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review(
        [
            turn("asking", call("request_evidence", **EVIDENCE_ARGUMENTS)),
            turn("thanks"),
        ]
    )
    run.answer_evidence("ER-001", "12 mm")

    with pytest.raises(ValueError, match="already answered"):
        run.answer_evidence("ER-001", "12 mm again")


# --- several answers, one resumed turn (feature 008 T082, FR-025, SC-005) ----------------------


def ask(what: str) -> ScriptedToolCall:
    """One evidence request; each `what` is its own request."""
    return call("request_evidence", **{**EVIDENCE_ARGUMENTS, "what": what})


THREE_ASKS = (ask("the thread depth"), ask("the washer grade"), ask("the drawing revision"))


class SpyProvider(FakeProvider):
    """The scripted adapter, keeping a copy of the history each turn was sent."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sent: list[list[dict[str, Any]]] = []

    def run(self, **kwargs: Any) -> TurnResult:
        self.sent.append([dict(message) for message in kwargs["messages"]])
        return super().run(**kwargs)


def waiting_on_three(
    review: Callable[..., runner.ReviewRun], resumed: ScriptedTurn | None = None
) -> tuple[runner.ReviewRun, SpyProvider]:
    """A run whose opening turn opened ER-001 to ER-003 and whose next turn is `resumed`."""
    provider = SpyProvider(
        script=[turn("asking", *THREE_ASKS), resumed or turn("thanks")], model=MODEL
    )
    run = review([], provider=provider)
    assert [request.status for request in run.session.evidence_requests] == ["open"] * 3
    return run, provider


def unchanged_state(run: runner.ReviewRun) -> tuple[Any, ...]:
    """Everything a refused batch must leave exactly as it was."""
    return (
        [request.model_dump(mode="json") for request in run.session.evidence_requests],
        len(events_of(run)),
        run.turns,
        len(run.messages),
    )


SUBMITTED = (
    ("ER-002", "Grade 8.8, zinc flake."),
    ("ER-003", "Revision C is released."),
    ("ER-001", "The usable thread depth is 12 mm."),
)
"""Three answers in an order that is not the ids', so submission order is visible."""


def test_a_batch_of_three_answers_every_request_and_resumes_once(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run, provider = waiting_on_three(review)
    turns_before = run.turns

    session = run.answer_evidence_batch(SUBMITTED)

    by_id = {request.id: request for request in session.evidence_requests}
    for request_id, answer in SUBMITTED:
        assert by_id[request_id].status == "answered"
        assert by_id[request_id].answer == answer
        assert by_id[request_id].answered_at is not None
    answered = [event["body"] for event in events_of(run) if event["type"] == "evidence.answered"]
    assert answered == [{"request_id": rid, "answer": answer} for rid, answer in SUBMITTED]
    assert run.turns == turns_before + 1
    assert len(provider.sent) == 2


def test_the_resumed_turn_opens_on_one_message_listing_every_answer(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run, provider = waiting_on_three(review)

    run.answer_evidence_batch(SUBMITTED)

    assert provider.sent[-1][-1] == {
        "role": "user",
        "content": (
            "The engineer answered your evidence requests:\n"
            "- ER-002: Grade 8.8, zinc flake.\n"
            "- ER-003: Revision C is released.\n"
            "- ER-001: The usable thread depth is 12 mm.\n"
            "Continue the review with these answers."
        ),
    }
    assert provider.sent[-1][-1]["content"] == runner.answers_message(SUBMITTED)


def test_every_evidence_answered_event_comes_before_the_resumed_turn(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """The replay reads consecutive `evidence.answered` events before one turn as one batch
    (contracts/replay.md section 2), so nothing of the turn may come between them."""
    run, _ = waiting_on_three(review)
    start = len(events_of(run))

    run.answer_evidence_batch(SUBMITTED)

    kinds = [event["type"] for event in events_of(run)][start:]
    assert kinds[:3] == ["evidence.answered"] * 3
    assert kinds.count("turn.ended") == 1
    assert kinds.count("session.ended") == 1


def test_a_batch_of_one_sends_exactly_the_single_answer_message(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run, provider = waiting_on_three(review)

    run.answer_evidence_batch([("ER-001", "12 mm")])

    assert provider.sent[-1][-1]["content"] == runner.ANSWER_MESSAGE.format(
        request_id="ER-001", answer="12 mm"
    )
    assert runner.answers_message([("ER-001", "12 mm")]) == runner.ANSWER_MESSAGE.format(
        request_id="ER-001", answer="12 mm"
    )
    statuses = [request.status for request in run.session.evidence_requests]
    assert statuses == ["answered", "open", "open"]


def test_the_single_answer_sends_what_it_always_sent(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """`answer_evidence` delegates to the batch; its message is byte-identical (T083)."""
    run, provider = waiting_on_three(review)

    run.answer_evidence("ER-003", "Revision C is released.")

    assert provider.sent[-1][-1]["content"] == runner.ANSWER_MESSAGE.format(
        request_id="ER-003", answer="Revision C is released."
    )


def test_a_batch_folds_each_rerun_onto_the_verdict_it_rejudges(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """Resume rule (c) holds for a batch: the re-run replaces its earlier verdict in place,
    and the fold is announced again under the earlier id."""
    provider = SpyProvider(
        script=[
            turn("blocked", drawing_finding("unresolved"), *THREE_ASKS),
            turn("resolved", drawing_finding("suspected")),
        ],
        model=MODEL,
    )
    run = review([], provider=provider)

    session = run.answer_evidence_batch(SUBMITTED)

    assert [finding.id for finding in session.findings] == ["F-001"]
    assert session.findings[0].status == "suspected"
    announced = bodies_of(run, "finding")
    assert [body["id"] for body in announced] == ["F-001", "F-002", "F-001"]
    assert announced[-1] == session.findings[0].model_dump(mode="json")


def test_answering_every_request_leaves_no_evidence_item_unresolved(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run, _ = waiting_on_three(review)

    session = run.answer_evidence_batch(SUBMITTED)

    assert [
        item for item in session.coverage.unresolved if item.check == runner.EVIDENCE_CHECK
    ] == []


@pytest.mark.parametrize(
    ("answers", "error", "named"),
    [
        ([("ER-404", "anything")], runner.UnknownEvidenceRequestError, "ER-404"),
        (
            [("ER-001", "12 mm"), ("ER-404", "anything")],
            runner.UnknownEvidenceRequestError,
            "ER-404",
        ),
        ([("ER-001", "12 mm"), ("ER-001", "12 mm again")], ValueError, "ER-001"),
        (
            [("ER-002", "a"), ("ER-003", "b"), ("ER-002", "c")],
            ValueError,
            "ER-002",
        ),
    ],
    ids=["unknown", "valid-then-unknown", "repeated", "repeated-later"],
)
def test_a_bad_id_refuses_the_whole_batch_and_changes_nothing(
    review: Callable[..., runner.ReviewRun],
    answers: list[tuple[str, str]],
    error: type[Exception],
    named: str,
) -> None:
    run, provider = waiting_on_three(review)
    before = unchanged_state(run)

    with pytest.raises(error, match=named):
        run.answer_evidence_batch(answers)

    assert unchanged_state(run) == before
    assert len(provider.sent) == 1


def test_an_answered_id_refuses_the_whole_batch_and_changes_nothing(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run, provider = waiting_on_three(review, resumed=turn("thanks"))
    run.answer_evidence("ER-001", "12 mm")
    before = unchanged_state(run)

    with pytest.raises(runner.EvidenceAlreadyAnsweredError, match="ER-001") as refused:
        run.answer_evidence_batch([("ER-002", "grade 8.8"), ("ER-001", "12 mm again")])

    assert refused.value.request_id == "ER-001"
    assert "already answered" in str(refused.value)
    assert unchanged_state(run) == before
    assert len(provider.sent) == 2


def test_an_empty_batch_is_refused(review: Callable[..., runner.ReviewRun]) -> None:
    run, _ = waiting_on_three(review)
    before = unchanged_state(run)

    with pytest.raises(ValueError, match="at least one"):
        run.answer_evidence_batch([])

    assert unchanged_state(run) == before


def test_both_refusals_are_value_errors_naming_their_request() -> None:
    """Callers that caught `ValueError` before the batch existed still catch both."""
    assert issubclass(runner.UnknownEvidenceRequestError, ValueError)
    assert issubclass(runner.EvidenceAlreadyAnsweredError, ValueError)


def test_answerable_returns_the_open_request_and_refuses_the_rest(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """The one validator the runner and both routes call (contracts/answer-batch.md)."""
    run, _ = waiting_on_three(review, resumed=turn("thanks"))
    run.answer_evidence("ER-001", "12 mm")

    assert runner.answerable(run.session, "ER-002").id == "ER-002"
    with pytest.raises(runner.UnknownEvidenceRequestError) as unknown:
        runner.answerable(run.session, "ER-404")
    assert unknown.value.request_id == "ER-404"
    assert str(unknown.value) == (
        "no evidence request 'ER-404' in this session; open: ['ER-002', 'ER-003']"
    )
    with pytest.raises(runner.EvidenceAlreadyAnsweredError) as answered:
        runner.answerable(run.session, "ER-001")
    assert str(answered.value) == "evidence request ER-001 is already answered"


# --- resume rule (a): finalization is idempotent -----------------------------------------------


def test_a_second_finalization_produces_the_same_coverage_not_duplicates(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("done", call("request_evidence", **EVIDENCE_ARGUMENTS))])
    first = run.session.coverage.model_dump(mode="json")

    run.finalize()

    assert run.session.coverage.model_dump(mode="json") == first
    evidence_items = [
        item for item in run.session.coverage.unresolved if item.check == runner.EVIDENCE_CHECK
    ]
    assert len(evidence_items) == 1


def test_finalization_keeps_coverage_the_model_recorded_itself(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review(
        [
            turn(
                "done",
                call(
                    "mark_coverage",
                    check="coverage.closeout",
                    bucket="unresolved",
                    scope={},
                    reason="the package has no interference results to close this out",
                ),
            )
        ]
    )

    run.finalize()

    closeout = [
        item for item in run.session.coverage.unresolved if item.check == runner.CLOSEOUT_CHECK
    ]
    assert len(closeout) == 1
    assert "interference results" in closeout[0].reason


# --- resume rule (b): an answered request stops being unresolved -------------------------------


def test_answering_a_request_removes_its_unresolved_coverage_item(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review(
        [
            turn("asking", call("request_evidence", **EVIDENCE_ARGUMENTS)),
            turn("thanks"),
        ]
    )
    opened = [
        item for item in run.session.coverage.unresolved if item.check == runner.EVIDENCE_CHECK
    ]
    assert len(opened) == 1
    assert "ER-001 is still open" in opened[0].reason
    assert opened[0].scope.component_ids == ["cmp:0001"]

    session = run.answer_evidence("ER-001", "12 mm")

    assert [
        item for item in session.coverage.unresolved if item.check == runner.EVIDENCE_CHECK
    ] == []


# --- resume rule (c): a re-evaluated check has one verdict --------------------------------------


def test_a_check_rerun_after_an_answer_yields_one_verdict(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review(
        [
            turn(
                "blocked",
                drawing_finding("unresolved"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
            ),
            turn("resolved", drawing_finding("suspected")),
        ]
    )
    assert [finding.id for finding in run.session.findings] == ["F-001"]

    session = run.answer_evidence("ER-001", "The usable thread depth is 12 mm.")

    assert [finding.id for finding in session.findings] == ["F-001"]
    assert session.findings[0].status == "suspected"
    assert session.findings[0].severity == "medium"


def test_a_rerun_that_covers_something_else_is_a_second_finding(
    review: Callable[..., runner.ReviewRun],
) -> None:
    other = ScriptedToolCall(
        name="record_drawing_finding",
        arguments={
            **DRAWING_FINDING_ARGUMENTS,
            "sheet": "Sheet2",
            "source_refs": [{"document_id": "doc:2", "sheet": "Sheet2"}],
            "status": "suspected",
        },
    )

    run = review(
        [
            turn(
                "blocked",
                drawing_finding("unresolved"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
            ),
            turn("and another sheet", other),
        ]
    )

    session = run.answer_evidence("ER-001", "12 mm")

    assert [finding.id for finding in session.findings] == ["F-001", "F-002"]


# --- resume rule (d): max_steps is a per-turn budget --------------------------------------------


def test_max_steps_is_a_per_turn_budget_and_the_cumulative_count_is_kept_apart(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review(
        [
            turn("cut short", call("list_gaps"), call("list_holes"), call("list_fasteners")),
            turn("resumed", call("list_mates")),
        ],
        max_steps=2,
    )
    assert [step.tool for step in run.session.steps] == ["list_gaps", "list_holes"]
    assert run.total_steps == 2
    closeout = [
        item for item in run.session.coverage.unresolved if item.check == runner.CLOSEOUT_CHECK
    ]
    assert len(closeout) == 1
    assert "max_steps reached (2 tool calls)" in closeout[0].reason

    session = run.continue_session("Keep going.")

    assert [step.tool for step in session.steps][-1] == "list_mates"
    assert run.total_steps == 3
    reasons = [
        event["body"]["reason"] for event in events_of(run) if event["type"] == "turn.ended"
    ]
    assert reasons == ["max_steps", "end"]


# --- resume rule (e): a truncated turn ------------------------------------------------------------


def test_a_truncated_turn_is_reported_and_recorded_as_unresolved(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("half an ans", call("list_gaps"), end_reason="truncated")])

    reasons = [event["body"]["reason"] for event in events_of(run) if event["type"] == "turn.ended"]
    assert reasons == ["truncated"]
    truncated = [
        item
        for item in run.session.coverage.unresolved
        if item.check == runner.CLOSEOUT_CHECK and "output ceiling" in item.reason
    ]
    assert len(truncated) == 1


# --- resume rule (f): a provider failure still finalizes ------------------------------------------


def test_a_provider_exception_still_finalizes_and_writes_the_session(
    start: Callable[..., runner.ReviewRun],
) -> None:
    run = start([], provider=RaisingProvider())

    with pytest.raises(RuntimeError, match="connection dropped"):
        run.start()

    assert run.session.ended_at is not None
    written = written_session(run)
    assert written["ended_at"] is not None
    types = [event["type"] for event in events_of(run)]
    assert types[-3:] == ["error", "turn.ended", "session.ended"]
    error = [event for event in events_of(run) if event["type"] == "error"][0]
    assert error["body"]["error_class"] == "RuntimeError"
    assert error["body"]["retryable"] is True
    assert [
        event["body"]["reason"] for event in events_of(run) if event["type"] == "turn.ended"
    ] == ["error"]


# --- the written session --------------------------------------------------------------------------


def test_the_session_is_timed_and_written(review: Callable[..., runner.ReviewRun]) -> None:
    run = review([turn("done", call("list_gaps"))])

    session = run.session
    assert session.ended_at is not None
    assert session.ended_at >= session.started_at
    assert session.timing.unattended_runtime_minutes >= 0
    assert session.timing.baseline_minutes is None
    assert written_session(run)["design_id"] == "dsn:1"


def test_the_saved_session_validates_against_the_contract(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review(
        [
            turn(
                "done",
                call("get_package_summary"),
                call("get_component", component_id="cmp:9999"),
                drawing_finding("suspected"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
            )
        ],
        retry_of="6f1d1d6a-6c8a-4f29-9f3f-0b0f6f5b9e11",
    )

    session = run.session
    assert session.findings and session.coverage.failed and session.coverage.unresolved
    contract_validator("review-session.schema.json").validate(written_session(run))


def test_open_checklist_items_become_unresolved_coverage(
    review: Callable[..., runner.ReviewRun],
) -> None:
    from swreview.agent.checklist import load_checklist

    run = review(
        [
            turn(
                "done",
                drawing_finding("suspected"),
                call(
                    "mark_coverage",
                    check="interference",
                    bucket="skipped",
                    scope={},
                    reason="no interference results in this package",
                ),
            )
        ]
    )

    closed = {"drawing.manufacturing_inputs", "interference"}
    expected = [item.id for item in load_checklist().items if item.id not in closed]
    left_open = [
        item.check
        for item in run.session.coverage.unresolved
        if item.check != runner.EVIDENCE_CHECK
    ]
    assert left_open == expected


# --- run_review, the one-shot entry point ---------------------------------------------------------


def test_run_review_plays_one_turn_and_returns_the_session(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    provider = FakeProvider(script=[turn("done", call("list_gaps"))], model=MODEL)

    session = runner.run_review(tmp_package_dir, tmp_path / "out", provider=provider, effort=EFFORT)

    assert isinstance(session, ReviewSession)
    assert [step.tool for step in session.steps] == ["list_gaps"]
    assert (tmp_path / "out" / runner.SESSION_FILE_NAME).is_file()
    assert (tmp_path / "out" / runner.EVENTS_FILE_NAME).is_file()


# --- the live bridge and the exception store ------------------------------------------------------


class FakeBridge:
    """The two things the runner does with a bridge: hand it over, and close it."""

    def __init__(self, pipe_name: str, secret: str | None = None) -> None:
        self.pipe_name = pipe_name
        self.secret = secret
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_bridge_true_wires_a_client_into_the_context_and_the_tools(
    review: Callable[..., runner.ReviewRun],
) -> None:
    built: list[FakeBridge] = []

    def factory(pipe_name: str, secret: str | None) -> FakeBridge:
        built.append(FakeBridge(pipe_name, secret))
        return built[-1]

    run = review([turn("done")], bridge=True, bridge_factory=factory)

    assert [client.pipe_name for client in built] == ["swreview"]
    names = {tool.name for tool in run.tools}
    assert {"bridge_capture", "bridge_measure", "bridge_interference"} <= names
    assert run.context.bridge is built[0]

    run.close()
    assert built[0].closed


def test_the_sessions_bridge_secret_reaches_the_client(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """The pane sends `{pipe, secret}`; both halves have to arrive at the client (T049)."""
    built: list[FakeBridge] = []

    run = review(
        [turn("done")],
        bridge=True,
        pipe_name="swreview-abc",
        bridge_secret="s3cret",
        bridge_factory=lambda pipe_name, secret: built.append(FakeBridge(pipe_name, secret))
        or built[-1],
    )

    assert [(client.pipe_name, client.secret) for client in built] == [
        ("swreview-abc", "s3cret")
    ]
    run.close()


def test_without_the_bridge_there_is_none_and_no_bridge_tools(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("done")])

    names = {tool.name for tool in run.tools}
    assert not names & {"bridge_capture", "bridge_measure", "bridge_interference"}
    assert run.context.bridge is None


def test_run_review_closes_the_bridge_when_the_review_ends(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    built: list[FakeBridge] = []
    provider = FakeProvider(script=[turn("done")], model=MODEL)

    runner.run_review(
        tmp_package_dir,
        tmp_path / "out",
        provider=provider,
        effort=EFFORT,
        bridge=True,
        bridge_factory=lambda pipe_name, secret: built.append(FakeBridge(pipe_name, secret))
        or built[-1],
    )

    assert built[0].closed


def test_an_exceptions_file_beside_the_package_is_loaded(
    review: Callable[..., runner.ReviewRun], tmp_package_dir: Path
) -> None:
    (tmp_package_dir / "exceptions.json").write_text(
        json.dumps(
            {
                "exceptions": [
                    {
                        "id": "EX-001",
                        "check": "interference.static",
                        "component_persist_refs": ["Y21wOjAwMDE="],
                        "persist_ref_scopes": ["doc:1"],
                        "configuration": "Default",
                        "geometry_fingerprint": "0" * 64,
                        "accepted_by": "engineer",
                        "accepted_at": "2026-09-01T00:00:00Z",
                        "note": "press fit, intended",
                        "status": "active",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    run = review([turn("done", call("get_exceptions"))])

    assert run.session.steps[0].status == "ok"
    store = run.context.exception_store()
    assert store is not None
    assert [exception.id for exception in store.exceptions] == ["EX-001"]


def test_no_exceptions_file_means_no_exception_store(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("done", call("get_exceptions"))])

    assert run.context.exceptions is None
    assert run.session.steps[0].status == "ok"
