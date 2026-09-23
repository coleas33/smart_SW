"""What the OpenAI adapter sends once it knows the model view (feature 008 T070).

`start_review` tells a `ModelViewAware` adapter the session's model view once. With history
pruning on, every request is encoded from `prune_history(history, N)`, so a result two
rounds old reaches the model as its stub; with payload slimming on, every result is compact
JSON. With the view off, every request body is byte for byte what it was. The history the
adapter hands back is never pruned: a follow-up's first request prunes it afresh.
"""

from __future__ import annotations

import json
from typing import Any

import respx

from swreview.agent.providers import ModelViewAware, tool_result_text
from swreview.agent.providers.gemini_provider import GeminiProvider
from swreview.agent.providers.openai_provider import OpenAIProvider
from swreview.agent.providers.pruning import PRUNED_NOTE, prune_history
from swreview.agent.settings import MODEL_VIEW_OFF, MODEL_VIEW_PANE
from tests.support.toolsets import withholding
from tests.unit.test_openai_provider import (
    RESPONSES_URL,
    FakeTool,
    Sink,
    completed,
    function_call_item,
    item_done,
    make_provider,
    message_item,
    request_bodies,
    run,
    stream_response,
)


def big(prefix: str) -> dict[str, Any]:
    return {
        "result": [
            {"id": f"{prefix}:{n:04d}", "name": f"row {n}", "note": "y" * 50} for n in range(1, 31)
        ]
    }


TOOLS = (
    FakeTool(name="list_components", payload=big("cmp")),
    FakeTool(name="list_mates", payload=big("mat")),
    FakeTool(name="list_holes", payload=big("hol")),
)


def call_round(index: int, name: str) -> Any:
    item = function_call_item(call_id=f"call_{index}", name=name, arguments='{"component_id":"C1"}')
    return stream_response(item_done(item, index=0), completed(item))


def three_calls_then_text() -> list[Any]:
    return [
        call_round(0, "list_components"),
        call_round(1, "list_mates"),
        call_round(2, "list_holes"),
        stream_response(completed(message_item("done"))),
    ]


def outputs(body: dict[str, Any]) -> dict[str, str]:
    return {
        item["call_id"]: item["output"]
        for item in body["input"]
        if item.get("type") == "function_call_output"
    }


def played(settings: Any = None) -> tuple[list[dict[str, Any]], Any, OpenAIProvider]:
    with respx.mock:
        route = respx.post(RESPONSES_URL).mock(side_effect=three_calls_then_text())
        provider = make_provider()
        if settings is not None:
            provider.use_model_view(settings)
        result, _ = run(provider, tools=list(TOOLS))
        return request_bodies(route), result, provider


def test_both_real_adapters_are_model_view_aware() -> None:
    assert issubclass(OpenAIProvider, ModelViewAware)
    assert isinstance(make_provider(), ModelViewAware)
    assert hasattr(GeminiProvider, "use_model_view")


def test_a_result_two_rounds_old_is_sent_as_its_compact_stub() -> None:
    bodies, result, _ = played(MODEL_VIEW_PANE)

    last = outputs(bodies[3])
    stub = json.loads(last["call_0"])
    assert stub["pruned"] == PRUNED_NOTE
    assert stub["tool"] == "list_components"
    assert last["call_0"] == json.dumps(stub, separators=(",", ":"))
    assert json.loads(last["call_2"]) == big("hol"), "the newest result is in full"
    assert json.loads(outputs(bodies[2])["call_0"]) == big("cmp"), "one round old: in full"


def test_outputs_are_compact_json_under_slimming() -> None:
    bodies, _, _ = played(MODEL_VIEW_PANE)

    assert outputs(bodies[1])["call_0"] == json.dumps(big("cmp"), separators=(",", ":"))
    assert tool_result_text(big("cmp"), compact=True) == json.dumps(
        big("cmp"), separators=(",", ":")
    )


def test_each_request_keeps_the_previous_ones_prefix_up_to_the_first_pruned_item() -> None:
    """The cache-prefix property: pruning changes only the item that crossed the age."""
    bodies, _, _ = played(MODEL_VIEW_PANE)

    for earlier, later in zip(bodies, bodies[1:], strict=False):
        before, after = earlier["input"], later["input"]
        first = next(
            (i for i, (a, b) in enumerate(zip(before, after, strict=False)) if a != b), len(before)
        )
        assert after[:first] == before[:first]
        if first < len(before):
            assert after[first]["type"] == "function_call_output"
            assert json.loads(after[first]["output"])["pruned"] == PRUNED_NOTE


def test_with_the_view_off_every_request_is_todays_request() -> None:
    untouched, _, _ = played()
    off, _, _ = played(MODEL_VIEW_OFF)

    assert off == untouched
    assert all(PRUNED_NOTE not in json.dumps(body) for body in off)


def test_the_history_handed_back_is_never_pruned() -> None:
    _, result, _ = played(MODEL_VIEW_PANE)

    tool_messages = [m for m in result.messages if m["role"] == "tool"]
    assert [m["content"] for m in tool_messages] == [big("cmp"), big("mat"), big("hol")]


def test_a_follow_up_turns_first_request_already_carries_the_stubs() -> None:
    _, result, provider = played(MODEL_VIEW_PANE)

    with respx.mock:
        route = respx.post(RESPONSES_URL).mock(
            side_effect=[stream_response(completed(message_item("these")))]
        )
        run(
            provider,
            tools=list(TOOLS),
            messages=[*result.messages, {"role": "user", "content": "which holes?"}],
        )
        [first] = request_bodies(route)

    sent = outputs(first)
    assert json.loads(sent["call_0"])["pruned"] == PRUNED_NOTE
    assert json.loads(sent["call_1"])["pruned"] == PRUNED_NOTE
    assert json.loads(sent["call_2"]) == big("hol"), "one round old at the follow-up"
    expected = prune_history(
        [*result.messages, {"role": "user", "content": "which holes?"}], 2
    )
    assert json.loads(sent["call_0"]) == expected[2]["content"]


# --- a withheld tool's answer, aged (feature 008 amendment, T113) ------------------------------

GUARD_ANSWER: dict[str, Any] = {
    "status": "already_run",
    "ran_at_step": 3,
    "note": "Checks first ran this call before your first turn; its findings are in the "
    "session. It was not run again.",
    "outcome": {
        "findings": 12,
        "rules": 4,
        "by_status": {"demonstrated": 8, "suspected": 4},
        "by_severity": {"low": 4, "medium": 8},
    },
}
"""What `prerun.PrerunGuard` answers a tool lever 13 withheld with, shaped as it does."""

NOT_OFFERED = "check_rms_part is not offered this session, so it cannot be called again"


def withheld_then_two_rounds() -> list[Any]:
    return [
        call_round(0, "check_rms_part"),
        call_round(1, "list_components"),
        call_round(2, "list_mates"),
        stream_response(completed(message_item("done"))),
    ]


def test_a_withheld_tools_answer_ages_into_a_stub_that_does_not_ask_for_it_again() -> None:
    """A model called a tool it was not offered, and the guard answered; two rounds later the
    stub must not tell it to call that tool again (`contracts/checks-first.md` section 7)."""
    withheld = FakeTool(name="check_rms_part", payload=GUARD_ANSWER)
    with respx.mock:
        route = respx.post(RESPONSES_URL).mock(side_effect=withheld_then_two_rounds())
        provider = make_provider()
        provider.use_model_view(MODEL_VIEW_PANE)
        provider.run(
            system="you are a design reviewer",
            messages=[{"role": "user", "content": "review it"}],
            tools=withholding(list(TOOLS[:2]), withheld),
            effort="high",
            max_steps=10,
            on_event=Sink(),
        )
        bodies = request_bodies(route)

    assert all("check_rms_part" not in [t["name"] for t in body["tools"]] for body in bodies)
    assert json.loads(outputs(bodies[1])["call_0"]) == GUARD_ANSWER, "in full while young"
    stub = json.loads(outputs(bodies[3])["call_0"])
    assert stub["pruned"] == PRUNED_NOTE
    assert stub["refetch"] == NOT_OFFERED
    assert json.loads(outputs(bodies[3])["call_1"]) == big("cmp"), "one round old: in full"
