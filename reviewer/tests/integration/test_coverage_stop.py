"""Lever 7 end to end (T081): the stop fires, and the session survives it.

**Why this test is an OpenAI recorded-client test and not a `FakeProvider` one.** The stop
is mechanism C - the tools are withdrawn for the *next* round, `tool_choice: "none"` on
OpenAI and `FunctionCallingConfigMode.NONE` on Gemini - and the whole reason C was chosen
over mechanism A (raising out of `ToolSet.call`, the way `StoppableTools` does for Stop) is
what it leaves behind in the history: every `function_call` still has its matching
`function_call_output`, so the session can be continued and an evidence request answered
afterwards. A scripted provider has no round loop, no request body and no history rule to
break, so **the fake cannot tell the two mechanisms apart** - it would pass against the
implementation that silently breaks `answer_evidence` on the next request.

So the Responses endpoint is replayed through `respx`, and the stand-in honours exactly one
field: `tool_choice: "none"` means the next response is a message rather than the next
scripted call. A flat list of canned responses would return the same rounds in both arms
and the test would pass with no lever at all; `Service` below is the smallest thing that
makes the two arms actually differ.

**One script, two arms.** Ten `mark_coverage(bucket="checked")` rounds close the ten
checklist items, and the script then holds one more call. Flag off, that call runs and
there is a step for it. Flag on, the round that would have carried it goes out with the
tools withdrawn, the model writes its closing message, and the turn ends `end` through the
existing path.

No `pytest.mark.integration`: that marker means "needs a saved native evidence package"
and `tests/conftest.py` skips the whole marker when one is absent. This test needs no
native package and no key - it integrates the runner, the real tool registry and the real
OpenAI adapter over a replayed transport - so marking it would only mean never running it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import httpx
import respx
from google.genai import types

from swreview.agent import runner
from swreview.agent.checklist import load_checklist
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.providers.openai_provider import OpenAIProvider
from swreview.agent.settings import EfficiencySettings, efficiency_from_levers
from swreview.tools.registry import ToolDispatch
from tests.support.toolsets import toolset
from tests.unit.test_gemini_provider import FakeTool, call_part, chunk, text_part
from tests.unit.test_gemini_provider import build as build_gemini
from tests.unit.test_openai_provider import (
    CEILING,
    MODEL,
    RESPONSES_URL,
    completed,
    function_call_item,
    make_client,
    message_item,
    stream_response,
)
from tests.unit.test_stop_predicate import closed_by_coverage

CHECKLIST = load_checklist()

CLOSING_TEXT = "Every checklist item is closed; here is the summary."
SPARE_TOOL = "list_gaps"
"""A real, argument-free tool the script asks for *after* the checklist is closed.

Flag on it must never run, and "never ran" is the assertion: no step, no `tool.started`.
"""

ON = efficiency_from_levers(["coverage_stop"])
OFF = EfficiencySettings()


# --- the endpoint, as far as this lever is concerned --------------------------------------


class Service:
    """The Responses endpoint: plays the script, and honours `tool_choice: "none"`.

    That one field is the whole of the service behaviour lever 7 rests on ("none: the
    model will not call any tool"), so it is the one field modelled here. Every request
    body is kept, because what the adapter *sent* is half of what this file asserts.
    """

    def __init__(self, rounds: Iterable[dict[str, Any]]) -> None:
        self._rounds = iter(rounds)
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        if body.get("tool_choice") == "none":
            return stream_response(completed(message_item(CLOSING_TEXT)))
        return stream_response(next(self._rounds))

    @property
    def tool_choices(self) -> list[Any]:
        """What each request asked for, `None` where the request said nothing at all."""
        return [body.get("tool_choice") for body in self.bodies]


def call_round(index: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """One `response.completed` carrying a single `function_call`, as feature 001 sends."""
    item = function_call_item(
        call_id=f"call_{index}", name=name, arguments=json.dumps(arguments)
    )
    item["id"] = f"fc_{index}"
    return completed(item)


def one_round_of(*calls: tuple[int, str, dict[str, Any]]) -> dict[str, Any]:
    """One `response.completed` carrying several `function_call` items: lever 6's shape."""
    items = []
    for index, name, arguments in calls:
        item = function_call_item(
            call_id=f"call_{index}", name=name, arguments=json.dumps(arguments)
        )
        item["id"] = f"fc_{index}"
        items.append(item)
    return completed(*items)


def coverage_arguments(check: str) -> dict[str, Any]:
    return {
        "check": check,
        "bucket": "checked",
        "scope": {},
        "reason": f"{check} was checked against the evidence in the package",
    }


def closing_rounds(*, start: int = 1) -> list[dict[str, Any]]:
    """Ten rounds, one `mark_coverage` each: the checklist closed the honest way."""
    return [
        call_round(start + offset, "mark_coverage", coverage_arguments(item.id))
        for offset, item in enumerate(CHECKLIST.items)
    ]


def script_with_one_call_to_spare() -> list[dict[str, Any]]:
    """The checklist closed, then one more call, then a closing message.

    The last two rounds are consumed by the off arm and never reached by the on arm; that
    difference is the lever.
    """
    return [
        *closing_rounds(),
        call_round(11, SPARE_TOOL, {}),
        completed(message_item(CLOSING_TEXT)),
    ]


# --- the harness ---------------------------------------------------------------------------


def start(
    package_dir: Path,
    out_dir: Path,
    service: Service,
    *,
    efficiency: EfficiencySettings,
) -> runner.ReviewRun:
    respx.post(RESPONSES_URL).mock(side_effect=service)
    return runner.start_review(
        package_dir,
        out_dir,
        provider=OpenAIProvider(model=MODEL, max_output_tokens=CEILING, client=make_client()),
        efficiency=efficiency,
    )


def tools_called(run: runner.ReviewRun) -> list[str]:
    return [step.tool for step in run.session.steps]


def events_of(run: runner.ReviewRun) -> list[dict[str, Any]]:
    text = run.events_path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def turn_reasons(run: runner.ReviewRun) -> list[str]:
    return [event["body"]["reason"] for event in events_of(run) if event["type"] == "turn.ended"]


def call_pairing(body: dict[str, Any]) -> tuple[list[str], list[str]]:
    """The `function_call` ids and the `function_call_output` ids of one request, in order.

    Mechanism A leaves the triggering call with no output, and the module docstring of
    `openai_provider.py` says plainly what the API then does with the next request; this is
    the one assertion that can tell the two mechanisms apart.
    """
    items = body["input"]
    return (
        [item["call_id"] for item in items if item.get("type") == "function_call"],
        [item["call_id"] for item in items if item.get("type") == "function_call_output"],
    )


def outputs_in(body: dict[str, Any]) -> str:
    """Every `function_call_output` of one request, concatenated - what the model was told."""
    return "\n".join(
        str(item.get("output", ""))
        for item in body["input"]
        if item.get("type") == "function_call_output"
    )


# --- the stop fires --------------------------------------------------------------------------


@respx.mock
def test_the_stop_withdraws_the_tools_for_the_next_round(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """The round after the checklist closes goes out with `tool_choice: "none"`."""
    service = Service(script_with_one_call_to_spare())

    run = start(tmp_package_dir, tmp_path / "on", service, efficiency=ON)
    run.start()

    assert service.tool_choices == [*[None] * 10, "none"]


@respx.mock
def test_the_call_the_script_still_held_never_runs(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """No step, and no `tool.started`: the model could not ask, so nothing was recorded."""
    service = Service(script_with_one_call_to_spare())

    run = start(tmp_package_dir, tmp_path / "on", service, efficiency=ON)
    run.start()

    assert tools_called(run) == ["mark_coverage"] * len(CHECKLIST.items)
    assert SPARE_TOOL not in [
        event["body"]["tool"] for event in events_of(run) if event["type"] == "tool.started"
    ]


@respx.mock
def test_the_turn_ends_through_the_existing_path(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """`end`, not `stopped` and not an error: the model wrote its closing message."""
    service = Service(script_with_one_call_to_spare())

    run = start(tmp_package_dir, tmp_path / "on", service, efficiency=ON)
    session = run.start()

    assert turn_reasons(run) == ["end"]
    assert session.ended_at is not None
    assert run.session_path.is_file()


@respx.mock
def test_the_withdrawing_round_carries_an_output_for_every_call(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """Mechanism C, and the reason it was chosen over mechanism A."""
    service = Service(script_with_one_call_to_spare())

    run = start(tmp_package_dir, tmp_path / "on", service, efficiency=ON)
    run.start()

    calls, outputs = call_pairing(service.bodies[-1])
    assert calls == [f"call_{index}" for index in range(1, len(CHECKLIST.items) + 1)]
    assert outputs == calls


@respx.mock
def test_the_stop_sentence_rides_with_the_final_call_s_result(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """Mechanism B's sentence as C's accompanying text: the model is told why it stopped.

    It is in the session's own history, on the result of the call that closed the last
    item, and nowhere else - not on the eight calls before it.
    """
    service = Service(script_with_one_call_to_spare())

    run = start(tmp_package_dir, tmp_path / "on", service, efficiency=ON)
    run.start()

    told = outputs_in(service.bodies[-1])
    assert told.count(runner.COVERAGE_STOP_SENTENCE) == 1
    assert runner.COVERAGE_STOP_SENTENCE not in outputs_in(service.bodies[-2])


# --- with the flag off, nothing above happens ---------------------------------------------


@respx.mock
def test_with_the_flag_off_the_same_script_makes_the_call(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """The off arm of the A/B: the same ten rounds, and then the eleventh call runs."""
    service = Service(script_with_one_call_to_spare())

    run = start(tmp_package_dir, tmp_path / "off", service, efficiency=OFF)
    run.start()

    assert tools_called(run) == ["mark_coverage"] * len(CHECKLIST.items) + [SPARE_TOOL]
    assert service.tool_choices == [None] * 12
    assert turn_reasons(run) == ["end"]


@respx.mock
def test_with_the_flag_off_the_adapter_is_handed_the_dispatch_itself(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """No wrapper is built at all, which is why the off arm has nothing to measure."""
    service = Service(script_with_one_call_to_spare())

    run = start(tmp_package_dir, tmp_path / "off", service, efficiency=OFF)

    assert isinstance(run.tools, ToolDispatch)


def test_with_the_flag_off_the_event_stream_is_the_one_a_lever_free_run_writes(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """FR-039: one commit runs both arms, and the off arm is the build without the lever.

    Played on the scripted provider with a frozen clock, so the two streams are comparable
    field by field rather than modulo every measured number. A run that passes no settings
    at all - every caller that predates feature 005 - is the lever-free build; a run that
    passes `EfficiencySettings()` is the off arm, and the two files must agree everywhere
    except the four values no two runs can share: the event stamp, the session id, the end
    time and the runtime it implies.
    """
    script = [
        ScriptedTurn(
            text="done",
            tool_calls=tuple(
                ScriptedToolCall(name="mark_coverage", arguments=coverage_arguments(item.id))
                for item in CHECKLIST.items
            ),
        )
    ]

    streams = []
    for name, efficiency in (("none", None), ("off", OFF)):
        run = runner.start_review(
            tmp_package_dir,
            tmp_path / name,
            provider=FakeProvider(script=list(script), model="fake-1", clock=lambda: 0.0),
            efficiency=efficiency,
        )
        run.start()
        streams.append(volatile_fields_dropped(events_of(run)))

    assert streams[0] == streams[1]


def volatile_fields_dropped(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every event with the four values no two runs share blanked out.

    The event stamp and the session id, and on `session.ended` the end time and the
    unattended runtime derived from it. Everything else - every tool call, every finding,
    every coverage item, every token count - is compared verbatim.
    """
    out: list[dict[str, Any]] = []
    for event in events:
        body = {
            key: value for key, value in event["body"].items()
            if key not in ("session_id", "ended_at")
        }
        timing = body.get("timing")
        if isinstance(timing, dict):
            body["timing"] = {**timing, "unattended_runtime_minutes": None}
        out.append({**event, "at": None, "body": body})
    return out


# --- an open evidence request keeps the turn alive ----------------------------------------


@respx.mock
def test_an_open_evidence_request_keeps_the_turn_alive(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """A review waiting on an engineer has not finished, however closed the checklist is."""
    service = Service(
        [
            call_round(
                1,
                "request_evidence",
                {
                    "what": "the usable thread depth of hole:1",
                    "why": "fastener.engagement needs it",
                    "entity_ids": ["cmp:0001"],
                },
            ),
            *closing_rounds(start=2),
            call_round(12, SPARE_TOOL, {}),
            completed(message_item(CLOSING_TEXT)),
        ]
    )

    run = start(tmp_package_dir, tmp_path / "open", service, efficiency=ON)
    run.start()

    assert [request.status for request in run.session.evidence_requests] == ["open"]
    assert tools_called(run)[-1] == SPARE_TOOL
    assert service.tool_choices == [None] * 13


@respx.mock
def test_answering_the_request_resumes_the_review_and_then_stops(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """The assertion mechanism A would fail: a stopped-and-resumed session is replayable.

    The first turn leaves a request open, so nothing is withdrawn. Answering it closes the
    last thing holding the review open, the resumed turn runs its call, and *then* the
    tools are withdrawn - one turn's worth of exploration each time, never a session that
    can no longer be talked to.
    """
    service = Service(
        [
            call_round(
                1,
                "request_evidence",
                {
                    "what": "the usable thread depth of hole:1",
                    "why": "fastener.engagement needs it",
                    "entity_ids": ["cmp:0001"],
                },
            ),
            *closing_rounds(start=2),
            completed(message_item("waiting on the thread depth")),
            call_round(12, SPARE_TOOL, {}),
        ]
    )

    run = start(tmp_package_dir, tmp_path / "answered", service, efficiency=ON)
    run.start()
    session = run.answer_evidence("ER-001", "the usable thread depth is 12 mm")

    assert [request.status for request in session.evidence_requests] == ["answered"]
    assert tools_called(run)[-1] == SPARE_TOOL
    assert service.tool_choices[-1] == "none"
    assert turn_reasons(run) == ["end", "end"]
    calls, outputs = call_pairing(service.bodies[-1])
    assert calls == outputs
    assert session.ended_at is not None


@respx.mock
def test_a_continued_session_gets_its_tools_back_for_the_new_turn(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """The withdrawal is per turn, not per session: a follow-up question can be answered.

    A latch that outlived the turn would leave the engineer talking to a model that can no
    longer look anything up, which is `continue_session` broken in a quieter way than
    mechanism A breaks it.
    """
    service = Service(script_with_one_call_to_spare()[:-1])

    run = start(tmp_package_dir, tmp_path / "continued", service, efficiency=ON)
    run.start()
    run.continue_session("what about the gaps?")

    assert tools_called(run)[-1] == SPARE_TOOL
    assert service.tool_choices == [*[None] * 10, "none", None, "none"]
    assert turn_reasons(run) == ["end", "end"]


# --- the other adapter's dialect of the same withdrawal ------------------------------------


def test_gemini_withdraws_the_tools_with_a_function_calling_config_of_none() -> None:
    """Gemini's half of mechanism C, at the one seam its stub client exposes: the config.

    The adapter builds `config` once before its round loop, so lever 7 is the one thing
    that makes it rebuild - and it rebuilds *once*, when the stop fires. The declarations
    stay, because the history refers to them; `FunctionCallingConfigMode.NONE` is what
    forbids the call ("Model will not predict any function calls").

    Driven through the real `CoverageStopTools` over a session whose checklist is already
    closed, so what withdraws the tools here is the same predicate the OpenAI tests above
    run through end to end, not a stub that says yes.
    """
    adapter, models = build_gemini(
        [chunk(call_part("fc_1", "list_gaps", {}))],
        [chunk(text_part("done"), finish_reason=types.FinishReason.STOP)],
    )
    tools = runner.CoverageStopTools(
        toolset([FakeTool(name="list_gaps", payload={"gaps": []})]),
        CHECKLIST,
        closed_by_coverage("checked"),
    )

    adapter.run(
        system="you are a reviewer",
        messages=[{"role": "user", "content": "review it"}],
        tools=tools,
        effort="high",
        max_steps=10,
        on_event=lambda event_type, body: None,
    )

    first, second = (call["config"] for call in models.calls)
    assert first.tool_config is None
    assert second.tool_config.function_calling_config.mode is types.FunctionCallingConfigMode.NONE
    assert second.tools == first.tools


# --- with lever 6 on as well ---------------------------------------------------------------


@respx.mock
def test_the_rest_of_the_round_that_closed_the_checklist_still_runs(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """FR-076, stated as a test so the measured saving is not later read as a defect.

    Mechanism C withdraws the tools for the **next** round, and with lever 6 on the round
    that closes the last checklist item may carry two more calls behind it. Those two
    still run: they were asked for before the review was finished, they have to have their
    outputs for the history to stay valid, and refusing them is mechanism A wearing a
    different hat. Only the round after them is withdrawn, and only the call that actually
    closed the review carries the sentence.
    """
    service = Service(
        [
            *closing_rounds()[:-1],
            one_round_of(
                (10, "mark_coverage", coverage_arguments(CHECKLIST.items[-1].id)),
                (11, SPARE_TOOL, {}),
                (12, "get_package_summary", {}),
            ),
        ]
    )
    respx.post(RESPONSES_URL).mock(side_effect=service)
    run = runner.start_review(
        tmp_package_dir,
        tmp_path / "batched",
        provider=OpenAIProvider(
            model=MODEL,
            max_output_tokens=CEILING,
            client=make_client(),
            parallel_tool_calls=True,
        ),
        efficiency=efficiency_from_levers(["coverage_stop", "parallel_tool_calls"]),
    )
    run.start()

    assert tools_called(run)[-3:] == ["mark_coverage", SPARE_TOOL, "get_package_summary"]
    assert service.tool_choices == [*[None] * 10, "none"]
    assert outputs_in(service.bodies[-1]).count(runner.COVERAGE_STOP_SENTENCE) == 1
