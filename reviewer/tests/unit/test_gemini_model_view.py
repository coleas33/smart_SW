"""The Gemini adapter's request, rebuilt from the neutral history (feature 008 T051, T070).

User Story 3 prunes old tool results out of every request, in both adapters, with one pure
function over the neutral history (research R2.29). The OpenAI adapter already re-encodes the
whole history every round; the Gemini adapter builds `contents` once per turn and appends to
it. To prune, it has to rebuild `contents` from the history each round instead - and that is
a refactor of what Gemini is sent, which Gemini 3 is strict about (thought signatures,
`role="tool"` grouping of parallel answers).

So the first test here is a **characterization, written green before any change**: for a
multi-round turn with parallel calls and a thought signature, rebuilding `contents` from the
history as it stood at each round gives, part for part, exactly the contents the adapter sent
that round. It must stay green through the rebuild (RK-11).
"""

from __future__ import annotations

import json
from typing import Any

from google.genai import types

from swreview.agent.providers.gemini_provider import _to_contents
from swreview.agent.providers.openai_provider import _encode_history
from swreview.agent.providers.pruning import PRUNED_NOTE, prune_history
from swreview.agent.settings import MODEL_VIEW_OFF, MODEL_VIEW_PANE
from tests.support.toolsets import withholding
from tests.unit.test_gemini_provider import (
    FakeTool,
    Sink,
    build,
    call_part,
    chunk,
    run,
    text_part,
)
from tests.unit.test_openai_model_view import GUARD_ANSWER, NOT_OFFERED

SIGNATURE = b"\x07\x08thought"


def three_round_turn(settings: Any = None) -> tuple[Any, Any]:
    """Round 0 asks for two tools at once (with a signed thought), round 1 for one, round 2
    answers."""
    first = FakeTool(name="list_components", payload={"components": [{"id": "cmp:0001"}]})
    second = FakeTool(name="list_mates", payload={"mates": [{"id": "mate:0001"}]})
    third = FakeTool(name="get_component", payload={"id": "cmp:0001", "name": "housing"})
    adapter, models = build(
        [
            chunk(
                text_part("looking", signature=SIGNATURE),
                call_part("fc_1", "list_components", {}),
                call_part("fc_2", "list_mates", {"component_id": None}),
            )
        ],
        [chunk(call_part("fc_3", "get_component", {"component_id": "cmp:0001"}))],
        [chunk(text_part("all clear"), finish_reason=types.FinishReason.STOP)],
    )
    if settings is not None:
        adapter.use_model_view(settings)
    result, _ = run(adapter, [first, second, third])
    return result, models


def history_lengths(messages: list[dict[str, Any]]) -> list[int]:
    """How long the history was when each round's request went out: the opening message,
    then after each round's answers."""
    lengths = [1]
    for index, message in enumerate(messages[1:], start=1):
        following = messages[index + 1] if index + 1 < len(messages) else None
        if message.get("role") == "tool" and (following is None or following["role"] != "tool"):
            lengths.append(index + 1)
    return lengths


def dumped(contents: list[types.Content]) -> list[dict[str, Any]]:
    return [content.model_dump(mode="json", exclude_none=True) for content in contents]


def test_rebuilt_contents_equal_the_contents_sent() -> None:
    result, models = three_round_turn()

    lengths = history_lengths(result.messages)
    assert len(lengths) == len(models.calls) == 3
    for round_index, length in enumerate(lengths):
        sent = models.calls[round_index]["contents"]
        rebuilt = _to_contents(result.messages[:length])
        assert dumped(rebuilt) == dumped(sent), f"round {round_index}"


def test_the_signature_and_the_grouped_answers_are_in_what_was_sent_with_the_view_off() -> None:
    """T070: with `MODEL_VIEW_OFF` the rebuilt requests are the characterized ones."""
    result, models = three_round_turn(MODEL_VIEW_OFF)

    for round_index, length in enumerate(history_lengths(result.messages)):
        assert dumped(models.calls[round_index]["contents"]) == dumped(
            _to_contents(result.messages[:length])
        )


def big(prefix: str) -> dict[str, Any]:
    return {
        "result": [
            {"id": f"{prefix}:{n:04d}", "name": f"row {n}", "note": "z" * 50} for n in range(1, 31)
        ]
    }


def four_round_turn(settings: Any) -> tuple[Any, Any]:
    tools = [
        FakeTool(name="list_components", payload=big("cmp")),
        FakeTool(name="list_mates", payload=big("mat")),
        FakeTool(name="list_holes", payload=big("hol")),
    ]
    adapter, models = build(
        [chunk(call_part("", "list_components", {}))],
        [chunk(call_part("", "list_mates", {}))],
        [chunk(call_part("", "list_holes", {}))],
        [chunk(text_part("done"), finish_reason=types.FinishReason.STOP)],
    )
    adapter.use_model_view(settings)
    result, _ = run(adapter, tools)
    return result, models


def responses(contents: list[types.Content]) -> list[dict[str, Any]]:
    return [
        part.function_response.response
        for content in contents
        if content.role == "tool"
        for part in content.parts
    ]


def test_a_call_older_than_two_rounds_reaches_gemini_as_its_stub() -> None:
    result, models = four_round_turn(MODEL_VIEW_PANE)

    last = responses(models.calls[3]["contents"])
    assert last[0]["output"]["pruned"] == PRUNED_NOTE
    assert last[0]["output"]["tool"] == "list_components"
    assert last[1]["output"] == big("mat")
    assert last[2]["output"] == big("hol")
    assert responses(models.calls[2]["contents"])[0]["output"] == big("cmp")


def test_the_stubs_are_the_ones_the_openai_adapter_sends_for_the_same_history() -> None:
    result, models = four_round_turn(MODEL_VIEW_PANE)
    length = history_lengths(result.messages)[3]
    history = result.messages[:length]

    gemini_stub = responses(models.calls[3]["contents"])[0]["output"]
    openai_items = _encode_history(prune_history(history, 2), compact=True)
    openai_stub = json.loads(
        next(item["output"] for item in openai_items if item.get("type") == "function_call_output")
    )

    assert gemini_stub == openai_stub == prune_history(history, 2)[2]["content"]


def test_a_withheld_tools_aged_answer_is_the_stub_the_openai_adapter_sends() -> None:
    """Feature 008 amendment (T113): the guard answered a tool the model was not offered;
    two rounds later Gemini gets the same stub OpenAI would, saying the tool is not offered."""
    withheld = FakeTool(name="check_rms_part", payload=GUARD_ANSWER)
    offered = [
        FakeTool(name="list_components", payload=big("cmp")),
        FakeTool(name="list_mates", payload=big("mat")),
    ]
    adapter, models = build(
        [chunk(call_part("", "check_rms_part", {}))],
        [chunk(call_part("", "list_components", {}))],
        [chunk(call_part("", "list_mates", {}))],
        [chunk(text_part("done"), finish_reason=types.FinishReason.STOP)],
    )
    adapter.use_model_view(MODEL_VIEW_PANE)
    result = adapter.run(
        system="you are a reviewer",
        messages=[{"role": "user", "content": "review it"}],
        tools=withholding(offered, withheld),
        effort="high",
        max_steps=10,
        on_event=Sink(),
    )

    for call in models.calls:
        declared = [d.name for d in call["config"].tools[0].function_declarations]
        assert declared == ["list_components", "list_mates"]
    gemini_stub = responses(models.calls[3]["contents"])[0]["output"]
    assert gemini_stub["refetch"] == NOT_OFFERED
    history = result.messages[: history_lengths(result.messages)[3]]
    names = {"list_components", "list_mates"}
    openai_items = _encode_history(prune_history(history, 2, offered=names), compact=True)
    openai_stub = json.loads(
        next(item["output"] for item in openai_items if item.get("type") == "function_call_output")
    )
    assert gemini_stub == openai_stub


def test_the_signature_and_the_grouped_answers_are_in_what_was_sent() -> None:
    """What the characterization pins, stated: the signed thought survives and the two
    parallel answers travel in one `role="tool"` content."""
    _, models = three_round_turn()

    second_request = models.calls[1]["contents"]
    assert [content.role for content in second_request] == ["user", "model", "tool"]
    assert second_request[1].parts[0].thought_signature == SIGNATURE
    assert [part.function_response.id for part in second_request[2].parts] == ["fc_1", "fc_2"]
