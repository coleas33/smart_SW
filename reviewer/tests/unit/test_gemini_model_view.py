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

from typing import Any

from google.genai import types

from swreview.agent.providers.gemini_provider import _to_contents
from tests.unit.test_gemini_provider import (
    FakeTool,
    build,
    call_part,
    chunk,
    run,
    text_part,
)

SIGNATURE = b"\x07\x08thought"


def three_round_turn() -> tuple[Any, Any]:
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


def test_the_signature_and_the_grouped_answers_are_in_what_was_sent() -> None:
    """What the characterization pins, stated: the signed thought survives and the two
    parallel answers travel in one `role="tool"` content."""
    _, models = three_round_turn()

    second_request = models.calls[1]["contents"]
    assert [content.role for content in second_request] == ["user", "model", "tool"]
    assert second_request[1].parts[0].thought_signature == SIGNATURE
    assert [part.function_response.id for part in second_request[2].parts] == ["fc_1", "fc_2"]
