"""Key-gated proof that the strictified tool schemas are accepted by the real API (T018a).

`tests/unit/test_openai_provider.py` replays bodies we authored, so it can prove what the
adapter *sends* but never that OpenAI *accepts* it. Strict mode rejects a schema with a
400 and nothing in a recorded exchange would ever show it. This test posts each tool group
once, against the real endpoint, and asserts the request was not rejected.

It is deliberately cheap: `tool_choice="none"` and a tiny `max_output_tokens` mean the
model reads the tool list and writes almost nothing, so each group costs a few tokens. A
`400` is the failure this test exists to catch and its body is printed in the assertion
message; a `401`, a `429` or a `5xx` is an environment problem rather than a schema
problem and is reported as a skip, so a throttled account never turns into a red schema.

Skipped without `OPENAI_API_KEY`, through `tests/conftest.py` (the same convention the
`integration` marker uses), so a checkout with no key runs the suite unchanged. The model
is `SWREVIEW_LIVE_MODEL` when set: strict-mode acceptance is a property of the endpoint,
not of one model, and a seat without access to the default should still be able to prove
its schemas. The literal here is a test fixture, not a product default - `agent/settings.py`
owns the per-provider default model (FR-026).
"""

from __future__ import annotations

import os

import openai
import pytest

from swreview.agent.providers.openai_provider import tool_param
from swreview.agent.providers.schema import tool_spec
from swreview.tools.registry import REGISTRATIONS, bridge_tools

pytestmark = pytest.mark.live

MODEL = os.environ.get("SWREVIEW_LIVE_MODEL", "gpt-5.6")
MIN_OUTPUT_TOKENS = 16
"""This test wants no output at all; the API requires the field to be at least 16."""

GROUPS = [*REGISTRATIONS, bridge_tools]
"""Every tool group, the bridge group included: `--bridge` sends it to the same API."""


@pytest.fixture(scope="module")
def client() -> openai.OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:  # a seat holding only a Gemini key still collects this module
        pytest.skip("no OPENAI_API_KEY set; the strict schemas are not proved")
    return openai.OpenAI(api_key=key, max_retries=0)


@pytest.mark.parametrize("group", GROUPS, ids=lambda group: group.__name__)
def test_the_strictified_schemas_of_one_tool_group_are_accepted(
    group: object, client: openai.OpenAI
) -> None:
    tools = [tool_param(tool_spec(function)) for function in group()]  # type: ignore[operator]
    assert tools, f"{group.__name__} registered no tools"  # type: ignore[attr-defined]

    try:
        client.responses.create(
            model=MODEL,
            instructions="Reply with the single word ok. Do not call any tool.",
            input=[{"role": "user", "content": "ok"}],
            tools=tools,
            tool_choice="none",
            max_output_tokens=MIN_OUTPUT_TOKENS,
            parallel_tool_calls=False,
        )
    except openai.BadRequestError as rejected:  # the one failure this test is for
        pytest.fail(f"{group.__name__} tool schemas rejected: {rejected}")  # type: ignore[attr-defined]
    except openai.APIStatusError as unavailable:
        pytest.skip(f"API unavailable ({unavailable.status_code}); schemas not proved")
    except openai.APIConnectionError as unreachable:
        pytest.skip(f"API unreachable ({unreachable}); schemas not proved")
