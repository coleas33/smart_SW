"""Lever 6: one round trip may carry several tool calls, and we still run them in order.

Two tasks land here because they are one subject and share one set of recorded rounds:
**T070**, the request carries the flag off and on, and **T071**, several calls in one
response are executed in request order.

**The lever is a request field, not a loop.** The OpenAI adapter's loop already handles a
response with several `function_call` items - `_tool_requests` collects every one of them,
the caller iterates them and appends a `function_call_output` for each, and only then
loops back - so the whole change is that the request stops pinning
`parallel_tool_calls: False`. Everything asserted below about execution is therefore a
regression test on behaviour that already exists, written now because this is the first
time we will actually receive such a response.

**Local execution stays serial, in request order, and that is a decision.** Requesting
several calls in one round trip is the token and latency win. Running them on threads
would save wall clock only if the calls were slow - ours are scans over in-memory pydantic
lists - and would cost three real things: `ToolContext.current_step_id` returns
`len(session.steps)`, so two concurrent tools read the same value and one cites the other's
step (silent provenance corruption, not a crash); `SequentialIdAllocator.__next__` is not
atomic, so two findings can take the same `F-003`; and the step log stops being
deterministic while `tests/golden/` compares sessions. The order tests below are what a
later thread pool would have to break.

**Gemini has no such switch**, and this file says so with the installed package rather than
with prose: `GenerateContentConfig` offers no way to disable parallel calls, the adapter's
`_config` sets five fields and none of them is about this, and its loop is already written
for several calls per round (`test_gemini_provider.py::test_parallel_calls_in_one_round_
are_answered_in_one_tool_content`). Gemini is therefore already on in production, the
"off" arm would be a new capability rather than a measurement, and the command line
refuses that arm in the words the ledger row will use.

**Probe L5 is folded in here**: toggling the flag must not move the cacheable prefix. It is
a request field and not prompt content, and it is not one of the miss reasons
`PromptCacheDiagnosticsCacheMiss` lists, so `test_toggling_the_flag_moves_nothing_else_in_
the_request` is the strongest statement this side of the wire - it pins that the two A/B
arms differ in exactly one key. The wire half is the probe itself.

No key and no network: every exchange is replayed through `respx`, and the runner-level
tests drive the real adapter on the same recorded client.

**Feature 008 (T080) makes lever 6 the pane default for OpenAI** (FR-024, research R2.40):
the pane's construction site asks for parallel calls, three bridge calls in one response still
reach SOLIDWORKS one at a time in response order, both answers of a Gemini parallel round age
out of the model's view together, and four independent queries batched by the model cost one
round rather than four.
"""

from __future__ import annotations

import inspect
import json
import socket
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from google.genai import types
from openai import OpenAI
from pydantic import SecretStr

from swreview.agent import runner
from swreview.agent.providers import AgentProvider, ProviderName, TokenUsage, openai_provider
from swreview.agent.providers.fake import (
    FakeProvider,
    ScriptedRound,
    ScriptedToolCall,
    ScriptedTurn,
)
from swreview.agent.providers.openai_provider import BUDGET_EXHAUSTED, OpenAIProvider
from swreview.agent.providers.pruning import PRUNED_NOTE
from swreview.agent.settings import (
    MODEL_VIEW_PANE,
    EfficiencySettings,
    ProviderSettings,
    efficiency_from_levers,
)
from swreview.chat.server import build_provider
from swreview.cli import provider_factory
from swreview.ir.loader import load_package
from swreview.tools.refs import resolve_entity_ref
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME
from tests.support.review_bridge import ScriptedReviewBridge
from tests.unit.test_gemini_model_view import big as big_payload
from tests.unit.test_gemini_model_view import responses as gemini_responses
from tests.unit.test_gemini_provider import FakeTool as GeminiTool
from tests.unit.test_gemini_provider import build as build_gemini
from tests.unit.test_gemini_provider import call_part as gemini_call_part
from tests.unit.test_gemini_provider import chunk, text_part
from tests.unit.test_gemini_provider import run as run_gemini
from tests.unit.test_openai_provider import (
    CEILING,
    KEY,
    MODEL,
    RESPONSES_URL,
    FakeTool,
    completed,
    function_call_item,
    make_client,
    message_item,
    request_bodies,
    run,
    stream_response,
)

TOOL_NAMES = ("get_component", "list_holes", "list_gaps")
"""Three distinct tools in one round, so the order is visible in the event stream."""

FREE_TOOLS = ("get_package_summary", "list_gaps", "get_review_checklist")
"""Three real registered tools that take no arguments, for the runner-level rounds.

Real ones, because the budget test asserts what the *runner* does with a cut-short turn,
and a stub would be testing the test.
"""


# --- helpers ----------------------------------------------------------------------------


def call_item(*, call_id: str, name: str, component: str) -> dict[str, Any]:
    """One `function_call` item with its own id, so a round of three is three items."""
    item = function_call_item(
        call_id=call_id, name=name, arguments=json.dumps({"component_id": component})
    )
    item["id"] = "fc_" + call_id.removeprefix("call_")
    return item


def one_round_of_three() -> dict[str, Any]:
    """A `response.completed` carrying three calls: what this lever is for."""
    return completed(
        *(
            call_item(call_id=f"call_{index}", name=name, component=f"C{index}")
            for index, name in enumerate(TOOL_NAMES, start=1)
        )
    )


def free_call_item(*, call_id: str, name: str) -> dict[str, Any]:
    """A call on a real no-argument tool, for the rounds the runner plays."""
    item = function_call_item(call_id=call_id, name=name, arguments="{}")
    item["id"] = "fc_" + call_id.removeprefix("call_")
    return item


def provider(*, parallel_tool_calls: bool = False) -> OpenAIProvider:
    return OpenAIProvider(
        model=MODEL,
        max_output_tokens=CEILING,
        client=make_client(),
        parallel_tool_calls=parallel_tool_calls,
    )


def stubs() -> list[FakeTool]:
    return [FakeTool(name=name) for name in TOOL_NAMES]


def openai_settings() -> ProviderSettings:
    """What `cli.provider_factory` is handed for an OpenAI run, without touching the env."""
    return ProviderSettings(
        provider=ProviderName.OPENAI, model=MODEL, api_key=SecretStr(KEY), key_source="env"
    )


def gemini_config() -> types.GenerateContentConfig:
    """The config the Gemini adapter really sends, taken off its own stub client.

    Through `run`, not through the private builder, so what is asserted is what would have
    gone to the service - which is the only place "no off switch" can be true or false.
    """
    adapter, models = build_gemini(
        [chunk(text_part("done"), finish_reason=types.FinishReason.STOP)]
    )
    run_gemini(adapter, [])
    config: types.GenerateContentConfig = models.calls[0]["config"]
    return config


# --- the flag on the request (T070) -------------------------------------------------------


def test_the_flag_is_read_at_construction_and_is_not_a_new_argument_on_the_port() -> None:
    """`AgentProvider.run` is the port contract; changing it would touch three adapters."""
    assert "parallel_tool_calls" in inspect.signature(OpenAIProvider.__init__).parameters
    assert "parallel_tool_calls" not in inspect.signature(AgentProvider.run).parameters


@respx.mock
def test_with_the_lever_off_the_request_still_pins_parallel_tool_calls_false() -> None:
    """A flag-off run sends exactly what feature 001 sent: one call per round trip."""
    route = respx.post(RESPONSES_URL).mock(
        return_value=stream_response(completed(message_item("done")))
    )

    run(provider())

    assert request_bodies(route)[0]["parallel_tool_calls"] is False


@respx.mock
def test_with_the_lever_on_the_request_carries_parallel_tool_calls_true() -> None:
    route = respx.post(RESPONSES_URL).mock(
        return_value=stream_response(completed(message_item("done")))
    )

    run(provider(parallel_tool_calls=True))

    assert request_bodies(route)[0]["parallel_tool_calls"] is True


@respx.mock
def test_toggling_the_flag_moves_nothing_else_in_the_request() -> None:
    """Probe L5, as far as this side of the wire can state it.

    `parallel_tool_calls` is a request field and not prompt content, and it is not one of
    the reasons `PromptCacheDiagnosticsCacheMiss` lists, so flipping it should not cost a
    cache hit. What is provable here is the premise: the two A/B arms differ in exactly
    this one key, so anything the wire then reports is about the field itself and not
    about a prompt we moved while we were changing it.
    """
    route = respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(completed(message_item("done"))),
            stream_response(completed(message_item("done"))),
        ]
    )

    run(provider(), tools=stubs())
    run(provider(parallel_tool_calls=True), tools=stubs())

    off, on = request_bodies(route)
    assert off["parallel_tool_calls"] is False
    assert on["parallel_tool_calls"] is True
    assert {key: value for key, value in off.items() if key != "parallel_tool_calls"} == {
        key: value for key, value in on.items() if key != "parallel_tool_calls"
    }


def test_the_factory_builds_the_adapter_with_the_flag_off_when_nothing_was_asked_for() -> None:
    """The default is off and stays off, including for a caller that passes no settings."""
    assert provider_factory(openai_settings()).parallel_tool_calls is False
    assert (
        provider_factory(openai_settings(), efficiency=EfficiencySettings()).parallel_tool_calls
        is False
    )


def test_the_factory_turns_the_flag_on_for_a_run_that_typed_the_lever() -> None:
    """`--lever parallel_tool_calls` reaches the adapter at construction and nowhere else."""
    efficiency = efficiency_from_levers(
        ["parallel_tool_calls"], provider=ProviderName.OPENAI
    )

    built = provider_factory(openai_settings(), efficiency=efficiency)

    assert built.parallel_tool_calls is True


# --- the pane default for OpenAI (feature 008 T080, FR-024) --------------------------------


def refuse_the_network(*args: Any, **kwargs: Any) -> None:
    raise AssertionError("a unit test reached for the network")


@respx.mock
def test_the_pane_builds_its_openai_adapter_asking_for_parallel_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`chat.server.build_provider` - the pane's one construction site - passes the pane's
    levers, so the request an OpenAI pane review sends carries `parallel_tool_calls: true`.

    The adapter builds its own client from the key, as in the pane; the SDK's default HTTP
    client is one `respx` does not reach, so the constructor is handed the interceptable one
    `make_client` uses, and the socket is shut so nothing can leave the machine.
    """
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setattr(socket.socket, "connect", refuse_the_network)
    monkeypatch.setattr(
        openai_provider,
        "OpenAI",
        lambda **kwargs: OpenAI(**kwargs, http_client=httpx.Client(), max_retries=0),
    )
    route = respx.post(RESPONSES_URL).mock(
        return_value=stream_response(completed(message_item("done")))
    )

    built = build_provider(openai_settings())

    assert isinstance(built, OpenAIProvider)
    assert built.parallel_tool_calls is True
    run(built)
    assert request_bodies(route)[0]["parallel_tool_calls"] is True


MEASURED_PAIRS: tuple[tuple[str, str], ...] = (
    ("cmp:0001", "cmp:0002"),
    ("cmp:0001", "hole:1"),
    ("cmp:0002", "fst:1"),
)
"""Three entity pairs of the fixture package, each with a persistent reference to measure."""


def measure_item(*, call_id: str, pair: tuple[str, str]) -> dict[str, Any]:
    item = function_call_item(
        call_id=call_id,
        name="bridge_measure",
        arguments=json.dumps({"entity_id_a": pair[0], "entity_id_b": pair[1]}),
    )
    item["id"] = "fc_" + call_id.removeprefix("call_")
    return item


@respx.mock
def test_three_bridge_calls_in_one_response_reach_solidworks_one_at_a_time(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """FR-024: calls into SOLIDWORKS still run one at a time when the model batches them.

    `ScriptedReviewBridge` fails any call that starts while another is in progress, as the
    host's one STA thread would serialize it differently; the three calls arrive in response
    order, and each is recorded as its own step with its own stored result.
    """
    respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(
                completed(
                    *(
                        measure_item(call_id=f"call_{index}", pair=pair)
                        for index, pair in enumerate(MEASURED_PAIRS, start=1)
                    )
                )
            ),
            stream_response(completed(message_item("done"))),
        ]
    )
    bridge = ScriptedReviewBridge(
        results={"measure": [{"distance": 0.001 * n} for n in range(1, 4)]}
    )
    out = tmp_path / "out"
    review = runner.start_review(
        tmp_package_dir,
        out,
        provider=provider(parallel_tool_calls=True),
        bridge=True,
        bridge_factory=lambda pipe, secret: bridge,
    )
    try:
        review.start()
    finally:
        review.close()

    package = load_package(tmp_package_dir).package
    ref = {
        entity_id: resolve_entity_ref(package, entity_id)[0]
        for pair in MEASURED_PAIRS
        for entity_id in pair
    }
    assert bridge.calls == [
        (
            "measure",
            {
                "persist_ref_a": ref[a],
                "persist_ref_b": ref[b],
                "scope_document_a": None,
                "scope_document_b": None,
            },
        )
        for a, b in MEASURED_PAIRS
    ]
    steps = review.session.steps
    assert [step.index for step in steps] == [0, 1, 2]
    assert [step.tool for step in steps] == ["bridge_measure"] * 3
    assert [step.status for step in steps] == ["ok", "ok", "ok"]
    assert [
        (step.arguments["entity_id_a"], step.arguments["entity_id_b"]) for step in steps
    ] == list(MEASURED_PAIRS)
    stored = [
        json.loads((out / TOOL_RESULTS_DIR_NAME / f"step-{index}.json").read_text("utf-8"))
        for index in range(3)
    ]
    assert [(item["step"], item["tool"]) for item in stored] == [
        (index, "bridge_measure") for index in range(3)
    ]
    assert [item["payload"]["measurement"] for item in stored] == [
        {"distance": 0.001 * n} for n in range(1, 4)
    ]


def gemini_parallel_turn() -> Any:
    """Round 0 asks for two tools at once, rounds 1 and 2 for one each, round 3 answers.

    Every payload is large enough that its stub is smaller, so pruning replaces it.
    """
    tools = [
        GeminiTool(name=name, payload=big_payload(prefix))
        for name, prefix in (
            ("list_components", "cmp"),
            ("list_mates", "mat"),
            ("list_holes", "hol"),
            ("list_fasteners", "fst"),
        )
    ]
    adapter, models = build_gemini(
        [
            chunk(
                gemini_call_part("fc_1", "list_components", {}),
                gemini_call_part("fc_2", "list_mates", {}),
            )
        ],
        [chunk(gemini_call_part("fc_3", "list_holes", {}))],
        [chunk(gemini_call_part("fc_4", "list_fasteners", {}))],
        [chunk(text_part("done"), finish_reason=types.FinishReason.STOP)],
    )
    adapter.use_model_view(MODEL_VIEW_PANE)
    run_gemini(adapter, tools)
    return models


def test_a_gemini_round_of_parallel_calls_ages_together_under_pruning() -> None:
    """Both answers of one parallel round are one round old at the same time, so the pane's
    pruning replaces them in the same request: full in requests 1 and 2, stubs in 3."""
    models = gemini_parallel_turn()

    def outputs(request: int) -> list[dict[str, Any]]:
        contents = models.calls[request]["contents"]
        return [response["output"] for response in gemini_responses(contents)]

    assert outputs(1)[:2] == [big_payload("cmp"), big_payload("mat")]
    assert outputs(2)[:2] == [big_payload("cmp"), big_payload("mat")]
    first, second = outputs(3)[:2]
    assert (first["pruned"], first["tool"]) == (PRUNED_NOTE, "list_components")
    assert (second["pruned"], second["tool"]) == (PRUNED_NOTE, "list_mates")
    assert outputs(3)[2:] == [big_payload("hol"), big_payload("fst")]


FOUR_QUERIES = (
    ScriptedToolCall("get_package_summary"),
    ScriptedToolCall("get_component", {"component_id": "cmp:0001"}),
    ScriptedToolCall("get_component", {"component_id": "cmp:0002"}),
    ScriptedToolCall("get_review_checklist"),
)
"""Four independent `get_*` queries the model can ask for at once."""

ROUND_USAGE = TokenUsage(
    input_tokens=1_200,
    cached_input_tokens=0,
    cache_write_tokens=None,
    output_tokens=80,
    reasoning_tokens=0,
    tool_result_input_tokens=None,
    total_tokens=1_280,
    latency_s=0.2,
)


def test_four_independent_queries_in_one_response_are_one_round_and_four_steps(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """US4's independent test: a model that batches four queries pays for one round, not four,
    and the session still records four steps in the order it asked."""
    review = runner.start_review(
        tmp_package_dir,
        tmp_path / "batched",
        provider=FakeProvider(
            script=[
                ScriptedTurn(
                    text="done",
                    rounds=(ScriptedRound(FOUR_QUERIES, usage=ROUND_USAGE),),
                    usage=ROUND_USAGE,
                )
            ],
            model="fake-1",
            clock=lambda: 0.0,
        ),
    )
    try:
        review.start()
    finally:
        review.close()

    events = scrubbed(review)
    kinds = [event["type"] for event in events]
    first_call = kinds.index("tool.started")
    last_call = len(kinds) - 1 - kinds[::-1].index("tool.finished")
    assert kinds[:first_call].count("usage") == 1
    assert kinds[first_call:last_call].count("usage") == 0
    assert kinds.count("usage") == 2, "one round for the four calls, one for the answer"
    assert [step.tool for step in review.session.steps] == [call.name for call in FOUR_QUERIES]
    assert [step.index for step in review.session.steps] == [0, 1, 2, 3]
    assert all(step.status == "ok" for step in review.session.steps)


# --- Gemini: on by default, not measurable as an A/B --------------------------------------


def test_the_installed_genai_config_offers_no_way_to_disable_parallel_calls() -> None:
    """VERIFIED by absence, against the installed package rather than by assertion in prose.

    This is the whole reason lever 6's Gemini row reads "on by default, not measurable as
    an A/B": the "off" direction is not a flag we decline to set, it is a capability the
    API does not have. An SDK that later grows one fails here, which is the moment to
    revisit the row.
    """
    assert not [
        name for name in types.GenerateContentConfig.model_fields if "parallel" in name.lower()
    ]


def test_the_gemini_adapter_sets_five_config_fields_and_none_is_about_parallel_calls() -> None:
    config = gemini_config()

    assert config.model_fields_set == {
        "system_instruction",
        "tools",
        "automatic_function_calling",
        "thinking_config",
        "max_output_tokens",
    }


def test_the_gemini_arm_is_refused_in_the_words_its_ledger_row_would_have_used() -> None:
    """The refusal is the row: already on, no off switch, so the arm would measure nothing.

    It is refused where the lever is chosen rather than at `benchmark compare`, because a
    refusal after six paid runs is worthless.
    """
    with pytest.raises(ValueError) as excinfo:
        efficiency_from_levers(["parallel_tool_calls"], provider=ProviderName.GEMINI)

    message = str(excinfo.value)
    assert "already makes parallel tool calls" in message
    assert "no disable switch" in message
    assert "measure nothing" in message


# --- several calls in one response, executed in order (T071) ------------------------------


@respx.mock
def test_three_calls_in_one_response_are_all_executed_in_request_order() -> None:
    """Three `tool.started`/`tool.finished` pairs, in the order the model asked for them."""
    respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(one_round_of_three()),
            stream_response(completed(message_item("done"))),
        ]
    )
    tools = stubs()

    result, sink = run(provider(parallel_tool_calls=True), tools=tools)

    assert [body["tool"] for body in sink.bodies("tool.started")] == list(TOOL_NAMES)
    assert [body["step_index"] for body in sink.bodies("tool.started")] == [0, 1, 2]
    assert [body["step_index"] for body in sink.bodies("tool.finished")] == [0, 1, 2]
    assert [body["status"] for body in sink.bodies("tool.finished")] == ["ok", "ok", "ok"]
    assert [tool.calls for tool in tools] == [
        [({"component_id": "C1"}, "call_1")],
        [({"component_id": "C2"}, "call_2")],
        [({"component_id": "C3"}, "call_3")],
    ]
    assert result.steps == 3
    assert result.reason == "end"


@respx.mock
def test_each_call_of_the_round_is_answered_with_its_own_output_in_the_same_order() -> None:
    """One `function_call_output` per call: a missing one is a 400 on the next request."""
    route = respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(one_round_of_three()),
            stream_response(completed(message_item("done"))),
        ]
    )

    run(provider(parallel_tool_calls=True), tools=stubs())

    second = request_bodies(route)[1]["input"]
    calls = [item for item in second if item.get("type") == "function_call"]
    outputs = [item for item in second if item.get("type") == "function_call_output"]
    assert [item["call_id"] for item in calls] == ["call_1", "call_2", "call_3"]
    assert [item["call_id"] for item in outputs] == ["call_1", "call_2", "call_3"]
    assert second.index(calls[-1]) < second.index(outputs[0]), (
        "the whole round is echoed before its results, which is the shape of one round trip"
    )


@respx.mock
def test_the_budget_still_bounds_a_round_and_the_runner_closes_the_turn_out(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """Three calls with `max_steps=2`: two run, the third is answered `BUDGET_EXHAUSTED`.

    Through the runner, because the part that is not already pinned on the adapter alone
    is what the runner does next: an unresolved `coverage.closeout` item, so a turn that
    was cut short is never read as a finished one.
    """
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(
            completed(
                *(
                    free_call_item(call_id=f"call_{index}", name=name)
                    for index, name in enumerate(FREE_TOOLS, start=1)
                )
            )
        )
    )
    review = runner.start_review(
        tmp_package_dir,
        tmp_path / "budget",
        provider=provider(parallel_tool_calls=True),
        max_steps=2,
    )
    try:
        review.start()
    finally:
        review.close()

    session = review.session
    assert [step.tool for step in session.steps] == list(FREE_TOOLS[:2])
    assert [step.index for step in session.steps] == [0, 1]
    answered = [message for message in review.messages if message.get("role") == "tool"]
    assert [message["call_id"] for message in answered] == ["call_1", "call_2", "call_3"]
    assert answered[2]["content"] == {"error": BUDGET_EXHAUSTED}
    assert answered[2]["is_error"] is True
    closeout = [
        item for item in session.coverage.unresolved if item.check == runner.CLOSEOUT_CHECK
    ]
    assert len(closeout) == 1
    assert "max_steps reached (2 tool calls)" in closeout[0].reason


# --- the fake grows a multi-call round ----------------------------------------------------


def scripted(*names: str, one_round: bool) -> ScriptedTurn:
    return ScriptedTurn(
        text="done",
        tool_calls=tuple(ScriptedToolCall(name=name) for name in names),
        one_round=one_round,
    )


def played(
    package_dir: Path, out_dir: Path, script: Sequence[ScriptedTurn]
) -> runner.ReviewRun:
    """One scripted session, with the fake's clock frozen so `elapsed_s` is a constant."""
    review = runner.start_review(
        package_dir,
        out_dir,
        provider=FakeProvider(script=script, model="fake-1", clock=lambda: 0.0),
    )
    try:
        review.start()
    finally:
        review.close()
    return review


def test_the_fake_still_appends_one_assistant_message_per_call_by_default(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """The serial shape the fake has always modelled, unchanged: this flag is opt-in."""
    review = played(
        tmp_package_dir, tmp_path / "serial", [scripted(*FREE_TOOLS, one_round=False)]
    )

    assistant = [
        message
        for message in review.messages
        if message.get("role") == "assistant" and message.get("tool_calls")
    ]
    assert [len(message["tool_calls"]) for message in assistant] == [1, 1, 1]


def test_a_script_can_say_that_three_calls_were_one_round(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """One assistant message carrying three calls, then one tool message per call.

    This is the history shape a parallel round really takes, and it is what a runner or
    report test needs in order to exercise lever 6 without a recorded OpenAI exchange. The
    calls still run one after another, in order, which is the whole point of the lever.
    """
    review = played(
        tmp_package_dir, tmp_path / "grouped", [scripted(*FREE_TOOLS, one_round=True)]
    )

    assistant = [
        message
        for message in review.messages
        if message.get("role") == "assistant" and message.get("tool_calls")
    ]
    assert len(assistant) == 1
    assert [call["name"] for call in assistant[0]["tool_calls"]] == list(FREE_TOOLS)
    answered = [message for message in review.messages if message.get("role") == "tool"]
    assert [message["name"] for message in answered] == list(FREE_TOOLS)
    assert [step.index for step in review.session.steps] == [0, 1, 2]
    assert [step.tool for step in review.session.steps] == list(FREE_TOOLS)


def test_a_grouped_round_the_budget_cuts_short_leaves_no_unanswered_call(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """The fake stops at the budget, and the round it records is the part it dispatched.

    The fake does not grow the real adapter's `BUDGET_EXHAUSTED` output - that belongs to
    the adapter that has to keep a wire history replayable, and it is pinned above on the
    recorded client. What matters here is that the fake's history never carries a call
    with no result, grouped or not.
    """
    review = runner.start_review(
        tmp_package_dir,
        tmp_path / "cut",
        provider=FakeProvider(
            script=[scripted(*FREE_TOOLS, one_round=True)], model="fake-1", clock=lambda: 0.0
        ),
        max_steps=2,
    )
    try:
        review.start()
    finally:
        review.close()

    assistant = [
        message
        for message in review.messages
        if message.get("role") == "assistant" and message.get("tool_calls")
    ]
    assert [call["name"] for call in assistant[0]["tool_calls"]] == list(FREE_TOOLS[:2])
    answered = [message for message in review.messages if message.get("role") == "tool"]
    assert [message["name"] for message in answered] == list(FREE_TOOLS[:2])


# --- determinism ---------------------------------------------------------------------------

VOLATILE: tuple[tuple[str, str], ...] = (
    ("session.started", "session_id"),
    ("session.ended", "ended_at"),
    ("session.ended", "timing"),
)
"""The three values in the stream that are a clock or a fresh uuid rather than a decision.

Everything else, `tool.finished`'s `elapsed_s` included, is compared: the fake's clock is
injected and frozen, so a difference there would be a real one.
"""


def scrubbed(review: runner.ReviewRun) -> list[dict[str, Any]]:
    """Every line of `events.jsonl` with the clock and the run's identity blanked."""
    events = [
        json.loads(line)
        for line in review.events_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    for event in events:
        event["at"] = None
        for event_type, key in VOLATILE:
            if event["type"] == event_type and key in event["body"]:
                event["body"][key] = None
    return events


def test_two_runs_of_one_multi_call_script_write_byte_identical_events(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """Serial execution in request order is what keeps this true; a thread pool would not."""
    script = [scripted(*FREE_TOOLS, one_round=True)]

    first = played(tmp_package_dir, tmp_path / "first", script)
    second = played(tmp_package_dir, tmp_path / "second", script)

    assert scrubbed(first) == scrubbed(second)
    assert [event["type"] for event in scrubbed(first)].count("tool.finished") == 3
