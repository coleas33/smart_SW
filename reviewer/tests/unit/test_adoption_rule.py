"""The adoption rule, over hand-built scorecards (T042, for T043).

The rule is four answers, fixed before the first A/B run and never argued after a result
is in hand (FR-028, spec.md):

1. **No known defect lost, on the worst case.** Rejected if *any* on-run misses a defect
   *any* off-run found. A defect found two times in three is found unreliably, and a
   lever that makes it two in three when it was three in three has cost quality.
   Conservative is the right direction for a review tool.
2. **No new false alarm, on the median, with the worst case recorded.** Asymmetric on
   purpose: a false alarm is the noisier metric and the cheaper failure, tracked as
   `false_alarm_handling_minutes`, while a lost defect is the failure the product exists
   to prevent.
3. **Worth the code: a median reduction of at least 20 percent in total tokens or in wall
   clock**, against the off arm's median over the whole set. Below that the result is
   inside run-to-run variance at three repetitions and does not justify a flag, a settings
   field, a test suite and a permanent branch in the code.
4. **Control-arm stability first.** If the off-runs disagree with each other about which
   defects were found, the computed decision is `re-measure` with `CONTROL UNSTABLE`
   printed beside it. A gate whose control arm is unstable cannot decide anything.

`Decision` is a closed enum of exactly three - `adopt`, `keep off`, `re-measure`. The
control-arm signal is a printed reason, not a fourth member. A **refusal** is an absence:
`decision` is `None` when the study can produce no recall number or when a contributing
run carried the too-small-set override (FR-029, SC-011), which does not widen the enum.

Scorecards are hand-built here because that is where the edge cases live and where they
are cheapest: no run folder, no provider, no file.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.adoption import (
    ADOPT,
    BELOW_THRESHOLD,
    CONTROL_UNSTABLE,
    DECISIONS,
    DEFECT_LOST,
    KEEP_OFF,
    NEW_FALSE_ALARM,
    NO_METRIC,
    NO_RECALL,
    RE_MEASURE,
    SET_TOO_SMALL,
    THRESHOLD,
    TOO_FEW_REPS,
    off_on,
)
from swreview.benchmark.adoption import decide as decide_rule
from tests.support.studies import ArmRun, PackageSpec, RunSpec, arm, arm_run

OFF_TOKENS = 400_000
OFF_WALL_CLOCK = 500.0


def off_arm(count: int = 3, **overrides: object) -> list[ArmRun]:
    return arm("off", count, **overrides)


def on_arm(
    count: int = 3, *, total_tokens: int | None = 200_000, wall_clock_s: float | None = 500.0
) -> list[ArmRun]:
    """An on arm that halved the token bill and changed nothing else."""
    return arm(
        "on",
        count,
        packages=(PackageSpec(total_tokens=total_tokens, wall_clock_s=wall_clock_s),),
    )


def base_off() -> list[ArmRun]:
    return off_arm(packages=(PackageSpec(total_tokens=OFF_TOKENS, wall_clock_s=OFF_WALL_CLOCK),))


def one_run(name: str, **package_overrides: object) -> ArmRun:
    arm_name = name.split("-")[0]
    return arm_run(
        RunSpec(
            run=name,
            arm=arm_name,
            rep=int(name.split("-")[1]),
            packages=(
                replace(
                    PackageSpec(total_tokens=OFF_TOKENS, wall_clock_s=OFF_WALL_CLOCK),
                    **package_overrides,  # type: ignore[arg-type]
                ),
            ),
        )
    )


# --- the happy path, and the closed enum -----------------------------------------


def test_a_lever_that_halves_the_bill_and_loses_nothing_is_adopted() -> None:
    verdict = decide_rule(base_off(), on_arm())

    assert verdict.decision == ADOPT
    assert verdict.worst_case_defects_lost == 0


def test_every_decision_is_one_of_exactly_three() -> None:
    assert set(DECISIONS) == {ADOPT, KEEP_OFF, RE_MEASURE}
    assert len(DECISIONS) == 3


def test_deciding_writes_no_flag_default() -> None:
    """The rule computes; adoption is the owner's act and happens in another change."""
    decide_rule(base_off(), on_arm())

    assert EfficiencySettings() == EfficiencySettings(**{})
    assert not any(EfficiencySettings().model_dump().values())


def test_timing_on_the_scorecards_never_moves_a_decision() -> None:
    """FR-006: the median net saved minutes is **reported** and never gated on.

    `decide` names the metrics it reads, so a new `METRICS` entry gates nothing by
    construction; this is the assertion that says so out loud. An on arm that saved two
    hours per package and an off arm that saved none decide exactly as the same two arms
    with no timing at all - the token threshold is still the only thing that moved.
    """
    timed_off = off_arm(
        packages=(
            PackageSpec(
                total_tokens=OFF_TOKENS,
                wall_clock_s=OFF_WALL_CLOCK,
                baseline_minutes=90.0,
                assisted_minutes=85.0,
            ),
        )
    )
    timed_on = arm(
        "on",
        3,
        packages=(
            PackageSpec(
                total_tokens=200_000,
                wall_clock_s=500.0,
                baseline_minutes=90.0,
                assisted_minutes=10.0,
            ),
        ),
    )

    untimed = decide_rule(base_off(), on_arm())
    timed = decide_rule(timed_off, timed_on)

    assert timed_on[0].scorecard.aggregate.median_net_saved_minutes == 80.0
    assert timed == untimed


# --- rule 1, defects lost, on the worst case -------------------------------------


def test_one_on_run_losing_a_defect_any_off_run_found_keeps_the_lever_off() -> None:
    on = [
        one_run("on-1", total_tokens=200_000),
        one_run("on-2", total_tokens=200_000, matched=("D-1",), missed=("D-2",)),
        one_run("on-3", total_tokens=200_000),
    ]

    verdict = decide_rule(base_off(), on)

    assert verdict.decision == KEEP_OFF
    assert DEFECT_LOST in verdict.reason
    assert verdict.lost_defect_ids == ["D-2"]
    assert "rms-part" in verdict.reason


def test_a_defect_no_off_run_ever_found_is_not_counted_as_lost() -> None:
    """The comparison is against what the control arm actually found, not the key."""
    off = [one_run(f"off-{rep}", matched=("D-1",), missed=("D-2",)) for rep in (1, 2, 3)]
    on = [
        one_run(f"on-{rep}", matched=("D-1",), missed=("D-2",), total_tokens=200_000)
        for rep in (1, 2, 3)
    ]

    verdict = decide_rule(off, on)

    assert verdict.worst_case_defects_lost == 0
    assert verdict.decision == ADOPT


# --- rule 2, false alarms, on the median -----------------------------------------


def test_a_higher_median_false_alarm_count_keeps_the_lever_off() -> None:
    on = [one_run(f"on-{rep}", total_tokens=200_000, false_alarms=4) for rep in (1, 2, 3)]

    verdict = decide_rule(base_off(), on)

    assert verdict.decision == KEEP_OFF
    assert NEW_FALSE_ALARM in verdict.reason


def test_one_noisy_on_run_does_not_fail_the_median_but_is_recorded() -> None:
    """Asymmetric on purpose: the worst case is printed, the median decides."""
    on = [
        one_run("on-1", total_tokens=200_000),
        one_run("on-2", total_tokens=200_000, false_alarms=9),
        one_run("on-3", total_tokens=200_000),
    ]

    verdict = decide_rule(base_off(), on)

    assert verdict.decision == ADOPT
    assert "9" in verdict.reason


# --- rule 3, the 20 percent threshold, on the median -----------------------------


def test_the_threshold_is_twenty_percent() -> None:
    assert THRESHOLD == pytest.approx(0.20)


def test_a_nineteen_percent_median_with_a_thirty_five_percent_best_case_does_not_pass() -> None:
    on = [
        one_run("on-1", total_tokens=int(OFF_TOKENS * 0.81)),
        one_run("on-2", total_tokens=int(OFF_TOKENS * 0.65)),
        one_run("on-3", total_tokens=int(OFF_TOKENS * 0.81)),
    ]

    verdict = decide_rule(base_off(), on)

    assert verdict.decision == KEEP_OFF
    assert BELOW_THRESHOLD in verdict.reason


def test_exactly_twenty_percent_passes() -> None:
    on = [one_run(f"on-{rep}", total_tokens=int(OFF_TOKENS * 0.80)) for rep in (1, 2, 3)]

    verdict = decide_rule(base_off(), on)

    assert verdict.decision == ADOPT


def test_a_wall_clock_reduction_alone_passes() -> None:
    """Either metric, not both: a lever may buy time rather than tokens."""
    on = [
        one_run(f"on-{rep}", total_tokens=OFF_TOKENS, wall_clock_s=OFF_WALL_CLOCK * 0.5)
        for rep in (1, 2, 3)
    ]

    verdict = decide_rule(base_off(), on)

    assert verdict.decision == ADOPT


def test_a_study_with_neither_number_is_re_measured_rather_than_adopted() -> None:
    """SC-009: no decision may rest on a metric absent from the scorecards."""
    off = [one_run(f"off-{rep}", total_tokens=None, wall_clock_s=None) for rep in (1, 2, 3)]
    on = [one_run(f"on-{rep}", total_tokens=None, wall_clock_s=None) for rep in (1, 2, 3)]

    verdict = decide_rule(off, on)

    assert verdict.decision == RE_MEASURE
    assert NO_METRIC in verdict.reason


# --- rule 4, the control arm, read first -----------------------------------------


def test_off_runs_that_disagree_about_defects_are_re_measured_and_never_a_pass() -> None:
    off = [
        one_run("off-1"),
        one_run("off-2", matched=("D-1",), missed=("D-2",)),
        one_run("off-3"),
    ]

    verdict = decide_rule(off, on_arm())

    assert verdict.decision == RE_MEASURE
    assert CONTROL_UNSTABLE in verdict.reason
    assert "D-2" in verdict.reason
    assert "rms-part" in verdict.reason


def test_an_unstable_control_arm_reports_the_worst_case_as_unknown_never_zero() -> None:
    """The defects-lost comparison never ran, so its number is absent, not zero (RK-1)."""
    off = [
        one_run("off-1"),
        one_run("off-2", matched=("D-1",), missed=("D-2",)),
        one_run("off-3"),
    ]

    verdict = decide_rule(off, on_arm())

    assert verdict.decision == RE_MEASURE
    assert verdict.worst_case_defects_lost is None


def test_an_unstable_control_arm_outranks_a_defect_lost() -> None:
    """A gate whose control arm is unstable cannot decide anything, including `keep off`."""
    off = [
        one_run("off-1"),
        one_run("off-2", matched=("D-1",), missed=("D-2",)),
        one_run("off-3"),
    ]
    on = [
        one_run(f"on-{rep}", matched=(), missed=("D-1", "D-2"), total_tokens=1)
        for rep in (1, 2, 3)
    ]

    verdict = decide_rule(off, on)

    assert verdict.decision == RE_MEASURE
    assert CONTROL_UNSTABLE in verdict.reason


# --- the preconditions, read before the four rules (FR-029, SC-011) --------------


def test_a_study_that_can_produce_no_recall_number_gets_no_decision() -> None:
    not_held_out = {"packages": (PackageSpec(package_id="cover-blind-tap", held_out=False),)}
    verdict = decide_rule(off_arm(**not_held_out), arm("on", 3, **not_held_out))

    assert verdict.decision is None
    assert NO_RECALL in verdict.reason


def test_a_contributing_run_with_the_too_small_override_gets_no_decision() -> None:
    on = on_arm()
    on[1] = arm_run(
        RunSpec(
            run="on-2",
            arm="on",
            rep=2,
            set_too_small_override=True,
            packages=(PackageSpec(total_tokens=200_000),),
        )
    )

    verdict = decide_rule(base_off(), on)

    assert verdict.decision is None
    assert SET_TOO_SMALL in verdict.reason
    assert "on-2" in verdict.reason


def test_a_refused_precondition_reports_the_worst_case_as_unknown_never_zero() -> None:
    """Both FR-029 preconditions return before the defects-lost rule runs."""
    not_held_out = {"packages": (PackageSpec(held_out=False),)}
    no_recall = decide_rule(off_arm(**not_held_out), arm("on", 3, **not_held_out))

    on = on_arm()
    on[1] = arm_run(
        RunSpec(
            run="on-2",
            arm="on",
            rep=2,
            set_too_small_override=True,
            packages=(PackageSpec(total_tokens=200_000),),
        )
    )
    overridden = decide_rule(base_off(), on)

    assert (no_recall.decision, no_recall.worst_case_defects_lost) == (None, None)
    assert (overridden.decision, overridden.worst_case_defects_lost) == (None, None)


def test_the_worst_case_is_zero_only_where_the_comparison_actually_ran() -> None:
    """`0` is a measurement: it may be printed only after `_defects_lost` returned empty."""
    below = decide_rule(base_off(), on_arm(total_tokens=OFF_TOKENS, wall_clock_s=OFF_WALL_CLOCK))
    too_few = decide_rule(base_off()[:2], on_arm(2))

    assert (below.decision, below.worst_case_defects_lost) == (KEEP_OFF, 0)
    assert BELOW_THRESHOLD in below.reason
    assert (too_few.decision, too_few.worst_case_defects_lost) == (RE_MEASURE, 0)
    assert TOO_FEW_REPS in too_few.reason


def test_a_refused_decision_is_an_absence_and_not_a_fourth_value() -> None:
    not_held_out = {"packages": (PackageSpec(held_out=False),)}
    verdict = decide_rule(off_arm(**not_held_out), arm("on", 3, **not_held_out))

    assert verdict.decision is None
    assert None not in DECISIONS


# --- an arm that is not six runs --------------------------------------------------


def test_fewer_than_three_repetitions_per_arm_cannot_adopt() -> None:
    verdict = decide_rule(base_off()[:2], on_arm(2))

    assert verdict.decision == RE_MEASURE
    assert TOO_FEW_REPS in verdict.reason


def test_a_quality_failure_still_decides_below_three_repetitions() -> None:
    """A lost defect is decisive whatever the repetition count; only `adopt` needs six."""
    on = [one_run("on-1", total_tokens=200_000, matched=("D-1",), missed=("D-2",))]

    verdict = decide_rule(base_off()[:1], on)

    assert verdict.decision == KEEP_OFF


# --- the off/on statistic every column is built from -----------------------------


def test_off_on_reports_median_min_max_and_the_delta() -> None:
    stat = off_on([100.0, 200.0, 300.0], [50.0, 60.0, 70.0])

    assert (stat.off_median, stat.off_min, stat.off_max) == (200.0, 100.0, 300.0)
    assert (stat.on_median, stat.on_min, stat.on_max) == (60.0, 50.0, 70.0)
    assert stat.delta_pct == pytest.approx((60.0 - 200.0) / 200.0)
    assert (stat.off_rows, stat.on_rows) == (3, 3)


def test_off_on_skips_nulls_and_says_how_many_rows_contributed() -> None:
    stat = off_on([100.0, None, 300.0], [None, None, None])

    assert stat.off_median == 200.0
    assert stat.off_rows == 2
    assert stat.on_median is None
    assert stat.on_rows == 0
    assert stat.delta_pct is None


def test_off_on_has_no_delta_against_a_zero_off_median() -> None:
    stat = off_on([0.0, 0.0], [1.0, 1.0])

    assert stat.delta_pct is None
