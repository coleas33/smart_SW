"""Lever 14: earlier turns' reasoning items leave the OpenAI request view (feature 013 T120).

`contracts/tokens.md` section 4. A turn is the span between two user messages of the runner's
history. With `drop_prior_reasoning` on, the request the adapter builds leaves out the raw
`reasoning` items of every assistant message before the current turn's user message, and sends
every other item - and every item of the current turn - byte for byte. The runner's history, and
so `session.json`, keeps every item. With the lever off every request is byte-identical to
today's. Gemini sends no reasoning items: the lever is inert there, recorded as set.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from swreview.agent.providers import PriorReasoningAware
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.providers.openai_provider import (
    OpenAIProvider,
    OpenAIProviderError,
    _encode_history,
)
from swreview.agent.runner import start_review
from swreview.agent.settings import EfficiencySettings
from tests.unit.test_openai_provider import (
    CEILING,
    KEY,
    MODEL,
    RESPONSES_URL,
    FakeTool,
    Sink,
    completed,
    function_call_item,
    item_done,
    make_client,
    make_provider,
    message_item,
    reasoning_item,
    request_bodies,
    run,
    stream_response,
)


def tool_round(reasoning_id: str, call_id: str) -> Any:
    """A round that thinks, then calls `get_component`."""
    reasoning = reasoning_item(item_id=reasoning_id)
    call = function_call_item(call_id=call_id)
    return stream_response(
        item_done(reasoning, index=0), item_done(call, index=1), completed(reasoning, call)
    )


def answer_round(text: str, reasoning_id: str | None = None) -> Any:
    output = [reasoning_item(item_id=reasoning_id)] if reasoning_id else []
    return stream_response(completed(*output, message_item(text)))


def two_turns(provider: OpenAIProvider) -> tuple[list[dict[str, Any]], Any]:
    """Turn 1 thinks, calls a tool and answers; turn 2 does the same. Returns every request
    body and turn 2's result."""
    route = respx.post(RESPONSES_URL).mock(
        side_effect=[
            tool_round("rs_turn1", "call_1"),
            answer_round("first answer", "rs_turn1_end"),
            tool_round("rs_turn2", "call_2"),
            answer_round("second answer"),
        ]
    )
    first, _ = run(provider, tools=[FakeTool(name="get_component")])
    second, _ = run(
        provider,
        tools=[FakeTool(name="get_component")],
        messages=[*first.messages, {"role": "user", "content": "and the other one?"}],
    )
    return request_bodies(route), second


def reasoning_ids(body: dict[str, Any]) -> list[str]:
    return [item["id"] for item in body["input"] if item.get("type") == "reasoning"]


def dropping_provider() -> OpenAIProvider:
    provider = make_provider()
    provider.drop_prior_reasoning()
    return provider


@respx.mock
def test_with_the_lever_on_earlier_turns_reasoning_leaves_the_request() -> None:
    bodies, _ = two_turns(dropping_provider())

    # Turn 2's first request: turn 1's two reasoning items are gone, nothing else is. Edited
    # deliberately on the review of 2026-09-27: the answer turn 1 gave is sent in the easy form
    # (its reasoning item is gone, so it carries no item id), hence the role, not "message".
    turn_2_first = bodies[2]
    assert reasoning_ids(turn_2_first) == []
    types = [item.get("type", item.get("role")) for item in turn_2_first["input"]]
    assert types == ["user", "function_call", "function_call_output", "assistant", "user"]


@respx.mock
def test_the_current_turns_reasoning_is_still_sent() -> None:
    bodies, _ = two_turns(dropping_provider())

    # Turn 1's second request carries turn 1's own reasoning; turn 2's second carries turn 2's.
    assert reasoning_ids(bodies[1]) == ["rs_turn1"]
    assert reasoning_ids(bodies[3]) == ["rs_turn2"]


@respx.mock
def test_with_the_lever_off_every_request_is_todays() -> None:
    bodies, second = two_turns(make_provider())

    assert reasoning_ids(bodies[2]) == ["rs_turn1", "rs_turn1_end"]
    history_before_the_last_request = second.messages[:-1]  # all but the final answer
    assert bodies[3]["input"] == _encode_history(history_before_the_last_request)


@respx.mock
def test_the_stored_history_keeps_every_reasoning_item() -> None:
    _, second = two_turns(dropping_provider())

    kept = [
        item["id"]
        for message in second.messages
        if message.get("role") == "assistant"
        for item in message.get("openai", {}).get("output", [])
        if item["type"] == "reasoning"
    ]
    assert kept == ["rs_turn1", "rs_turn1_end", "rs_turn2"]


def test_the_encoder_drops_only_before_the_last_user_message() -> None:
    history = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "a", "openai": {"output": [
            reasoning_item(item_id="rs_a"), message_item("a", item_id="msg_a")]}},
        {"role": "user", "content": "two"},
        {"role": "assistant", "content": "b", "openai": {"output": [
            reasoning_item(item_id="rs_b"), message_item("b", item_id="msg_b")]}},
    ]

    kept = _encode_history(history, drop_prior_reasoning=True)
    whole = _encode_history(history)

    # Edited deliberately on the review of 2026-09-27: the earlier turn's message lost its
    # reasoning item, so it is sent in the easy form with no item id (section "item ids" below).
    assert [item.get("id") for item in kept] == [None, None, None, "rs_b", "msg_b"]
    assert kept[1] == {"role": "assistant", "content": "a"}
    assert [item.get("id") for item in whole] == [None, "rs_a", "msg_a", None, "rs_b", "msg_b"]


def test_a_history_with_no_user_message_drops_nothing() -> None:
    history = [
        {"role": "assistant", "content": "a", "openai": {"output": [
            reasoning_item(item_id="rs_a"), message_item("a", item_id="msg_a")]}},
    ]

    assert _encode_history(history, drop_prior_reasoning=True) == _encode_history(history)


def test_an_earlier_round_of_reasoning_alone_contributes_nothing() -> None:
    history = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "", "openai": {"output": [reasoning_item()]}},
        {"role": "user", "content": "two"},
    ]

    assert _encode_history(history, drop_prior_reasoning=True) == [
        {"role": "user", "content": "one"},
        {"role": "user", "content": "two"},
    ]


# --- item ids: nothing sent still points at a reasoning item left out (review, 2026-09-27) --------
#
# The Responses API ties the items one response produced: a `function_call` or `message` item sent
# back with its id, stored (the adapter leaves `store` at its default), is refused without the
# `reasoning` item that preceded it ("... was provided without its required 'reasoning' item").
# Lever 14 leaves those reasoning items out, so the items of the same earlier message are sent
# without their ids: a call keeps its `call_id`, which its output answers, and drops `id`; an
# answer is sent in the easy form, `{"role": "assistant", "content": text}` - the form this adapter
# already sends for an assistant turn it did not produce.


def earlier_turn(*output: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "a", "openai": {"output": list(output)}},
        {"role": "tool", "call_id": "call_1", "content": {"mass_kg": 1}},
        {"role": "user", "content": "two"},
    ]


def test_an_earlier_call_whose_reasoning_is_left_out_is_sent_without_its_item_id() -> None:
    call = function_call_item(call_id="call_1")

    history = earlier_turn(reasoning_item(item_id="rs_a"), call)

    kept = _encode_history(history, drop_prior_reasoning=True)

    sent = kept[1]
    assert sent == {key: value for key, value in call.items() if key != "id"}
    assert sent["call_id"] == "call_1" and "id" not in sent
    assert kept[2]["type"] == "function_call_output" and kept[2]["call_id"] == "call_1"


def test_an_earlier_answer_whose_reasoning_is_left_out_is_sent_in_the_easy_form() -> None:
    answer = message_item("the mass is 1 kg", item_id="msg_a")

    history = earlier_turn(reasoning_item(item_id="rs_a"), answer)

    kept = _encode_history(history, drop_prior_reasoning=True)

    assert kept[1] == {"role": "assistant", "content": "the mass is 1 kg"}


def test_an_answer_of_several_text_parts_is_sent_as_their_text_in_order() -> None:
    answer = message_item("first", item_id="msg_a")
    answer["content"].append({"type": "output_text", "text": " second", "annotations": []})

    kept = _encode_history(earlier_turn(reasoning_item(), answer), drop_prior_reasoning=True)

    assert kept[1] == {"role": "assistant", "content": "first second"}


def test_an_earlier_message_that_had_no_reasoning_item_keeps_every_byte() -> None:
    call = function_call_item(call_id="call_1")
    history = earlier_turn(call)

    assert _encode_history(history, drop_prior_reasoning=True) == _encode_history(history)
    assert _encode_history(history, drop_prior_reasoning=True)[1]["id"] == "fc_1"


def test_the_current_turns_items_keep_their_ids() -> None:
    history = [
        *earlier_turn(reasoning_item(item_id="rs_a"), function_call_item(call_id="call_1")),
        {"role": "assistant", "content": "", "openai": {"output": [
            reasoning_item(item_id="rs_b"), function_call_item(call_id="call_2")]}},
    ]

    kept = _encode_history(history, drop_prior_reasoning=True)

    assert [item.get("id") for item in kept[-2:]] == ["rs_b", "fc_1"]


@respx.mock
def test_no_request_with_the_lever_on_sends_an_item_id_of_an_earlier_turn() -> None:
    bodies, _ = two_turns(dropping_provider())

    # Turn 2's second request: turn 1's items (the first four), then turn 2's own.
    earlier, current = bodies[3]["input"][:4], bodies[3]["input"][5:]
    assert all("id" not in item for item in earlier)
    assert [item.get("id") for item in current if item.get("id")] == ["rs_turn2", "fc_1"]


# --- the adapters, and start_review -----------------------------------------------------------


def test_only_the_openai_adapter_takes_the_lever() -> None:
    from swreview.agent.providers.gemini_provider import GeminiProvider

    assert isinstance(make_provider(), PriorReasoningAware)
    assert not issubclass(GeminiProvider, PriorReasoningAware)
    assert not isinstance(FakeProvider(script=[], model="fake"), PriorReasoningAware)


def test_start_review_turns_the_lever_on_in_the_adapter(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    provider = OpenAIProvider(model=MODEL, max_output_tokens=CEILING, client=make_client())

    start_review(
        tmp_package_dir, tmp_path / "on", provider=provider,
        efficiency=EfficiencySettings(drop_prior_reasoning=True),
    )

    assert provider.drops_prior_reasoning is True


def test_off_the_adapter_keeps_every_item(tmp_package_dir: Path, tmp_path: Path) -> None:
    provider = OpenAIProvider(model=MODEL, max_output_tokens=CEILING, client=make_client())

    start_review(tmp_package_dir, tmp_path / "off", provider=provider)

    assert provider.drops_prior_reasoning is False


def test_a_provider_without_the_lever_records_it_as_set(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    run_ = start_review(
        tmp_package_dir,
        tmp_path / "fake",
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        efficiency=EfficiencySettings(drop_prior_reasoning=True),
    )

    assert run_.session.efficiency is not None
    assert run_.session.efficiency.drop_prior_reasoning is True


# --- lever 14 falls back once when the endpoint refuses its request (013 T151-T152) -----------

REFUSED_WITHOUT_REASONING = (
    "Item 'fc_turn1' of type 'function_call' was provided without its required 'reasoning' "
    "item: 'rs_turn1'."
)
"""The Responses API's words for a stored item sent back without the reasoning item before it."""

LEVER_14_REFUSALS = (
    REFUSED_WITHOUT_REASONING,
    "Item 'msg_1' of type 'message' was provided without its required 'reasoning' item: 'rs_1'.",
    "Item with id 'rs_turn1' not found.",
    "The input item 'fc_turn1' is linked to an item that was not provided.",
)
"""Refusals about a missing reasoning item or a linked item: the ones the adapter falls back on."""

OTHER_REFUSALS = (
    "invalid schema for function 'get_component'",
    "Unsupported value: 'reasoning.effort' does not support 'xhigh' with this model.",
)
"""Refusals of another kind, the second naming reasoning but no item: raised as today."""


def refused(message: str, status: int = 400) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"message": message, "type": "invalid_request_error", "param": "input",
                        "code": None}},
    )


def turn_1_then(*turn_2: Any) -> list[Any]:
    """Turn 1 thinks, calls a tool and answers; then turn 2's responses, as given."""
    return [tool_round("rs_turn1", "call_1"), answer_round("first answer", "rs_turn1_end"), *turn_2]


def run_two_turns(
    provider: OpenAIProvider, responses: list[Any], sink: Sink | None = None
) -> tuple[respx.Route, Any, Any]:
    route = respx.post(RESPONSES_URL).mock(side_effect=responses)
    first, _ = run(provider, tools=[FakeTool(name="get_component")])
    second, _ = run(
        provider,
        tools=[FakeTool(name="get_component")],
        messages=[*first.messages, {"role": "user", "content": "and the other one?"}],
        sink=sink,
    )
    return route, first, second


@respx.mock
@pytest.mark.parametrize("message", LEVER_14_REFUSALS)
def test_a_refused_request_is_sent_again_with_the_earlier_reasoning_kept(message: str) -> None:
    provider = dropping_provider()

    route, _, second = run_two_turns(
        provider,
        turn_1_then(refused(message), tool_round("rs_turn2", "call_2"), answer_round("second")),
    )

    bodies = request_bodies(route)
    refused_body, resent = bodies[2], bodies[3]
    assert reasoning_ids(refused_body) == []
    assert reasoning_ids(resent) == ["rs_turn1", "rs_turn1_end"]
    assert {k: v for k, v in resent.items() if k != "input"} == {
        k: v for k, v in refused_body.items() if k != "input"
    }
    assert second.reason == "end" and second.text == "second"


@respx.mock
def test_the_resent_request_is_the_one_the_lever_off_sends() -> None:
    """Byte for byte what every review sent before lever 14: the history encoded with no item
    left out."""
    provider = dropping_provider()

    route, first, _ = run_two_turns(
        provider,
        turn_1_then(
            refused(REFUSED_WITHOUT_REASONING), tool_round("rs_turn2", "call_2"),
            answer_round("second"),
        ),
    )

    history = [*first.messages, {"role": "user", "content": "and the other one?"}]
    assert request_bodies(route)[3]["input"] == _encode_history(history)


@respx.mock
def test_after_the_fallback_the_lever_is_off_for_the_rest_of_the_session() -> None:
    provider = dropping_provider()
    route, _, second = run_two_turns(
        provider,
        turn_1_then(
            refused(REFUSED_WITHOUT_REASONING), tool_round("rs_turn2", "call_2"),
            answer_round("second", "rs_turn2_end"),
            answer_round("third"),
        ),
    )

    run(provider, messages=[*second.messages, {"role": "user", "content": "and then?"}])

    assert provider.drops_prior_reasoning is False
    turn_3 = request_bodies(route)[-1]
    assert reasoning_ids(turn_3) == ["rs_turn1", "rs_turn1_end", "rs_turn2", "rs_turn2_end"]
    assert len(request_bodies(route)) == 6, "no request of turn 3 was refused or sent twice"


@respx.mock
def test_the_fallback_logs_one_plain_line_and_emits_no_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = Sink()
    caplog.set_level(logging.WARNING, logger="swreview.providers.openai")

    run_two_turns(
        dropping_provider(),
        turn_1_then(
            refused(f"{REFUSED_WITHOUT_REASONING} (key {KEY})"), tool_round("rs_turn2", "call_2"),
            answer_round("second"),
        ),
        sink=sink,
    )

    [record] = [r for r in caplog.records if r.name == "swreview.providers.openai"]
    line = record.getMessage()
    assert "lever 14" in line and "sent again with that reasoning kept" in line
    assert "\n" not in line
    assert KEY not in line
    assert "error" not in sink.types, "the refused request was answered, not a failure"


@respx.mock
@pytest.mark.parametrize("message", OTHER_REFUSALS)
def test_a_refusal_of_another_kind_is_raised_and_the_lever_stays_on(message: str) -> None:
    provider = dropping_provider()

    with pytest.raises(OpenAIProviderError) as caught:
        run_two_turns(provider, turn_1_then(refused(message)))

    assert caught.value.error_class == "BadRequestError"
    assert provider.drops_prior_reasoning is True
    assert len(respx.calls) == 3, "nothing was sent again"


@respx.mock
def test_a_refusal_of_a_request_that_left_nothing_out_is_raised() -> None:
    """Turn 1's first request carries no earlier turn: the lever left nothing out, so the refusal
    is about something else and sending the same bytes again would change nothing."""
    provider = dropping_provider()
    respx.post(RESPONSES_URL).mock(side_effect=[refused(REFUSED_WITHOUT_REASONING)])

    with pytest.raises(OpenAIProviderError):
        run(provider, tools=[FakeTool(name="get_component")])

    assert provider.drops_prior_reasoning is True
    assert len(respx.calls) == 1


@respx.mock
def test_with_the_lever_off_a_refusal_is_raised_as_today() -> None:
    provider = make_provider()

    with pytest.raises(OpenAIProviderError):
        run_two_turns(provider, turn_1_then(refused(REFUSED_WITHOUT_REASONING)))

    assert len(respx.calls) == 3


@respx.mock
@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(httpx.Response(500, json={"error": {"message": "reasoning item store down"}}),
                     id="a-server-error"),
        pytest.param(httpx.ConnectError("reasoning item unreachable"), id="a-connection-error"),
    ],
)
def test_a_server_or_connection_failure_is_raised_and_the_lever_stays_on(failure: Any) -> None:
    provider = dropping_provider()

    with pytest.raises(OpenAIProviderError) as caught:
        run_two_turns(provider, turn_1_then(failure))

    assert caught.value.retryable is True
    assert provider.drops_prior_reasoning is True
    assert len(respx.calls) == 3


@respx.mock
def test_a_refusal_of_the_resent_request_is_raised_once() -> None:
    provider = dropping_provider()
    sink = Sink()

    with pytest.raises(OpenAIProviderError) as caught:
        run_two_turns(
            provider,
            turn_1_then(refused(REFUSED_WITHOUT_REASONING), refused("invalid schema for 'x'")),
            sink=sink,
        )

    assert "invalid schema" in caught.value.message
    assert len(respx.calls) == 4, "sent once, then once again, and no more"
    assert len(sink.bodies("error")) == 1
    assert provider.drops_prior_reasoning is False


@respx.mock
def test_the_stored_history_keeps_every_reasoning_item_after_the_fallback() -> None:
    _, _, second = run_two_turns(
        dropping_provider(),
        turn_1_then(
            refused(REFUSED_WITHOUT_REASONING), tool_round("rs_turn2", "call_2"),
            answer_round("second"),
        ),
    )

    kept = [
        item["id"]
        for message in second.messages
        if message.get("role") == "assistant"
        for item in message.get("openai", {}).get("output", [])
        if item["type"] == "reasoning"
    ]
    assert kept == ["rs_turn1", "rs_turn1_end", "rs_turn2"]


@respx.mock
def test_the_session_still_records_the_lever_as_requested(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """`session.efficiency` is what the review asked for, the A/B arm it belongs to; the fallback
    is the adapter's and its log line says so."""
    provider = OpenAIProvider(model=MODEL, max_output_tokens=CEILING, client=make_client())
    respx.post(RESPONSES_URL).mock(side_effect=[answer_round("done", "rs_1")])

    review = start_review(
        tmp_package_dir, tmp_path / "on", provider=provider,
        efficiency=EfficiencySettings(drop_prior_reasoning=True),
    )
    provider.drops_prior_reasoning = False  # as the fallback leaves it

    assert review.session.efficiency is not None
    assert review.session.efficiency.drop_prior_reasoning is True
