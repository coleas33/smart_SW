"""An attempt's facts come from one replay into the product's usage ledger (T187)."""

from __future__ import annotations

import dataclasses
import gzip
import json
import threading
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import events
from swreview.agent import runner as agent_runner
from swreview.agent.providers import (
    AgentEvent,
    EventCallback,
    ProviderError,
    TokenUsage,
    retry,
    tools_withdrawn,
    usage_body,
)
from swreview.agent.providers.fake import (
    SYNTHETIC_USAGE,
    FakeProvider,
    ScriptedRound,
    ScriptedToolCall,
    ScriptedTurn,
)
from swreview.agent.runner import ReviewRun, start_review
from swreview.benchmark import prices, runner

MODEL = "fict-model-a-2026-10-01"
SERVED = ("fict-served-b-2026-10-01", "fict-served-a-2026-10-01")
FIRST = SYNTHETIC_USAGE
SECOND = FIRST.model_copy(update={"input_tokens": 2003, "total_tokens": 2214})
THIRD = FIRST.model_copy(update={"input_tokens": 3011, "total_tokens": 3222})


class TransientError(ProviderError):
    retryable = True


def write_attempt(
    package_dir: Path,
    folder: Path,
    script: Sequence[ScriptedTurn],
    *,
    with_policy: bool = False,
) -> tuple[ReviewRun, list[AgentEvent]]:
    """Write real runner events, including its generic error after an adapter raises."""
    provider = FakeProvider(script=script, model=MODEL, clock=lambda: 0.0)
    if with_policy:
        provider.use_retry(
            retry.RetryPolicy(retries=2, initial_delay_s=0.5, max_delay_s=2.0),
            stop_requested=lambda: False,
        )
    written: list[AgentEvent] = []
    run = start_review(package_dir, folder, provider=provider, callbacks=[written.append])
    for index, turn in enumerate(script):
        def play(index: int = index) -> None:
            if index == 0:
                run.start()
            else:
                run.continue_session("Continue the fictional review.")

        if turn.fails is None:
            play()
        else:
            with pytest.raises(type(turn.fails)) as raised:
                play()
            assert raised.value is turn.fails
    return run, written


def test_usage_ledger_rounds_is_an_ordered_copy() -> None:
    ledger = events.UsageLedger()
    assert ledger.rounds() == ()
    sink = events.EventSink(listeners=[ledger])
    for index, usage in enumerate((FIRST, SECOND)):
        sink.emit("usage", usage_body(usage, round_index=index, provider="fake", model=MODEL))

    snapshot = ledger.rounds()
    assert isinstance(snapshot, tuple)
    assert snapshot == (FIRST, SECOND)

    sink.emit("usage", usage_body(THIRD, round_index=2, provider="fake", model=MODEL))
    assert snapshot == (FIRST, SECOND)
    assert ledger.rounds() == (FIRST, SECOND, THIRD)


@pytest.mark.parametrize("stop_reason", [None, "content_filter", ""])
def test_attempt_facts_reads_through_replay_events_into_the_usage_ledger(
    tmp_path: Path, tmp_package_dir: Path, monkeypatch: pytest.MonkeyPatch,
    stop_reason: str | None,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(retry, "sleep", sleeps.append)
    monkeypatch.setattr(retry, "uniform", lambda low, high: high)
    real_response = FakeProvider._response
    response_calls = 0

    def transient_response(self: FakeProvider, scripted: Any, on_event: EventCallback) -> Any:
        nonlocal response_calls
        response_calls += 1
        if response_calls == 1:
            raise TransientError("fict first request temporarily busy")
        return real_response(self, scripted, on_event)

    monkeypatch.setattr(FakeProvider, "_response", transient_response)
    failure = TransientError("fict closing request refused")
    failure.stop_reason = stop_reason
    call = ScriptedToolCall("list_components")
    run, written = write_attempt(
        tmp_package_dir,
        tmp_path / "attempt",
        (
            ScriptedTurn(
                text="First turn.", rounds=(ScriptedRound((call,), FIRST),),
                usage=SECOND, served_model=SERVED[0],
            ),
            ScriptedTurn(text="Second turn.", usage=THIRD, served_model=SERVED[1]),
            ScriptedTurn(text="Unreported usage.", usage=None, served_model="fict-unreported"),
            ScriptedTurn(
                text="Unreached.", rounds=(ScriptedRound((call,), SECOND),),
                fails=failure, served_model=SERVED[0],
            ),
        ),
        with_policy=True,
    )
    usage_bodies = [event.body for event in written if event.type == "usage"]
    error_bodies = [event.body for event in written if event.type == "error"]
    assert [body["round_index"] for body in usage_bodies] == [0, 1, 0, 0]
    assert [body["retries"] for body in usage_bodies] == [1, 0, 0, 0]
    assert len(error_bodies) == 2
    assert error_bodies[0]["retries"] == (2 if stop_reason is None else 0)
    assert "retries" not in error_bodies[1]
    assert "stop_reason" not in error_bodies[1]
    assert sleeps == ([0.5, 0.5, 1.0] if stop_reason is None else [0.5])

    ledgers: list[SpyLedger] = []

    class SpyLedger(events.UsageLedger):
        def __init__(self) -> None:
            super().__init__()
            self.received: list[AgentEvent] = []
            self.snapshots: list[tuple[TokenUsage, ...]] = []
            ledgers.append(self)

        def __call__(self, event: AgentEvent) -> None:
            self.received.append(event)
            super().__call__(event)

        def rounds(self) -> tuple[TokenUsage, ...]:
            snapshot = super().rounds()
            self.snapshots.append(snapshot)
            return snapshot

    folders: list[Path] = []
    replayed: list[Path] = []
    real_stream, real_replay = events.event_stream, events.replay_events

    def stream_spy(folder: Path | str) -> Path:
        folders.append(Path(folder))
        return real_stream(folder)

    def replay_spy(path: Path | str, after: int = 0, **hooks: Any) -> Iterator[AgentEvent]:
        replayed.append(Path(path))
        return real_replay(path, after, **hooks)

    monkeypatch.setattr(events, "UsageLedger", SpyLedger)
    monkeypatch.setattr(events, "event_stream", stream_spy)
    monkeypatch.setattr(events, "replay_events", replay_spy)

    facts = runner.attempt_facts(run.out_dir)

    assert isinstance(facts, runner.AttemptFacts)
    assert isinstance(facts.rounds, tuple)
    assert [round_.usage for round_ in facts.rounds] == [FIRST, SECOND, THIRD, SECOND]
    assert facts.served_models == list(SERVED)
    assert facts.retries == (3 if stop_reason is None else 1)
    assert facts.stop_reasons == ([] if stop_reason is None else [stop_reason])
    assert facts.paid is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        facts.paid = False

    data = run.events_path.read_bytes()
    packed = tmp_path / "packed"
    packed.mkdir()
    packed_path = packed / events.PACKED_EVENTS_FILE_NAME
    packed_path.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    packed_facts = runner.attempt_facts(packed)
    assert packed_facts == facts

    damaged = tmp_path / "damaged"
    damaged.mkdir()
    damaged_path = damaged / events.EVENTS_FILE_NAME
    damaged_path.write_bytes(data + b"{unreadable tail\n" + data)
    damaged_facts = runner.attempt_facts(damaged)
    assert damaged_facts == facts

    assert folders == [run.out_dir, packed, damaged]
    assert replayed == [run.events_path, packed_path, damaged_path]
    assert len(ledgers) == 3
    for observed, ledger in zip((facts, packed_facts, damaged_facts), ledgers, strict=True):
        assert ledger.received == written
        assert len(ledger.snapshots) == 1
        for round_, usage, body in zip(
            observed.rounds, ledger.snapshots[0], usage_bodies, strict=True,
        ):
            assert type(round_) is prices.RoundFacts
            assert round_.usage is usage
            assert round_.usage == usage
            assert (round_.provider, round_.model, round_.served_model, round_.retries) == (
                body["provider"], body["model"], body.get("served_model"), body.get("retries"),
            )


@pytest.mark.parametrize("unknown_counts", [False, True])
def test_paid_means_a_round_reported_usage_even_when_its_counts_are_unknown(
    tmp_path: Path, tmp_package_dir: Path, unknown_counts: bool,
) -> None:
    usage = FIRST.model_copy(update={
        name: None for name in TokenUsage.model_fields if name != "latency_s"
    }) if unknown_counts else None
    run, _ = write_attempt(
        tmp_package_dir, tmp_path / "attempt", (ScriptedTurn(text="Done.", usage=usage),),
    )

    facts = runner.attempt_facts(run.out_dir)

    assert facts.served_models == []
    assert facts.retries == 0
    assert facts.stop_reasons == []
    assert facts.paid is unknown_counts
    assert facts.rounds == (() if usage is None else (prices.RoundFacts(usage, "fake", MODEL),))


def test_an_attempt_with_no_stream_has_empty_unpaid_facts(tmp_path: Path) -> None:
    folder = tmp_path / "failed_before_first_event"
    folder.mkdir()

    facts = runner.attempt_facts(folder)

    assert facts.rounds == ()
    assert facts.served_models == []
    assert facts.retries == 0
    assert facts.stop_reasons == []
    assert facts.paid is False


def test_the_stop_wrapper_forwards_tools_withdrawn() -> None:
    """RF-18: wrapping a set preserves its withdrawal, including its absence."""

    class Withdrawable:
        def __init__(self, withdrawn: bool) -> None:
            self.withdrawn = withdrawn

        def tools_withdrawn(self) -> bool:
            return self.withdrawn

    stop = threading.Event()
    for withdrawn in (False, True):
        assert (
            tools_withdrawn(agent_runner.StoppableTools(Withdrawable(withdrawn), stop)) is withdrawn
        )
    assert tools_withdrawn(agent_runner.StoppableTools(object(), stop)) is False


def _attempt_listener_control() -> tuple[threading.Event, Any, events.EventSink]:
    from swreview.benchmark import attempt

    stop = threading.Event()
    listener = attempt.AttemptListener(
        stop,
        provider="openai",
        requested_model=MODEL,
        clock=lambda: 0.0,
    )
    return stop, listener, events.EventSink(listeners=[listener])


def test_infrastructure_wins_over_a_later_behavioural_stop() -> None:
    from swreview.benchmark import attempt

    stop, listener, sink = _attempt_listener_control()
    sink.emit("turn.ended", {"reason": "max_steps"})
    wrong = "fict-other-model-2026-10-01"
    sink.emit(
        "usage",
        usage_body(
            FIRST,
            round_index=0,
            provider="openai",
            model=MODEL,
            served_model=wrong,
        ),
    )
    outcome = attempt.run_attempt(
        lambda: None, stop=stop, listener=listener, limit_s=10, clock=listener.clock,
    )
    assert (outcome.kind, outcome.class_) == ("infrastructure", "wrong_model")
    assert MODEL in outcome.message and wrong in outcome.message
    assert stop.is_set()

    stop, listener, sink = _attempt_listener_control()
    sink.emit("turn.ended", {"reason": "max_steps"})
    failure = ProviderError("fict service connection failed")

    def failed_body() -> None:
        raise failure

    outcome = attempt.run_attempt(
        failed_body, stop=stop, listener=listener, limit_s=10, clock=listener.clock,
    )
    assert (outcome.kind, outcome.class_) == ("infrastructure", "provider_error")
    assert outcome.error_class == "ProviderError"
    assert outcome.message == str(failure)


def test_the_first_behavioural_stop_wins() -> None:
    from swreview.benchmark import attempt

    stop, listener, sink = _attempt_listener_control()
    sink.emit("turn.ended", {"reason": "max_steps"})
    workers: list[threading.Thread] = []

    def body() -> None:
        workers.append(threading.current_thread())
        assert stop.wait(30)

    try:
        outcome = attempt.run_attempt(
            body,
            stop=stop,
            listener=listener,
            limit_s=0,
            grace_s=1,
            clock=lambda: 0.0,
        )
        assert stop.is_set()
    finally:
        stop.set()
        for worker in workers:
            worker.join(30)
            assert not worker.is_alive()
    assert (outcome.kind, outcome.class_) == ("behavioural", "max_steps")
    assert outcome.stream_active_at_limit is True


def test_the_inferred_overflow_is_recognised_by_type() -> None:
    """94A defers Gemini adapter variants; T193 explicitly retains this type inference."""
    from swreview.agent.providers.gemini_provider import GeminiRequestError
    from swreview.agent.providers.openai_provider import OpenAIProviderError
    from swreview.benchmark import attempt

    message = "gemini 400 FICT request refused"
    cases = (
        (
            OpenAIProviderError(message, error_class="GeminiRequestError", retryable=False),
            True,
            "infrastructure",
            "provider_error",
            None,
        ),
        (
            GeminiRequestError(message),
            True,
            "behavioural",
            "provider_stop",
            "input_token_limit_inferred",
        ),
        (GeminiRequestError(message), False, "infrastructure", "provider_error", None),
    )
    for failure, answered, kind, class_, reason in cases:
        stop, listener, sink = _attempt_listener_control()
        if answered:
            sink.emit("usage", usage_body(FIRST, round_index=0, provider="openai", model=MODEL))

        def failed_body(failure: ProviderError = failure) -> None:
            raise failure

        outcome = attempt.run_attempt(
            failed_body, stop=stop, listener=listener, limit_s=10, clock=listener.clock,
        )
        assert (outcome.kind, outcome.class_, outcome.stop_reason) == (kind, class_, reason)
        assert outcome.message == message


def test_the_driver_waits_in_short_slices_so_an_interrupt_is_seen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from swreview.benchmark import attempt

    now = [0.0]
    stop = threading.Event()
    release, entered, returned = threading.Event(), threading.Event(), threading.Event()
    listener = attempt.AttemptListener(
        stop,
        provider="openai",
        requested_model=MODEL,
        clock=lambda: now[0],
    )
    timeouts: list[float] = []

    def body() -> None:
        entered.set()
        assert release.wait(30)
        returned.set()

    def wait(_queue: Any, block: bool = True, timeout: float | None = None) -> Any:
        assert entered.wait(30)
        assert timeout is not None
        timeouts.append(timeout)
        now[0] += timeout
        if len(timeouts) == 3:
            raise KeyboardInterrupt
        raise attempt.queue.Empty

    monkeypatch.setattr(attempt.queue.Queue, "get", wait)
    try:
        with pytest.raises(KeyboardInterrupt):
            attempt.run_attempt(
                body,
                stop=stop,
                listener=listener,
                limit_s=10,
                clock=lambda: now[0],
            )
    finally:
        release.set()

    assert returned.wait(30)
    assert timeouts == [attempt.WAIT_SLICE_S] * 3
    assert all(timeout <= attempt.WAIT_SLICE_S for timeout in timeouts)
    assert stop.is_set()


def test_a_malformed_usage_body_records_an_internal_error_without_escaping_the_listener() -> None:
    from swreview.benchmark import attempt

    stop, listener, sink = _attempt_listener_control()
    sink.emit("usage", {})
    assert stop.is_set()
    outcome = attempt.run_attempt(
        lambda: None, stop=stop, listener=listener, limit_s=10, clock=listener.clock,
    )
    assert (outcome.kind, outcome.class_) == ("infrastructure", "internal_error")
    assert outcome.error_class == "KeyError"
    assert "KeyError" in outcome.message and "input_tokens" in outcome.message


def test_stopping_a_turn_clears_its_unfinished_tools() -> None:
    _stop, listener, sink = _attempt_listener_control()
    sink.emit("tool.started", {"step_index": 0})
    assert listener.stream_active(1000, 10) is True

    sink.emit("turn.ended", {"reason": "stopped"})

    assert listener.stream_active(1000, 10) is False


@pytest.mark.parametrize("grace_s", [0.0, 1.0])
def test_a_returned_worker_is_collected_before_a_late_deadline_check(
    monkeypatch: pytest.MonkeyPatch, grace_s: float,
) -> None:
    from swreview.benchmark import attempt

    queued = threading.Event()
    real_put = attempt.queue.Queue.put
    clock_calls = 0

    def put(self: Any, item: Any, *args: Any, **kwargs: Any) -> None:
        real_put(self, item, *args, **kwargs)
        queued.set()

    def clock() -> float:
        nonlocal clock_calls
        if threading.current_thread() is not threading.main_thread():
            return 0.0
        clock_calls += 1
        if clock_calls == 1:
            return 0.0
        assert queued.wait(30)
        return 2.0

    monkeypatch.setattr(attempt.queue.Queue, "put", put)
    stop, listener, _sink = _attempt_listener_control()
    outcome = attempt.run_attempt(
        lambda: None, stop=stop, listener=listener, limit_s=1, grace_s=grace_s, clock=clock,
    )
    assert (outcome.kind, outcome.class_) == ("completed", None)
    assert outcome.stream_active_at_limit is None
    assert not stop.is_set()


@pytest.mark.parametrize("active", [False, True])
def test_a_worker_finished_before_the_limit_is_completed_when_its_result_is_not_yet_queued(
    monkeypatch: pytest.MonkeyPatch, active: bool,
) -> None:
    from swreview.benchmark import attempt

    ready_to_queue, release_queue = threading.Event(), threading.Event()
    real_put, real_get = attempt.queue.Queue.put, attempt.queue.Queue.get
    clock_calls = 0
    observed_conditions: list[Any] = []
    stop, listener, sink = _attempt_listener_control()
    if active:
        sink.emit("text.delta", {"text": "FICT activity before completion."})

    def clock() -> float:
        nonlocal clock_calls
        if threading.current_thread() is not threading.main_thread():
            return 0.5
        clock_calls += 1
        if clock_calls == 1:
            return 0.0
        assert ready_to_queue.wait(30)
        return 1.0

    def put(self: Any, item: Any, *args: Any, **kwargs: Any) -> None:
        ready_to_queue.set()
        assert release_queue.wait(30)
        real_put(self, item, *args, **kwargs)

    def get(self: Any, block: bool = True, timeout: float | None = None) -> Any:
        observed_conditions.extend(listener.conditions)
        assert stop.is_set()
        release_queue.set()
        # The queue release, rather than a short real deadline, orders this race.
        return real_get(self, block=block, timeout=30 if block else None)

    monkeypatch.setattr(attempt.queue.Queue, "put", put)
    monkeypatch.setattr(attempt.queue.Queue, "get", get)
    try:
        outcome = attempt.run_attempt(
            lambda: None, stop=stop, listener=listener, limit_s=1, grace_s=1, clock=clock,
        )
    finally:
        release_queue.set()

    assert (outcome.kind, outcome.class_) == ("completed", None)
    assert outcome.stream_active_at_limit is None
    assert listener.conditions == ()
    assert observed_conditions == []


@pytest.mark.parametrize(
    ("active", "grace_s", "kind", "class_"),
    [
        (False, 5.0, "infrastructure", "wall_clock_silent"),
        (True, 5.0, "behavioural", "wall_clock"),
        (True, 0.5, "infrastructure", "abandoned"),
    ],
)
def test_a_blocking_wait_returning_after_the_deadline_observes_the_limit(
    monkeypatch: pytest.MonkeyPatch, active: bool, grace_s: float, kind: str, class_: str,
) -> None:
    from swreview.benchmark import attempt

    now = [0.0]
    release = threading.Event()
    stop, listener, sink = _attempt_listener_control()
    if active:
        sink.emit("text.delta", {"text": "FICT activity before the deadline."})
    real_get = attempt.queue.Queue.get

    def get(self: Any, block: bool = True, timeout: float | None = None) -> Any:
        if not block:
            return real_get(self, block=False)
        now[0] = 2.0
        release.set()
        return real_get(self, timeout=30)

    monkeypatch.setattr(attempt.queue.Queue, "get", get)
    try:
        outcome = attempt.run_attempt(
            lambda: release.wait(30), stop=stop, listener=listener, limit_s=1,
            activity_window_s=5, grace_s=grace_s, clock=lambda: now[0],
        )
    finally:
        release.set()
    assert (outcome.kind, outcome.class_) == (kind, class_)
    assert outcome.stream_active_at_limit is active
    assert stop.is_set()


# --- T194: classification through the real benchmark body -----------------------------


def prepare_driver_set(
    folder: Path, ids: Sequence[str] = ("fict-a",), *, held_out: bool = False
) -> runner.PreflightedSet:
    """An offline set over the questions fixture, preflighted through the public seam."""
    from swreview.agent.checklist import load_checklist
    from swreview.ir.loader import save_package
    from tests.unit.test_benchmark_questions import PACKAGE

    entries = []
    for package_id in ids:
        package_dir = folder / "packages" / package_id
        save_package(PACKAGE, package_dir)
        entries.append({"package_id": package_id, "path": str(package_dir), "held_out": held_out})
    source = folder / "set.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes((json.dumps({"name": "fict-driver", "packages": entries}) + "\n").encode())
    return runner.preflight_set(source, None, load_checklist())


def install_driver_providers(
    monkeypatch: pytest.MonkeyPatch,
    scripts: Sequence[Sequence[ScriptedTurn]],
    *,
    kind: type[FakeProvider] = FakeProvider,
    **provider_options: Any,
) -> list[FakeProvider]:
    """Every attempt gets its own adapter; retries sleep only into the test's list."""
    from swreview import cli

    built: list[FakeProvider] = []
    provider_options.setdefault("clock", lambda: 0.0)
    provider_options.setdefault("sleep", lambda delay: None)

    def factory(settings: Any, efficiency: Any = None) -> FakeProvider:
        adapter = kind(script=scripts[len(built)], model=settings.model, **provider_options)
        built.append(adapter)
        return adapter

    monkeypatch.setattr(cli, "provider_factory", factory)
    return built


def driver_run(
    preflighted: runner.PreflightedSet,
    out: Path,
    *,
    provider: str = "fake",
    model: str = MODEL,
    **options: Any,
) -> list[Path]:
    from swreview import cli

    # Other test modules import this helper to exercise explicit real deadlines.
    if "package_time_limit_s" not in options:
        options.setdefault("clock", lambda: 0.0)
    return runner.run_benchmark(
        preflighted,
        out,
        provider=provider,
        model=model,
        effort="high",
        review_fn=cli._review_fn,
        **options,
    )


def driver_status(out: Path) -> dict[str, Any]:
    return json.loads((out / "run-status.json").read_bytes())


def driver_row(out: Path, package_id: str = "fict-a") -> dict[str, Any]:
    return driver_status(out)["packages"][package_id]["attempts"][-1]


def driver_events(folder: Path) -> list[AgentEvent]:
    return list(events.replay_events(events.event_stream(folder)))


def provider_stop(reason: str) -> ProviderError:
    from swreview.agent.providers.openai_provider import OpenAIProviderError

    error = OpenAIProviderError("fict provider stopped", error_class="FictStop", retryable=True)
    error.stop_reason = reason
    return error


@pytest.fixture
def driver_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    from swreview import cli

    sleeps: list[float] = []
    monkeypatch.setattr(retry, "sleep", sleeps.append)
    monkeypatch.setattr(retry, "uniform", lambda low, high: high / 2)
    real_run = cli.run_benchmark

    def run(*args: Any, **options: Any) -> Any:
        options.setdefault("clock", lambda: 0.0)
        return real_run(*args, **options)

    monkeypatch.setattr(cli, "run_benchmark", run)
    return sleeps


@pytest.fixture
def failed_driver_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> Path:
    preflighted = prepare_driver_set(tmp_path, ("fict-a", "fict-b", "fict-c"))
    install_driver_providers(
        monkeypatch,
        [
            [ScriptedTurn(text="", fails=TransientError("fict exhausted request"))],
            [ScriptedTurn(text="Reviewed second.")],
            [ScriptedTurn(text="Reviewed third.")],
        ],
    )
    out = tmp_path / "run"
    driver_run(preflighted, out)
    return out


def test_a_provider_error_after_retries_is_an_infrastructure_failure_with_its_exact_retry_count(
    failed_driver_run: Path, driver_sleeps: list[float]
) -> None:
    out = failed_driver_run
    row = driver_row(out)
    assert (row["kind"], row["class"], row["error_class"]) == (
        "infrastructure",
        "provider_error",
        "TransientError",
    )
    assert row["folder"] == "attempts/fict-a/1"
    folder = out / row["folder"]
    assert folder.is_dir() and not (out / "fict-a").exists()
    errors = [event.body for event in driver_events(folder) if event.type == "error"]
    assert errors[0]["retries"] == retry.BENCHMARK_RETRY.retries == 5
    assert runner.attempt_facts(folder).retries == 5
    assert len(driver_sleeps) == 5


def test_the_other_packages_complete(failed_driver_run: Path) -> None:
    for package_id in ("fict-b", "fict-c"):
        row = driver_row(failed_driver_run, package_id)
        assert (row["kind"], row["class"], row["folder"]) == ("completed", None, package_id)
        assert driver_status(failed_driver_run)["packages"][package_id]["kept_attempt"] == 1
        assert (failed_driver_run / package_id / "session.json").is_file()
        assert not (failed_driver_run / "attempts" / package_id / "1").exists()


def test_a_gemini_safety_stop_is_a_behavioural_provider_stop_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    """94A: exercise the returned SAFETY stop on the scripted provider; Gemini deferred."""
    from swreview.report.session import load_session

    preflighted = prepare_driver_set(tmp_path)
    install_driver_providers(
        monkeypatch, [[ScriptedTurn(text="", stop_reason="SAFETY", end_reason="error")]]
    )
    out = tmp_path / "run"
    assert driver_run(preflighted, out) == [out / "fict-a"]
    row = driver_row(out)
    assert (row["kind"], row["class"], row["stop_reason"]) == (
        "behavioural",
        "provider_stop",
        "SAFETY",
    )
    assert load_session(out / "fict-a" / "session.json").ended_at is not None
    assert driver_sleeps == []


def test_an_openai_content_filter_stop_is_a_behavioural_provider_stop_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    from swreview.report.session import load_session

    preflighted = prepare_driver_set(tmp_path)
    install_driver_providers(
        monkeypatch, [[ScriptedTurn(text="", fails=provider_stop("content_filter"))]]
    )
    out = tmp_path / "run"
    assert driver_run(preflighted, out) == [out / "fict-a"]
    assert (driver_row(out)["kind"], driver_row(out)["class"], driver_row(out)["stop_reason"]) == (
        "behavioural",
        "provider_stop",
        "content_filter",
    )
    assert load_session(out / "fict-a" / "session.json").ended_at is not None
    assert driver_sleeps == []


@pytest.mark.parametrize(
    ("provider_name", "reason"),
    [("fake", "FICT_LATER_STOP"), ("fake", "unset"), ("openai", "unset")],
)
def test_an_unnamed_stop_reason_on_either_provider_is_a_provider_stop_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float],
    provider_name: str, reason: str,
) -> None:
    """94A: OpenAI and scripted stops are covered; Gemini finish reasons are deferred."""
    preflighted = prepare_driver_set(tmp_path)
    out = tmp_path / "run"
    if provider_name == "fake":
        turn = (
            ScriptedTurn(text="", fails=provider_stop(reason))
            if reason == "unset"
            else ScriptedTurn(text="", stop_reason=reason, end_reason="error")
        )
        install_driver_providers(monkeypatch, [[turn]])
        folders = driver_run(preflighted, out)
    else:
        import respx

        from swreview import cli
        from tests.unit.test_provider_retry import URL, _provider, _response, _stream

        adapter = _provider()
        monkeypatch.setenv("OPENAI_API_KEY", "fict-offline-key")
        monkeypatch.setattr(cli, "provider_factory", lambda *args, **kwargs: adapter)
        response = _stream({
            "type": "response.incomplete", "sequence_number": 9,
            "response": _response(status="incomplete", incomplete_details=None),
        })
        with respx.mock(assert_all_called=True) as router:
            route = router.post(URL).mock(return_value=response)
            folders = driver_run(preflighted, out, provider="openai")
            assert route.call_count == 1
    assert folders == [out / "fict-a"]
    row = driver_row(out)
    assert (row["kind"], row["class"], row["stop_reason"]) == (
        "behavioural",
        "provider_stop",
        reason,
    )
    assert driver_sleeps == []


@pytest.mark.parametrize(
    ("shape", "code", "kind", "class_", "retries"),
    [
        ("failed", "invalid_prompt", "behavioural", "provider_stop", 0),
        ("http", "bio_policy", "behavioural", "provider_stop", 0),
        ("failed", "server_error", "infrastructure", "provider_error", 5),
    ],
)
def test_an_openai_policy_failure_is_a_provider_stop_and_never_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    driver_sleeps: list[float],
    shape: str,
    code: str,
    kind: str,
    class_: str,
    retries: int,
) -> None:
    import respx

    from swreview import cli
    from tests.unit.test_provider_retry import URL, _failed, _http_error, _provider

    adapter = _provider()
    monkeypatch.setenv("OPENAI_API_KEY", "fict-offline-key")
    monkeypatch.setattr(cli, "provider_factory", lambda *args, **kwargs: adapter)
    preflighted = prepare_driver_set(tmp_path)
    with respx.mock(assert_all_called=True) as router:
        route = router.post(URL).mock(
            side_effect=lambda request: (
                _failed(code) if shape == "failed" else _http_error(400, code=code)
            )
        )
        out = tmp_path / "run"
        driver_run(preflighted, out, provider="openai")
        assert route.call_count == retries + 1
    row = driver_row(out)
    assert (row["kind"], row["class"]) == (kind, class_)
    assert row["stop_reason"] == (code if kind == "behavioural" else None)
    assert len(driver_sleeps) == runner.attempt_facts(out / row["folder"]).retries == retries


@pytest.mark.parametrize("provider_name", ["openai", "fake"])
def test_a_context_overflow_is_a_provider_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float],
    provider_name: str,
) -> None:
    """94A: OpenAI and scripted overflows; Gemini input_token_limit is deferred."""
    preflighted = prepare_driver_set(tmp_path)
    out = tmp_path / "run"
    if provider_name == "fake":
        install_driver_providers(
            monkeypatch, [[ScriptedTurn(text="", fails=provider_stop("context_length_exceeded"))]]
        )
        folders = driver_run(preflighted, out)
    else:
        import respx

        from swreview import cli
        from tests.unit.test_provider_retry import URL, _http_error, _provider

        adapter = _provider()
        monkeypatch.setenv("OPENAI_API_KEY", "fict-offline-key")
        monkeypatch.setattr(cli, "provider_factory", lambda *args, **kwargs: adapter)
        with respx.mock(assert_all_called=True) as router:
            route = router.post(URL).mock(
                side_effect=lambda request: _http_error(400, code="context_length_exceeded")
            )
            folders = driver_run(preflighted, out, provider="openai")
            assert route.call_count == 1
    assert folders == [out / "fict-a"]
    row = driver_row(out)
    assert (row["kind"], row["class"], row["stop_reason"]) == (
        "behavioural",
        "provider_stop",
        "context_length_exceeded",
    )
    assert driver_sleeps == []


def test_an_unrecognised_gemini_request_error_after_an_answered_round_is_an_inferred_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    """26A's type inference stays covered on the scripted provider under 94A."""
    from swreview.agent.providers.gemini_provider import GeminiRequestError

    preflighted = prepare_driver_set(tmp_path)
    install_driver_providers(
        monkeypatch,
        [
            [
                ScriptedTurn(
                    text="",
                    rounds=(ScriptedRound((ScriptedToolCall("list_components"),), FIRST),),
                    fails=GeminiRequestError("gemini 400 FICT request refused"),
                )
            ]
        ],
    )
    out = tmp_path / "run"
    assert driver_run(preflighted, out) == [out / "fict-a"]
    row = driver_row(out)
    assert (row["kind"], row["class"], row["stop_reason"]) == (
        "behavioural",
        "provider_stop",
        "input_token_limit_inferred",
    )
    assert row["message"] == "gemini 400 FICT request refused"


def test_a_gemini_request_error_before_any_answered_round_stays_a_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    """26A's negative inference case uses a scripted error; Gemini calls deferred by 94A."""
    from swreview.agent.providers.gemini_provider import GeminiRequestError

    preflighted = prepare_driver_set(tmp_path)
    install_driver_providers(
        monkeypatch,
        [[ScriptedTurn(text="", fails=GeminiRequestError("gemini 400 FICT request refused"))]],
    )
    out = tmp_path / "run"
    assert driver_run(preflighted, out) == []
    assert (driver_row(out)["kind"], driver_row(out)["class"]) == (
        "infrastructure",
        "provider_error",
    )


def test_classification_reads_the_adapters_error_body_not_the_runners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    real_response = FakeProvider._response
    response_calls = 0

    def retried_response(self: FakeProvider, scripted: Any, on_event: EventCallback) -> Any:
        nonlocal response_calls
        response_calls += 1
        if response_calls <= 2:
            raise TransientError("fict request temporarily busy")
        return real_response(self, scripted, on_event)

    monkeypatch.setattr(FakeProvider, "_response", retried_response)
    preflighted = prepare_driver_set(tmp_path)
    install_driver_providers(
        monkeypatch, [[ScriptedTurn(text="", fails=provider_stop("content_filter"))]]
    )
    out = tmp_path / "run"
    driver_run(preflighted, out)
    errors = [event.body for event in driver_events(out / "fict-a") if event.type == "error"]
    assert len(errors) == 2
    assert errors[0]["stop_reason"] == "content_filter" and errors[0]["retries"] == 2
    assert "stop_reason" not in errors[1] and "retries" not in errors[1]
    assert driver_row(out)["class"] == "provider_stop"
    assert runner.attempt_facts(out / "fict-a").retries == len(driver_sleeps) == 2


def test_a_step_limit_is_a_behavioural_stop_and_its_session_is_finalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    from swreview.agent.runner import DEFAULT_MAX_STEPS
    from swreview.benchmark.answers import read_answer_log
    from swreview.report.session import load_session

    preflighted = prepare_driver_set(tmp_path)
    built = install_driver_providers(
        monkeypatch,
        [
            [
                ScriptedTurn(
                    text="",
                    tool_calls=(ScriptedToolCall("list_components"),) * (DEFAULT_MAX_STEPS + 1),
                )
            ]
        ],
    )
    out = tmp_path / "run"
    assert driver_run(preflighted, out) == [out / "fict-a"]
    assert (driver_row(out)["kind"], driver_row(out)["class"]) == ("behavioural", "max_steps")
    assert load_session(out / "fict-a" / "session.json").ended_at is not None
    assert built[0]._turn_index == 1
    assert read_answer_log(out / "fict-a").ended == "turn_did_not_end"


def test_reaching_the_answer_turn_bound_is_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    from swreview.agent.checklist import load_checklist
    from swreview.benchmark.answers import read_answer_log
    from tests.support.scripted_answers import ask, turn
    from tests.unit.test_benchmark_case_file import case, case_file_set, item_answer
    from tests.unit.test_benchmark_questions import FIT, PIN_1, PLATE_1

    preflighted = runner.preflight_set(
        case_file_set(tmp_path, case(item_answer())), None, load_checklist()
    )
    package_id = preflighted.benchmark_set.packages[0].package_id
    built = install_driver_providers(monkeypatch, [[turn(ask(PLATE_1, PIN_1, item=FIT))]])
    out = tmp_path / "run"
    assert driver_run(preflighted, out, max_answer_turns=0) == [out / package_id]
    assert driver_row(out, package_id)["kind"] == "completed"
    assert read_answer_log(out / package_id).ended == "bound_reached"
    assert built[0]._turn_index == 1


def test_an_internal_error_is_an_infrastructure_failure_and_the_set_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    from swreview import cli

    preflighted = prepare_driver_set(tmp_path, ("fict-a", "fict-b"))
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="")], [ScriptedTurn(text="Done.")]])
    real_start = cli.start_review

    def start(package_dir: Path, out_dir: Path, **options: Any) -> ReviewRun:
        if package_dir.name == "fict-a":
            raise ValueError("fict setup bug")
        return real_start(package_dir, out_dir, **options)

    monkeypatch.setattr(cli, "start_review", start)
    out = tmp_path / "run"
    assert driver_run(preflighted, out) == [out / "fict-b"]
    assert (driver_row(out)["kind"], driver_row(out)["class"], driver_row(out)["error_class"]) == (
        "infrastructure",
        "internal_error",
        "ValueError",
    )
    assert driver_row(out, "fict-b")["kind"] == "completed"


def test_ctrl_c_records_the_attempt_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    from typer.testing import CliRunner

    from swreview import cli
    from swreview.benchmark import attempt

    preflighted = prepare_driver_set(tmp_path)
    release = [threading.Event(), threading.Event()]
    observed: list[runner.AttemptRequest] = []
    entered = [threading.Event(), threading.Event()]
    workers: list[threading.Thread] = []
    attempt_index = 0
    real_body = cli._review_fn

    def body(*args: Any, **kwargs: Any) -> Any:
        index = len(observed)
        observed.append(kwargs["attempt"])
        workers.append(threading.current_thread())
        entered[index].set()
        return real_body(*args, **kwargs)

    def interrupted(self: Any, block: bool = True, timeout: float | None = None) -> Any:
        assert entered[attempt_index].wait(30)
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_review_fn", body)
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="", hang=release[0])]])
    monkeypatch.setattr(attempt.queue.Queue, "get", interrupted)
    out = tmp_path / "run"
    try:
        with pytest.raises(KeyboardInterrupt):
            driver_run(preflighted, out)
        row = driver_row(out)
        assert (row["kind"], row["class"]) == ("infrastructure", "interrupted")
        assert row["ended_at"].endswith("Z")
        assert observed[0].stop.is_set()
        release[0].set()
        workers[0].join(30)
        assert not workers[0].is_alive()
        attempt_index = 1
        install_driver_providers(monkeypatch, [[ScriptedTurn(text="", hang=release[1])]])
        result = CliRunner().invoke(
            cli.app,
            [
                "benchmark",
                "run",
                "--set",
                str(tmp_path / "set.json"),
                "--out",
                str(tmp_path / "cli-run"),
                "--provider",
                "fake",
            ],
        )
        assert result.exit_code == 1
        assert driver_row(tmp_path / "cli-run")["class"] == "interrupted"
        assert observed[1].stop.is_set()
    finally:
        for event in release:
            event.set()
        for worker in workers:
            worker.join(30)
            assert not worker.is_alive()


# --- T195: served ids and virtual wall clocks -----------------------------------------


@pytest.mark.parametrize("provider_name", ["openai", "fake"])
def test_a_served_model_outside_the_aliases_fails_the_attempt_at_the_next_tool_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    driver_sleeps: list[float],
    provider_name: str,
) -> None:
    """94A: the OpenAI alias rule and scripted adapter replace the Gemini variant."""
    preflighted = prepare_driver_set(tmp_path)
    built = install_driver_providers(
        monkeypatch,
        [
            [
                ScriptedTurn(
                    text="Unreached.",
                    served_model="fict-other-2026-10-01",
                    tool_calls=(ScriptedToolCall("list_components"),),
                )
            ]
        ],
    )
    monkeypatch.setenv("OPENAI_API_KEY", "fict-offline-key")
    out = tmp_path / "run"
    assert driver_run(preflighted, out, provider=provider_name) == []
    row = driver_row(out)
    assert (row["kind"], row["class"]) == ("infrastructure", "wrong_model")
    assert MODEL in row["message"] and "fict-other-2026-10-01" in row["message"]
    folder = out / row["folder"]
    assert len(runner.attempt_facts(folder).rounds) == 1
    assert built[0]._turn_index == 1
    recorded = driver_events(folder)
    assert not any(event.type == "tool.finished" for event in recorded)
    assert any(
        event.type == "turn.ended" and event.body["reason"] == "stopped" for event in recorded
    )


def test_a_dated_snapshot_is_within_the_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    """94A: a dated OpenAI id, reported by the offline scripted provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "fict-offline-key")
    preflighted = prepare_driver_set(tmp_path)
    install_driver_providers(
        monkeypatch,
        [[ScriptedTurn(text="Reviewed.", served_model="fict-base-2026-10-01")]],
    )
    out = tmp_path / "run"
    assert driver_run(preflighted, out, provider="openai", model="fict-base") == [out / "fict-a"]
    assert driver_row(out)["kind"] == "completed"


def test_an_unreported_served_model_fails_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    preflighted = prepare_driver_set(tmp_path)
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="Reviewed.")]])
    out = tmp_path / "run"
    assert driver_run(preflighted, out) == [out / "fict-a"]
    assert driver_row(out)["kind"] == "completed"
    assert runner.attempt_facts(out / "fict-a").served_models == []


class ToolAfterTextProvider(FakeProvider):
    """A scripted response's streamed text followed by its tool dispatch, as a real stream."""

    def run(self, **options: Any) -> Any:
        result = super().run(**options)
        options["tools"].call("list_components", {}, call_id="fict-boundary")
        return result


@dataclasses.dataclass
class ScheduledWorker:
    wake_at: float | None = None
    finished: bool = False
    released: bool = False


class DriverClock:
    """Advance only between worker checkpoints, never with the OS scheduler.

    Each provider sleep parks its worker. A driver wait moves to the earlier of
    the next wake or wait slice, then lets the driver check its deadline *before*
    resuming the worker. Real waits below are only deadlock guards.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.condition = threading.Condition()
        self.local = threading.local()
        self.workers: list[ScheduledWorker] = []

    def __call__(self) -> float:
        with self.condition:
            return self.now

    def sleep(self, delay: float) -> None:
        worker = self.local.worker
        with self.condition:
            if worker.released:
                return
            worker.wake_at = self.now + delay
            self.condition.notify_all()
            assert self.condition.wait_for(
                lambda: worker.wake_at is None or worker.released, timeout=30,
            ), "driver did not resume the scripted worker"

    def wait(self, worker: ScheduledWorker, results: Any, timeout: float) -> Any:
        from swreview.benchmark import attempt

        with self.condition:
            assert self.condition.wait_for(
                lambda: worker.wake_at is not None or worker.finished, timeout=30,
            ), "worker did not reach a checkpoint"
            if worker.wake_at is not None and worker.wake_at <= self.now:
                worker.wake_at = None
                self.condition.notify_all()
                assert self.condition.wait_for(
                    lambda: worker.wake_at is not None or worker.finished, timeout=30,
                ), "worker did not reach its next checkpoint"
            if not worker.finished:
                assert worker.wake_at is not None
                self.now = min(self.now + timeout, worker.wake_at)
                raise attempt.queue.Empty
        return results.get(timeout=30)

    def start(self, real_start: Callable[..., Any], body: Callable[[], Any], **options: Any) -> Any:
        worker = ScheduledWorker()
        self.workers.append(worker)

        def work() -> Any:
            self.local.worker = worker
            try:
                return body()
            finally:
                with self.condition:
                    worker.finished = True
                    self.condition.notify_all()

        return real_start(work, **options)

    def options(self, **overrides: float) -> dict[str, Any]:
        return {
            "clock": self,
            "package_time_limit_s": 10,
            "stream_activity_window_s": 2,
            "stop_grace_s": 40,
            **overrides,
        }

    def close(self) -> None:
        with self.condition:
            for worker in self.workers:
                worker.released = True
            self.condition.notify_all()
            assert self.condition.wait_for(
                lambda: all(worker.finished for worker in self.workers), timeout=30,
            ), "abandoned worker did not finish during cleanup"


@pytest.fixture
def driver_clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[DriverClock]:
    from swreview.benchmark import attempt

    clock = DriverClock()
    # T206 moves the scheduler to start/poll; keep the same virtual worker checkpoints.
    real_start = attempt.start_attempt
    workers: dict[Any, ScheduledWorker] = {}

    def start(body: Callable[[], Any], **options: Any) -> Any:
        running = clock.start(real_start, body, **options)
        workers[running] = clock.workers[-1]
        return running

    def wait(running: Sequence[Any], timeout: float) -> None:
        worker = running[0]
        worker.wait(
            timeout,
            wait_for_result=lambda results, seconds: clock.wait(workers[worker], results, seconds),
        )

    monkeypatch.setattr(attempt, "start_attempt", start)
    monkeypatch.setattr(runner, "_wait_for_attempts", wait)
    try:
        yield clock
    finally:
        clock.close()


def test_a_silent_stream_at_the_wall_clock_is_an_infrastructure_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float],
    driver_clock: DriverClock,
) -> None:
    preflighted = prepare_driver_set(tmp_path)

    class TimedSilentProvider(FakeProvider):
        def run(self, **options: Any) -> Any:
            driver_clock.sleep(12)
            return super().run(**options)

    install_driver_providers(
        monkeypatch,
        [[ScriptedTurn(text="", tool_calls=(ScriptedToolCall("list_components"),))]],
        kind=TimedSilentProvider,
        clock=driver_clock, sleep=driver_clock.sleep,
    )
    out = tmp_path / "run"
    assert driver_run(preflighted, out, **driver_clock.options()) == []
    row = driver_row(out)
    assert (row["kind"], row["class"], row["stream_active_at_limit"]) == (
        "infrastructure",
        "wall_clock_silent",
        False,
    )
    assert (out / "attempts/fict-a/1").is_dir() and not (out / "fict-a").exists()


def test_an_active_stream_at_the_wall_clock_is_a_behavioural_stop_not_re_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float],
    driver_clock: DriverClock,
) -> None:
    from swreview.report.session import load_session

    preflighted = prepare_driver_set(tmp_path)
    install_driver_providers(
        monkeypatch,
        [[ScriptedTurn(text=" ".join(["fict"] * 30), delta_interval_s=1)]],
        kind=ToolAfterTextProvider,
        clock=driver_clock, sleep=driver_clock.sleep,
    )
    ended: list[ReviewRun] = []
    real_end = ReviewRun.end_stopped

    def end(run: ReviewRun) -> None:
        ended.append(run)
        real_end(run)

    monkeypatch.setattr(ReviewRun, "end_stopped", end)
    out = tmp_path / "run"
    assert driver_run(preflighted, out, **driver_clock.options()) == [
        out / "fict-a"
    ]
    row = driver_row(out)
    assert (row["kind"], row["class"], row["stream_active_at_limit"]) == (
        "behavioural",
        "wall_clock",
        True,
    )
    assert len(ended) == 1
    assert load_session(out / "fict-a/session.json").ended_at is not None
    assert driver_status(out)["packages"]["fict-a"]["kept_attempt"] == 1


def test_a_tool_in_progress_at_the_wall_clock_counts_as_activity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float],
    driver_clock: DriverClock,
) -> None:
    from swreview import cli

    preflighted = prepare_driver_set(tmp_path)
    real_start = cli.start_review

    def start(*args: Any, **options: Any) -> ReviewRun:
        run = real_start(*args, **options)
        tools = run.tools

        class SlowTool:
            def __iter__(self) -> Any:
                return iter(tools)

            def __len__(self) -> int:
                return len(tools)

            def call(self, name: str, arguments: Any, call_id: str = "") -> Any:
                driver_clock.sleep(12)
                return tools.call(name, arguments, call_id)

        run.tools = SlowTool()
        return run

    monkeypatch.setattr(cli, "start_review", start)
    install_driver_providers(
        monkeypatch,
        [[ScriptedTurn(text="", tool_calls=(ScriptedToolCall("list_components"),))]],
        clock=driver_clock, sleep=driver_clock.sleep,
    )
    out = tmp_path / "run"
    assert driver_run(preflighted, out, **driver_clock.options()) == [out / "fict-a"]
    row = driver_row(out)
    assert (row["kind"], row["class"], row["stream_active_at_limit"]) == (
        "behavioural",
        "wall_clock",
        True,
    )


def test_a_worker_that_does_not_return_within_the_grace_is_abandoned_and_never_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float],
    driver_clock: DriverClock,
) -> None:
    preflighted = prepare_driver_set(tmp_path, ("fict-a", "fict-b"))
    built = install_driver_providers(
        monkeypatch,
        [
            [ScriptedTurn(text=" ".join(["fict"] * 100), delta_interval_s=1)],
            [ScriptedTurn(text="Reviewed next.")],
        ],
        kind=ToolAfterTextProvider,
        clock=driver_clock, sleep=driver_clock.sleep,
    )
    out = tmp_path / "run"
    assert driver_run(preflighted, out, **driver_clock.options(stop_grace_s=2)) == [out / "fict-b"]
    row = driver_row(out)
    assert (row["kind"], row["class"]) == ("infrastructure", "abandoned")
    assert row["folder"] == "attempts/fict-a/1"
    assert (out / row["folder"]).is_dir() and not (out / "fict-a").exists()
    assert driver_row(out, "fict-b")["kind"] == "completed"
    assert len(built) == 2


def test_a_hung_attempt_is_abandoned_and_the_process_still_exits(tmp_path: Path) -> None:
    """RF-50: a daemon worker blocked on an event cannot hold interpreter shutdown."""
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent("""
        import sys
        import threading
        from pathlib import Path
        from swreview import cli
        from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
        from swreview.benchmark import attempt
        from tests.unit.test_benchmark_attempts import prepare_driver_set, driver_run

        now = [0.0]
        entered = threading.Event()
        never = threading.Event()

        class HungProvider(FakeProvider):
            def run(self, **options):
                assert threading.current_thread().daemon
                entered.set()
                never.wait()

        real_get = attempt.queue.Queue.get

        def wait(self, block=True, timeout=None):
            if not block:
                return real_get(self, block=False)
            assert entered.wait(30)
            now[0] = 3.0
            raise attempt.queue.Empty

        attempt.queue.Queue.get = wait
        folder = Path(sys.argv[1])
        cli.provider_factory = lambda settings, efficiency=None: HungProvider(
            script=[ScriptedTurn(text="")], model=settings.model, clock=lambda: now[0]
        )
        driver_run(prepare_driver_set(folder), folder / "run",
                   package_time_limit_s=1, stream_activity_window_s=1, stop_grace_s=1,
                   clock=lambda: now[0])
        assert entered.is_set()
    """)
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert driver_row(tmp_path / "run")["class"] == "abandoned"
    assert not (tmp_path / "run/fict-a").exists()


def test_the_wall_clock_stops_answer_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float],
    driver_clock: DriverClock,
) -> None:
    from swreview.agent.checklist import load_checklist
    from swreview.benchmark.answers import read_answer_log
    from swreview.checks.standards.profile import load_profile
    from tests.support import roles_review
    from tests.unit.test_benchmark_case_file import case, case_file_set, roles_answer

    profile = roles_review.write_profile(tmp_path)
    preflighted = runner.preflight_set(
        case_file_set(tmp_path, case(roles_answer())), load_profile(profile), load_checklist()
    )
    package_id = preflighted.benchmark_set.packages[0].package_id
    built = install_driver_providers(
        monkeypatch, [[ScriptedTurn(text=" ".join(["fict"] * 30), delta_interval_s=1)]],
        clock=driver_clock, sleep=driver_clock.sleep,
    )
    out = tmp_path / "run"
    assert driver_run(
        preflighted, out, standards_profile=profile, **driver_clock.options()
    ) == [out / package_id]
    assert driver_row(out, package_id)["class"] == "wall_clock"
    assert read_answer_log(out / package_id).ended == "stopped"
    assert built[0]._turn_index == 1
    assert not any(event.type == "evidence.answered" for event in driver_events(out / package_id))


# --- T196: records, promotion, scrubbing and command output ----------------------------


def test_an_internal_error_naming_a_local_path_records_no_local_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    from tests.support.local_paths import scan_folder

    preflighted = prepare_driver_set(tmp_path)
    out = tmp_path / "run"

    class BrokenProvider(FakeProvider):
        def run(self, **options: Any) -> Any:
            raise PermissionError(f"cannot read {out / 'attempts/fict-a/1/private.txt'}")

    install_driver_providers(monkeypatch, [[ScriptedTurn(text="")]], kind=BrokenProvider)
    assert driver_run(preflighted, out) == []
    row = driver_row(out)
    assert (row["kind"], row["class"], row["error_class"]) == (
        "infrastructure",
        "internal_error",
        "PermissionError",
    )
    assert "<run>/attempts/fict-a/1/private.txt" in row["message"].replace("\\", "/")
    errors = [event.body for event in driver_events(out / row["folder"]) if event.type == "error"]
    assert errors and all(
        "<run>/attempts/fict-a/1/private.txt" in body["message"].replace("\\", "/")
        for body in errors
    )
    assert scan_folder(out) == []


def test_an_adapter_error_naming_a_local_path_is_found_by_the_scanner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    from tests.support.local_paths import scan_folder

    preflighted = prepare_driver_set(tmp_path)
    out = tmp_path / "run"
    message = f"fict adapter cannot read {out / 'attempts/fict-a/1/private.txt'}"
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="", fails=TransientError(message))]])
    driver_run(preflighted, out)
    row = driver_row(out)
    folder = out / row["folder"]
    errors = [event.body for event in driver_events(folder) if event.type == "error"]
    assert errors[0]["message"] == message
    assert str(out) not in errors[1]["message"]
    assert "<run>" in row["message"]
    assert any(offence.file == events.event_stream(folder) for offence in scan_folder(out))


def test_a_profile_changed_between_attempts_stops_the_run_with_exit_1_naming_both_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    from typer.testing import CliRunner

    from swreview import cli
    from swreview.benchmark.digest import sha256_of
    from swreview.checks.standards.profile import display_digest
    from tests.unit.test_run_provenance import example_profile_copy

    prepare_driver_set(tmp_path, ("fict-a", "fict-b"))
    install_driver_providers(
        monkeypatch, [[ScriptedTurn(text="Reviewed first.")], [ScriptedTurn(text="Unreached.")]]
    )
    profile = example_profile_copy(tmp_path / "profiles")
    recorded = sha256_of(profile)
    real_body = cli._review_fn
    reviewed: list[str] = []

    def body(package_dir: Path, out_dir: Path, **options: Any) -> Any:
        reviewed.append(package_dir.name)
        result = real_body(package_dir, out_dir, **options)
        profile.write_bytes(profile.read_bytes() + b"\n# fict changed profile\n")
        return result

    monkeypatch.setattr(cli, "_review_fn", body)
    out = tmp_path / "run"
    result = CliRunner().invoke(
        cli.app,
        [
            "benchmark",
            "run",
            "--set",
            str(tmp_path / "set.json"),
            "--out",
            str(out),
            "--provider",
            "fake",
            "--standards-profile",
            str(profile),
        ],
    )
    assert result.exit_code == 1, result.stdout + result.stderr
    assert reviewed == ["fict-a"]
    line = result.stderr.strip()
    assert display_digest(recorded) in line and display_digest(sha256_of(profile)) in line
    assert str(tmp_path) not in line and str(profile) not in line
    assert not (out / "attempts/fict-b/1").exists()


def test_a_kept_attempt_is_promoted_by_one_rename_and_a_failed_one_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    preflighted = prepare_driver_set(tmp_path, ("fict-a", "fict-b", "fict-c"))
    install_driver_providers(
        monkeypatch,
        [
            [ScriptedTurn(text="Reviewed.")],
            [ScriptedTurn(text="", fails=TransientError("fict exhausted request"))],
            [ScriptedTurn(text="", stop_reason="SAFETY", end_reason="error")],
        ],
    )
    renamed: list[tuple[Path, Path]] = []
    real_rename = Path.rename
    out = tmp_path / "run"

    def rename(path: Path, target: Any) -> Path:
        target = Path(target)
        if path.parent.parent.name == "attempts":
            package_id = path.parent.name
            row = driver_row(out, package_id)
            assert row["kind"] in ("completed", "behavioural")
            assert row["folder"] == package_id
            assert driver_status(out)["packages"][package_id]["kept_attempt"] == 1
            renamed.append((path, target))
        return real_rename(path, target)

    monkeypatch.setattr(Path, "rename", rename)
    assert driver_run(preflighted, out) == [out / "fict-a", out / "fict-c"]
    assert renamed == [
        (out / "attempts/fict-a/1", out / "fict-a"),
        (out / "attempts/fict-c/1", out / "fict-c"),
    ]
    failed = driver_row(out, "fict-b")
    assert failed["folder"] == "attempts/fict-b/1"
    assert (out / failed["folder"]).is_dir()


def test_every_record_is_written_atomically_with_lf_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    from typer.testing import CliRunner

    from swreview import atomic, cli

    prepare_driver_set(tmp_path)
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="Reviewed.")]])
    written: list[tuple[Path, bytes]] = []
    real_write = atomic.write_atomic

    def write(path: Path, data: bytes) -> None:
        written.append((Path(path), data))
        real_write(path, data)

    monkeypatch.setattr(atomic, "write_atomic", write)
    out = tmp_path / "run"
    result = CliRunner().invoke(
        cli.app,
        [
            "benchmark",
            "run",
            "--set",
            str(tmp_path / "set.json"),
            "--out",
            str(out),
            "--provider",
            "fake",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    names = {
        "run-provenance.json",
        "benchmark-set.json",
        "run-status.json",
        "prompts.json",
        "answer-log.json",
        "attention.json",
    }
    assert names <= {path.name for path, data in written}
    for path, data in written:
        if path.name in names:
            assert data.endswith(b"\n") and b"\r" not in data, path
            promoted = out / "fict-a" / path.name if path.parent.name == "1" else path
            assert promoted.read_bytes().endswith(b"\n")
            assert b"\r" not in promoted.read_bytes()


def test_an_offline_run_without_the_tokenizer_vocabulary_refuses_nothing_and_counts_read_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    from typer.testing import CliRunner

    from swreview import cli, tokens
    from swreview.report.session import load_session
    from tests.support.answer_keys import write_key

    prepare_driver_set(tmp_path)
    install_driver_providers(
        monkeypatch,
        [[ScriptedTurn(text="Reviewed.", tool_calls=(ScriptedToolCall("list_components"),))]],
    )
    write_key(tmp_path / "answer_keys", "fict-a")

    def missing() -> Any:
        raise tokens.TokenizerUnavailable("fict offline vocabulary unavailable")

    monkeypatch.setattr(tokens, "load_encoding", missing)
    tokens.encoding.cache_clear()
    out = tmp_path / "run"
    invoke = CliRunner().invoke
    try:
        result = invoke(
            cli.app,
            [
                "benchmark",
                "run",
                "--set",
                str(tmp_path / "set.json"),
                "--out",
                str(out),
                "--provider",
                "fake",
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        scored = invoke(
            cli.app,
            ["benchmark", "score", str(out), "--answer-keys", str(tmp_path / "answer_keys")],
        )
        assert scored.exit_code == 0, scored.stdout + scored.stderr
        reported = invoke(
            cli.app, ["benchmark", "report", str(out), "--out", str(tmp_path / "report")]
        )
        assert reported.exit_code == 0, reported.stdout + reported.stderr
        session = load_session(out / "fict-a/session.json")
        assert session.steps
        assert all(step.result_tokens is None for step in session.steps)
        stored = json.loads((out / "fict-a/session.json").read_bytes())["steps"]
        assert all(step.get("result_tokens") is None for step in stored)
    finally:
        tokens.encoding.cache_clear()


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_run_prints_one_line_per_package_and_json_carries_each_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    driver_sleeps: list[float],
    json_output: bool,
    fails: bool,
) -> None:
    """94A: the returned SAFETY stop is scripted; no Gemini adapter is built."""
    from typer.testing import CliRunner

    from swreview import cli

    prepare_driver_set(tmp_path, ("fict-a", "fict-b", "fict-c"))
    install_driver_providers(
        monkeypatch,
        [
            [ScriptedTurn(text="Reviewed.")],
            [ScriptedTurn(text="", stop_reason="SAFETY", end_reason="error")],
            [ScriptedTurn(text="", fails=TransientError("fict exhausted request"))]
            if fails
            else [ScriptedTurn(text="Reviewed last.")],
        ],
    )
    out = tmp_path / "run"
    result = CliRunner().invoke(
        cli.app,
        [
            "benchmark",
            "run",
            "--set",
            str(tmp_path / "set.json"),
            "--out",
            str(out),
            "--provider",
            "fake",
            *(["--json"] if json_output else []),
        ],
    )
    assert result.exit_code == (1 if fails else 0), result.stdout + result.stderr
    assert result.stderr.splitlines() == (
        [f"error: infrastructure failures: fict-c; run swreview benchmark resume {out}"]
        if fails else []
    )
    if json_output:
        payload = json.loads(result.stdout)
        rows = payload["packages"]
        assert [
            (row["package_id"], row["kind"], row["class"], row["stop_reason"], row["attempts"])
            for row in rows
        ] == [
            ("fict-a", "completed", None, None, 1),
            ("fict-b", "behavioural", "provider_stop", "SAFETY", 1),
            ("fict-c", "infrastructure", "provider_error", None, 1)
            if fails
            else ("fict-c", "completed", None, None, 1),
        ]
        assert rows[0]["out_dir"] == str(out / "fict-a")
        assert rows[1]["out_dir"] == str(out / "fict-b")
    else:
        assert result.stdout.splitlines() == [
            "fict-a: completed",
            "fict-b: behavioural provider_stop (SAFETY)",
            "fict-c: infrastructure provider_error (TransientError, 5 retries)"
            if fails
            else "fict-c: completed",
        ]


def test_a_failed_promotion_rename_leaves_the_attempt_for_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    """RF-22: a paid kept attempt survives a Windows rename refusal and is never replayed."""
    from swreview import cli
    from tests.unit.test_benchmark_resume import resume_command, snapshot, start_run

    out = tmp_path / "run"
    rename = Path.rename

    def locked(path: Path, target: Any) -> Path:
        if path == out / "attempts/fict-a/1":
            raise PermissionError("fict folder locked")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", locked)
    _, first = start_run(
        tmp_path, monkeypatch,
        [[ScriptedTurn(text="Reviewed first.")], [ScriptedTurn(text="Reviewed next.")]],
        ("fict-a", "fict-b"),
    )
    assert first.exit_code == 1, first.stdout + first.stderr
    assert f"swreview benchmark resume {out}" in first.stderr
    status = driver_status(out)
    assert status["packages"]["fict-a"]["kept_attempt"] == 1
    assert driver_row(out)["folder"] == "attempts/fict-a/1"
    kept_bytes = snapshot(out / "attempts/fict-a/1")
    next_bytes = snapshot(out / "fict-b")

    monkeypatch.setattr(Path, "rename", rename)
    install_driver_providers(monkeypatch, [[]])  # Provider preflight sends no request.

    def never_review(*args: Any, **options: Any) -> None:
        pytest.fail("promotion must reuse the kept attempt")

    monkeypatch.setattr(cli, "_review_fn", never_review)
    resumed = resume_command(out)
    assert resumed.exit_code == 0, resumed.stdout + resumed.stderr
    assert snapshot(out / "fict-a") == kept_bytes
    assert snapshot(out / "fict-b") == next_bytes
    assert len(driver_status(out)["packages"]["fict-a"]["attempts"]) == 1
    assert driver_row(out)["folder"] == "fict-a"
    assert first.stdout.splitlines() == ["fict-b: completed"]
    assert "fict-a: promotion failed: fict folder locked" in first.stderr


def test_status_is_recorded_before_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    """A crash after recording the destination is recoverable from the physical source."""
    from tests.unit.test_benchmark_resume import resume_command, snapshot, start_run

    out = tmp_path / "run"
    rename = Path.rename
    observed: list[dict[str, Any]] = []

    def crash(path: Path, target: Any) -> Path:
        if path == out / "attempts/fict-a/1":
            observed.append(driver_status(out)["packages"]["fict-a"])
            raise RuntimeError("fict crash between status and promotion")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", crash)
    _, first = start_run(tmp_path, monkeypatch, [[ScriptedTurn(text="Reviewed.")]], ("fict-a",))
    assert first.exit_code == 1
    assert observed[0]["kept_attempt"] == 1
    assert observed[0]["attempts"][0]["kind"] == "completed"
    assert observed[0]["attempts"][0]["folder"] == "fict-a"
    kept_bytes = snapshot(out / "attempts/fict-a/1")
    monkeypatch.setattr(Path, "rename", rename)
    install_driver_providers(monkeypatch, [[]])
    result = resume_command(out)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert snapshot(out / "fict-a") == kept_bytes
    assert driver_status(out)["packages"]["fict-a"] == observed[0]


def test_unattended_runtime_is_the_kept_attempts_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    from swreview import cli
    from swreview.report.session import load_session
    from tests.unit.test_benchmark_resume import start_run

    out, first = start_run(
        tmp_path, monkeypatch,
        [[ScriptedTurn(text="", fails=TransientError("fict exhausted request"))]],
        ("fict-a",),
    )
    assert first.exit_code == 1
    before = driver_status(out)["packages"]["fict-a"]["attempts"][0]
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="Reviewed on resume.")]])
    clock_value = [9000.0]

    def review(package_dir: Path, folder: Path, **options: Any) -> Any:
        result = cli._review_fn(package_dir, folder, **options)
        clock_value[0] += 60.0
        return result

    runner.resume_benchmark(out, review_fn=review, clock=lambda: clock_value[0])
    session = load_session(out / "fict-a/session.json")
    assert session.timing.unattended_runtime_minutes == 1.0
    assert driver_status(out)["packages"]["fict-a"]["attempts"][0] == before


def test_no_home_folder_still_scrubs_the_run_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float]
) -> None:
    """104A/92A: a missing account home never prevents scrubbing run/repo/tmp."""
    from tests.support.local_paths import scan_folder

    preflighted = prepare_driver_set(tmp_path)
    out = tmp_path / "run"

    class BrokenProvider(FakeProvider):
        def run(self, **options: Any) -> Any:
            raise PermissionError(f"cannot read {out / 'attempts/fict-a/1/private.txt'}")

    install_driver_providers(monkeypatch, [[ScriptedTurn(text="")]], kind=BrokenProvider)

    def no_home(cls: type[Path]) -> Path:
        raise RuntimeError("fict account has no home folder")

    monkeypatch.setattr(Path, "home", classmethod(no_home))
    assert driver_run(preflighted, out) == []
    row = driver_row(out)
    assert row["error_class"] == "PermissionError"
    assert "<run>" in row["message"] and str(out) not in row["message"]
    assert scan_folder(out) == []
