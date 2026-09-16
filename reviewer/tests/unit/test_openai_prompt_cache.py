"""Lever 3 on OpenAI: naming the cache, and recording what it did (T048).

Our prefix is already stable (`test_prefix_stability.py`), so this lever is not "add
caching" - it is "name the cache, record the diagnostics, and stop the other levers from
breaking what we already have". Three things are pinned here, and they fail in different
ways.

**The flag is the whole switch.** Off, the request carries neither `prompt_cache_key` nor
`prompt_cache_options`, so a flag-off run is byte-identical to what feature 001 sent and
the A/B arms differ in exactly one thing.

**The key must survive a process restart.** The pane restarts the backend on a settings
save and resumes the same run folder. A process-local random value would look perfectly
correct in every test that only looks at one process, and would silently drop every hit
after a restart - a loss that shows up on the wire as `prompt_cache_key_changed` and
nowhere else, which is exactly why the diagnostics are worth recording. The key is
therefore `str(session.session_id)`, which is already persisted in `session.json`, and
the restart test below rebuilds the adapter from the file rather than from memory.

**A diagnostic that did not arrive is `None`, never a hit.** `cache_diagnostic` is
recorded verbatim as a nested object - not flattened, not summarised - because
`tools_changed` with a `cache_missed_tokens` number beside it is how lever 4 gets priced
before lever 4 is written (contracts/usage.md section 7).

Every package fact this file relies on is asserted against the installed `openai` package
in the first test, so an SDK upgrade that moved a field fails here rather than on the
wire. No key and no network: every exchange is replayed through `respx`.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, get_args

import pytest
import respx
from openai.resources.responses import Responses
from openai.types.responses import Response
from openai.types.responses.response import PromptCacheDiagnosticsCacheMiss
from openai.types.responses.response_create_params import PromptCacheOptions

from swreview.agent.providers import PromptCacheAware
from swreview.agent.providers.openai_provider import OpenAIProvider
from swreview.agent.runner import ReviewRun, start_review
from swreview.agent.settings import EfficiencySettings
from swreview.report.session import load_session
from tests.unit.test_openai_provider import (
    CEILING,
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

CACHE_MISS: dict[str, Any] = {
    "type": "cache_miss",
    "reason": "tools_changed",
    "cache_missed_tokens": 812,
}
"""The diagnostic that matters most: the one lever 4 will be priced with."""

REASONS = (
    "model_changed",
    "prompt_cache_key_changed",
    "tools_changed",
    "text_format_changed",
    "reasoning_effort_changed",
    "verbosity_changed",
    "context_compacted",
    "input_changed",
    "service_tier_changed",
)
"""The miss-reason enum as contracts/usage.md section 7 copies it, asserted below."""


# --- helpers ----------------------------------------------------------------------------


def completed_as(
    response_id: str, *output: dict[str, Any], diagnostics: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A `response.completed` event with its own id, and optionally a diagnostic.

    The id matters: `comparison_response_id` must be the *previous* round's response, and
    a fixture where every response shares one id could not tell that from the first.
    """
    event = completed(*output)
    event["response"]["id"] = response_id
    if diagnostics is not None:
        event["response"]["prompt_cache_diagnostics"] = diagnostics
    return event


def cached_provider(session_id: str) -> OpenAIProvider:
    """An adapter with lever 3 on, configured the way `start_review` configures it."""
    provider = OpenAIProvider(model=MODEL, max_output_tokens=CEILING, client=make_client())
    provider.use_prompt_cache(session_id)
    return provider


def review(
    package_dir: Path, out_dir: Path, *, efficiency: EfficiencySettings
) -> tuple[ReviewRun, OpenAIProvider]:
    """A real run over the fixture package, driving the real adapter on a recorded client."""
    provider = OpenAIProvider(model=MODEL, max_output_tokens=CEILING, client=make_client())
    run = start_review(package_dir, out_dir, provider=provider, efficiency=efficiency)
    return run, provider


# --- the package facts this lever rests on ----------------------------------------------


def test_the_installed_sdk_still_names_every_prompt_cache_field_this_lever_uses() -> None:
    """One test for every VERIFIED claim in research.md R-L3, against the real package."""
    parameters = inspect.signature(Responses.create).parameters
    assert "prompt_cache_key" in parameters
    assert "prompt_cache_options" in parameters
    # The SDK keeps its annotations as strings, so they are read as written.
    assert parameters["prompt_cache_key"].annotation.startswith("Optional[str]")

    options = {name: str(hint) for name, hint in PromptCacheOptions.__annotations__.items()}
    assert set(options) == {"comparison_response_id", "mode", "ttl"}
    assert "Optional[str]" in options["comparison_response_id"]
    assert "'implicit', 'explicit'" in options["mode"]
    assert "'30m'" in options["ttl"], "the only supported ttl; we send neither it nor the mode"

    assert "prompt_cache_diagnostics" in Response.model_fields
    assert "prompt_cache_key" in Response.model_fields
    reason = PromptCacheDiagnosticsCacheMiss.model_fields["reason"].annotation
    assert get_args(reason) == REASONS
    assert "cache_missed_tokens" in PromptCacheDiagnosticsCacheMiss.model_fields


def test_the_adapter_is_the_one_provider_that_can_name_a_cache() -> None:
    """The optional port extension `start_review` looks for, and nothing wider."""
    from swreview.agent.providers.fake import FakeProvider

    assert isinstance(cached_provider("s"), PromptCacheAware)
    assert not isinstance(FakeProvider(script=(), model="fake-1"), PromptCacheAware)


# --- the flag is the whole switch -------------------------------------------------------


@respx.mock
def test_with_the_lever_off_the_request_carries_no_cache_key_and_no_cache_options() -> None:
    """A flag-off run sends exactly what feature 001 sent."""
    route = respx.post(RESPONSES_URL).mock(
        return_value=stream_response(completed_as("resp_a", message_item("done")))
    )

    run(OpenAIProvider(model=MODEL, max_output_tokens=CEILING, client=make_client()))

    body = request_bodies(route)[0]
    assert "prompt_cache_key" not in body
    assert "prompt_cache_options" not in body


@respx.mock
def test_start_review_with_the_lever_off_sends_no_cache_key(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """Through the real entry point, because that is where the flag is read."""
    route = respx.post(RESPONSES_URL).mock(
        return_value=stream_response(completed_as("resp_a", message_item("done")))
    )
    review_run, provider = review(
        tmp_package_dir, tmp_path / "off", efficiency=EfficiencySettings()
    )
    try:
        review_run.start()
    finally:
        review_run.close()

    assert provider.prompt_cache_key is None
    assert "prompt_cache_key" not in request_bodies(route)[0]


@respx.mock
def test_start_review_with_the_lever_on_sends_the_session_id_as_the_cache_key(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """The key is the session id, and it is the one written to `session.json`."""
    route = respx.post(RESPONSES_URL).mock(
        return_value=stream_response(completed_as("resp_a", message_item("done")))
    )
    review_run, provider = review(
        tmp_package_dir, tmp_path / "on", efficiency=EfficiencySettings(prompt_cache_key=True)
    )
    try:
        review_run.start()
        persisted = load_session(review_run.session_path)
    finally:
        review_run.close()

    expected = str(review_run.session.session_id)
    assert provider.prompt_cache_key == expected
    assert request_bodies(route)[0]["prompt_cache_key"] == expected
    assert str(persisted.session_id) == expected


@respx.mock
def test_the_cache_key_survives_a_process_restart_because_it_is_read_off_disk(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """The failure a process-local value would cause, reproduced and refused.

    The second half of this test is what a restarted backend does: nothing of the first
    adapter survives, and the key is rebuilt from `session.json` alone. A random
    per-process value would pass every assertion above this one and fail this one.
    """
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(completed_as("resp_a", message_item("done")))
    )
    review_run, _ = review(
        tmp_package_dir, tmp_path / "on", efficiency=EfficiencySettings(prompt_cache_key=True)
    )
    try:
        review_run.start()
    finally:
        review_run.close()
    first = str(review_run.session.session_id)

    route = respx.post(RESPONSES_URL).mock(
        return_value=stream_response(completed_as("resp_b", message_item("resumed")))
    )
    resumed = load_session((tmp_path / "on") / "session.json")
    run(cached_provider(str(resumed.session_id)))

    assert request_bodies(route)[0]["prompt_cache_key"] == first


# --- the diagnostics are requested against the previous round ---------------------------


@respx.mock
def test_each_round_after_the_first_compares_against_the_round_before_it() -> None:
    """`comparison_response_id` is the previous response, not the turn's first one."""
    route = respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(completed_as("resp_a", function_call_item(call_id="call_1"))),
            stream_response(completed_as("resp_b", function_call_item(call_id="call_2"))),
            stream_response(completed_as("resp_c", message_item("done"))),
        ]
    )

    run(cached_provider("sess-1"), tools=[FakeTool(name="get_component")])

    bodies = request_bodies(route)
    assert "prompt_cache_options" not in bodies[0]
    assert bodies[1]["prompt_cache_options"] == {"comparison_response_id": "resp_a"}
    assert bodies[2]["prompt_cache_options"] == {"comparison_response_id": "resp_b"}
    assert [body["prompt_cache_key"] for body in bodies] == ["sess-1"] * 3


@respx.mock
def test_a_new_turn_compares_against_nothing_because_the_adapter_sees_one_turn() -> None:
    """The counter resets with `round_usage`: an adapter's state is per turn (T006)."""
    route = respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(completed_as("resp_a", message_item("one"))),
            stream_response(completed_as("resp_b", message_item("two"))),
        ]
    )
    provider = cached_provider("sess-1")

    first, _ = run(provider)
    run(provider, messages=[*first.messages, {"role": "user", "content": "again"}])

    bodies = request_bodies(route)
    assert "prompt_cache_options" not in bodies[0]
    assert "prompt_cache_options" not in bodies[1]


# --- what the diagnostic becomes on the usage event -------------------------------------


@respx.mock
def test_a_miss_is_recorded_verbatim_with_its_reason_and_missed_tokens() -> None:
    """Not flattened and not summarised: this object is how lever 4 gets priced."""
    respx.post(RESPONSES_URL).mock(
        side_effect=[
            stream_response(completed_as("resp_a", function_call_item())),
            stream_response(
                completed_as("resp_b", message_item("done"), diagnostics=CACHE_MISS)
            ),
        ]
    )

    _, sink = run(cached_provider("sess-1"), tools=[FakeTool(name="get_component")])

    bodies = sink.bodies("usage")
    assert len(bodies) == 2
    assert bodies[0]["cache_diagnostic"] is None
    assert bodies[1]["cache_diagnostic"] == CACHE_MISS


@respx.mock
def test_a_hit_is_recorded_as_the_hit_member_and_nothing_else() -> None:
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(
            completed_as("resp_a", message_item("done"), diagnostics={"type": "cache_hit"})
        )
    )

    _, sink = run(cached_provider("sess-1"))

    assert sink.one("usage")["cache_diagnostic"] == {"type": "cache_hit"}


@pytest.mark.parametrize(
    "diagnostics",
    [{"type": "comparison_response_not_found"}, {"type": "unavailable"}],
)
@respx.mock
def test_the_two_no_answer_members_are_recorded_rather_than_dropped(
    diagnostics: dict[str, Any],
) -> None:
    """"The comparison is gone" and "no diagnostic for this request" are answers."""
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(
            completed_as("resp_a", message_item("done"), diagnostics=diagnostics)
        )
    )

    _, sink = run(cached_provider("sess-1"))

    assert sink.one("usage")["cache_diagnostic"] == diagnostics


@respx.mock
def test_a_response_with_no_diagnostic_records_none_and_never_a_hit() -> None:
    """Unknown stays unknown: a silent `cache_hit` would overstate every A/B row."""
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(completed_as("resp_a", message_item("done")))
    )

    _, sink = run(cached_provider("sess-1"))

    assert sink.one("usage")["cache_diagnostic"] is None


@respx.mock
def test_with_the_lever_off_the_usage_event_still_carries_the_null_field() -> None:
    """The `usage` body is additively unchanged, which keeps feature 001 goldens valid."""
    respx.post(RESPONSES_URL).mock(
        return_value=stream_response(completed_as("resp_a", message_item("done")))
    )

    _, sink = run(OpenAIProvider(model=MODEL, max_output_tokens=CEILING, client=make_client()))

    body = sink.one("usage")
    assert body["cache_diagnostic"] is None
    assert json.dumps(body)  # the body is still JSON, which is what the sink writes
