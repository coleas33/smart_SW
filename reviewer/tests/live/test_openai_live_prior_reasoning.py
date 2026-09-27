"""Key-gated proof that the real Responses API accepts lever 14's request (013 review, 2026-09-27).

Lever 14 (`drop_prior_reasoning`, a pane default since 013 T125) leaves earlier turns' `reasoning`
items out of each request. The replay priced it and the unit tests pin the request's shape against
a fake transport, but only the real endpoint can say it accepts that shape: a stored `function_call`
or `message` item sent back with its id, without the reasoning item that preceded it, is refused.
The adapter sends those earlier items without their ids (`_encode_history`); this test plays two
turns - a tool call and an answer, then a follow-up - on a reasoning model with the lever on and
asserts neither turn's requests were rejected.

Skipped without `OPENAI_API_KEY`, like `test_openai_live_schemas.py`; the model is
`SWREVIEW_LIVE_MODEL` when set (a reasoning model: with none, there is nothing to leave out). A
`401`, `429` or `5xx` is an environment problem and is reported as a skip. It costs a few thousand
tokens.
"""

from __future__ import annotations

import os
from typing import Any

import openai
import pytest

from swreview.agent.providers.openai_provider import OpenAIProvider
from tests.support.toolsets import toolset
from tests.unit.test_openai_provider import FakeTool, Sink

pytestmark = pytest.mark.live

MODEL = os.environ.get("SWREVIEW_LIVE_MODEL", "gpt-5.6")
CEILING = 2_000


def test_two_turns_with_earlier_reasoning_left_out_are_accepted() -> None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        pytest.skip("no OPENAI_API_KEY set; lever 14's request is not proved")
    provider = OpenAIProvider(
        model=MODEL, max_output_tokens=CEILING, client=openai.OpenAI(api_key=key, max_retries=0)
    )
    provider.drop_prior_reasoning()
    tools = toolset([FakeTool(name="get_component")])
    system = "Call get_component once with component_id C1, then answer in one short sentence."

    def turn(messages: list[dict[str, Any]]) -> Any:
        return provider.run(
            system=system, messages=messages, tools=tools, effort="low", max_steps=3,
            on_event=Sink(),
        )

    try:
        first = turn([{"role": "user", "content": "What is the mass of C1?"}])
        reasoned = [
            item
            for message in first.messages
            if message.get("role") == "assistant"
            for item in message.get("openai", {}).get("output", [])
            if item.get("type") == "reasoning"
        ]
        if not reasoned:
            pytest.skip(f"{MODEL} returned no reasoning item; nothing for lever 14 to leave out")
        second = turn([*first.messages, {"role": "user", "content": "And in grams?"}])
    except openai.BadRequestError as rejected:  # the one failure this test is for
        pytest.fail(f"a request with earlier reasoning left out was rejected: {rejected}")
    except openai.APIStatusError as unavailable:
        pytest.skip(f"API unavailable ({unavailable.status_code}); lever 14 not proved")
    except openai.APIConnectionError as unreachable:
        pytest.skip(f"API unreachable ({unreachable}); lever 14 not proved")

    assert second.reason == "end"
