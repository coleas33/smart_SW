"""Request retries through the real OpenAI adapter over recorded HTTP exchanges."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest
import respx
from openai import OpenAI
from pydantic import ValidationError

from swreview.agent.providers import ProviderError
from swreview.agent.providers.openai_provider import OpenAIProvider, OpenAIProviderError
from tests.support.toolsets import toolset

URL = "https://api.openai.com/v1/responses"
MODEL = "fict-model-a-2026-10-01"


def _retry() -> Any:
    # Import inside each test so the test-first run names every missing behavior.
    from swreview.agent.providers import retry

    return retry


def _response(*, output: list[dict[str, Any]] | None = None, **fields: Any) -> dict[str, Any]:
    return {
        "id": "resp_fict",
        "object": "response",
        "created_at": 0,
        "model": MODEL,
        "status": "completed",
        "output": output or [],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        **fields,
    }


def _stream(*events: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text="".join(
            "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"
            for event in events
        ),
    )


def _complete(*, output: list[dict[str, Any]] | None = None) -> httpx.Response:
    return _stream(
        {"type": "response.completed", "sequence_number": 9, "response": _response(output=output)}
    )


def _failed(code: str | None = "server_error", *, delta: bool = False) -> httpx.Response:
    events: list[dict[str, Any]] = []
    if delta:
        events.append(
            {
                "type": "response.output_text.delta",
                "delta": "fict partial text",
                "item_id": "msg_fict",
                "output_index": 0,
                "content_index": 0,
                "logprobs": [],
                "sequence_number": 1,
            }
        )
    events.append(
        {
            "type": "response.failed",
            "sequence_number": 9,
            "response": _response(
                status="failed", error={"code": code, "message": "fict transient failure"}
            ),
        }
    )
    return _stream(*events)


def _http_error(
    status: int = 500, *, code: str | None = None, retry_after: str | None = None
) -> httpx.Response:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return httpx.Response(
        status,
        headers=headers,
        json={"error": {"message": "fict request failure", "code": code}},
    )


def _provider(*, library_retries: int = 0) -> OpenAIProvider:
    return OpenAIProvider(
        model=MODEL,
        max_output_tokens=1200,
        client=OpenAI(
            api_key="fict-key", http_client=httpx.Client(), max_retries=library_retries
        ),
    )


def _run(
    provider: OpenAIProvider, events: list[tuple[str, dict[str, Any]]]
) -> Any:
    return provider.run(
        system="fict system",
        messages=[{"role": "user", "content": "fict review"}],
        tools=toolset([]),
        effort="high",
        max_steps=10,
        on_event=lambda kind, body: events.append((kind, dict(body))),
    )


def _bodies(events: list[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [body for event_kind, body in events if event_kind == kind]


def _enable(
    provider: OpenAIProvider, monkeypatch: pytest.MonkeyPatch, *, retries: int = 2
) -> list[float]:
    retry = _retry()
    sleeps: list[float] = []
    monkeypatch.setattr(retry, "sleep", sleeps.append)
    monkeypatch.setattr(retry, "uniform", lambda low, high: high / 2)
    provider.use_retry(
        retry.RetryPolicy(retries=retries, initial_delay_s=2.0, max_delay_s=5.0),
        stop_requested=lambda: False,
    )
    return sleeps


def test_retry_policy_is_frozen_strict_nonnegative_and_json_serializable() -> None:
    retry = _retry()
    policy = retry.RetryPolicy(retries=5, initial_delay_s=2.0, max_delay_s=60.0)
    assert retry.BENCHMARK_RETRY == policy
    assert policy.model_dump(mode="json") == {
        "retries": 5,
        "initial_delay_s": 2.0,
        "max_delay_s": 60.0,
    }
    with pytest.raises(ValidationError):
        policy.retries = 1
    for invalid in (
        {"retries": -1},
        {"initial_delay_s": -1.0},
        {"max_delay_s": -1.0},
        {"extra": 1},
    ):
        fields = {"retries": 1, "initial_delay_s": 2.0, "max_delay_s": 5.0, **invalid}
        with pytest.raises(ValidationError):
            retry.RetryPolicy(**fields)


@respx.mock
def test_full_jitter_backoff_draws_within_the_capped_doubling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry = _retry()
    provider = _provider()
    sleeps = _enable(provider, monkeypatch, retries=4)
    bounds: list[tuple[float, float]] = []
    seeded = random.Random(176)

    def draw(low: float, high: float) -> float:
        bounds.append((low, high))
        return seeded.uniform(low, high)

    monkeypatch.setattr(retry, "uniform", draw)
    route = respx.post(URL).mock(
        side_effect=[_http_error() for _ in range(4)] + [_complete()]
    )
    events: list[tuple[str, dict[str, Any]]] = []
    _run(provider, events)
    expected_random = random.Random(176)
    assert bounds == [(0, 2.0), (0, 4.0), (0, 5.0), (0, 5.0)]
    assert sleeps == [expected_random.uniform(low, high) for low, high in bounds]
    assert route.call_count == 5
    assert _bodies(events, "usage")[0]["retries"] == 4
    assert not _bodies(events, "error")


@pytest.mark.parametrize("header,expected", [("3.5", 3.5), ("120", 5.0), ("0", 1.0)])
@respx.mock
def test_retry_after_raises_the_delay_up_to_the_cap(
    monkeypatch: pytest.MonkeyPatch, header: str, expected: float
) -> None:
    _retry()
    provider = _provider()
    sleeps = _enable(provider, monkeypatch)
    respx.post(URL).mock(side_effect=[_http_error(429, retry_after=header), _complete()])
    _run(provider, [])
    assert sleeps == [expected]


@respx.mock
def test_retry_after_http_date_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    _retry()
    provider = _provider()
    sleeps = _enable(provider, monkeypatch)
    future = format_datetime(datetime.now(UTC) + timedelta(minutes=5), usegmt=True)
    respx.post(URL).mock(side_effect=[_http_error(429, retry_after=future), _complete()])
    _run(provider, [])
    assert sleeps == [5.0]


@respx.mock
def test_a_request_is_retried_only_before_its_first_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _retry()
    provider = _provider()
    sleeps = _enable(provider, monkeypatch)
    route = respx.post(URL).mock(side_effect=[_failed(delta=True), _complete()])
    events: list[tuple[str, dict[str, Any]]] = []
    with pytest.raises(OpenAIProviderError) as caught:
        _run(provider, events)
    assert route.call_count == 1
    assert sleeps == []
    assert _bodies(events, "text.delta") == [{"text": "fict partial text"}]
    assert _bodies(events, "usage") == []
    assert len(_bodies(events, "error")) == 1
    assert _bodies(events, "error")[0]["retries"] == 0
    assert caught.value.retries == 0


@pytest.mark.parametrize("code", ["server_error", "rate_limit_exceeded", None])
@pytest.mark.parametrize("exhausted", [False, True])
@respx.mock
def test_a_failed_response_before_any_delta_is_retried_with_no_error_event_on_the_stream(
    monkeypatch: pytest.MonkeyPatch, code: str | None, exhausted: bool
) -> None:
    _retry()
    provider = _provider()
    _enable(provider, monkeypatch, retries=1)
    route = respx.post(URL).mock(
        side_effect=[_failed(code), _failed(code) if exhausted else _complete()]
    )
    events: list[tuple[str, dict[str, Any]]] = []
    if exhausted:
        with pytest.raises(OpenAIProviderError) as caught:
            _run(provider, events)
        assert caught.value.error_class == "ResponseFailedError"
        assert caught.value.retries == 1
        assert _bodies(events, "usage") == []
        assert len(_bodies(events, "error")) == 1
        assert _bodies(events, "error")[0]["retries"] == 1
    else:
        _run(provider, events)
        assert _bodies(events, "error") == []
        assert len(_bodies(events, "usage")) == 1
        assert _bodies(events, "usage")[0]["retries"] == 1
    assert route.call_count == 2


@pytest.mark.parametrize("exhausted", [False, True])
@respx.mock
def test_a_stream_that_ended_without_a_response_is_retried_with_no_error_event_on_the_stream(
    monkeypatch: pytest.MonkeyPatch, exhausted: bool
) -> None:
    _retry()
    provider = _provider()
    _enable(provider, monkeypatch, retries=1)
    route = respx.post(URL).mock(side_effect=[_stream(), _stream() if exhausted else _complete()])
    events: list[tuple[str, dict[str, Any]]] = []
    if exhausted:
        with pytest.raises(OpenAIProviderError) as caught:
            _run(provider, events)
        assert caught.value.error_class == "IncompleteStreamError"
        assert caught.value.retries == 1
        assert _bodies(events, "usage") == []
        assert len(_bodies(events, "error")) == 1
        assert _bodies(events, "error")[0]["retries"] == 1
    else:
        _run(provider, events)
        assert _bodies(events, "error") == []
        assert len(_bodies(events, "usage")) == 1
        assert _bodies(events, "usage")[0]["retries"] == 1
    assert route.call_count == 2


@pytest.mark.parametrize("when", ["before_retry", "before_sleep", "during_sleep"])
@respx.mock
def test_no_request_is_retried_after_the_attempt_stop_is_set(
    monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    retry = _retry()
    provider = _provider()
    stopped = when == "before_retry"
    sleeps: list[float] = []

    def draw(low: float, high: float) -> float:
        nonlocal stopped
        if when == "before_sleep":
            stopped = True
        return high

    def sleep(delay: float) -> None:
        nonlocal stopped
        sleeps.append(delay)
        if when == "during_sleep":
            stopped = True

    monkeypatch.setattr(retry, "uniform", draw)
    monkeypatch.setattr(retry, "sleep", sleep)
    provider.use_retry(
        retry.RetryPolicy(retries=2, initial_delay_s=2.0, max_delay_s=5.0),
        stop_requested=lambda: stopped,
    )
    route = respx.post(URL).mock(side_effect=[_http_error(), _complete()])
    events: list[tuple[str, dict[str, Any]]] = []
    with pytest.raises(OpenAIProviderError) as caught:
        _run(provider, events)
    assert caught.value.error_class == "InternalServerError"
    assert caught.value.retries == 0
    assert route.call_count == 1
    assert sleeps == ([2.0] if when == "during_sleep" else [])
    assert len(_bodies(events, "error")) == 1
    assert _bodies(events, "error")[0]["retries"] == 0


@pytest.mark.parametrize("retries", [0, 2])
@pytest.mark.parametrize("exhausted", [False, True])
@respx.mock
def test_retries_are_counted_on_the_usage_and_error_bodies(
    monkeypatch: pytest.MonkeyPatch, retries: int, exhausted: bool
) -> None:
    _retry()
    provider = _provider()
    _enable(provider, monkeypatch, retries=retries)
    attempts = [_http_error() for _ in range(retries)]
    attempts.append(_http_error() if exhausted else _complete())
    route = respx.post(URL).mock(side_effect=attempts)
    events: list[tuple[str, dict[str, Any]]] = []
    if exhausted:
        with pytest.raises(OpenAIProviderError) as caught:
            _run(provider, events)
        assert caught.value.retries == retries
        assert _bodies(events, "usage") == []
        measured = _bodies(events, "error")
    else:
        _run(provider, events)
        assert _bodies(events, "error") == []
        measured = _bodies(events, "usage")
    assert len(measured) == 1
    assert measured[0]["retries"] == retries
    assert route.call_count == retries + 1


@respx.mock
def test_the_retry_count_resets_for_each_round(monkeypatch: pytest.MonkeyPatch) -> None:
    _retry()
    provider = _provider()
    _enable(provider, monkeypatch)
    call = {
        "type": "function_call",
        "id": "fc_fict",
        "call_id": "call_fict",
        "name": "fict_unknown_tool",
        "arguments": "{}",
        "status": "completed",
    }
    route = respx.post(URL).mock(
        side_effect=[_http_error(), _complete(output=[call]), _complete()]
    )
    events: list[tuple[str, dict[str, Any]]] = []
    _run(provider, events)
    assert route.call_count == 3
    assert [body["retries"] for body in _bodies(events, "usage")] == [1, 0]
    assert [body["round_index"] for body in _bodies(events, "usage")] == [0, 1]
    assert _bodies(events, "error") == []


@respx.mock
def test_no_policy_keeps_the_library_defaults_and_writes_no_retries_field() -> None:
    _retry()
    provider = _provider(library_retries=2)
    assert provider._client.max_retries == 2
    route = respx.post(URL).mock(side_effect=[_complete(), _http_error(400, code="invalid_prompt")])
    events: list[tuple[str, dict[str, Any]]] = []
    _run(provider, events)
    assert _bodies(events, "usage")[0]["served_model"] == MODEL
    assert "retries" not in _bodies(events, "usage")[0]
    with pytest.raises(OpenAIProviderError):
        _run(provider, events)
    assert _bodies(events, "error")[0]["stop_reason"] == "invalid_prompt"
    assert "retries" not in _bodies(events, "error")[0]
    assert [kind for kind, _ in events] == ["usage", "error"]
    assert provider._client.max_retries == 2
    assert route.call_count == 2


def test_a_policy_turns_the_openai_library_retries_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _retry()
    from swreview.agent.providers import RetryAware

    provider = _provider(library_retries=2)
    assert isinstance(provider, RetryAware)
    original = provider._client
    calls: list[dict[str, Any]] = []
    real_with_options = original.with_options

    def with_options(**options: Any) -> OpenAI:
        calls.append(options)
        return real_with_options(**options)

    monkeypatch.setattr(original, "with_options", with_options)
    _enable(provider, monkeypatch)
    assert calls == [{"max_retries": 0}]
    assert provider._client is not original
    assert provider._client.max_retries == 0
    assert original.max_retries == 2


@respx.mock
def test_for_presentation_keeps_the_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _retry()
    provider = _provider()
    sleeps = _enable(provider, monkeypatch)
    presentation = provider.for_presentation(300)
    route = respx.post(URL).mock(side_effect=[_http_error(), _complete()])
    events: list[tuple[str, dict[str, Any]]] = []
    _run(presentation, events)
    assert route.call_count == 2
    assert sleeps == [1.0]
    assert _bodies(events, "usage")[0]["retries"] == 1
    assert presentation._client.max_retries == 0


@pytest.mark.parametrize(
    "kind,code",
    [
        ("failed", "invalid_prompt"),
        ("failed", "fict_policy_stop"),
        ("bad_request", "invalid_prompt"),
        ("bad_request", "bio_policy"),
        ("bad_request", "misalignment_policy_violation"),
        ("bad_request", "image_content_policy_violation"),
        ("bad_request", "context_length_exceeded"),
        ("bad_request", "fict_other_code"),
        ("authentication", None),
    ],
)
@respx.mock
def test_provider_stops_and_non_retryable_errors_are_never_retried(
    monkeypatch: pytest.MonkeyPatch, kind: str, code: str | None
) -> None:
    _retry()
    provider = _provider()
    sleeps = _enable(provider, monkeypatch)
    failure = (
        _failed(code)
        if kind == "failed"
        else _http_error(401 if kind == "authentication" else 400, code=code)
    )
    route = respx.post(URL).mock(side_effect=[failure, _complete()])
    events: list[tuple[str, dict[str, Any]]] = []
    with pytest.raises(OpenAIProviderError) as caught:
        _run(provider, events)
    assert route.call_count == 1
    assert sleeps == []
    assert caught.value.retryable is (kind == "failed")
    assert len(_bodies(events, "error")) == 1
    assert _bodies(events, "error")[0]["retries"] == 0


@respx.mock
def test_an_incomplete_provider_stop_counts_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _retry()
    provider = _provider()
    _enable(provider, monkeypatch)
    incomplete = _stream(
        {
            "type": "response.incomplete",
            "sequence_number": 9,
            "response": _response(
                status="incomplete", incomplete_details={"reason": "content_filter"}
            ),
        }
    )
    route = respx.post(URL).mock(side_effect=[_http_error(), incomplete, _complete()])
    events: list[tuple[str, dict[str, Any]]] = []
    with pytest.raises(OpenAIProviderError) as caught:
        _run(provider, events)
    assert caught.value.stop_reason == "content_filter"
    assert route.call_count == 2
    assert len(_bodies(events, "usage")) == 1
    assert _bodies(events, "usage")[0]["served_model"] == MODEL
    assert _bodies(events, "usage")[0]["retries"] == 0
    assert len(_bodies(events, "error")) == 1
    assert _bodies(events, "error")[0]["retries"] == 1
    assert sum(body["retries"] for kind, body in events if kind in {"usage", "error"}) == 1


def test_stopping_retries_raises_the_original_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry = _retry()
    provider = _provider()
    sleeps: list[float] = []
    monkeypatch.setattr(retry, "sleep", sleeps.append)
    provider.use_retry(retry.BENCHMARK_RETRY, stop_requested=lambda: True)
    error = ProviderError("fict original failure")
    error.retryable = True
    attempts = 0

    def create(**kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        raise error

    monkeypatch.setattr(provider._client.responses, "create", create)
    events: list[tuple[str, dict[str, Any]]] = []
    with pytest.raises(ProviderError) as caught:
        _run(provider, events)
    assert caught.value is error
    assert caught.value.retries == 0
    assert attempts == 1
    assert sleeps == []
    assert len(_bodies(events, "error")) == 1
    assert _bodies(events, "error")[0]["retries"] == 0


@respx.mock
def test_a_carried_empty_stop_reason_prevents_a_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _retry()
    provider = _provider()
    sleeps = _enable(provider, monkeypatch)
    route = respx.post(URL).mock(side_effect=[_failed(""), _complete()])
    events: list[tuple[str, dict[str, Any]]] = []
    with pytest.raises(OpenAIProviderError) as caught:
        _run(provider, events)
    assert caught.value.stop_reason == ""
    assert caught.value.retries == 0
    assert route.call_count == 1
    assert sleeps == []
    assert len(_bodies(events, "error")) == 1
    assert _bodies(events, "error")[0]["retries"] == 0
    assert _bodies(events, "error")[0]["stop_reason"] == ""


@respx.mock
def test_reasoning_fallback_does_not_retry_after_the_stop_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry = _retry()
    provider = _provider()
    sleeps = _enable(provider, monkeypatch)
    stopped = False
    provider.use_retry(retry.BENCHMARK_RETRY, stop_requested=lambda: stopped)

    def with_reasoning_kept(
        request: dict[str, Any], visible: Any, refused: Any
    ) -> dict[str, Any]:
        nonlocal stopped
        stopped = True
        return dict(request)

    monkeypatch.setattr(provider, "_with_reasoning_kept", with_reasoning_kept)
    route = respx.post(URL).mock(side_effect=[_http_error(400), _complete()])
    events: list[tuple[str, dict[str, Any]]] = []
    with pytest.raises(OpenAIProviderError) as caught:
        _run(provider, events)
    assert caught.value.error_class == "BadRequestError"
    assert caught.value.retries == 0
    assert route.call_count == 1
    assert sleeps == []
    assert len(_bodies(events, "error")) == 1
    assert _bodies(events, "error")[0]["retries"] == 0
