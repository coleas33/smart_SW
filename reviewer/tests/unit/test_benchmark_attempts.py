"""An attempt's facts come from one replay into the product's usage ledger (T187)."""

from __future__ import annotations

import dataclasses
import gzip
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import events
from swreview.agent.providers import (
    AgentEvent,
    EventCallback,
    ProviderError,
    TokenUsage,
    retry,
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
    provider = FakeProvider(script=script, model=MODEL)
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
