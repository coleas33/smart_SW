"""Key-gated proof that a `role="tool"` function response is accepted by the real API.

`tests/unit/test_gemini_provider.py` drives a stubbed `genai.Client`, so it can prove what
the adapter *sends* and never that Gemini *accepts* it. The `role` of the content carrying
a `function_response` is exactly that kind of claim, and the installed SDK says two things
about it:

- `types.Content.role` is documented "Must be either 'user' or 'model'"
  (`.venv/Lib/site-packages/google/genai/types.py:2575`), and the SDK's own automatic
  function-calling loop sends `types.Content(role='user', parts=func_response_parts)`
  (`google/genai/models.py:6295` and `:6483`);
- the same distribution's README - the manual-function-calling section, which is the loop
  this adapter replaces - builds `types.Content(role='tool', parts=[function_response_part])`
  and posts it to `gemini-3.5-flash` (`google_genai-2.23.0.dist-info/METADATA:851`).

`role="tool"` is what `research.md` and the T020 task text specify and what the adapter
sends. This test is the tiebreaker: it runs one real forced tool call, answers it the way
the adapter does, and fails if the API rejects the round.

A `400` is the failure this test exists to catch and its body is printed in the assertion
message; a `401`, a `429` or a `5xx` is an environment problem rather than a protocol
problem and is reported as a skip, so a throttled account never turns into a red run.

Skipped without `GOOGLE_API_KEY` or `GEMINI_API_KEY`, through `tests/conftest.py` and the
module fixture below (the same convention `tests/live/test_openai_live_schemas.py` uses).
The model is `SWREVIEW_LIVE_GEMINI_MODEL` when set; the literal here is a test fixture,
not a product default - `agent/settings.py` owns the per-provider default model (FR-026).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from google import genai
from google.genai import errors, types

from swreview.agent.providers import ToolCallResult
from swreview.agent.providers.gemini_provider import _request, _tool_content
from swreview.agent.providers.schema import gemini_adapt

pytestmark = pytest.mark.live

KEY_NAMES = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
"""`GOOGLE_API_KEY` first, the precedence `google.genai` applies itself."""

MODEL = os.environ.get("SWREVIEW_LIVE_GEMINI_MODEL", "gemini-3.5-flash")

DECLARATION = types.FunctionDeclaration(
    name="list_components",
    description="List the components of the open assembly.",
    parameters_json_schema=gemini_adapt(
        {
            "type": "object",
            "properties": {
                "configuration": {"type": "string", "description": "The configuration to read."}
            },
            "required": ["configuration"],
        }
    ),
)


@pytest.fixture(scope="module")
def client() -> genai.Client:
    key = next((os.environ[name] for name in KEY_NAMES if os.environ.get(name)), None)
    if key is None:
        pytest.skip(f"no Gemini key set: {', '.join(KEY_NAMES)}")
    return genai.Client(api_key=key)


def _config(**extra: Any) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=[DECLARATION])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        **extra,
    )


def test_a_tool_role_function_response_round_is_accepted(client: genai.Client) -> None:
    prompt = types.Content(
        role="user",
        parts=[types.Part(text="List the components of the Default configuration.")],
    )
    forced = _config(
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.ANY
            )
        )
    )

    try:
        first = client.models.generate_content(model=MODEL, contents=[prompt], config=forced)
    except errors.ClientError as rejected:
        if rejected.code == 400:  # the one failure this test is for
            pytest.fail(f"the forced tool call was rejected: {rejected}")
        pytest.skip(f"API unavailable ({rejected.code}); the response role is not proved")
    except errors.ServerError as unavailable:
        pytest.skip(f"API unavailable ({unavailable}); the response role is not proved")

    calls = first.function_calls or []
    if not calls:
        pytest.skip("the model returned no function call; the response role is not proved")

    answered = first.candidates[0].content
    assert answered is not None
    requests = [_request(call) for call in calls]
    results = [
        ToolCallResult(call_id=request.call_id, payload={"components": []}, is_error=False)
        for request in requests
    ]
    responses = _tool_content(requests, results)
    assert responses.role == "tool", "this is the claim under test"

    try:
        second = client.models.generate_content(
            model=MODEL, contents=[prompt, answered, responses], config=_config()
        )
    except errors.ClientError as rejected:
        if rejected.code == 400:  # the one failure this test is for
            pytest.fail(f'a role="tool" function response was rejected: {rejected}')
        pytest.skip(f"API unavailable ({rejected.code}); the response role is not proved")
    except errors.ServerError as unavailable:
        pytest.skip(f"API unavailable ({unavailable}); the response role is not proved")

    assert second.candidates, "the model answered the tool response with nothing at all"
