"""Lever 14: earlier turns' reasoning items leave the OpenAI request view (feature 013 T120).

`contracts/tokens.md` section 4. A turn is the span between two user messages of the runner's
history. With `drop_prior_reasoning` on, the request the adapter builds leaves out the raw
`reasoning` items of every assistant message before the current turn's user message, and sends
every other item - and every item of the current turn - byte for byte. The runner's history, and
so `session.json`, keeps every item. With the lever off every request is byte-identical to
today's. Gemini sends no reasoning items: the lever is inert there, recorded as set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import respx

from swreview.agent.providers import PriorReasoningAware
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.providers.openai_provider import OpenAIProvider, _encode_history
from swreview.agent.runner import start_review
from swreview.agent.settings import EfficiencySettings
from tests.unit.test_openai_provider import (
    CEILING,
    MODEL,
    RESPONSES_URL,
    FakeTool,
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
