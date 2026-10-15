"""Request retries shared by adapters, with call-time seams for backoff."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from random import uniform
from time import sleep
from typing import Any, TypeVar

from pydantic import ConfigDict, Field

from swreview.agent.providers import EventCallback, EventType, ProviderError, ProviderModel


class RetryPolicy(ProviderModel):
    """The retries after a first try, and their bounded full-jitter backoff."""

    model_config = ConfigDict(frozen=True)

    retries: int = Field(ge=0)
    initial_delay_s: float = Field(ge=0, allow_inf_nan=False)
    max_delay_s: float = Field(ge=0, allow_inf_nan=False)


BENCHMARK_RETRY = RetryPolicy(retries=5, initial_delay_s=2.0, max_delay_s=60.0)

_Result = TypeVar("_Result")


def run_request(
    request: Callable[[EventCallback], _Result],
    *,
    policy: RetryPolicy,
    stop_requested: Callable[[], bool],
    on_event: EventCallback,
) -> tuple[_Result, int]:
    """Run one request without replaying visible text or a provider-reported stop.

    Adapters build failures without announcing them here, then emit only the final
    failure. The same failure instance escapes, carrying the retries actually made.
    """
    retries = 0
    emitted_delta = False
    ceiling = min(policy.initial_delay_s, policy.max_delay_s)

    def emit(kind: EventType, body: Mapping[str, Any]) -> None:
        nonlocal emitted_delta
        if kind == "text.delta":
            emitted_delta = True
        on_event(kind, body)

    while True:
        try:
            return request(emit), retries
        except ProviderError as error:
            error.retries = retries
            if (
                emitted_delta
                or error.stop_reason is not None
                or not error.retryable
                or retries >= policy.retries
                or stop_requested()
            ):
                raise
            delay = min(
                policy.max_delay_s,
                max(uniform(0, ceiling), getattr(error, "retry_after_s", None) or 0.0),
            )
            if stop_requested():
                raise
            sleep(delay)
            if stop_requested():
                raise
            retries += 1
            ceiling = min(policy.max_delay_s, ceiling * 2)
