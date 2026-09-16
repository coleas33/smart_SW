"""The usage ledger: `usage` events in, `session.usage` out (T014).

`EventSink` already takes listeners, so the accumulator is one of them: it sees every
`usage` event as it is written and every `turn.ended` that delimits a turn, and
`ReviewRun.finalize()` asks it for the session's total **before** `save_session`. One
accumulator, one write point, one summing rule, which is `SessionUsage.summed` and is
called and not re-implemented here.

The test this module exists for is `test_a_turn_that_raises_on_its_third_round_records_the
_first_two`. Both adapters raise out of their round loop on a provider error and
`_run_turn`'s `except Exception` branch finalizes and re-raises with no `TurnResult` in
hand, so a design that carried usage home on `TurnResult` would report **zero cost for the
turn that cost the most**. The ledger reads the stream instead, and the stream is written
per event, so the rounds already paid for are already there.

Two counts are easy to confuse and are pinned apart below:

- `rounds` counts **model round trips** - one `usage` event each. It is the counter levers
  5, 6 and 7 are unmeasurable without.
- `session.steps` counts **tool calls**. One round that asks for three tools is one round
  and three steps, and with lever 6 on the two diverge by exactly the amount lever 6 is
  trying to save.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
from swreview.agent.providers import (
    EffortLevel,
    EffortMapping,
    EventCallback,
    ProviderName,
    ProviderTool,
    TokenUsage,
    TurnResult,
    usage_body,
)
from swreview.agent.providers.fake import SYNTHETIC_USAGE, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import UsageLedger
from swreview.report.session import SessionUsage
from tests.support.contracts import contract_validator

MODEL = "fake-1"
EFFORT: EffortLevel = "high"

ROUND_ONE = TokenUsage(
    input_tokens=1_009,
    cached_input_tokens=101,
    cache_write_tokens=None,
    output_tokens=53,
    reasoning_tokens=11,
    tool_result_input_tokens=None,
    total_tokens=1_062,
    latency_s=0.5,
)
ROUND_TWO = TokenUsage(
    input_tokens=2_003,
    cached_input_tokens=1_009,
    cache_write_tokens=None,
    output_tokens=71,
    reasoning_tokens=17,
    tool_result_input_tokens=None,
    total_tokens=2_074,
    latency_s=0.25,
)
ROUND_THREE = TokenUsage(
    input_tokens=3_001,
    cached_input_tokens=2_003,
    cache_write_tokens=None,
    output_tokens=29,
    reasoning_tokens=7,
    tool_result_input_tokens=None,
    total_tokens=3_030,
    latency_s=0.125,
)
"""Three rounds whose numbers are distinct in every field, so a total built from the wrong
subset of them is a different number rather than a coincidence."""


# --- the adapter stand-in ----------------------------------------------------------------


class RoundedProvider:
    """An adapter that emits a scripted `usage` event per round, then ends or raises.

    Neither the fake nor a recorded SDK exchange can produce "three rounds, the third of
    which raises" without dragging in a transport, and that sequence is the one claim this
    module is about. Everything else it does is what the real adapters do: it emits through
    `usage_body`, counts its own rounds from zero, and never touches the session.
    """

    name = ProviderName.FAKE

    def __init__(self, *turns: Sequence[TokenUsage], fail_after: int | None = None) -> None:
        self.model = MODEL
        self._turns = list(turns)
        self._fail_after = fail_after
        """How many rounds of the **first** turn succeed before it raises; None never fails."""

    def effort_mapping(self, effort: EffortLevel) -> EffortMapping:
        return EffortMapping(requested=effort, provider_param="fake.effort", provider_value=effort)

    def run(
        self,
        *,
        system: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[ProviderTool],
        effort: EffortLevel,
        max_steps: int,
        on_event: EventCallback,
    ) -> TurnResult:
        if not self._turns:
            raise AssertionError("the script has no turns left")
        rounds = self._turns.pop(0)
        for index, usage in enumerate(rounds):
            if self._fail_after is not None and index == self._fail_after:
                raise RuntimeError("the provider connection dropped")
            on_event(
                "usage",
                usage_body(usage, round_index=index, provider=self.name, model=self.model),
            )
        history = [dict(message) for message in messages]
        history.append({"role": "assistant", "content": "done"})
        return TurnResult(reason="end", text="done", steps=0, messages=history)


@pytest.fixture
def start(tmp_package_dir: Path, tmp_path: Path) -> Callable[..., runner.ReviewRun]:
    """`start_review` over the fixture package with whatever provider the test brings."""

    def begin(provider: Any, **kwargs: Any) -> runner.ReviewRun:
        return runner.start_review(
            tmp_package_dir,
            tmp_path / "out",
            provider=provider,
            effort=EFFORT,
            **kwargs,
        )

    return begin


def written_session(run: runner.ReviewRun) -> dict[str, Any]:
    return json.loads(run.session_path.read_text(encoding="utf-8"))


def events_of(run: runner.ReviewRun) -> list[dict[str, Any]]:
    text = run.events_path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


# --- the listener on its own ---------------------------------------------------------------


def feed(ledger: UsageLedger, *events: tuple[str, dict[str, Any]]) -> None:
    """Hand the ledger the events a sink would, without building a sink."""
    from datetime import UTC, datetime

    from swreview.agent.providers import AgentEvent

    for seq, (event_type, body) in enumerate(events, start=1):
        ledger(
            AgentEvent(
                seq=seq,
                at=datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC),
                type=event_type,  # type: ignore[arg-type]
                body=body,
            )
        )


def usage_event(usage: TokenUsage, round_index: int = 0) -> tuple[str, dict[str, Any]]:
    return ("usage", usage_body(usage, round_index=round_index, provider="fake", model=MODEL))


def turn_ended() -> tuple[str, dict[str, Any]]:
    return ("turn.ended", {"reason": "end"})


def test_a_ledger_that_saw_nothing_reports_no_usage_at_all() -> None:
    """`None`, not an all-zero record: a run whose provider reported nothing cost
    something we did not measure, and that is not zero (Principle I)."""
    assert UsageLedger().usage() is None


def test_one_usage_event_is_one_round() -> None:
    ledger = UsageLedger()

    feed(ledger, usage_event(ROUND_ONE), turn_ended())

    recorded = ledger.usage()
    assert recorded is not None
    assert recorded.rounds == 1
    assert recorded.turns == 1
    assert recorded.totals == ROUND_ONE


def test_the_ledger_ignores_every_event_that_is_not_usage_or_turn_ended() -> None:
    """It listens to the whole stream; only two types of it mean anything here."""
    ledger = UsageLedger()

    feed(
        ledger,
        ("session.started", {"model": MODEL}),
        ("text.delta", {"text": "checking"}),
        usage_event(ROUND_ONE),
        ("tool.started", {"step_index": 0, "tool": "list_gaps", "arguments": {}}),
        turn_ended(),
        ("session.ended", {"ended_at": None, "timing": {}}),
    )

    recorded = ledger.usage()
    assert recorded is not None
    assert recorded.rounds == 1


def test_turns_are_delimited_by_turn_ended_and_by_turn_follows_them() -> None:
    ledger = UsageLedger()

    feed(
        ledger,
        usage_event(ROUND_ONE, 0),
        usage_event(ROUND_TWO, 1),
        turn_ended(),
        usage_event(ROUND_THREE, 0),
        turn_ended(),
    )

    recorded = ledger.usage()
    assert recorded is not None
    assert recorded.rounds == 3
    assert recorded.turns == 2
    assert [one.total_tokens for one in recorded.by_turn] == [
        ROUND_ONE.total_tokens + ROUND_TWO.total_tokens,
        ROUND_THREE.total_tokens,
    ]


def test_a_turn_that_produced_no_round_is_not_counted_as_a_turn() -> None:
    """`turns` is turns that produced at least one round, which is what `summed` defines."""
    ledger = UsageLedger()

    feed(ledger, turn_ended(), usage_event(ROUND_ONE), turn_ended(), turn_ended())

    recorded = ledger.usage()
    assert recorded is not None
    assert recorded.turns == 1
    assert recorded.rounds == 1


def test_rounds_that_never_ended_a_turn_still_count() -> None:
    """The failure path in miniature: the turn raised, so no `turn.ended` followed it."""
    ledger = UsageLedger()

    feed(ledger, usage_event(ROUND_ONE, 0), usage_event(ROUND_TWO, 1))

    recorded = ledger.usage()
    assert recorded is not None
    assert recorded.rounds == 2
    assert recorded.turns == 1
    assert recorded.totals.total_tokens == ROUND_ONE.total_tokens + ROUND_TWO.total_tokens


def test_one_null_in_one_round_makes_that_total_null_and_leaves_the_others_summed() -> None:
    """The summing rule, reached through the ledger: a partial sum silently understates."""
    unreported = ROUND_TWO.model_copy(update={"output_tokens": None})
    ledger = UsageLedger()

    feed(ledger, usage_event(ROUND_ONE, 0), usage_event(unreported, 1), turn_ended())

    recorded = ledger.usage()
    assert recorded is not None
    assert recorded.totals.output_tokens is None
    assert recorded.totals.input_tokens == ROUND_ONE.input_tokens + ROUND_TWO.input_tokens


def test_the_ledger_sums_through_session_usage_and_not_through_a_second_rule() -> None:
    """One summing rule: the ledger's answer is `SessionUsage.summed`'s answer."""
    ledger = UsageLedger()

    feed(ledger, usage_event(ROUND_ONE, 0), usage_event(ROUND_TWO, 1), turn_ended())

    assert ledger.usage() == SessionUsage.summed([ROUND_ONE, ROUND_TWO], [2])


def test_a_usage_body_missing_a_count_raises_rather_than_reading_as_unknown() -> None:
    """A dropped field is a defect in the producer, not a provider that said nothing."""
    body = usage_body(ROUND_ONE, round_index=0, provider="fake", model=MODEL)
    del body["reasoning_tokens"]
    ledger = UsageLedger()

    with pytest.raises(KeyError):
        feed(ledger, ("usage", body))


# --- through a real run --------------------------------------------------------------------


def test_a_run_records_its_usage_on_the_session(
    start: Callable[..., runner.ReviewRun],
) -> None:
    run = start(RoundedProvider([ROUND_ONE, ROUND_TWO]))

    session = run.start()

    assert session.usage is not None
    assert session.usage.rounds == 2
    assert session.usage.turns == 1
    assert session.usage.totals.total_tokens == (
        ROUND_ONE.total_tokens + ROUND_TWO.total_tokens
    )


def test_the_usage_is_written_into_session_json_before_the_file_is_saved(
    start: Callable[..., runner.ReviewRun],
) -> None:
    """`finalize()` asks the ledger and then saves, so the file on disk carries it."""
    run = start(RoundedProvider([ROUND_ONE]))

    run.start()

    written = written_session(run)["usage"]
    assert written["rounds"] == 1
    assert written["totals"]["total_tokens"] == ROUND_ONE.total_tokens
    assert written["totals"]["cache_write_tokens"] is None


def test_a_turn_that_raises_on_its_third_round_records_the_first_two(
    start: Callable[..., runner.ReviewRun],
) -> None:
    """The claim this whole design exists for (RK-2).

    Five successful rounds and a rate limit on the sixth must not be reported as a turn
    that cost nothing. `_run_turn`'s `except` branch finalizes before it re-raises, and
    the ledger has already seen the rounds the stream already carries.
    """
    run = start(
        RoundedProvider([ROUND_ONE, ROUND_TWO, ROUND_THREE], fail_after=2)
    )

    with pytest.raises(RuntimeError, match="connection dropped"):
        run.start()

    session = run.session
    assert session.usage is not None
    assert session.usage.rounds == 2
    assert session.usage.totals.total_tokens == (
        ROUND_ONE.total_tokens + ROUND_TWO.total_tokens
    )
    assert written_session(run)["usage"]["rounds"] == 2


def test_a_failed_turn_still_counts_as_a_turn_because_the_runner_ends_it(
    start: Callable[..., runner.ReviewRun],
) -> None:
    """`_run_turn` emits `turn.ended {reason: error}` before it finalizes, so the rounds
    the failed turn paid for are one turn's worth and not an unended remainder."""
    run = start(RoundedProvider([ROUND_ONE, ROUND_TWO, ROUND_THREE], fail_after=2))

    with pytest.raises(RuntimeError):
        run.start()

    session = run.session
    assert session.usage is not None
    assert session.usage.turns == 1
    assert len(session.usage.by_turn) == 1


def test_a_second_turn_adds_to_the_first_rather_than_replacing_it(
    start: Callable[..., runner.ReviewRun],
) -> None:
    """`finalize()` runs once per turn and recomputes the whole session every time."""
    run = start(RoundedProvider([ROUND_ONE], [ROUND_TWO, ROUND_THREE]))

    run.start()
    first = run.session.usage
    assert first is not None
    assert first.rounds == 1

    session = run.continue_session("keep going")

    assert session.usage is not None
    assert session.usage.rounds == 3
    assert session.usage.turns == 2


def test_a_provider_that_reports_no_usage_leaves_the_session_without_any(
    start: Callable[..., runner.ReviewRun],
) -> None:
    """Absent, not zero, and a session written this way validates as a pre-feature one."""
    run = start(RoundedProvider([]))

    session = run.start()

    assert session.usage is None
    assert written_session(run)["usage"] is None


def test_rounds_are_round_trips_and_not_tool_calls(
    start: Callable[..., runner.ReviewRun],
) -> None:
    """One scripted fake turn is one round however many tools it calls.

    `TurnResult.steps` counts the calls, `usage.rounds` counts the requests, and lever 6
    is measured on the difference between them.
    """
    from swreview.agent.providers.fake import FakeProvider

    run = start(
        FakeProvider(
            script=[
                ScriptedTurn(
                    text="done",
                    tool_calls=(
                        ScriptedToolCall(name="get_package_summary"),
                        ScriptedToolCall(name="get_review_checklist"),
                        ScriptedToolCall(name="list_gaps"),
                    ),
                )
            ],
            model=MODEL,
        )
    )

    session = run.start()

    assert len(session.steps) == 3
    assert session.usage is not None
    assert session.usage.rounds == 1
    assert session.usage.totals == SYNTHETIC_USAGE


def test_the_session_ended_event_carries_the_same_totals(
    start: Callable[..., runner.ReviewRun],
) -> None:
    """The pane reads the stream, so it does not need a summing rule of its own (T016)."""
    run = start(RoundedProvider([ROUND_ONE, ROUND_TWO]))

    session = run.start()

    ended = [event for event in events_of(run) if event["type"] == "session.ended"]
    assert len(ended) == 1
    assert session.usage is not None
    assert ended[0]["body"]["usage"] == session.usage.model_dump(mode="json")


def test_session_ended_omits_usage_when_no_round_reported_any(
    start: Callable[..., runner.ReviewRun],
) -> None:
    """Optional in the contract, so a stream with nothing to say says nothing."""
    run = start(RoundedProvider([]))

    run.start()

    ended = [event for event in events_of(run) if event["type"] == "session.ended"]
    assert "usage" not in ended[0]["body"]


def test_every_event_of_a_recorded_run_still_validates_against_the_contract(
    start: Callable[..., runner.ReviewRun],
) -> None:
    validator = contract_validator("chat-events.schema.json")
    run = start(RoundedProvider([ROUND_ONE, ROUND_TWO]))

    run.start()

    for event in events_of(run):
        validator.validate(event)
