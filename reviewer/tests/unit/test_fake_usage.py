"""The fake provider's synthetic usage (T010).

The fake is what every runner, ledger, report and scorecard test drives, so it has to
produce a usage record - otherwise the whole path from a round trip to `session.usage` is
exercised only against a network nothing in CI has. Its one deliberate difference from a
real adapter is that nothing is random, and a fixed synthetic constant keeps exactly that:
two runs of one script record byte-identical usage, so a test downstream can assert exact
totals rather than a range.

Two properties of the constant are load-bearing and are asserted here rather than left to
whoever edits it next:

- **It is not round-numbered.** An accidental zero, a dropped field or a total built from
  the wrong two addends is visible against 1,337 and invisible against 1,000.
- **It carries at least one `None`.** The any-null-in-any-round-makes-the-total-null rule
  is then exercised by the default fixture every ledger test already uses, instead of only
  by a special test someone has to remember to write.
"""

from __future__ import annotations

import pytest

from swreview.agent.providers import TokenUsage
from swreview.agent.providers.fake import SYNTHETIC_USAGE, ScriptedToolCall, ScriptedTurn
from tests.unit.test_fake_provider import FakeTool, Sink, provider, run


def test_a_scripted_turn_carries_the_synthetic_usage_by_default() -> None:
    """Every script already written gets usage without being edited."""
    assert ScriptedTurn(text="done").usage == SYNTHETIC_USAGE


def test_the_synthetic_constant_is_a_token_usage_with_no_round_numbers() -> None:
    """A round number hides an accidental zero or a mis-summed total."""
    assert isinstance(SYNTHETIC_USAGE, TokenUsage)
    reported = [
        SYNTHETIC_USAGE.input_tokens,
        SYNTHETIC_USAGE.cached_input_tokens,
        SYNTHETIC_USAGE.output_tokens,
        SYNTHETIC_USAGE.reasoning_tokens,
        SYNTHETIC_USAGE.total_tokens,
    ]
    assert all(count is not None and count > 0 for count in reported)
    assert all(count % 100 != 0 for count in reported)


def test_the_synthetic_constant_carries_at_least_one_unknown_count() -> None:
    """So the any-null-makes-the-total-null rule is exercised by the default fixture."""
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
        "tool_result_input_tokens",
        "total_tokens",
    )
    assert any(getattr(SYNTHETIC_USAGE, name) is None for name in fields)


def test_the_synthetic_counts_nest_the_way_a_real_providers_do() -> None:
    """Cached is inside input, and the total is input plus output. A fixture whose numbers
    do not add up would let a ledger that sums the wrong fields look correct."""
    assert SYNTHETIC_USAGE.cached_input_tokens < SYNTHETIC_USAGE.input_tokens
    assert SYNTHETIC_USAGE.reasoning_tokens < SYNTHETIC_USAGE.output_tokens
    assert SYNTHETIC_USAGE.total_tokens == (
        SYNTHETIC_USAGE.input_tokens + SYNTHETIC_USAGE.output_tokens
    )
    assert SYNTHETIC_USAGE.latency_s > 0


def test_one_record_per_scripted_round() -> None:
    """A scripted turn is one round trip, so playing it records exactly one usage."""
    fake = provider(ScriptedTurn(text="done"))

    run(fake, [])

    assert fake.round_usage == [SYNTHETIC_USAGE]


def test_a_turn_with_tool_calls_is_still_one_scripted_round() -> None:
    """The fake has no round loop: its calls and its text are one scripted exchange."""
    fake = provider(
        ScriptedTurn(text="done", tool_calls=(ScriptedToolCall(name="get_component"),))
    )

    run(fake, [FakeTool(name="get_component")])

    assert len(fake.round_usage) == 1


def test_a_script_can_set_its_own_usage_per_turn() -> None:
    """A ledger test that needs two different rounds writes them into the script."""
    second = TokenUsage(
        input_tokens=2_113,
        cached_input_tokens=1_337,
        cache_write_tokens=None,
        output_tokens=97,
        reasoning_tokens=31,
        tool_result_input_tokens=None,
        total_tokens=2_210,
        latency_s=0.11,
    )
    fake = provider(ScriptedTurn(text="one"), ScriptedTurn(text="two", usage=second))

    run(fake, [])
    assert fake.round_usage == [SYNTHETIC_USAGE]

    run(fake, [])
    assert fake.round_usage == [second]


def test_a_turn_scripted_with_no_usage_records_none() -> None:
    """The provider-did-not-report case, so the unknown path has a fixture too."""
    fake = provider(ScriptedTurn(text="done", usage=None))

    run(fake, [])

    assert fake.round_usage == []


def test_two_runs_of_the_same_script_record_identical_usage() -> None:
    """The fake's contract is that nothing is random, usage included."""
    script = (
        ScriptedTurn(text="one", tool_calls=(ScriptedToolCall(name="get_component"),)),
        ScriptedTurn(text="two"),
    )

    def play() -> list[dict[str, object]]:
        fake = provider(*script)
        recorded: list[dict[str, object]] = []
        for _ in script:
            run(fake, [FakeTool(name="get_component")], sink=Sink())
            recorded.extend(one.model_dump(mode="json") for one in fake.round_usage)
        return recorded

    assert play() == play()


def test_a_fresh_fake_has_recorded_nothing() -> None:
    assert provider(ScriptedTurn(text="done")).round_usage == []


@pytest.mark.parametrize("turns", [1, 2, 3])
def test_the_record_is_this_turns_round_only(turns: int) -> None:
    """An adapter sees one turn, which is the convention `step_index` already follows."""
    fake = provider(*(ScriptedTurn(text=f"turn {n}") for n in range(turns)))

    for _ in range(turns):
        run(fake, [])

    assert len(fake.round_usage) == 1
