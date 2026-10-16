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

PACKAGE_TIME_LIMIT_S = 3600
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
        run_served_models: tuple[str, ...] = (),
    ) -> None:
        self.stop = stop
        self.provider = provider
        self.requested_model = requested_model
        self.clock = clock
        self.run_served_models = run_served_models
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
                        elif self.run_served_models and served not in self.run_served_models:
                            self._record(AttemptOutcome(
                                "infrastructure", "served_model_changed",
                                message=(
                                    f"served model {served!r} differs from the run's kept "
                                    f"responding models {', '.join(self.run_served_models)}"
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


class RunningAttempt:
    """A daemon worker whose result and wall clock can be polled without blocking."""

    def __init__(
        self,
        body: Callable[[], object],
        *,
        stop: threading.Event,
        listener: AttemptListener,
        limit_s: float,
        activity_window_s: float,
        grace_s: float,
        clock: Callable[[], float],
    ) -> None:
        self.stop = stop
        self.listener = listener
        self.clock = clock
        self.completed_at: float | None = None
        self._activity_window_s = activity_window_s
        self._grace_s = grace_s
        self._results: queue.Queue[_WorkerResult] = queue.Queue()
        self._pending_result: _WorkerResult | None = None
        self._outcome: AttemptOutcome | None = None
        self._deadline = clock() + limit_s
        self._stop_set_at: float | None = None
        self._grace_deadline: float | None = None
        self._active_at_limit: bool | None = None
        self._limit_condition: AttemptOutcome | None = None
        self._limit_condition_index = 0

        def work() -> None:
            value: object = None
            failure: BaseException | None = None
            try:
                value = body()
            except BaseException as error:
                failure = error
            self._results.put((value, failure, clock()))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _reach_limit(self, now: float, *, stop_worker: bool = True) -> None:
        if self._limit_condition is None and now >= self._deadline:
            self._active_at_limit = self.listener.stream_active(now, self._activity_window_s)
            self._limit_condition = AttemptOutcome(
                "behavioural" if self._active_at_limit else "infrastructure",
                "wall_clock" if self._active_at_limit else "wall_clock_silent",
                message="package wall clock limit reached",
            )
            self._limit_condition_index = len(self.listener.conditions)
            if stop_worker:
                self._stop_set_at = now
                self.stop.set()
                self._grace_deadline = now + self._grace_s

    def _abandoned(self) -> AttemptOutcome:
        self.completed_at = self._grace_deadline
        return AttemptOutcome(
            "infrastructure", "abandoned",
            message="attempt worker did not return within the stop grace",
            stream_active_at_limit=self._active_at_limit,
        )

    def _finish(self, error: BaseException | None, completed_at: float) -> AttemptOutcome:
        self.completed_at = completed_at
        # A worker can finish before the deadline and still be waiting to queue
        # its result when the driver observes the limit.
        if completed_at < self._deadline:
            return _classify(self.listener, error, None)
        # A result already returned needs no new stop. When polling was delayed,
        # only a stop actually requested earlier can have exhausted its grace.
        self._reach_limit(completed_at, stop_worker=False)
        if self._stop_set_at is not None and completed_at > self._stop_set_at + self._grace_s:
            return self._abandoned()
        if self._limit_condition is not None:
            self.listener._record(self._limit_condition, index=self._limit_condition_index)
        return _classify(self.listener, error, self._active_at_limit)

    def poll(self, now: float) -> AttemptOutcome | None:
        """Collect a ready result before checking W and G, without waiting for it."""
        if self._outcome is not None:
            return self._outcome
        # This driver's thread is the queue's only consumer, so a ready result
        # cannot disappear between the check and the non-blocking read.
        if self._pending_result is None and not self._results.empty():
            self._pending_result = self._results.get_nowait()
        if self._pending_result is not None:
            _value, error, completed_at = self._pending_result
            self._pending_result = None
            self._outcome = self._finish(error, completed_at)
        else:
            self._reach_limit(now)
            if self._grace_deadline is not None and now >= self._grace_deadline:
                self._outcome = self._abandoned()
        return self._outcome

    def wait_timeout(self, now: float, wait_slice_s: float = WAIT_SLICE_S) -> float:
        """Bound a driver's wait by the next wall-clock boundary and its slice."""
        boundary = self._deadline if self._grace_deadline is None else self._grace_deadline
        return max(0.0, min(wait_slice_s, boundary - now))

    def wait(
        self,
        timeout: float,
        wait_for_result: Callable[[queue.Queue[_WorkerResult], float], _WorkerResult] | None = None,
    ) -> None:
        """Store a result for the next poll, with an injectable timed queue wait."""
        if self._outcome is not None or self._pending_result is not None:
            return
        try:
            self._pending_result = (
                self._results.get(timeout=timeout) if wait_for_result is None
                else wait_for_result(self._results, timeout)
            )
        except queue.Empty:
            pass


def start_attempt(
    body: Callable[[], object],
    *,
    stop: threading.Event,
    listener: AttemptListener,
    limit_s: float,
    activity_window_s: float = STREAM_ACTIVITY_WINDOW_S,
    grace_s: float = STOP_GRACE_S,
    clock: Callable[[], float] = time.monotonic,
) -> RunningAttempt:
    """Start one attempt's daemon worker without waiting for its outcome."""
    return RunningAttempt(
        body, stop=stop, listener=listener, limit_s=limit_s,
        activity_window_s=activity_window_s, grace_s=grace_s, clock=clock,
    )


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
    try:
        running = start_attempt(
            body, stop=stop, listener=listener, limit_s=limit_s,
            activity_window_s=activity_window_s, grace_s=grace_s, clock=clock,
        )
        while True:
            now = clock()
            outcome = running.poll(now)
            if outcome is not None:
                return outcome
            running.wait(running.wait_timeout(now, wait_slice_s), wait_for_result)
    except KeyboardInterrupt:
        stop.set()
        raise
