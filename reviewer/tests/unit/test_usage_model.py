"""The two usage records, and the one summing rule the whole feature depends on.

`TokenUsage` is what one model round trip cost, in the fields the provider actually
reported. `SessionUsage` is what a run cost, and `SessionUsage.summed` is the only place
token counts are ever added.

Both records exist to keep one promise: **unknown stays unknown**. `None` means the
provider did not report the field; `0` means it reported zero; nothing anywhere collapses
the two. The consequence that needs a test of its own is the summing rule - a sum over
rounds where any round reported `None` is `None`, not a partial sum, because a partial
sum silently understates and no reader of the number can tell it happened.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from swreview.agent.providers import TokenUsage
from swreview.report.session import SessionUsage

TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
    "tool_result_input_tokens",
    "total_tokens",
)
"""Every nullable count, in declaration order. `latency_s` is not one of them: it is a
float we measured ourselves, so it is never null."""


def usage(**overrides: int | float | None) -> TokenUsage:
    """A fully reported round trip, with any field overridden - `None` included."""
    fields: dict[str, int | float | None] = {
        "input_tokens": 12_043,
        "cached_input_tokens": 10_240,
        "cache_write_tokens": 1_803,
        "output_tokens": 512,
        "reasoning_tokens": 448,
        "tool_result_input_tokens": 97,
        "total_tokens": 12_555,
        "latency_s": 4.31,
    }
    return TokenUsage(**{**fields, **overrides})  # type: ignore[arg-type]


# --- TokenUsage -------------------------------------------------------------------------


def test_token_usage_carries_the_seven_counts_and_a_latency() -> None:
    """The fields, by name, so a rename is a red test and not a silent null everywhere."""
    assert tuple(TokenUsage.model_fields) == (*TOKEN_FIELDS, "latency_s")


@pytest.mark.parametrize("field", TOKEN_FIELDS)
def test_every_count_accepts_none_and_keeps_it(field: str) -> None:
    """A field the provider omitted stays `None`. Coercing it to 0 is the whole hazard."""
    built = usage(**{field: None})
    assert getattr(built, field) is None
    assert built.model_dump()[field] is None


@pytest.mark.parametrize("field", TOKEN_FIELDS)
def test_zero_is_kept_apart_from_unknown(field: str) -> None:
    """`0` means the provider reported zero, and it is not `None`."""
    built = usage(**{field: 0})
    assert getattr(built, field) == 0
    assert getattr(built, field) is not None


@pytest.mark.parametrize("field", TOKEN_FIELDS)
def test_a_negative_count_is_rejected(field: str) -> None:
    """No provider reports a negative token count; one here would be a mapping bug."""
    with pytest.raises(ValidationError):
        usage(**{field: -1})


def test_latency_is_a_float_and_never_none() -> None:
    """If we made the call, we timed it, so there is no unknown latency to carry."""
    assert usage().latency_s == pytest.approx(4.31)
    with pytest.raises(ValidationError):
        usage(latency_s=None)
    with pytest.raises(ValidationError):
        usage(latency_s=-0.1)


def test_an_unexpected_field_is_rejected() -> None:
    """`ProviderModel` is strict: a field we did not declare is a bug, not a passenger."""
    with pytest.raises(ValidationError):
        usage(prompt_tokens=10)


def test_uncached_input_is_a_property_and_not_a_stored_field() -> None:
    """Derived, so it cannot go stale - the rule `Timing.replace` already follows."""
    assert "uncached_input_tokens" not in TokenUsage.model_fields
    assert "uncached_input_tokens" not in usage().model_dump()
    assert isinstance(TokenUsage.uncached_input_tokens, property)


def test_uncached_input_is_input_minus_cached() -> None:
    assert usage().uncached_input_tokens == 12_043 - 10_240


@pytest.mark.parametrize(
    ("input_tokens", "cached_input_tokens"),
    [(None, 10_240), (12_043, None), (None, None)],
)
def test_uncached_input_is_none_when_either_side_is_unknown(
    input_tokens: int | None, cached_input_tokens: int | None
) -> None:
    """Unknown minus known is unknown, not the known half."""
    built = usage(input_tokens=input_tokens, cached_input_tokens=cached_input_tokens)
    assert built.uncached_input_tokens is None


def test_uncached_input_is_zero_when_the_whole_prompt_was_cached() -> None:
    """Zero uncached input is a real answer and must not read as unknown."""
    assert usage(input_tokens=12_043, cached_input_tokens=12_043).uncached_input_tokens == 0


def test_the_cached_share_is_cached_over_input() -> None:
    assert usage().cached_input_share == pytest.approx(10_240 / 12_043)


@pytest.mark.parametrize(
    ("input_tokens", "cached_input_tokens"),
    [(None, 10_240), (12_043, None), (0, 0)],
)
def test_the_cached_share_is_none_when_it_cannot_be_divided(
    input_tokens: int | None, cached_input_tokens: int | None
) -> None:
    """Unknown over anything is unknown, and a share of nothing is not zero."""
    built = usage(input_tokens=input_tokens, cached_input_tokens=cached_input_tokens)
    assert built.cached_input_share is None


def test_a_round_reporting_more_cached_than_input_is_unknown_and_never_a_share() -> None:
    """The containment probe L1 asserts is UNVERIFIED for OpenAI, so this is reachable.

    Both derived values are well defined **only** because cached input is contained in
    input. If a provider ever reports it is not, the honest answer is `None` - unknown -
    and not a ratio above 1 or a negative uncached count. `input_tokens` and
    `cached_input_tokens` are still recorded verbatim, so the violation is visible in
    `scorecard.json` rather than swallowed.
    """
    built = usage(input_tokens=1_000, cached_input_tokens=1_200)

    assert built.cached_input_share is None
    assert built.uncached_input_tokens is None


# --- SessionUsage -----------------------------------------------------------------------


def test_session_usage_holds_rounds_turns_totals_and_by_turn() -> None:
    assert tuple(SessionUsage.model_fields) == ("rounds", "turns", "totals", "by_turn")


def test_summed_adds_every_field_over_every_round() -> None:
    """Three rounds of one turn: the totals are the arithmetic sums, field by field."""
    rounds = [usage(), usage(), usage()]
    summed = SessionUsage.summed(rounds, [3])

    assert summed.rounds == 3
    assert summed.turns == 1
    assert summed.totals.input_tokens == 3 * 12_043
    assert summed.totals.cached_input_tokens == 3 * 10_240
    assert summed.totals.cache_write_tokens == 3 * 1_803
    assert summed.totals.output_tokens == 3 * 512
    assert summed.totals.reasoning_tokens == 3 * 448
    assert summed.totals.tool_result_input_tokens == 3 * 97
    assert summed.totals.total_tokens == 3 * 12_555
    assert summed.totals.latency_s == pytest.approx(3 * 4.31)


@pytest.mark.parametrize("field", TOKEN_FIELDS)
def test_one_null_in_one_round_makes_that_total_null(field: str) -> None:
    """Asserted field by field, because a partial sum understates and nobody can tell.

    Every *other* field of the same session still sums: the rule is per field, so one
    provider that stopped reporting `cache_write_tokens` does not erase the token count.
    """
    rounds = [usage(), usage(**{field: None}), usage()]
    totals = SessionUsage.summed(rounds, [3]).totals

    assert getattr(totals, field) is None
    for other in TOKEN_FIELDS:
        if other != field:
            assert getattr(totals, other) == 3 * getattr(usage(), other)


def test_a_null_never_becomes_a_zero_in_the_total() -> None:
    """The failure this rule exists to prevent, stated the way a reader would hit it."""
    rounds = [usage(cached_input_tokens=None), usage(cached_input_tokens=0)]
    totals = SessionUsage.summed(rounds, [2]).totals
    assert totals.cached_input_tokens is None


def test_latency_always_sums_even_when_every_count_is_unknown() -> None:
    """We timed every request we made, whatever the provider chose to report."""
    rounds = [usage(**dict.fromkeys(TOKEN_FIELDS)), usage(**dict.fromkeys(TOKEN_FIELDS))]
    totals = SessionUsage.summed(rounds, [2]).totals
    assert all(getattr(totals, field) is None for field in TOKEN_FIELDS)
    assert totals.latency_s == pytest.approx(2 * 4.31)


def test_by_turn_is_delimited_by_the_turn_boundaries() -> None:
    """Two turns, two and three rounds: `by_turn` is one summed entry per turn, in order."""
    rounds = [usage(input_tokens=n) for n in (1, 2, 4, 8, 16)]
    summed = SessionUsage.summed(rounds, [2, 5])

    assert summed.rounds == 5
    assert summed.turns == 2
    assert len(summed.by_turn) == summed.turns
    assert [entry.input_tokens for entry in summed.by_turn] == [3, 28]


def test_totals_equal_the_sum_of_by_turn_field_by_field_including_the_nulls() -> None:
    """The invariant a reader relies on: the two ways of adding agree, nulls included."""
    rounds = [usage(), usage(reasoning_tokens=None), usage(), usage()]
    summed = SessionUsage.summed(rounds, [2, 4])
    regrouped = SessionUsage.summed(summed.by_turn, [len(summed.by_turn)])

    assert regrouped.totals.model_dump() == summed.totals.model_dump()
    assert summed.totals.reasoning_tokens is None


def test_a_turn_that_made_no_round_is_not_counted() -> None:
    """`turns` counts turns that produced at least one round, so a repeated boundary is
    not a turn and does not add an empty `by_turn` entry that would read as a free turn."""
    rounds = [usage(), usage()]
    summed = SessionUsage.summed(rounds, [2, 2])
    assert summed.turns == 1
    assert len(summed.by_turn) == 1


def test_rounds_after_the_last_boundary_are_the_turn_that_never_ended() -> None:
    """The failure path, which is the reason usage is a stream event at all.

    A turn that raises on its third round emits no `turn.ended`, so the ledger has no
    boundary for it - and those two paid rounds must still be in `totals` and must still
    be a turn, not silently dropped for want of a delimiter.
    """
    rounds = [usage(input_tokens=1), usage(input_tokens=2), usage(input_tokens=4)]
    summed = SessionUsage.summed(rounds, [1])

    assert summed.rounds == 3
    assert summed.turns == 2
    assert [entry.input_tokens for entry in summed.by_turn] == [1, 6]
    assert summed.totals.input_tokens == 7


def test_a_session_with_no_rounds_sums_to_zero_and_not_to_unknown() -> None:
    """Nothing was spent and nothing is unreported, so zero is the honest answer."""
    summed = SessionUsage.summed([], [])
    assert (summed.rounds, summed.turns, summed.by_turn) == (0, 0, [])
    assert all(getattr(summed.totals, field) == 0 for field in TOKEN_FIELDS)
    assert summed.totals.latency_s == 0.0


@pytest.mark.parametrize("boundaries", [[2, 1], [-1], [4]])
def test_boundaries_that_cannot_delimit_these_rounds_raise(boundaries: list[int]) -> None:
    """Out of order, negative, or past the end: a ledger bug, caught where it happens."""
    with pytest.raises(ValueError):
        SessionUsage.summed([usage(), usage(), usage()], boundaries)
