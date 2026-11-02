"""Unit tests for the provider-driven agent runner (T014).

The runner no longer owns a vendor SDK's tool loop: it drives an `AgentProvider` turn by
turn and owns everything around it - the step budget, the event stream, the session, and
the resume rules in `specs/002-task-pane-assistant/data-model.md` section 3. The scripted
`FakeProvider` stands in for a real adapter, so every path below is reachable without a
network call, a key, or a recorded exchange.

One test per resume rule, named after the rule it pins down:

- (a) a second finalization produces the same coverage, not duplicates;
- (b) an answered evidence request stops being unresolved coverage;
- (c) a check re-run after its blocking request is answered yields one verdict, keeping a
  decision whose verdict - status and severity - is unchanged and clearing, with a notice, one
  whose verdict changed (owner decisions 189A and 191A);
- (d) `max_steps` is a per-turn budget and the cumulative count is kept separately;
- (e) a turn the provider truncated is `turn.ended {reason: "truncated"}` plus unresolved
  coverage;
- (f) a provider exception still finalizes and still writes `session.json`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
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
from swreview.chat.sessions import record_disposition
from swreview.checks import part_roles
from swreview.checks.provenance import PROVENANCE_CHECK
from swreview.checks.thread_pitch import CHECK_FINE_PITCH
from swreview.findings import Disposition, Finding, build_finding
from swreview.ir.loader import save_package
from swreview.report.names import component_names
from swreview.report.session import ReviewSession
from swreview.report.titles import display_title, pane_finding, title_from
from tests.support.contracts import contract_validator
from tests.support.packages import build_package, persist_ref
from tests.support.roles_review import review_brief

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
            "content": f"{review_brief(run)}\n\n{runner.OPENING_MESSAGE}",
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
    # Edited deliberately by feature 013: setup announces provenance's checked row (T060) and,
    # a review with no profile being in the `absent` state, its bought-parts row ("Bought parts
    # were not told apart", part-roles.md section 7), both before the first round.
    assert [event["type"] for event in events][:7] == [
        "session.started",
        "coverage",
        "coverage",
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


SETUP_CHECKS = frozenset({PROVENANCE_CHECK, *part_roles.ROW_CHECKS})
"""The rows setup writes before any turn (feature 013): provenance's checked row (T060) and the
part roles' rows - with no profile, "Bought parts were not told apart" (part-roles.md 7)."""


def turn_coverage(run: runner.ReviewRun) -> list[dict[str, Any]]:
    """The `coverage` bodies the turn announced: every one but the rows setup wrote."""
    return [
        body for body in bodies_of(run, "coverage") if body["item"]["check"] not in SETUP_CHECKS
    ]


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

    # Edited deliberately by feature 013: the rows setup wrote are not the turn's (T060 and
    # the part roles), and finalization appends the close-out after the model's row (T117).
    announced = turn_coverage(run)
    assert [body["bucket"] for body in announced] == ["checked"]
    [recorded] = [
        item for item in run.session.coverage.checked
        if item.check == COVERAGE_ARGUMENTS["check"]
    ]
    assert announced[0]["item"] == recorded.model_dump(mode="json")


def test_a_failed_tool_call_announces_the_failed_coverage_it_wrote(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """The bucket the model cannot write itself reaches the pane the same way."""
    run = review([turn("done", call("list_gaps"))], fail_tool=("list_gaps",))

    announced = turn_coverage(run)
    assert [body["bucket"] for body in announced] == ["failed"]
    assert announced[0]["item"]["check"] == "tool.list_gaps"
    assert announced[0]["item"]["error"] == run.session.coverage.failed[0].error


def test_a_turn_cut_short_announces_the_unresolved_item_it_wrote(
    review: Callable[..., runner.ReviewRun],
) -> None:
    run = review([turn("cut short", call("list_gaps"), call("list_gaps"))], max_steps=1)

    announced = turn_coverage(run)
    assert [body["bucket"] for body in announced] == ["unresolved"]
    assert announced[0]["item"]["check"] == runner.CLOSEOUT_CHECK


def test_a_rerun_folded_onto_an_earlier_finding_is_reannounced_under_that_id(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """Resume rule (c) reuses the earlier id, so the stream has to say so.

    The re-run's finding is announced under the id it was allocated, and the fold is
    announced again under the id it was folded onto - a client keyed by finding id then
    ends on the same verdict `session.json` holds, titled as the pane shows it
    (`pane_finding`, decision 2A; the next test is the case where the two titles differ).
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
    assert announced[-1] == pane_finding(run.session.findings[0], component_names(run.context.ir))


LONG_DRAWING_OBSERVED = (
    "The drawing of cmp:0001 calls out the tapped hole without the usable thread depth, so the "
    "engagement of the screw cannot be judged from the sheet. Nothing else is missing."
)
"""A first sentence past 80 characters that names `housing-1` by its id (feature 009 T061)."""


def long_drawing_finding(status: str) -> ScriptedToolCall:
    arguments = {**DRAWING_FINDING_ARGUMENTS, "observed": LONG_DRAWING_OBSERVED, "status": status}
    return ScriptedToolCall(name="record_drawing_finding", arguments=arguments)


def test_every_finding_announcement_carries_the_title_a_person_reads(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """Decision 2A (feature 009 research R2.28): the stream is what the pane prints, so both
    announcements - the tool's and the runner's re-announcement of a fold - carry the whole,
    named title, while `session.json` keeps the recorded one the model read."""
    run = review(
        [
            turn(
                "blocked",
                long_drawing_finding("unresolved"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
            ),
            turn("resolved", long_drawing_finding("suspected")),
        ]
    )

    run.answer_evidence("ER-001", "The usable thread depth is 12 mm.")

    announced = bodies_of(run, "finding")
    names = component_names(run.context.ir)
    [recorded] = run.session.findings
    assert [body["id"] for body in announced] == ["F-001", "F-002", "F-001"]
    assert {body["title"] for body in announced} == {display_title(recorded, names)}
    assert announced[-1] == pane_finding(recorded, names)
    assert recorded.title == title_from(LONG_DRAWING_OBSERVED)
    assert written_session(run)["findings"][0]["title"] == title_from(LONG_DRAWING_OBSERVED)
    assert "housing-1" in announced[-1]["title"] and "…" not in announced[-1]["title"]


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
        "content": f"{review_brief(run)}\n\n{runner.OPENING_MESSAGE}",
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


def ask(what: str, entity_ids: list[str] | None = None) -> ScriptedToolCall:
    """One evidence request; each `what`, about its own entity, is its own request.

    Edited deliberately by feature 013 T064: each ask names its own entity, since the re-ask guard
    answers a model question naming the same parts with no checklist item from the earlier one
    (contracts/re-ask-guard.md section 3).
    """
    ids = EVIDENCE_ARGUMENTS["entity_ids"] if entity_ids is None else entity_ids
    return call("request_evidence", **{**EVIDENCE_ARGUMENTS, "what": what, "entity_ids": ids})


THREE_ASKS = (
    ask("the thread depth"),
    ask("the washer grade", ["fst:1"]),
    ask("the drawing revision", ["cmp:0002"]),
)


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
    # Edited deliberately by feature 013 T117: the close-out is code's now, so the model's own
    # row is on an item it owns.
    run = review(
        [
            turn(
                "done",
                call(
                    "mark_coverage",
                    check="interfaces.stack",
                    bucket="unresolved",
                    scope={},
                    reason="the package has no stack to close this out",
                ),
            )
        ]
    )

    run.finalize()

    stack = [
        item for item in run.session.coverage.unresolved if item.check == "interfaces.stack"
    ]
    assert len(stack) == 1
    assert "no stack" in stack[0].reason


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


def test_a_rerun_of_one_of_two_hole_pairs_on_the_same_components_keeps_each_its_verdict(
    tmp_path: Path,
) -> None:
    """Two `hole.coaxiality` findings on the same two components, with no tolerance, differ
    only by their holes (008 research R2.8): re-running the first pair folds onto the first
    and leaves the second pair's verdict where it was (owner decision 166A)."""
    template = build_package().holes[0]
    holes = [
        template.model_copy(
            update={"id": hole_id, "persist_ref": persist_ref(hole_id), "component_id": owner}
        )
        for hole_id, owner in (
            ("hol:0001", "cmp:0001"),
            ("hol:0002", "cmp:0001"),
            ("hol:0003", "cmp:0002"),
            ("hol:0004", "cmp:0002"),
        )
    ]
    package = tmp_path / "package"
    save_package(build_package(holes=holes, gaps=[]), package)
    first = call("check_hole_alignment", hole_id_a="hol:0001", hole_id_b="hol:0003")
    second = call("check_hole_alignment", hole_id_a="hol:0002", hole_id_b="hol:0004")
    asked = call(
        "request_evidence",
        what="The position tolerance of hol:0001 and hol:0003",
        why="hole.coaxiality needs it",
        entity_ids=["hol:0001", "hol:0003"],
    )
    run = runner.start_review(
        package,
        tmp_path / "out",
        provider=FakeProvider(
            script=[turn("blocked", first, second, asked), turn("re-run", first)], model=MODEL
        ),
        effort=EFFORT,
    )
    run.start()

    session = run.answer_evidence("ER-001", "There is none on the drawing.")

    assert [(finding.id, finding.inputs) for finding in session.findings] == [
        ("F-001", ["hol:0001", "hol:0003"]),
        ("F-002", ["hol:0002", "hol:0004"]),
    ]


def test_a_rerun_of_two_joints_on_the_same_components_keeps_each_its_verdict(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """Two joints across the same two components, with no drawing location, differ only by
    their hole instances as the joint map numbers them (`hol:0001#1`, `checks/joints.py`): a
    resumed turn's re-run of both folds each onto its own (008 T132)."""
    run = review([turn("nothing yet")])

    def joint(finding_id: str, number: int, status: str) -> Finding:
        return build_finding(
            finding_id=finding_id,
            check="hole.nominal_alignment",
            title=f"Joint {number}",
            status=status,  # type: ignore[arg-type]
            severity="medium",
            package=run.context.ir,
            configuration=run.context.ir.design.active_configuration,
            observed=f"joint {number} is {status}",
            requirement="the member axes meet within the joint's clearance",
            recommended_action="look again",
            component_ids=["cmp:0001", "cmp:0002"],
            inputs=[f"hol:0001#{number}", f"hol:0003#{number}"],
            coverage_limits=["the position tolerance is not on the drawing"],
            numeric=False,
        )

    session = run.session
    session.findings[:] = [
        joint("F-001", 1, "unresolved"),
        joint("F-002", 2, "unresolved"),
        joint("F-003", 1, "suspected"),
        joint("F-004", 2, "unresolved"),
    ]

    runner._reconcile_reruns(session, 2)

    assert [(finding.id, finding.inputs, finding.status) for finding in session.findings] == [
        ("F-001", ["hol:0001#1", "hol:0003#1"], "suspected"),
        ("F-002", ["hol:0001#2", "hol:0003#2"], "unresolved"),
    ]


@pytest.mark.parametrize(
    "place", [{"sheet": "Sheet1"}, {"annotation": "D3"}], ids=["sheet", "annotation"]
)
def test_a_rerun_citing_the_same_place_with_its_reference_yields_one_verdict(
    review: Callable[..., runner.ReviewRun], place: dict[str, str]
) -> None:
    """The model's citation of a sheet or an annotation first without and then with the
    persistent reference is one place: the re-run folds onto the finding it re-judges (008
    T132, T136)."""
    [locator] = place.values()

    def cited(status: str, **reference: str) -> ScriptedToolCall:
        return ScriptedToolCall(
            name="record_drawing_finding",
            arguments={
                **DRAWING_FINDING_ARGUMENTS,
                "source_refs": [{"document_id": "doc:2", **place, **reference}],
                "status": status,
            },
        )

    run = review(
        [
            turn(
                "blocked",
                cited("unresolved"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
            ),
            turn("resolved", cited("suspected", persist_ref=persist_ref(locator))),
        ]
    )

    session = run.answer_evidence("ER-001", "The usable thread depth is 12 mm.")

    assert [(finding.id, finding.status) for finding in session.findings] == [
        ("F-001", "suspected")
    ]


def test_a_rerun_citing_another_reference_alone_is_a_second_finding(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """A citation by persistent reference alone names its item by that reference, so another
    reference is another place and another finding (008 T132; owner decision 25A)."""

    def by_reference(seed: str, status: str) -> ScriptedToolCall:
        return ScriptedToolCall(
            name="record_drawing_finding",
            arguments={
                **DRAWING_FINDING_ARGUMENTS,
                "source_refs": [{"document_id": "doc:2", "persist_ref": persist_ref(seed)}],
                "status": status,
            },
        )

    run = review(
        [
            turn(
                "blocked",
                by_reference("note-1", "unresolved"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
            ),
            turn("and another note", by_reference("note-2", "suspected")),
        ]
    )

    session = run.answer_evidence("ER-001", "12 mm")

    assert [(finding.id, finding.status) for finding in session.findings] == [
        ("F-001", "unresolved"),
        ("F-002", "suspected"),
    ]


def on_the_pair(finding_id: str, *inputs: str, check: str = "hole.coaxiality") -> Finding:
    """A finding on `cmp:0001` and `cmp:0002` that only its entity ids tell from its siblings."""
    package = build_package()
    return build_finding(
        finding_id=finding_id,
        check=check,
        title="Holes on the pair",
        status="unresolved",
        severity="medium",
        package=package,
        configuration=package.design.active_configuration,
        observed="the hole axes are not shown to meet",
        requirement="the member axes meet within the joint's clearance",
        recommended_action="look again",
        component_ids=["cmp:0001", "cmp:0002"],
        inputs=list(inputs),
        coverage_limits=["the position tolerance is not on the drawing"],
        numeric=False,
    )


def test_a_restated_finding_on_other_holes_re_judges_no_earlier_finding() -> None:
    """The regrade only drops a finding's newly bought sources, so a restated finding about
    other holes of the same components takes neither the earlier finding's id nor its
    disposition (008 T134)."""
    earlier = [on_the_pair("F-001", "hol:0004", "hol:0010")]
    restated = [on_the_pair("F-009", "hol:0017", "hol:0027")]

    assert runner._restated_targets(earlier, restated) == {}


def test_a_restated_finding_that_lost_a_bought_source_re_judges_the_earlier_one() -> None:
    """The regrade left the fastener and dropped the newly bought tapped hole: the restated
    finding's entity ids are a subset of the earlier one's (58A; 008 T133, T134)."""
    earlier = [on_the_pair("F-001", "fst:0001", "hol:0004", check=CHECK_FINE_PITCH)]
    restated = [on_the_pair("F-009", "fst:0001", check=CHECK_FINE_PITCH)]

    assert runner._restated_targets(earlier, restated) == {0: 0}


def test_a_restated_finding_with_the_same_entity_ids_re_judges_its_own_earlier_one() -> None:
    """Equal entity ids match through the verdict key, so two siblings that share the key less
    their entity ids each find their own (166A; 008 T134)."""
    earlier = [
        on_the_pair("F-001", "hol:0004", "hol:0010"),
        on_the_pair("F-002", "hol:0017", "hol:0027"),
    ]
    restated = [
        on_the_pair("F-009", "hol:0017", "hol:0027"),
        on_the_pair("F-010", "hol:0004", "hol:0010"),
    ]

    assert runner._restated_targets(earlier, restated) == {0: 1, 1: 0}


def test_two_earlier_findings_a_restated_one_could_narrow_leave_it_unmatched() -> None:
    """Two unmatched earlier findings share the key less their entity ids, each with its own
    disposition, and the restated finding narrows either: which it re-judges is unknown, so it
    takes neither id nor disposition (58A; 008 T136)."""
    when = datetime(2026, 10, 31, tzinfo=UTC)
    earlier = [
        on_the_pair("F-001", "fst:0001", "hol:0004", check=CHECK_FINE_PITCH).model_copy(
            update={"disposition": Disposition(decision="accepted", note="meant", by="a", at=when)}
        ),
        on_the_pair("F-002", "fst:0001", "hol:0010", check=CHECK_FINE_PITCH).model_copy(
            update={"disposition": Disposition(decision="rejected", note="a slip", by="a", at=when)}
        ),
    ]
    restated = [on_the_pair("F-009", "fst:0001", check=CHECK_FINE_PITCH)]

    assert runner._restated_targets(earlier, restated) == {}


def test_two_restated_findings_that_could_narrow_one_earlier_finding_take_nothing() -> None:
    """The mirror: two unmatched restated findings each narrow the one earlier finding, so
    neither takes it (008 T136)."""
    earlier = [on_the_pair("F-001", "fst:0001", "hol:0004", check=CHECK_FINE_PITCH)]
    restated = [
        on_the_pair("F-009", "fst:0001", check=CHECK_FINE_PITCH),
        on_the_pair("F-010", "hol:0004", check=CHECK_FINE_PITCH),
    ]

    assert runner._restated_targets(earlier, restated) == {}


def test_a_resumed_turn_on_another_hole_pair_of_the_same_components_is_a_second_finding(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """In a resumed turn a finding on other holes of the same two components is the model
    checking something else: it never takes the earlier pair's id (166A; 008 T136)."""
    run = review([turn("nothing yet")])
    session = run.session
    session.findings[:] = [
        on_the_pair("F-001", "hol:0004", "hol:0010"),
        on_the_pair("F-002", "hol:0017", "hol:0027"),
    ]

    runner._reconcile_reruns(session, 1)

    assert [(finding.id, finding.inputs) for finding in session.findings] == [
        ("F-001", ["hol:0004", "hol:0010"]),
        ("F-002", ["hol:0017", "hol:0027"]),
    ]


# --- resume rule (c) and a decision: owner decisions 189A and 191A (002 T326) -------------------

ENGINEER = "FICT-ENG"
"""Who the decisions below are recorded by: a fictional engineer."""

DECIDED = Disposition(
    decision="accepted",
    note="FICT intended",
    by=ENGINEER,
    at=datetime(2026, 11, 1, 9, 0, tzinfo=UTC),
    triage="already_known",
)
"""An Accept with its triage, recorded on a finding before an answer resumed the turn."""

CLEARED_LINE = (
    "The check ran again after your answer and its verdict changed, so your Accept (real but "
    "already known) was cleared. Decide again."
)
"""The words file's line for an Accept recorded as `already_known` that a re-run cleared."""


def decided_before_the_answer(
    review: Callable[..., runner.ReviewRun], rerun_status: str
) -> tuple[runner.ReviewRun, Disposition]:
    """A drawing finding recorded `suspected` (medium) beside an evidence request, accepted as
    `already_known` through the live route while the request is open; then the request is
    answered and the resumed turn records the finding again as `rerun_status`: `suspected`, the
    verdict decided, or `unresolved`, another status and severity (low). Returns the run and the
    disposition recorded before the answer."""
    run = review(
        [
            turn(
                "blocked",
                drawing_finding("suspected"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
            ),
            turn("re-run", drawing_finding(rerun_status)),
        ]
    )
    recorded = record_disposition(
        run, "F-001", decision="accepted", note="FICT intended", by=ENGINEER, triage="already_known"
    ).disposition
    assert recorded is not None
    run.answer_evidence("ER-001", "The usable thread depth is 12 mm.")
    return run, recorded


def judged(
    finding_id: str, status: str = "unresolved", severity: str = "medium", **fields: Any
) -> Finding:
    """`on_the_pair`'s finding on `hol:0004` and `hol:0010`, with this verdict and these fields:
    every one of them folds onto every other in a resumed turn."""
    return on_the_pair(finding_id, "hol:0004", "hol:0010").model_copy(
        update={"status": status, "severity": severity, **fields}
    )


def test_a_check_rerun_after_an_answer_keeps_the_decision_and_its_triage(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """Owner decisions 189A and 191A: the re-run's status and severity are the ones decided, so
    the fold keeps the whole disposition - decision, triage, note, engineer and time - as a
    restated finding keeps it (58A); its re-announcement carries it, and nothing is cleared."""
    run, recorded = decided_before_the_answer(review, "suspected")

    [folded] = run.session.findings
    assert (folded.id, folded.status, folded.severity) == ("F-001", "suspected", "medium")
    assert folded.disposition == recorded
    assert recorded.triage == "already_known"
    announced = bodies_of(run, "finding")
    assert [body["id"] for body in announced] == ["F-001", "F-002", "F-001"]
    assert announced[-1]["disposition"] == recorded.model_dump(mode="json")
    assert bodies_of(run, "disposition.cleared") == []


def test_a_check_rerun_with_another_verdict_clears_the_decision_and_says_so(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """Owner decisions 189A and 191A: the re-run changed the status and the severity, so the
    folded finding carries no disposition, and right after the fold's `finding` event one
    `disposition.cleared` names the finding, the disposition cleared and the line the card
    prints, which names the decision and its triage and asks for a new decision."""
    run, recorded = decided_before_the_answer(review, "unresolved")

    [folded] = run.session.findings
    assert (folded.id, folded.status, folded.severity) == ("F-001", "unresolved", "low")
    assert folded.disposition is None
    events = events_of(run)
    refolded = max(
        index
        for index, event in enumerate(events)
        if event["type"] == "finding" and event["body"]["id"] == "F-001"
    )
    assert events[refolded]["body"]["disposition"] is None
    cleared = [
        (index, event["body"])
        for index, event in enumerate(events)
        if event["type"] == "disposition.cleared"
    ]
    assert cleared == [
        (
            refolded + 1,
            {
                "finding_id": "F-001",
                "disposition": recorded.model_dump(mode="json"),
                "reason": CLEARED_LINE,
            },
        )
    ]


@pytest.mark.parametrize(
    ("status", "severity"),
    [("unresolved", "high"), ("suspected", "medium")],
    ids=["severity", "status"],
)
def test_a_rerun_that_changes_only_the_status_or_only_the_severity_clears_the_decision(
    review: Callable[..., runner.ReviewRun], status: str, severity: str
) -> None:
    """Owner decision 191A: a changed verdict is a changed status or severity, so either alone
    clears the decision and its triage, and the fold names the disposition it cleared.

    *Changed 2026-11-01 on purpose (002 T340; the backlog's cycle 3 section):* each fold names
    the id its re-run was first announced under, F-002, which the stream withdraws.

    *Changed again 2026-11-01 on purpose (cycle 6's Tier 1 review):* the decision cleared is named
    by the finding as decided, F-001 whole, not its id and disposition alone, since its status
    words a pass's triage in the line."""
    run = review([turn("nothing yet")])
    session = run.session
    decided = judged("F-001", disposition=DECIDED)
    session.findings[:] = [decided, judged("F-002", status, severity)]

    returned = runner._reconcile_reruns(session, 1)

    assert [
        (finding.id, finding.status, finding.severity, finding.disposition)
        for finding in session.findings
    ] == [("F-001", status, severity, None)]
    assert returned == ([("F-002", session.findings[0])], [decided])


def test_a_rerun_that_changes_neither_keeps_the_whole_disposition(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """Owner decision 191A: a re-run with the status and the severity decided keeps the whole
    disposition - decision, triage, note, engineer and time - though what it observed reads
    otherwise, and clears nothing.

    *Changed 2026-11-01 on purpose (002 T340; the backlog's cycle 3 section):* the fold names
    the id its re-run was first announced under, F-002, which the stream withdraws."""
    run = review([turn("nothing yet")])
    session = run.session
    observed = "FICT the axes now read further apart"
    session.findings[:] = [
        judged("F-001", disposition=DECIDED),
        judged("F-002", observed=observed),
    ]

    returned = runner._reconcile_reruns(session, 1)

    assert [
        (finding.id, finding.observed, finding.disposition) for finding in session.findings
    ] == [("F-001", observed, DECIDED)]
    assert returned == ([("F-002", session.findings[0])], [])


@pytest.mark.parametrize(
    ("first", "last", "kept"),
    [("suspected", "unresolved", True), ("unresolved", "suspected", False)],
    ids=["back-to-the-verdict-decided", "changed-last"],
)
def test_two_reruns_of_one_finding_are_judged_against_the_finding_as_decided(
    review: Callable[..., runner.ReviewRun], first: str, last: str, kept: bool
) -> None:
    """Of two re-runs in one resumed turn that fold onto one decided finding, the last alone
    says whether the decision stands: each is compared with the finding as decided, never with
    the re-run before it, so one back to the verdict decided keeps the disposition and one
    changed last clears it, named once.

    *Changed 2026-11-01 on purpose (002 T340; the backlog's cycle 3 section):* each fold names
    the id its re-run was first announced under, which the stream withdraws.

    *Changed again 2026-11-01 on purpose (cycle 6's Tier 1 review):* the decision cleared is named
    by the finding as decided, F-001 whole, not its id and disposition alone, since its status
    words a pass's triage in the line."""
    run = review([turn("nothing yet")])
    session = run.session
    decided = judged("F-001", disposition=DECIDED)
    session.findings[:] = [decided, judged("F-002", first), judged("F-003", last)]

    folded, cleared = runner._reconcile_reruns(session, 1)

    [final] = session.findings
    assert (final.id, final.status) == ("F-001", last)
    assert final.disposition == (DECIDED if kept else None)
    assert [(spent, finding.id) for spent, finding in folded] == [
        ("F-002", "F-001"),
        ("F-003", "F-001"),
    ]
    assert folded[-1][1] == final
    assert cleared == ([] if kept else [decided])


@pytest.mark.parametrize(
    "rerun_status", ["suspected", "unresolved"], ids=["same-verdict", "another-verdict"]
)
def test_a_check_rerun_of_an_undecided_finding_folds_as_before(
    review: Callable[..., runner.ReviewRun], rerun_status: str
) -> None:
    """A finding nobody decided folds as it always has, whichever its re-run's verdict, and
    nothing is cleared."""
    run = review(
        [
            turn(
                "blocked",
                drawing_finding("suspected"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
            ),
            turn("re-run", drawing_finding(rerun_status)),
        ]
    )

    session = run.answer_evidence("ER-001", "The usable thread depth is 12 mm.")

    assert [
        (finding.id, finding.status, finding.disposition) for finding in session.findings
    ] == [("F-001", rerun_status, None)]
    assert [body["id"] for body in bodies_of(run, "finding")] == ["F-001", "F-002", "F-001"]
    assert bodies_of(run, "disposition.cleared") == []


def test_a_cleared_decisions_notice_validates_against_the_events_contract(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """The `disposition.cleared` event is in chat-events.schema.json, and the run that writes
    it writes nothing the contract refuses."""
    run, _ = decided_before_the_answer(review, "unresolved")

    validator = contract_validator("chat-events.schema.json")
    events = events_of(run)
    for event in events:
        validator.validate(event)
    assert [event["type"] for event in events].count("disposition.cleared") == 1


# --- the re-run fixes on the card: owner decisions 193A and 194A (002 T340) ----------------------

FOLDED_REASON = "a second verdict on what {id} judges, shown as {id}"
"""Why the id a re-run or restated finding was first announced under is withdrawn once it folds."""

RESTATED_LINE = (
    "Your answer graded the checks again and this verdict changed, so your Accept (real but "
    "already known) was cleared. Decide again."
)
"""The words file's line for an Accept recorded as `already_known` that a restate cleared."""


def standing(events: Sequence[Mapping[str, Any]]) -> set[str]:
    """The finding ids a reader of the stream holds at its end: every id a `finding` event
    announced and no later `finding.withdrawn` dropped."""
    held: set[str] = set()
    for event in events:
        if event["type"] == "finding":
            held.add(event["body"]["id"])
        elif event["type"] == "finding.withdrawn":
            held.discard(event["body"]["finding_id"])
    return held


def on_sheet(sheet: str, status: str) -> ScriptedToolCall:
    """`drawing_finding` cited on `sheet`: another place, so a finding of its own."""
    return ScriptedToolCall(
        name="record_drawing_finding",
        arguments={
            **DRAWING_FINDING_ARGUMENTS,
            "sheet": sheet,
            "source_refs": [{"document_id": "doc:2", "sheet": sheet}],
            "status": status,
        },
    )


def test_a_folded_reruns_own_id_is_withdrawn_before_the_fold_is_announced(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """The backlog's cycle 3 section (FR-031: the stream MUST agree with the fold): the tool layer
    announced the re-run under its own id, F-002, and the fold put it under F-001, so F-002 is
    withdrawn - naming F-001, the id it folded onto - right before F-001's `finding` event. A
    reader of the stream then holds exactly the ids the session holds, and every event validates
    against the contract."""
    run, _ = decided_before_the_answer(review, "unresolved")

    events = events_of(run)
    refolded = max(
        index
        for index, event in enumerate(events)
        if event["type"] == "finding" and event["body"]["id"] == "F-001"
    )
    withdrawal = events[refolded - 1]
    assert (withdrawal["type"], withdrawal["body"]) == (
        "finding.withdrawn",
        {
            "finding_id": "F-002",
            "reason": FOLDED_REASON.format(id="F-001"),
            "folded_into": "F-001",
        },
    )
    assert standing(events) == {finding.id for finding in run.session.findings} == {"F-001"}
    validator = contract_validator("chat-events.schema.json")
    for event in events:
        validator.validate(event)


def test_several_folds_at_once_announce_every_finding_before_any_cleared_line(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """The backlog's cycle 3 section (its tests): two decided findings fold in one resumed turn -
    Sheet1's Accept with its triage, run again with the verdict decided, and Sheet2's Defer with
    no triage, run again with another verdict. The Accept stands whole; the Defer is cleared and
    its line names it with no triage, exactly; and every `finding` and `finding.withdrawn` the
    folds write comes before every `disposition.cleared`."""
    run = review(
        [
            turn(
                "blocked",
                on_sheet("Sheet1", "suspected"),
                on_sheet("Sheet2", "suspected"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
            ),
            turn("re-run", on_sheet("Sheet1", "suspected"), on_sheet("Sheet2", "unresolved")),
        ]
    )
    accepted = record_disposition(
        run, "F-001", decision="accepted", note="FICT intended", by=ENGINEER, triage="already_known"
    ).disposition
    deferred = record_disposition(
        run, "F-002", decision="deferred", note="FICT later", by=ENGINEER
    ).disposition
    assert accepted is not None and deferred is not None and deferred.triage is None
    mark = len(events_of(run))

    run.answer_evidence("ER-001", "The usable thread depth is 12 mm.")

    assert [(finding.id, finding.disposition) for finding in run.session.findings] == [
        ("F-001", accepted),
        ("F-002", None),
    ]
    after = events_of(run)[mark:]
    kinds = [event["type"] for event in after]
    cleared = [event["body"] for event in after if event["type"] == "disposition.cleared"]
    assert cleared == [
        {
            "finding_id": "F-002",
            "disposition": deferred.model_dump(mode="json"),
            "reason": (
                "The check ran again after your answer and its verdict changed, so your Defer "
                "was cleared. Decide again."
            ),
        }
    ]
    last_fold = max(
        index for index, kind in enumerate(kinds) if kind in ("finding", "finding.withdrawn")
    )
    assert last_fold < kinds.index("disposition.cleared")
    assert standing(events_of(run)) == {"F-001", "F-002"}


def test_two_earlier_findings_with_one_verdict_key_take_no_rerun(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """The backlog's cycle 3 section: an ordinary turn's duplicates are left as recorded, so two
    earlier findings can share a verdict key. Which one a re-run judges again is unknown, so it
    folds onto neither and stays a finding of its own, and both decisions stand, as
    `_restated_targets` takes neither when either could be re-judged (008 T136)."""
    run = review([turn("nothing yet")])
    session = run.session
    rejected = DECIDED.model_copy(update={"decision": "rejected", "triage": "wrong"})
    session.findings[:] = [
        judged("F-001", disposition=DECIDED),
        judged("F-002", disposition=rejected),
        judged("F-003", "suspected", "high"),
    ]

    returned = runner._reconcile_reruns(session, 2)

    assert [
        (finding.id, finding.status, finding.disposition) for finding in session.findings
    ] == [
        ("F-001", "unresolved", DECIDED),
        ("F-002", "unresolved", rejected),
        ("F-003", "suspected", None),
    ]
    assert returned == ([], [])


@pytest.mark.parametrize(
    ("status", "severity", "kept"),
    [("unresolved", "medium", True), ("suspected", "medium", False), ("unresolved", "high", False)],
    ids=["neither", "status", "severity"],
)
def test_a_restate_keeps_or_clears_a_decision_as_a_rerun_does(
    review: Callable[..., runner.ReviewRun], status: str, severity: str, kept: bool
) -> None:
    """Owner decision 194A: 191A's rule governs 58A's restate. F-002, restated, re-judges the
    decided F-001 (`_restated_targets`, its verdict key): with the status and severity decided the
    fold keeps the whole disposition, and with either changed it clears it and the card says so,
    the line naming the restate. Either way F-002, which the restated call announced under its own
    id, is withdrawn with `folded_into` right before F-001's `finding` event."""
    run = review([turn("nothing yet")])
    run.session.findings[:] = [
        judged("F-001", disposition=DECIDED),
        judged("F-002", status, severity),
    ]
    mark = len(events_of(run))

    stale = run._reconcile_restated(1, {}, [], {})

    [restated] = run.session.findings
    assert (restated.id, restated.status, restated.severity) == ("F-001", status, severity)
    assert restated.disposition == (DECIDED if kept else None)
    assert stale == []
    after = [(event["type"], event["body"]) for event in events_of(run)[mark:]]
    assert after[0] == (
        "finding.withdrawn",
        {"finding_id": "F-002", "reason": FOLDED_REASON.format(id="F-001"), "folded_into": "F-001"},
    )
    assert (after[1][0], after[1][1]["id"], after[1][1]["disposition"]) == (
        "finding",
        "F-001",
        DECIDED.model_dump(mode="json") if kept else None,
    )
    assert after[2:] == (
        []
        if kept
        else [
            (
                "disposition.cleared",
                {
                    "finding_id": "F-001",
                    "disposition": DECIDED.model_dump(mode="json"),
                    "reason": RESTATED_LINE,
                },
            )
        ]
    )


# --- a pass's miss in the cleared line: cycle 6's Tier 1 review --------------------------------

MISSED = DECIDED.model_copy(
    update={"decision": "rejected", "note": "FICT a miss", "triage": "wrong"}
)
"""A pass rejected and judged wrong: a miss (owner decision 187A)."""


def test_a_rerun_that_clears_a_passs_miss_words_it_as_the_passs_card_does(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """Owner decision 187A: a pass's `wrong` is a miss, and the pass's card words it "wrong: a
    miss" (`labels.pass_triage`), never the false alarm a flagged finding's "wrong" is. A pass
    rejected as a miss is run again after the answer as a flagged finding, so its decision is
    cleared, and the line names the miss as the pass's card does."""
    run = review(
        [
            turn(
                "blocked",
                drawing_finding("suspected"),
                call("request_evidence", **EVIDENCE_ARGUMENTS),
            ),
            turn("re-run", drawing_finding("suspected")),
        ]
    )
    run.session.findings[0] = run.session.findings[0].model_copy(
        update={"status": "checked_within_scope", "severity": "info"}
    )
    recorded = record_disposition(
        run, "F-001", decision="rejected", note="FICT a miss", by=ENGINEER, triage="wrong"
    ).disposition
    assert recorded is not None

    run.answer_evidence("ER-001", "The usable thread depth is 12 mm.")

    assert bodies_of(run, "disposition.cleared") == [
        {
            "finding_id": "F-001",
            "disposition": recorded.model_dump(mode="json"),
            "reason": (
                "The check ran again after your answer and its verdict changed, so your Reject "
                "(wrong: a miss) was cleared. Decide again."
            ),
        }
    ]


def test_a_restate_that_clears_a_passs_miss_words_it_as_the_passs_card_does(
    review: Callable[..., runner.ReviewRun],
) -> None:
    """Owner decisions 187A and 194A: a pass rejected as a miss, restated as a flagged finding,
    loses its decision, and the restate's line names the miss as the pass's card does."""
    run = review([turn("nothing yet")])
    run.session.findings[:] = [
        judged("F-001", "checked_within_scope", "info", disposition=MISSED),
        judged("F-002"),
    ]

    run._reconcile_restated(1, {}, [], {})

    assert bodies_of(run, "disposition.cleared") == [
        {
            "finding_id": "F-001",
            "disposition": MISSED.model_dump(mode="json"),
            "reason": (
                "Your answer graded the checks again and this verdict changed, so your Reject "
                "(wrong: a miss) was cleared. Decide again."
            ),
        }
    ]


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

    # Edited deliberately by feature 013 T060 and T117: code closes provenance before the turn
    # and the close-out when the review ends.
    closed = {
        "drawing.manufacturing_inputs", "interference", PROVENANCE_CHECK, runner.CLOSEOUT_CHECK,
    }
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
