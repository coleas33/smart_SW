"""Classify an attempt's live events and bound its daemon worker by a wall clock."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from swreview.agent.providers import AgentEvent, ProviderError, ProviderName, usage_from_body
from swreview.benchmark.scrub import one_line
from swreview.benchmark.served import aliases

STREAM_ACTIVITY_WINDOW_S = 600
STOP_GRACE_S = 900
WAIT_SLICE_S = 1.0

AttemptKind = Literal["completed", "behavioural", "infrastructure"]
AttemptClass = Literal[
    "provider_error", "wrong_model", "served_model_changed", "wall_clock_silent",
    "abandoned", "internal_error", "interrupted", "max_steps", "truncated",
    "provider_stop", "wall_clock",
]
_WorkerResult = tuple[object, BaseException | None, float]


@dataclass(frozen=True)
class AttemptOutcome:
    kind: AttemptKind
    class_: AttemptClass | None = None
    stop_reason: str | None = None
    error_class: str | None = None
    message: str | None = None
    stream_active_at_limit: bool | None = None


class AttemptListener:
    """Observe activity and stops without letting a callback failure escape a round."""

    def __init__(
        self,
        stop: threading.Event,
        *,
        provider: ProviderName | str,
        requested_model: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.stop = stop
        self.provider = provider
        self.requested_model = requested_model
        self.clock = clock
        self.last_event_at: float | None = None
        self.turn_end_reasons: list[str] = []
        self._tools_in_progress: set[int] = set()
        self._round_answered = False
        self._provider_stop_seen = False
        self._conditions: list[AttemptOutcome] = []
        self._lock = threading.RLock()

    @property
    def round_answered(self) -> bool:
        with self._lock:
            return self._round_answered

    @property
    def conditions(self) -> tuple[AttemptOutcome, ...]:
        with self._lock:
            return tuple(self._conditions)

    def _record(self, condition: AttemptOutcome, *, index: int | None = None) -> None:
        with self._lock:
            if index is None:
                self._conditions.append(condition)
            else:
                self._conditions.insert(index, condition)

    def __call__(self, event: AgentEvent) -> None:
        try:
            with self._lock:
                self.last_event_at = self.clock()
                body = event.body
                if event.type == "tool.started":
                    self._tools_in_progress.add(body["step_index"])
                elif event.type == "tool.finished":
                    self._tools_in_progress.discard(body["step_index"])
                elif event.type == "turn.ended":
                    reason = body["reason"]
                    self.turn_end_reasons.append(reason)
                    if reason == "stopped":
                        self._tools_in_progress.clear()
                    if reason in {"max_steps", "truncated"}:
                        self._record(AttemptOutcome("behavioural", reason))
                elif event.type == "error" and body.get("stop_reason") is not None:
                    if not isinstance(body["stop_reason"], str):
                        raise TypeError("stop_reason must be a string")
                    if not self._provider_stop_seen:
                        self._provider_stop_seen = True
                        self._record(AttemptOutcome(
                            "behavioural", "provider_stop", stop_reason=body["stop_reason"],
                            error_class=body.get("error_class"),
                            message=(
                                one_line(body["message"], preserve_spacing=True)
                                if "message" in body else None
                            ),
                        ))
                elif event.type == "usage":
                    usage_from_body(body)
                    self._round_answered = True
                    served = body.get("served_model")
                    if served is not None:
                        if not isinstance(served, str):
                            raise TypeError("served_model must be a string")
                        if not aliases(self.provider, self.requested_model, served):
                            self._record(AttemptOutcome(
                                "infrastructure", "wrong_model",
                                message=(
                                    f"served model {served!r} is outside the aliases for "
                                    f"requested model {self.requested_model!r}"
                                ),
                            ))
                            self.stop.set()
        except Exception as error:
            self._record(AttemptOutcome(
                "infrastructure", "internal_error", error_class=type(error).__name__,
                message=(
                    f"attempt listener {type(error).__name__}: "
                    f"{one_line(error, preserve_spacing=True)}"
                ),
            ))
            self.stop.set()

    def stream_active(self, now: float, window_s: float) -> bool:
        with self._lock:
            return bool(self._tools_in_progress) or (
                self.last_event_at is not None and now - self.last_event_at <= window_s
            )


def _exception_condition(error: BaseException, listener: AttemptListener) -> AttemptOutcome:
    error_class = getattr(error, "error_class", type(error).__name__)
    message = one_line(error, preserve_spacing=True)
    if isinstance(error, ProviderError):
        reason = error.stop_reason
        if reason is None and listener.round_answered:
            from swreview.agent.providers.gemini_provider import GeminiRequestError

            if isinstance(error, GeminiRequestError):
                reason = "input_token_limit_inferred"
        if reason is not None:
            return AttemptOutcome(
                "behavioural", "provider_stop", stop_reason=reason,
                error_class=error_class, message=message,
            )
        return AttemptOutcome(
            "infrastructure", "provider_error", error_class=error_class, message=message,
        )
    return AttemptOutcome(
        "infrastructure", "internal_error", error_class=error_class, message=message,
    )


def _classify(
    listener: AttemptListener, error: BaseException | None, active_at_limit: bool | None,
) -> AttemptOutcome:
    if error is not None:
        listener._record(_exception_condition(error, listener))
    conditions = listener.conditions
    for kind in ("infrastructure", "behavioural"):
        for condition in conditions:
            if condition.kind == kind:
                return replace(condition, stream_active_at_limit=active_at_limit)
    return AttemptOutcome("completed", stream_active_at_limit=active_at_limit)


def run_attempt(
    body: Callable[[], object],
    *,
    stop: threading.Event,
    listener: AttemptListener,
    limit_s: float,
    activity_window_s: float = STREAM_ACTIVITY_WINDOW_S,
    grace_s: float = STOP_GRACE_S,
    clock: Callable[[], float] = time.monotonic,
    wait_slice_s: float = WAIT_SLICE_S,
    wait_for_result: Callable[[queue.Queue[_WorkerResult], float], _WorkerResult] | None = None,
) -> AttemptOutcome:
    """Wait in short slices; a worker surviving its stop grace is left as a daemon.

    `wait_for_result` defaults to the queue's timed get; tests can drive that wait
    with the same clock as the worker and listener.
    """
    if wait_slice_s <= 0:
        raise ValueError("wait_slice_s must be above zero")
    results: queue.Queue[_WorkerResult] = queue.Queue()

    def work() -> None:
        value: object = None
        failure: BaseException | None = None
        try:
            value = body()
        except BaseException as error:
            failure = error
        results.put((value, failure, clock()))

    deadline = clock() + limit_s
    grace_deadline: float | None = None
    active_at_limit: bool | None = None
    limit_condition: AttemptOutcome | None = None
    limit_condition_index = 0

    def reach_limit(now: float) -> None:
        nonlocal active_at_limit, grace_deadline, limit_condition, limit_condition_index
        if grace_deadline is None and now >= deadline:
            active_at_limit = listener.stream_active(now, activity_window_s)
            limit_condition = AttemptOutcome(
                "behavioural" if active_at_limit else "infrastructure",
                "wall_clock" if active_at_limit else "wall_clock_silent",
                message="package wall clock limit reached",
            )
            limit_condition_index = len(listener.conditions)
            stop.set()
            grace_deadline = deadline + grace_s

    def abandoned() -> AttemptOutcome:
        return AttemptOutcome(
            "infrastructure", "abandoned",
            message="attempt worker did not return within the stop grace",
            stream_active_at_limit=active_at_limit,
        )

    def finish(error: BaseException | None, completed_at: float) -> AttemptOutcome:
        # A worker can finish before the deadline and still be waiting to queue
        # its result when the driver observes the limit.
        if completed_at < deadline:
            return _classify(listener, error, None)
        reach_limit(completed_at)
        if grace_deadline is not None and completed_at > grace_deadline:
            return abandoned()
        if limit_condition is not None:
            listener._record(limit_condition, index=limit_condition_index)
        return _classify(listener, error, active_at_limit)

    worker = threading.Thread(target=work, daemon=True)
    try:
        worker.start()
        while True:
            now = clock()
            # This driver is the queue's only consumer, so a ready result cannot
            # disappear between this check and the non-blocking read.
            if not results.empty():
                _value, error, completed_at = results.get_nowait()
                return finish(error, completed_at)
            reach_limit(now)
            wait_until = deadline if grace_deadline is None else grace_deadline
            remaining = wait_until - now
            if grace_deadline is not None and remaining <= 0:
                return abandoned()
            try:
                timeout = min(wait_slice_s, remaining)
                _value, error, completed_at = (
                    results.get(timeout=timeout) if wait_for_result is None
                    else wait_for_result(results, timeout)
                )
            except queue.Empty:
                continue
            return finish(error, completed_at)
    except KeyboardInterrupt:
        stop.set()
        raise
