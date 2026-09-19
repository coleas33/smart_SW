"""The adoption rule: four fixed answers applied mechanically to N scorecards (T043).

**The decision is computed and is never typeable** (FR-027, SC-009). `swreview benchmark
compare` renders what `decide` returns into the ledger's `Decision` column; the owner's
approval is a *separate* field beside it, `owner_signed_off`, written by hand into the
committed `ledger.md` once the owner has read the row and carried forward unchanged by
every later regeneration (`compare.carry_sign_offs`). That is how the decision stays the
owner's without the audited number becoming free text. **Nothing here writes a flag
default**: adopting a lever is a later change in code with its own review.

The four answers, fixed before the first A/B run and not argued after a result is in hand
(FR-028, contracts/ab-harness.md section 5, levers.md section 7):

1. **Defects lost: worst case.** `keep off` if *any* on-run misses a defect *any* off-run
   found. Not a median and not an average: a defect found two times in three is found
   unreliably, and conservative is the right direction for a review tool.
2. **False alarms: median, with the worst case printed beside it.** Asymmetric on
   purpose - a false alarm is the noisier metric and the cheaper failure, tracked as
   `false_alarm_handling_minutes`, while a lost defect is the failure the product exists
   to prevent.
3. **Worth the code: a median reduction of at least 20 percent in total tokens or in wall
   clock**, against the off arm's median over the whole set. Below that the result is
   inside run-to-run variance at three repetitions.
4. **Control-arm stability, read first.** Off-runs that disagree with each other about
   which defects were found make the set too noisy to gate on: the decision is
   `re-measure` and the printed reason is `CONTROL UNSTABLE`.

Read **before** all four, the FR-029 / SC-011 precondition: a study whose scorecards can
produce no recall number, or any of whose runs carried the too-small-set override, gets
**no decision at all**. That absence is `None`, not a fourth enum value, and the raw
per-run rows still render (`compare.py`).

The order the rules fire in is stated once, in `decide`, and it is deliberate: a quality
failure decides at any repetition count, while `adopt` needs the full six runs and a
metric that is actually in the scorecards.

This module reads `Scorecard` objects and nothing else - no run folder, no provider, no
answer key - which is why its tests are hand-built scorecards.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from typing import Literal

from swreview.benchmark.scorecard import Scorecard
from swreview.findings import ReviewModel

Decision = Literal["adopt", "keep off", "re-measure"]

ADOPT: Decision = "adopt"
KEEP_OFF: Decision = "keep off"
RE_MEASURE: Decision = "re-measure"

DECISIONS: tuple[Decision, ...] = (ADOPT, KEEP_OFF, RE_MEASURE)
"""The closed enum, taken from the constants so nothing retypes them. A refused decision
is `None` - an absence beside the enum, never a fourth member (FR-027)."""

THRESHOLD = 0.20
"""The median reduction, in total tokens or in wall clock, that a lever has to buy to be
worth a flag, a settings field, a test suite and a permanent branch in the code."""

CONTROL_UNSTABLE = "CONTROL UNSTABLE"
DEFECT_LOST = "DEFECT LOST"
NEW_FALSE_ALARM = "NEW FALSE ALARM"
BELOW_THRESHOLD = "BELOW THRESHOLD"
TOO_FEW_REPS = "FEWER THAN THREE REPETITIONS PER ARM"
NO_METRIC = "NO TOKEN OR WALL-CLOCK NUMBER"
NO_RECALL = "NO RECALL NUMBER"
SET_TOO_SMALL = "SET TOO SMALL"
BASELINE = "BASELINE"
"""The printed reasons. Constants because the ledger, the tests and the owner reading a
row all quote the same string, and a reason nobody can grep for is prose."""

MIN_REPS = 3
"""Three per arm, six per study. Fewer cannot support a median or a worst case (FR-023,
FR-030b), so fewer can never compute `adopt`."""


class ArmRun(ReviewModel):
    """One run of one arm, as the rule sees it: its scorecard, and two facts beside it.

    `tool_calls` is `len(session.steps)` summed over the run's packages, which no
    scorecard field carries and which lever 6's gate reads beside `round_trips`.
    `set_too_small_override` comes from the run's provenance record and is what makes the
    SC-011 refusal possible without reopening the run folder here.
    """

    run: str
    scorecard: Scorecard
    tool_calls: int | None = None
    set_too_small_override: bool = False


class OffOn(ReviewModel):
    """One metric's off arm against its on arm: median, min, max and the delta.

    `off_rows` and `on_rows` say **how many runs contributed**, because a median over a
    column containing nulls is computed over the non-null values and a reader who cannot
    see the count cannot tell a three-run median from a one-run one (RK-1).
    """

    off_median: float | None
    off_min: float | None
    off_max: float | None
    on_median: float | None
    on_min: float | None
    on_max: float | None
    delta_pct: float | None
    off_rows: int
    on_rows: int


def off_on(off: Sequence[float | None], on: Sequence[float | None]) -> OffOn:
    """The statistic every decision-row column is built from, computed in one place.

    `delta_pct` is `(on_median - off_median) / off_median` and is `None` when the off
    median is `None` or zero: a percentage against nothing is not a number, and the
    adoption threshold reads this field on total tokens and on wall clock.
    """
    off_values = [value for value in off if value is not None]
    on_values = [value for value in on if value is not None]
    off_median = statistics.median(off_values) if off_values else None
    on_median = statistics.median(on_values) if on_values else None
    delta_pct = (
        (on_median - off_median) / off_median
        if off_median not in (None, 0) and on_median is not None and off_median is not None
        else None
    )
    return OffOn(
        off_median=off_median,
        off_min=min(off_values) if off_values else None,
        off_max=max(off_values) if off_values else None,
        on_median=on_median,
        on_min=min(on_values) if on_values else None,
        on_max=max(on_values) if on_values else None,
        delta_pct=delta_pct,
        off_rows=len(off_values),
        on_rows=len(on_values),
    )


def _wall_clock_s(run: ArmRun) -> float | None:
    """The run's wall clock: the sum of its packages', null if any package is null.

    `PackageScore.wall_clock_s` and not `unattended_runtime_minutes`, which has two
    writers and whose second one also covers package load and adapter construction
    (data-model.md 8.1).
    """
    values = [score.wall_clock_s for score in run.scorecard.per_package]
    return None if any(value is None for value in values) else sum(values)  # type: ignore[arg-type]


METRICS: dict[str, Callable[[ArmRun], float | None]] = {
    "input_tokens": lambda run: run.scorecard.aggregate.input_tokens,
    "cached_input_tokens": lambda run: run.scorecard.aggregate.cached_input_tokens,
    "output_tokens": lambda run: run.scorecard.aggregate.output_tokens,
    "reasoning_tokens": lambda run: run.scorecard.aggregate.reasoning_tokens,
    "total_tokens": lambda run: run.scorecard.aggregate.total_tokens,
    "round_trips": lambda run: run.scorecard.aggregate.round_trips,
    "tool_calls": lambda run: run.tool_calls,
    "wall_clock_s": _wall_clock_s,
    "dump_wall_clock_s": lambda run: None,
    "valid_findings": lambda run: run.scorecard.aggregate.valid_findings,
    "missed_known_defects": lambda run: run.scorecard.aggregate.missed_known_defects,
    "false_alarms": lambda run: run.scorecard.aggregate.false_alarms,
    "unresolved_count": lambda run: run.scorecard.aggregate.unresolved_count,
    "recall_held_out": lambda run: run.scorecard.aggregate.recall,
    "median_net_saved_minutes": lambda run: run.scorecard.aggregate.median_net_saved_minutes,
}
"""Every metric the ledger compares, each read from its **one** source.

`compare` builds its decision-row columns from this table and `decide` reads the two the
threshold rests on, so the ledger and the gate can never disagree about what a number is.
`dump_wall_clock_s` is `None` until the workstation harness writes it (FR-030a): the
column exists so the row says "unknown" rather than leaving levers 9 and 10 unrepresented.
`median_net_saved_minutes` is the number the pilot is judged on and the one metric here
that is **reported and never gated on** (feature 007 FR-006): `decide` names the metrics
it reads, so adding an entry to this table gates nothing by construction.
"""


def metric(runs: Sequence[ArmRun], name: str) -> list[float | None]:
    """One metric across an arm, in run order."""
    return [METRICS[name](run) for run in runs]


class Verdict(ReviewModel):
    """What the rule computed, and the sentence printed beside it."""

    decision: Decision | None
    reason: str
    worst_case_defects_lost: int | None
    """How many defects the worst on-run lost, or `None` where the comparison never ran.

    `0` is a **measurement**: `_defects_lost` was called and found nothing. `None` is the
    absence of one, and is what the two FR-029 preconditions and an unstable control arm
    return, because they decide before rule 1 fires. The ledger renders `None` as
    `unknown`, never as `0` (RK-1)."""

    lost_defect_ids: list[str]


def _found_by_arm(runs: Sequence[ArmRun]) -> dict[str, set[str]]:
    """Package id to every defect id *any* run of the arm matched."""
    found: dict[str, set[str]] = {}
    for run in runs:
        for score in run.scorecard.per_package:
            found.setdefault(score.package_id, set()).update(score.matched_defect_ids)
    return found


def _unstable_control(off: Sequence[ArmRun]) -> list[str]:
    """Packages and defect ids the off-runs disagree with each other about."""
    disagreements: list[str] = []
    per_package: dict[str, list[set[str]]] = {}
    for run in off:
        for score in run.scorecard.per_package:
            per_package.setdefault(score.package_id, []).append(set(score.matched_defect_ids))
    for package_id, found in sorted(per_package.items()):
        union: set[str] = set().union(*found) if found else set()
        intersection: set[str] = set.intersection(*found) if found else set()
        if union != intersection:
            disagreements.append(f"{package_id}: {', '.join(sorted(union - intersection))}")
    return disagreements


def _defects_lost(off: Sequence[ArmRun], on: Sequence[ArmRun]) -> tuple[list[str], list[str]]:
    """Defect ids any off-run found that some on-run missed, and where. Worst case."""
    found = _found_by_arm(off)
    lost: set[str] = set()
    where: list[str] = []
    for run in on:
        for score in run.scorecard.per_package:
            missing = found.get(score.package_id, set()) - set(score.matched_defect_ids)
            if missing:
                lost |= missing
                where.append(f"{run.run} / {score.package_id}: {', '.join(sorted(missing))}")
    return sorted(lost), where


def _pct(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1%}"


def _reduction(stat: OffOn) -> float | None:
    """How much the on arm saved, as a positive fraction; `None` when it cannot be had."""
    return None if stat.delta_pct is None else -stat.delta_pct


def decide(off: Sequence[ArmRun], on: Sequence[ArmRun]) -> Verdict:
    """The computed decision for one lever, one provider and one model.

    The order is the rule: the two preconditions, then control stability, then the two
    quality rules, then - only for a study that could support one - `adopt`.
    """
    contributing = [*off, *on]
    overridden = [run.run for run in contributing if run.set_too_small_override]
    if overridden:
        return _refused(
            f"{SET_TOO_SMALL}: {', '.join(sorted(overridden))} carried "
            f"--i-know-the-set-is-too-small, so these runs gate nothing"
        )
    if all(run.scorecard.aggregate.recall is None for run in contributing):
        return _refused(
            f"{NO_RECALL}: no held_out: true package in the set, so recall never computes "
            f"and this study can gate nothing"
        )

    unstable = _unstable_control(off)
    if unstable:
        return Verdict(
            decision=RE_MEASURE,
            reason=(
                f"{CONTROL_UNSTABLE}: the off-runs disagree about which defects were "
                f"found ({'; '.join(unstable)}); a gate whose control arm is unstable "
                f"cannot decide anything"
            ),
            worst_case_defects_lost=None,
            lost_defect_ids=[],
        )

    lost, where = _defects_lost(off, on)
    false_alarms = off_on(metric(off, "false_alarms"), metric(on, "false_alarms"))
    false_alarm_note = (
        f"false alarms median {_number(false_alarms.off_median)} -> "
        f"{_number(false_alarms.on_median)}, worst case {_number(false_alarms.off_max)} -> "
        f"{_number(false_alarms.on_max)}"
    )
    if lost:
        return Verdict(
            decision=KEEP_OFF,
            reason=f"{DEFECT_LOST}: {'; '.join(where)} ({false_alarm_note})",
            worst_case_defects_lost=len(lost),
            lost_defect_ids=lost,
        )

    if (
        false_alarms.on_median is not None
        and false_alarms.off_median is not None
        and false_alarms.on_median > false_alarms.off_median
    ):
        return Verdict(
            decision=KEEP_OFF,
            reason=f"{NEW_FALSE_ALARM}: {false_alarm_note}",
            worst_case_defects_lost=0,
            lost_defect_ids=[],
        )

    tokens = off_on(metric(off, "total_tokens"), metric(on, "total_tokens"))
    wall_clock = off_on(metric(off, "wall_clock_s"), metric(on, "wall_clock_s"))
    savings = (
        f"total tokens {_pct(_reduction(tokens))}, wall clock {_pct(_reduction(wall_clock))} "
        f"({false_alarm_note})"
    )

    if len(off) < MIN_REPS or len(on) < MIN_REPS:
        return Verdict(
            decision=RE_MEASURE,
            reason=(
                f"{TOO_FEW_REPS}: {len(off)} off and {len(on)} on; a median and a worst "
                f"case need {MIN_REPS} of each ({savings})"
            ),
            worst_case_defects_lost=0,
            lost_defect_ids=[],
        )

    reductions = [
        value for value in (_reduction(tokens), _reduction(wall_clock)) if value is not None
    ]
    if not reductions:
        return Verdict(
            decision=RE_MEASURE,
            reason=(
                f"{NO_METRIC}: neither a total-token nor a wall-clock median is in these "
                f"scorecards, and no decision may rest on a metric that is not ({savings})"
            ),
            worst_case_defects_lost=0,
            lost_defect_ids=[],
        )

    if max(reductions) < THRESHOLD:
        return Verdict(
            decision=KEEP_OFF,
            reason=(
                f"{BELOW_THRESHOLD}: the median reduction is under {THRESHOLD:.0%} on both "
                f"metrics - {savings}"
            ),
            worst_case_defects_lost=0,
            lost_defect_ids=[],
        )

    return Verdict(
        decision=ADOPT,
        reason=f"no defect lost, no new false alarm, and {savings}",
        worst_case_defects_lost=0,
        lost_defect_ids=[],
    )


def _refused(reason: str) -> Verdict:
    """No decision at all: an absence beside the enum, not a fourth value (FR-029)."""
    return Verdict(
        decision=None, reason=reason, worst_case_defects_lost=None, lost_defect_ids=[]
    )


def _number(value: float | None) -> str:
    if value is None:
        return "unknown"
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"
