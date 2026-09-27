"""Every model answer carries its basis line (feature 013 T107, `contracts/sources.md` section 3).

The runner keeps a step marker. It wraps the provider's `on_event`, so every `text.done` body
becomes `{text, basis}`, with `basis` computed by `report/sources.answer_basis` from the session's
steps since the marker - never from the model's text. The marker advances when a turn that
answered ends, so:

- turn 1 counts the pre-run's checks, recorded before it;
- an answer turn counts the checks `_restate` ran after the engineer's answer;
- a turn that ended without an answer (stopped) rolls its steps into the next answer;
- the explanation pass never reaches the sink, so it gets no basis.

The sitting's follow-up turn called no tool and read as a drawing review; its basis says it is
general guidance and that no drawing was read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
from swreview.agent.providers.fake import ScriptedToolCall, ScriptedTurn
from swreview.agent.settings import EfficiencySettings
from swreview.report.sources import READ_EXCLUDED
from tests.support.contracts import contract_validator
from tests.support.roles_review import roles_review

Events = list[tuple[str, dict[str, Any]]]

GENERAL = "No evidence was read for this answer: this is general guidance."
NO_DRAWING = " No drawing was read in this review."
ONE_READ = "Based on 1 result read for this answer."
SUMMARY = ScriptedToolCall("get_package_summary")
"""One read: the package census."""


def many_reads(n: int) -> str:
    return f"Based on {n} results read for this answer."


def answers(events: Events) -> list[dict[str, Any]]:
    """The `text.done` bodies, in stream order."""
    return [body for kind, body in events if kind == "text.done"]


def reads(run: runner.ReviewRun, steps: slice) -> int:
    """The results a slice of the session's steps read: ok, and not a writer or bookkeeping."""
    return sum(
        1
        for step in run.session.steps[steps]
        if step.status == "ok" and step.tool not in READ_EXCLUDED
    )


# --- 1. the line on every answer -----------------------------------------------------------------


def test_an_answer_that_read_one_result_says_so(tmp_path: Path) -> None:
    events: Events = []
    run = roles_review(
        tmp_path,
        turns=(ScriptedTurn(text="one read", tool_calls=(SUMMARY,)),),
        profile=None,
        events=events,
    )
    run.start()

    assert answers(events) == [{"text": "one read", "basis": ONE_READ + NO_DRAWING}]


def test_the_sittings_follow_up_that_called_no_tool_is_general_guidance(tmp_path: Path) -> None:
    events: Events = []
    run = roles_review(
        tmp_path,
        turns=(
            ScriptedTurn(text="reviewed", tool_calls=(SUMMARY,)),
            ScriptedTurn(text="Here is some general advice."),
        ),
        profile=None,
        events=events,
    )
    run.start()
    run.continue_session("drawing feedback?")

    follow_up = answers(events)[-1]
    assert follow_up == {
        "text": "Here is some general advice.",
        "basis": GENERAL + NO_DRAWING,
    }


def test_writers_and_bookkeeping_are_not_reads(tmp_path: Path) -> None:
    events: Events = []
    run = roles_review(
        tmp_path,
        turns=(
            ScriptedTurn(
                text="marked",
                tool_calls=(
                    ScriptedToolCall("get_review_checklist"),
                    ScriptedToolCall(
                        "mark_coverage",
                        {
                            "check": "fasteners",
                            "bucket": "unresolved",
                            "scope": {},
                            "reason": "no fastener was read",
                        },
                    ),
                ),
            ),
        ),
        profile=None,
        events=events,
    )
    run.start()

    assert answers(events)[-1]["basis"] == GENERAL + NO_DRAWING


def test_a_failed_step_is_not_a_read(tmp_path: Path) -> None:
    events: Events = []
    run = roles_review(
        tmp_path,
        turns=(
            ScriptedTurn(
                text="one failed",
                tool_calls=(
                    ScriptedToolCall("get_component", {"component_id": "cmp:9999"}),
                    SUMMARY,
                ),
            ),
        ),
        profile=None,
        events=events,
    )
    run.start()

    assert [step.status for step in run.session.steps] == ["error", "ok"]
    assert answers(events)[-1]["basis"] == ONE_READ + NO_DRAWING


# --- 2. the marker: turn 1, the answer turn, a stopped turn --------------------------------------


def test_turn_one_counts_the_pre_runs_checks(tmp_path: Path) -> None:
    events: Events = []
    run = roles_review(
        tmp_path,
        turns=(ScriptedTurn(text="from the digest"),),
        profile=None,
        events=events,
        efficiency=EfficiencySettings(prerun_checks=True),
    )
    prerun_reads = reads(run, slice(None))
    assert prerun_reads > 1  # the pre-run recorded its checks before turn 1

    run.start()

    assert answers(events) == [
        {"text": "from the digest", "basis": many_reads(prerun_reads) + NO_DRAWING}
    ]


def test_each_answer_counts_only_its_own_turns_steps(tmp_path: Path) -> None:
    events: Events = []
    run = roles_review(
        tmp_path,
        turns=(
            ScriptedTurn(
                text="first",
                tool_calls=(
                    SUMMARY,
                    ScriptedToolCall("list_components"),
                ),
            ),
            ScriptedTurn(text="second", tool_calls=(SUMMARY,)),
        ),
        profile=None,
        events=events,
    )
    run.start()
    run.continue_session("and?")

    assert [body["basis"] for body in answers(events)] == [
        many_reads(2) + NO_DRAWING,
        ONE_READ + NO_DRAWING,
    ]


def test_a_stopped_turns_steps_roll_into_the_next_answer(tmp_path: Path) -> None:
    events: Events = []
    run = roles_review(
        tmp_path,
        turns=(
            ScriptedTurn(
                text="",
                tool_calls=(SUMMARY,),
                end_reason="stopped",
            ),
            ScriptedTurn(text="after the stop", tool_calls=(ScriptedToolCall("list_components"),)),
        ),
        profile=None,
        events=events,
    )
    run.start()
    assert answers(events) == []  # the stopped turn gave no answer

    run.continue_session("go on")

    assert answers(events) == [{"text": "after the stop", "basis": many_reads(2) + NO_DRAWING}]


def test_the_answer_turn_counts_the_checks_restated_after_the_answer(tmp_path: Path) -> None:
    events: Events = []
    run = roles_review(
        tmp_path,
        turns=(ScriptedTurn(text="graded"), ScriptedTurn(text="resumed")),
        events=events,
        efficiency=EfficiencySettings(prerun_checks=True),
    )
    run.start()
    answered_through = len(run.session.steps)

    run.answer_evidence_batch([("ER-001", "All bought")])

    restated = reads(run, slice(answered_through, None))
    assert restated > 0  # the regrade restated the role-reading checks as recorded steps
    expected = ONE_READ if restated == 1 else many_reads(restated)
    assert answers(events)[-1] == {"text": "resumed", "basis": expected + NO_DRAWING}


# --- 3. what gets no basis -----------------------------------------------------------------------


def test_the_explanation_pass_gets_no_basis_and_adds_no_answer(tmp_path: Path) -> None:
    events: Events = []
    run = roles_review(
        tmp_path,
        turns=(ScriptedTurn(text="reviewed"),),
        events=events,
        efficiency=EfficiencySettings(prerun_checks=True),
        explain_findings=True,
    )
    run.start()

    assert [body["text"] for body in answers(events)] == ["reviewed"]
    assert all("basis" in body for body in answers(events))


def test_a_delta_carries_no_basis(tmp_path: Path) -> None:
    events: Events = []
    run = roles_review(
        tmp_path, turns=(ScriptedTurn(text="two words"),), profile=None, events=events
    )
    run.start()

    deltas = [body for kind, body in events if kind == "text.delta"]
    assert deltas and all(set(body) == {"text"} for body in deltas)


# --- 4. the contract ----------------------------------------------------------------------------


def _event(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    return {"seq": 1, "at": "2026-09-27T09:00:00+00:00", "type": kind, "body": body}


def test_basis_is_optional_on_text_done_in_the_schema() -> None:
    validator = contract_validator("chat-events.schema.json")
    validator.validate(_event("text.done", {"text": "answer", "basis": GENERAL}))
    validator.validate(_event("text.done", {"text": "an older answer"}))


@pytest.mark.parametrize(
    "event",
    [
        _event("text.done", {"text": "answer", "basis": 3}),
        _event("text.delta", {"text": "a", "basis": GENERAL}),
    ],
    ids=["basis-not-a-string", "basis-on-a-delta"],
)
def test_a_basis_the_contract_forbids_fails(event: dict[str, Any]) -> None:
    validator = contract_validator("chat-events.schema.json")
    with pytest.raises(Exception):  # noqa: B017 - jsonschema's ValidationError
        validator.validate(event)


def test_every_event_of_a_basis_run_validates(tmp_path: Path) -> None:
    events: Events = []
    run = roles_review(
        tmp_path,
        turns=(ScriptedTurn(text="one read", tool_calls=(SUMMARY,)),),
        profile=None,
        events=events,
    )
    run.start()

    validator = contract_validator("chat-events.schema.json")
    for seq, (kind, body) in enumerate(events, start=1):
        validator.validate({**_event(kind, body), "seq": seq})
