"""The real recordings' rule: each round's drift is the size change of what it carried (008 T118).

`contracts/replay.md` section 10, research R2.55 (owner decision 3A, 2026-09-23). The recorded
reviews of 2026-09-20 can never be regenerated, so the replay of them is not held to 1% of the
bill. What is held instead, for every round `q`:

    drift(q)    = as_recorded_input(q) - recorded_input(q)
    change(r)   = sum over r's calls of (size_A(call) + FRAMING_TOKENS) - growth(r)
    residual(q) = drift(q) - sum over carried(q) of change(r)          must be 0

- `size_A` is what pass A sends of a call, counted here from the played call - the current
  code's result for a call pass A ran, its estimate (`estimated_sizes`) for one it could not -
  and never read off the replay's own pricing.
- `growth(r)` is the recorded growth after `r` (`Recording.growth_after`), so
  `growth(r) - FRAMING_TOKENS x calls` is the size of `r`'s results as recorded and `change(r)`
  their size change. The bill framed each result in 11 to 14 tokens, not 12, so a result the
  current code returns unchanged shows -2 to +1: the framing noise lives in `change`, and the
  residual is exact.
- `carried(q)` is read from the recording alone: every main round with calls earlier in `q`'s
  turn, and in every earlier turn that committed (not `stopped` or `error`).

A presentation round carries nothing of its own and is priced at its recorded size, so its
change is 0 and its drift must be too. A round is outside the rule - `change` is `None` - when
the replay flags it lower bound, or when a round it carries has no observable growth: neither
has a recorded size to compare with. The rule is written for a recording made with every lever
and the model view off and storing no results, replayed with its own settings; anything else is
refused (`DriftRuleRefused`), naming what.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from swreview.agent.providers import FRAMING_TOKENS, tool_result_text
from swreview.agent.settings import LEVER_NAMES, MODEL_VIEW_OFF
from swreview.benchmark.recording import UNCOMMITTED_ENDS, RecordedRound, Recording
from swreview.benchmark.replay import (
    PlayedCall,
    ReplayPasses,
    ReplayReport,
    ReplayRound,
    estimated_sizes,
)
from swreview.tokens import count_tokens

__all__ = ["DriftRuleRefused", "RoundDrift", "round_drifts"]

RAN = frozenset({"reproduced", "changed", "answered_from_checks"})
"""The classes of a call pass A ran, whose result is the current code's own."""

RoundKey = tuple[int, int]


class DriftRuleRefused(ValueError):
    """The replay is not one the rule is written for; the message names what."""


@dataclass(frozen=True)
class RoundDrift:
    """One round of a recording under the rule."""

    turn: int
    round: int
    kind: Literal["main", "presentation"]
    drift: int
    """`as_recorded_input - recorded_input`."""
    change: int | None
    """The size change of every result the round's recorded request carried; `None` when the
    round is outside the rule."""

    @property
    def residual(self) -> int | None:
        """What the size change leaves unexplained: 0, or a replay defect."""
        return None if self.change is None else self.drift - self.change


def round_drifts(passes: ReplayPasses, report: ReplayReport) -> list[RoundDrift]:
    """Every round of `passes.recording` under the rule, in recorded order.

    `report` is `report_of(passes)`; a report of other passes is refused, and so is a replay
    the rule is not written for (see the module's docstring).
    """
    recording = passes.recording
    _refuse_what_the_rule_is_not_for(passes, report)
    rows = {(row.turn, row.round, row.kind): row for row in report.rounds}
    changes = _changes(recording, passes, rows)

    drifts: list[RoundDrift] = []
    committed: list[RoundKey] = []
    for turn in recording.turns:
        carried = list(committed)
        for recorded in turn.rounds:
            row = rows[(recorded.turn, recorded.index, recorded.kind)]
            drift = row.as_recorded_input - row.recorded_input
            if recorded.kind == "presentation":
                drifts.append(_drift(row, drift, 0))
                continue
            outside = row.lower_bound or any(changes[key] is None for key in carried)
            change = None if outside else sum(changes[key] or 0 for key in carried)
            drifts.append(_drift(row, drift, change))
            if recorded.calls:
                carried.append((recorded.turn, recorded.index))
        if turn.end_reason not in UNCOMMITTED_ENDS:
            committed = carried
    return drifts


def _drift(row: ReplayRound, drift: int, change: int | None) -> RoundDrift:
    return RoundDrift(turn=row.turn, round=row.round, kind=row.kind, drift=drift, change=change)


def _refuse_what_the_rule_is_not_for(passes: ReplayPasses, report: ReplayReport) -> None:
    recording = passes.recording
    recorded_rounds = [(r.turn, r.index, r.kind) for t in recording.turns for r in t.rounds]
    if report.run_dir != str(recording.run_dir) or recorded_rounds != [
        (row.turn, row.round, row.kind) for row in report.rounds
    ]:
        raise DriftRuleRefused(
            f"the report is not the report of these passes: it prices {report.run_dir} in "
            f"{len(report.rounds)} rounds, and the recording {recording.run_dir} has "
            f"{len(recorded_rounds)}"
        )
    if (passes.requested, passes.requested_view) != (passes.as_recorded, passes.as_recorded_view):
        raise DriftRuleRefused(
            "the rule holds a replay with the recording's own settings, and this one requested "
            "others; replay the recording as it was recorded"
        )
    levers_on = [name for name in LEVER_NAMES if getattr(passes.as_recorded, name)]
    if levers_on:
        raise DriftRuleRefused(
            f"the recording was made with {', '.join(levers_on)} on; the rule is written for "
            "recordings made with every lever off"
        )
    if passes.as_recorded_view != MODEL_VIEW_OFF:
        raise DriftRuleRefused(
            "the recording was made with the model view on, whose pruned requests can shrink "
            "and whose stubs are not their results' size; the rule is written for recordings "
            "made with the model view off"
        )
    stored = sorted(
        call.step for row in report.rounds for call in row.calls if call.class_ == "stored"
    )
    if stored:
        raise DriftRuleRefused(
            f"steps {stored} are sized from their stored result, which the rule does not "
            "count; it is written for recordings that store no result"
        )


def _changes(
    recording: Recording,
    passes: ReplayPasses,
    rows: dict[tuple[int, int, str], ReplayRound],
) -> dict[RoundKey, int | None]:
    """`change(r)` of every recorded main round with calls; `None` when its growth is not
    observable. Calls are matched to pass A's played calls by position, as the replay does."""
    played = [call for played_round in passes.first.rounds for call in played_round.calls]
    changes: dict[RoundKey, int | None] = {}
    index = 0
    for turn in recording.turns:
        for recorded in turn.main_rounds:
            if not recorded.calls:
                continue
            row = rows[(recorded.turn, recorded.index, "main")]
            classes = {call.step: call.class_ for call in row.calls}
            ran = {
                call.step: _size(played[index + offset])
                for offset, call in enumerate(recorded.calls)
                if classes[call.step] in RAN
            }
            index += len(recorded.calls)
            changes[(recorded.turn, recorded.index)] = _change(recording, recorded, ran)
    return changes


def _size(call: PlayedCall) -> int:
    """`T` of a result as pass A sends it with the model view off: its whole payload."""
    return count_tokens(tool_result_text(call.result.payload))


def _change(recording: Recording, recorded: RecordedRound, ran: dict[int, int]) -> int | None:
    growth = recording.growth_after(recorded)
    if growth is None:
        return None
    estimated = {
        step: size for step, (size, _) in estimated_sizes(recording, recorded, ran).items()
    }
    sizes = {**ran, **estimated}
    return sum(sizes[call.step] + FRAMING_TOKENS for call in recorded.calls) - growth
