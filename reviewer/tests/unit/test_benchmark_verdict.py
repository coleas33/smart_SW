"""T226: the pane rule over fictional, hand-built scorecards; no run folders."""

from __future__ import annotations

import ast
from collections.abc import Callable
from copy import deepcopy
from dataclasses import fields, replace
from pathlib import Path
from statistics import median
from typing import get_args

import numpy as np
import pytest
from pydantic import ValidationError

from swreview.benchmark import origins, stats, verdict
from swreview.benchmark.scorecard import Scorecard, UnscoredPackage
from tests.support.studies import PanePackage, pane_run

Edit = Callable[[str, int, int, PanePackage], PanePackage]
RULES = verdict.VerdictRules(alpha=0.025, cleared_guard_decides=False)
REASONS = {
    "RECALL LOSS", "FALSE-ALARM RISE", "CODE DEFECT LOST", "CLEARED", "BELOW FLOOR",
    "RECALL NOT COMPUTABLE", "LOWER END AT OR BELOW -10 POINTS",
}


def study(edit: Edit | None = None, *, packages: int = 18, reps: int = 3):
    """36 held-out model defects, with paired package differences +1/2 and -1/2.

    Their mean is zero and their nonzero standard error puts the lower bound above
    -10 points. Defect ids deliberately repeat across packages: identity is the pair.
    """
    runs = []
    for rep in range(1, reps + 1):
        for arm in ("off", "on"):
            scores = []
            for index in range(packages):
                matched = ("D-1",)
                if arm == "on" and index == 0:
                    matched = ("D-1", "D-2")
                elif arm == "on" and index == 1:
                    matched = ()
                package = PanePackage(package_id=f"case-{index:02d}", matched=matched)
                scores.append(edit(arm, rep, index, package) if edit else package)
            runs.append(pane_run(f"{arm}-{rep}", arm, scores))
    return runs


def judge(runs, *, rules=RULES):
    results = verdict.judge(verdict.study_stats(runs), rules)
    assert len(results) == 1
    result = results[0]
    assert result.verdict in {"quality loss", "no 10-point loss", "inconclusive"}
    assert all(reason.split(":", 1)[0] in REASONS for reason in result.reasons)
    return result


def has_reason(result, reason: str, figure: str | None = None) -> bool:
    return any(
        item.startswith(reason + ":") and (figure is None or ": " + figure in item)
        for item in result.reasons
    )


def refs(rows):
    return {(row.package_id, row.defect_id) for row in rows}


def test_computable_clear_study_has_no_ten_point_loss_and_two_figures():
    result = judge(study())
    assert result.verdict == "no 10-point loss"
    assert result.reasons == []
    for figure in (result.figures.main, result.figures.sensitivity):
        assert figure.retained_defects == 36
        assert figure.retained_packages == 18
        assert figure.dropped_defects == figure.dropped_packages == []
        assert figure.recall.estimate == pytest.approx(0)
        assert figure.recall.lower > -0.10
        assert figure.recall.upper > 0
        assert figure.recall.alpha == 0.025
        assert figure.recall.df == 17
        assert figure.recall.packages == 18


@pytest.mark.parametrize("tag", ["held_out", "tuned_on"])
def test_v6_code_guard_precedes_every_other_rule_and_names_the_missed_run(tag):
    def edit(arm, rep, index, package):
        if index != 2:
            return package
        detected = () if arm == "on" and rep == 1 else ("C-1",)
        return replace(package, **{f"code_{tag}": ("C-1",)},
                       matched=package.matched + detected)

    result = judge(study(edit), rules=replace(RULES, floor=100))
    assert result.verdict == "quality loss"
    assert has_reason(result, "CODE DEFECT LOST")
    assert refs(result.code_guard.lost) == {("case-02", "C-1")}
    assert result.code_guard.lost[0].runs == ["on-1"]
    assert any("case-02" in reason and "C-1" in reason and "on-1" in reason
               for reason in result.reasons)


def test_v7_off_only_sometimes_is_named_and_does_not_make_a_clear_study_inconclusive():
    def edit(arm, rep, index, package):
        if index != 2:
            return package
        detected = ("C-1",) if arm == "off" and rep != 1 else ()
        return replace(package, code_held_out=("C-1",), matched=package.matched + detected)

    result = judge(study(edit))
    assert result.verdict == "no 10-point loss"
    assert result.code_guard.lost == []
    assert refs(result.code_guard.off_only_sometimes) == {("case-02", "C-1")}
    assert result.code_guard.off_only_sometimes[0].reason == (
        "the off arm detected it only sometimes"
    )


def test_code_guard_names_and_skips_a_package_without_completed_runs_in_an_arm():
    def edit(arm, rep, index, package):
        if index != 2:
            return package
        return replace(package, code_tuned_on=("C-1",), matched=package.matched + ("C-1",),
                       status="behavioural" if arm == "on" else "completed")

    result = judge(study(edit))
    assert result.code_guard.lost == []
    assert refs(result.code_guard.skipped) == {("case-02", "C-1")}
    assert result.code_guard.skipped[0].reason


@pytest.mark.parametrize("status", ["completed", "behavioural"])
@pytest.mark.parametrize("decides", [False, True])
def test_v8_held_out_clear_is_named_on_completed_and_stopped_runs_and_only_decides_if_approved(
    status, decides
):
    def edit(arm, rep, index, package):
        if arm == "on" and rep == 1 and index == 2:
            return replace(package, cleared=("D-2",), status=status)
        return package

    result = judge(study(edit), rules=replace(RULES, cleared_guard_decides=decides))
    assert result.verdict == ("quality loss" if decides else "no 10-point loss")
    assert result.cleared_guard.decides is decides
    assert refs(result.cleared_guard.named) == {("case-02", "D-2")}
    assert result.cleared_guard.named[0].runs == ["on-1"]
    assert has_reason(result, "CLEARED") is decides


def test_tuned_on_clear_is_named_but_never_decides_even_when_guard_approved():
    def edit(arm, rep, index, package):
        if index != 2:
            return package
        return replace(package, model_tuned_on=("T-1",),
                       cleared=("T-1",) if arm == "on" and rep == 1 else ())

    result = judge(study(edit), rules=replace(RULES, cleared_guard_decides=True))
    assert result.verdict == "no 10-point loss"
    assert refs(result.cleared_guard.named) == {("case-02", "T-1")}
    assert not has_reason(result, "CLEARED")


def test_a_clear_also_seen_in_the_off_arm_is_not_named():
    def edit(arm, rep, index, package):
        return replace(package, cleared=("D-2",)) if index == 2 and rep == 1 else package

    result = judge(study(edit), rules=replace(RULES, cleared_guard_decides=True))
    assert result.verdict == "no 10-point loss"
    assert result.cleared_guard.named == []


def test_v12_zero_width_recall_is_inconclusive_and_zero_width_false_alarms_call_no_loss():
    result = judge(study(lambda arm, rep, index, package: replace(package, matched=("D-1",))))
    assert result.verdict == "inconclusive"
    for name in ("main", "sensitivity"):
        figure = getattr(result.figures, name)
        assert figure.recall.computable is False
        assert figure.recall.lower is figure.recall.upper is None
        assert figure.false_alarms.computable is False
        assert figure.false_alarms.lower is figure.false_alarms.upper is None
        assert figure.false_alarms.loss is False
        assert has_reason(result, "RECALL NOT COMPUTABLE", name)
    assert any("zero" in reason.lower() for reason in result.reasons)


def test_recall_with_fewer_than_two_packages_explains_why_not_computable():
    runs = [pane_run(arm + "-1", arm, [PanePackage("one", matched=())])
            for arm in ("off", "on")]
    result = judge(runs, rules=replace(RULES, floor=1))
    assert result.verdict == "inconclusive"
    assert has_reason(result, "RECALL NOT COMPUTABLE", "main")
    assert any("two" in reason.lower() or "2" in reason for reason in result.reasons)


def batch_interval_stub(moments, estimate, lower, upper):
    shape = moments.estimate.shape
    return stats.BatchInterval(
        estimate=np.full(shape, estimate),
        lower=np.full(shape, np.nan if lower is None else lower),
        upper=np.full(shape, np.nan if upper is None else upper),
        df=moments.df,
        packages=moments.packages,
        computable=np.full(shape, lower is not None and upper is not None),
    )


def interval_stub(monkeypatch, lower: float, upper: float):
    def interval(moments, alpha, sides=1):
        if np.any(moments.computable):  # Recall varies; this study's alarms are all zero.
            return batch_interval_stub(moments, (lower + upper) / 2, lower, upper)
        return batch_interval_stub(moments, 0, None, None)

    monkeypatch.setattr(stats, "package_intervals_from_moments", interval)


def test_v13_lower_minus_eighteen_upper_plus_four_is_inconclusive(monkeypatch):
    interval_stub(monkeypatch, -0.18, 0.04)
    result = judge(study())
    assert result.verdict == "inconclusive"
    assert has_reason(result, "LOWER END AT OR BELOW -10 POINTS", "main")
    assert has_reason(result, "LOWER END AT OR BELOW -10 POINTS", "sensitivity")
    assert not has_reason(result, "RECALL LOSS")


def test_v14_infrastructure_is_excluded_and_drops_are_named_in_both_figures():
    def edit(arm, rep, index, package):
        if arm == "on" and index == 17:
            return replace(package, status="infrastructure")
        if arm == "off" and index == 2:
            if rep == 1:
                return replace(package, status="infrastructure")
            if rep == 2:
                return replace(package, matched=())
        return package

    runs = study(edit)
    data = verdict.study_stats(runs)
    assert data.package_runs[0, 0, 0, data.package_ids.index("case-02")] == 2
    result = judge(runs)
    for figure in (result.figures.main, result.figures.sensitivity):
        assert figure.retained_defects == 34
        assert figure.retained_packages == 17
        assert refs(figure.dropped_defects) == {("case-17", "D-1"), ("case-17", "D-2")}
        assert figure.dropped_packages == ["case-17"]
        assert figure.recall.estimate == pytest.approx(0.5 / 34)


def test_unscored_package_is_excluded_even_if_a_scored_row_with_its_id_remains():
    runs = study()
    for index, run in enumerate(runs):
        if run.arm == "on":
            unscored = UnscoredPackage(package_id="case-17", kind="infrastructure",
                                      class_="provider_error", error_class="FictionalError",
                                      attempts=1, folder="attempts/case-17/1")
            runs[index] = replace(run, scorecard=run.scorecard.model_copy(
                update={"unscored_packages": [unscored]}))
    result = judge(runs)
    assert result.figures.main.retained_defects == 34
    assert result.figures.sensitivity.retained_defects == 34
    assert result.figures.main.dropped_packages == ["case-17"]


def test_v15_stopped_runs_detect_nothing_and_sensitivity_recall_can_decide_alone():
    def edit(arm, rep, index, package):
        if arm == "on" and rep == 1:
            return replace(package, status="behavioural", matched=package.model_held_out)
        return package

    result = judge(study(edit))
    assert result.verdict == "quality loss"
    assert result.figures.main.recall.estimate == pytest.approx(0)
    assert result.figures.main.recall.loss is False
    assert result.figures.sensitivity.recall.estimate == pytest.approx(-1 / 6)
    assert result.figures.sensitivity.recall.loss is True
    assert not has_reason(result, "RECALL LOSS", "main")
    assert has_reason(result, "RECALL LOSS", "sensitivity")


def test_v15_stopped_runs_keep_their_false_alarms_up_to_the_stop():
    def edit(arm, rep, index, package):
        package = replace(package, matched=())
        if arm == "on" and rep == 1:
            alarms = (("F-1", "model"),) if index == 0 else (
                ("F-1", "model"), ("F-2", "configured_check"))
            return replace(package, status="behavioural", false_alarms=alarms)
        return package

    result = judge(study(edit))
    assert result.verdict == "quality loss"
    assert result.figures.main.false_alarms.estimate == pytest.approx(0)
    assert result.figures.main.false_alarms.loss is False
    assert result.figures.sensitivity.false_alarms.estimate == pytest.approx(35 / 54)
    assert result.figures.sensitivity.false_alarms.loss is True
    assert not has_reason(result, "FALSE-ALARM RISE", "main")
    assert has_reason(result, "FALSE-ALARM RISE", "sensitivity")


@pytest.mark.parametrize("code_loss", [False, True])
def test_v16_main_33_sensitivity_36_is_below_floor_unless_a_guard_decides(code_loss):
    def edit(arm, rep, index, package):
        if index == 0:
            package = replace(package, model_held_out=("D-1", "D-2", "D-3"),
                              status="behavioural" if arm == "on" else "completed")
        elif index == 17:
            package = replace(package, model_held_out=("D-1",))
        if code_loss and index == 2:
            detected = () if arm == "on" and rep == 1 else ("C-1",)
            package = replace(package, code_held_out=("C-1",), matched=package.matched + detected)
        return package

    result = judge(study(edit))
    assert result.figures.main.retained_defects == 33
    assert result.figures.sensitivity.retained_defects == 36
    if code_loss:
        assert result.verdict == "quality loss"
        assert has_reason(result, "CODE DEFECT LOST")
    else:
        assert result.verdict == "inconclusive"
        assert has_reason(result, "BELOW FLOOR")
        text = " ".join(result.reasons)
        assert all(token in text for token in ("main", "33", "sensitivity", "36", "case-00"))
        assert refs(result.figures.main.dropped_defects) == {
            ("case-00", "D-1"), ("case-00", "D-2"), ("case-00", "D-3")}


def test_v17_false_alarm_median_rises_but_interval_includes_zero_so_no_loss():
    def edit(arm, rep, index, package):
        count = 10 if arm == "off" and index == 0 else int(arm == "on" and index != 0)
        return replace(package, false_alarms=tuple((f"F-{n}", "model") for n in range(count)))

    assert median([-10] + [1] * 17) > 0
    result = judge(study(edit))
    assert result.verdict == "no 10-point loss"
    for figure in (result.figures.main, result.figures.sensitivity):
        assert figure.false_alarms.estimate == pytest.approx(7 / 18)
        assert figure.false_alarms.lower < 0 < figure.false_alarms.upper
        assert figure.false_alarms.loss is False


def test_v19_bound_reached_completed_reviews_count_in_the_main_figure():
    bounded = study(lambda arm, rep, index, package: replace(package, bound_reached=True))
    data = verdict.study_stats(bounded)
    assert np.all(data.package_runs[0, :, 0] == 3)
    assert judge(bounded) == judge(study())


def test_v20_unstable_control_has_no_adoption_rule_and_tokens_and_wall_clock_never_decide():
    def unstable(arm, rep, index, package):
        return replace(package, matched=()) if arm == "off" and rep == 1 and index == 2 else package

    def expensive(arm, rep, index, package):
        package = unstable(arm, rep, index, package)
        value = 10_000_000 if arm == "on" else 1
        return replace(package, score_overrides={
            "usage": {"input_tokens": value, "cached_input_tokens": 0,
                      "cache_write_tokens": value, "output_tokens": value,
                      "reasoning_tokens": value, "tool_result_input_tokens": value,
                      "total_tokens": value * 2, "latency_s": float(value)},
            "wall_clock_s": float(value), "seconds_to_first_finding": float(value),
            "round_trips": value,
        })

    result = judge(study(unstable))
    assert result.verdict == "no 10-point loss"
    assert not any("CONTROL UNSTABLE" in reason for reason in result.reasons)
    assert judge(study(expensive)) == result


@pytest.mark.parametrize("lower, upper, expected", [(-0.05, 0.0, "no 10-point loss"),
                                                   (-0.10, 0.05, "inconclusive")])
def test_v23_recall_comparisons_are_strict(monkeypatch, lower, upper, expected):
    interval_stub(monkeypatch, lower, upper)
    result = judge(study())
    assert result.verdict == expected
    assert not has_reason(result, "RECALL LOSS")
    if lower == -0.10:
        assert has_reason(result, "LOWER END AT OR BELOW -10 POINTS", "main")
        assert has_reason(result, "LOWER END AT OR BELOW -10 POINTS", "sensitivity")


def test_false_alarm_lower_end_exactly_zero_is_no_loss(monkeypatch):
    def interval(moments, alpha, sides=1):
        if np.any(moments.computable):
            return batch_interval_stub(moments, 0, -0.05, 0.05)
        return batch_interval_stub(moments, 0.1, 0.0, 0.2)

    monkeypatch.setattr(stats, "package_intervals_from_moments", interval)
    result = judge(study())
    assert result.verdict == "no 10-point loss"
    assert result.figures.main.false_alarms.loss is False
    assert result.figures.sensitivity.false_alarms.loss is False


def test_every_firing_paired_rule_is_listed_on_both_figures():
    def edit(arm, rep, index, package):
        if arm == "off":
            return replace(package, matched=package.model_held_out)
        return replace(package, matched=("D-1",) if index == 0 else (),
                       false_alarms=tuple((f"F-{n}", "model")
                                          for n in range(1 if index == 0 else 2)))

    result = judge(study(edit))
    assert result.verdict == "quality loss"
    for figure in ("main", "sensitivity"):
        assert has_reason(result, "RECALL LOSS", figure)
        assert has_reason(result, "FALSE-ALARM RISE", figure)


def test_deciding_false_alarms_use_one_shared_definition_and_exclude_tuned_on_hits(monkeypatch):
    from swreview.benchmark import report_page

    assert report_page.deciding_false_alarm_ids is origins.deciding_false_alarm_ids
    calls = []
    original = origins.deciding_false_alarm_ids

    def spy(score):
        calls.append(score.package_id)
        return original(score)

    monkeypatch.setattr(origins, "deciding_false_alarm_ids", spy)
    alarms = tuple(("F-" + origin, origin) for origin in get_args(origins.Origin)) + (
        ("F-tuned", "model"),)

    def edit(arm, rep, index, package):
        return replace(package, false_alarms=alarms, tuned_on_false_alarms=("F-tuned",)) if (
            arm == "on") else package

    result = judge(study(edit))
    assert len(calls) == 6 * 18
    for figure in (result.figures.main, result.figures.sensitivity):
        # `model` and `configured_check`, even when they match no key entry.
        assert figure.false_alarms.estimate == pytest.approx(2)


def test_false_alarm_rule_averages_over_clean_twins_and_anchors_as_well_as_defect_cases():
    runs = []
    for rep in range(1, 4):
        for arm in ("off", "on"):
            packages = []
            for index in range(21):
                clean = index >= 18
                matched = () if clean or (arm == "on" and index == 1) else ("D-1",)
                if arm == "on" and index == 0:
                    matched = ("D-1", "D-2")
                alarm_count = (2 if clean else 1) if arm == "on" else 0
                packages.append(PanePackage(
                    package_id=("twin", "anchor-turn", "anchor-fit")[index - 18] if clean else (
                        f"case-{index:02d}"), model_held_out=() if clean else ("D-1", "D-2"),
                    matched=matched,
                    false_alarms=tuple((f"F-{n}", "model") for n in range(alarm_count))))
            runs.append(pane_run(f"{arm}-{rep}", arm, packages))
    result = judge(runs)
    for figure in (result.figures.main, result.figures.sensitivity):
        assert figure.retained_packages == 21
        assert figure.recall.packages == 18
        assert figure.false_alarms.packages == 21
        assert figure.false_alarms.estimate == pytest.approx(24 / 21)


@pytest.mark.parametrize("detected", [False, True])
def test_tuned_on_model_defects_never_change_either_held_out_recall_figure(detected):
    def edit(arm, rep, index, package):
        return replace(package, model_tuned_on=("T-1",),
                       matched=package.matched + (("T-1",) if detected and arm == "on" else ()))

    result = judge(study(edit))
    assert result == judge(study())
    assert result.figures.main.retained_defects == 36


def test_flagged_and_credited_defects_both_count_as_detected():
    def edit(arm, rep, index, package):
        return replace(package, matched=(), flagged=package.matched)

    assert judge(study(edit)) == judge(study())


def test_unequal_package_defect_counts_use_the_ratio_over_defects():
    runs = [
        pane_run("off-1", "off", [PanePackage("one", model_held_out=("D-1",), matched=()),
                                    PanePackage("two", matched=("D-1", "D-2"))]),
        pane_run("on-1", "on", [PanePackage("one", model_held_out=("D-1",)),
                                  PanePackage("two", matched=("D-1",))]),
    ]
    result = judge(runs, rules=replace(RULES, floor=1))
    for figure in (result.figures.main, result.figures.sensitivity):
        assert figure.retained_defects == 3
        assert figure.recall.estimate == pytest.approx(0)  # (1 - 1) / 3, not (1 - 1/2) / 2.
        assert figure.recall.packages == 2


def test_one_arm_pilot_runs_fill_off_arm_and_leave_on_arm_empty():
    data = verdict.study_stats([run for run in study() if run.arm == "off"])
    assert data.detections.shape == (1, 2, 2, 36)
    assert np.all(data.counted_runs[0, 0] == 3)
    assert np.all(data.counted_runs[0, 1] == 0)
    assert np.all(data.package_runs[0, 0] == 3)
    assert np.all(data.package_runs[0, 1] == 0)
    assert np.all(data.detections[0, 1] == 0)


def test_leading_axis_of_three_studies_is_judged_like_three_individual_calls():
    def stopped(arm, rep, index, package):
        return replace(package, status="behavioural") if arm == "on" and rep == 1 else package

    studies = [study(), study(stopped),
               study(lambda arm, rep, index, package: replace(package, matched=("D-1",)))]
    individual = [verdict.study_stats(runs) for runs in studies]
    arrays = {
        field.name: np.concatenate([getattr(item, field.name) for item in individual], axis=0)
        for field in fields(individual[0])
        if isinstance(getattr(individual[0], field.name), np.ndarray)
        and getattr(individual[0], field.name).ndim >= 3
    }
    batched = replace(individual[0], **arrays)
    assert verdict.judge(batched, RULES) == [verdict.judge(item, RULES)[0] for item in individual]


def test_v25_seeded_simulator_draws_match_scorecards_including_stopped_runs(tmp_path):
    """The same raw draws reach the one rule through both of its callers."""
    from swreview.benchmark import simulate

    layout = simulate.Layout(packages=(2, 1, 2, 1, 0, 0))
    scenario = simulate.Scenario(
        name="v25-mixed", rates="uniform", sd=1.0, fa_mean=1.0, fa_size=0.5,
        stop_rate=0.2, clearance_count=6, clearance_rate=0.15,
        code_count=2, code_rate=0.8,
    )
    draws = simulate.draw_studies(
        scenario, seed=230025, sims=200, reps=3, layout=layout, return_draws=True,
    )
    package_ids = tuple(f"package-{index:02d}" for index in range(len(layout.packages)))
    model_refs = tuple(
        verdict.DefectRef(package_id=package_ids[int(package)], defect_id=f"D-{index:02d}")
        for index, package in enumerate(draws.defect_packages)
    )
    code_refs = tuple(
        verdict.DefectRef(package_id=package_ids[int(package)], defect_id=f"C-{index:02d}")
        for index, package in enumerate(draws.code_packages)
    )
    known_refs = model_refs + code_refs
    known_packages = np.concatenate((draws.defect_packages, draws.code_packages))

    def ordered(refs):
        return sorted(range(len(refs)), key=lambda index: (
            refs[index].package_id, refs[index].defect_id))

    model_order, code_order, clear_order = map(ordered, (model_refs, code_refs, known_refs))
    clear_runs = {
        (study_index, named_index): tuple(
            f"on-{rep + 1}"
            for rep in np.flatnonzero(draws.clears[study_index, 1, :, raw_index])
        )
        for study_index in range(200)
        for named_index, raw_index in enumerate(clear_order)
        if np.any(draws.clears[study_index, 1, :, raw_index])
    }
    # Supply report identities and canonical ordering only; counts remain the
    # simulator's own sufficient statistics, never rebuilt from the scorecards.
    direct = replace(
        draws.stats,
        detections=draws.stats.detections[..., model_order],
        counted_runs=draws.stats.counted_runs[..., model_order],
        defect_packages=draws.stats.defect_packages[model_order],
        code_detections=draws.stats.code_detections[..., code_order],
        code_runs=draws.stats.code_runs[..., code_order],
        clears=draws.stats.clears[..., clear_order],
        clear_held_out=draws.stats.clear_held_out[clear_order],
        defect_ids=tuple(model_refs[index] for index in model_order),
        package_ids=package_ids,
        code_ids=tuple(code_refs[index] for index in code_order),
        clear_ids=tuple(known_refs[index] for index in clear_order),
        clear_runs=clear_runs,
    )
    rulesets = (
        verdict.VerdictRules(alpha=0.025, cleared_guard_decides=False, floor=4),
        verdict.VerdictRules(alpha=0.01, cleared_guard_decides=True, floor=4),
    )
    direct_results = [verdict.judge(direct, rules) for rules in rulesets]
    assert draws.stats.detections.shape[0] == 200
    assert np.any(draws.false_alarms[draws.stopped] > 0)
    assert np.any(draws.detections & draws.stopped[..., draws.defect_packages])
    assert np.any(draws.clears & draws.stopped[..., known_packages])
    stopped_scorecards = 0

    for study_index in range(200):
        runs = []
        for rep in range(3):
            for arm_index, arm in enumerate(("off", "on")):
                packages = []
                for package_index, package_id in enumerate(package_ids):
                    model_indices = np.flatnonzero(draws.defect_packages == package_index)
                    code_indices = np.flatnonzero(draws.code_packages == package_index)
                    detected = tuple(
                        model_refs[index].defect_id for index in model_indices
                        if draws.detections[study_index, arm_index, rep, index]
                    ) + tuple(
                        code_refs[index].defect_id for index in code_indices
                        if draws.code_detections[study_index, arm_index, rep, index]
                    )
                    cleared = tuple(
                        known_refs[index].defect_id
                        for index in np.flatnonzero(known_packages == package_index)
                        if draws.clears[study_index, arm_index, rep, index]
                    )
                    alarm_count = int(draws.false_alarms[
                        study_index, arm_index, rep, package_index])
                    stopped = bool(draws.stopped[study_index, arm_index, rep, package_index])
                    stopped_scorecards += int(stopped)
                    packages.append(PanePackage(
                        package_id=package_id,
                        model_held_out=tuple(model_refs[index].defect_id
                                             for index in model_indices),
                        code_held_out=tuple(code_refs[index].defect_id for index in code_indices),
                        matched=detected, cleared=cleared,
                        false_alarms=tuple((f"F-{index}", "model")
                                           for index in range(alarm_count)),
                        status="behavioural" if stopped else "completed",
                    ))
                run = pane_run(f"{arm}-{rep + 1}", arm, packages)
                scorecard_path = tmp_path / f"study-{study_index:03d}-{arm}-{rep + 1}.json"
                scorecard_path.write_text(run.scorecard.model_dump_json(), encoding="utf-8")
                parsed = Scorecard.model_validate_json(scorecard_path.read_bytes())
                for score, package in zip(parsed.per_package, packages, strict=True):
                    assert score.run_status.kind == package.status
                    assert len(score.false_alarm_finding_ids) == len(package.false_alarms)
                runs.append(replace(run, scorecard=parsed))

        read = verdict.study_stats(runs)
        for field in fields(read):
            actual, expected = getattr(read, field.name), getattr(direct, field.name)
            if isinstance(actual, np.ndarray):
                if expected.ndim >= 3:
                    expected = expected[study_index:study_index + 1]
                np.testing.assert_array_equal(actual, expected, err_msg=field.name)
        assert read.defect_ids == direct.defect_ids
        assert read.package_ids == direct.package_ids
        assert read.code_ids == direct.code_ids
        assert read.clear_ids == direct.clear_ids
        assert read.code_missed_runs == {}
        assert read.clear_runs == {
            (0, index): names for (study, index), names in clear_runs.items()
            if study == study_index
        }
        for rules_index, rules in enumerate(rulesets):
            assert verdict.judge(read, rules)[0] == direct_results[rules_index][study_index]

    assert stopped_scorecards == np.count_nonzero(draws.stopped)


def test_verdict_imports_no_report_compare_simulator_pilot_or_adoption_rule():
    tree = ast.parse(Path(verdict.__file__).read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
            names.extend(alias.name for alias in node.names)
    forbidden = {"report_page", "compare", "simulate", "pilot", "adoption"}
    assert not {part for name in names for part in name.split(".")} & forbidden


def ledger_sample():
    """Section 8's ledger shape, without deriving any field from the implementation."""
    interval = {"estimate": 0.0, "lower": -0.05, "upper": 0.05, "alpha": 0.025,
                "df": 17, "packages": 18, "computable": True, "loss": False}
    figure = {"retained_defects": 36, "retained_packages": 18, "dropped_defects": [],
              "dropped_packages": [], "recall": interval, "false_alarms": interval}
    return deepcopy({
        "study": "pane_defaults", "provider": "openai", "model": "gpt-5.6-sol",
        "commit": "5733efd", "slice": "committed", "run_dirs": ["pane/off-1", "pane/on-1"],
        "reps": {"off": 1, "on": 1}, "verdict": "no 10-point loss", "reasons": [],
        "refusal": None,
        "approval": {
            "file_sha256": "a" * 64, "approved_at": "2026-10-05", "alpha": 0.025,
            "held_out_model_defects": 36, "reps": 1, "cleared_guard_decides": False,
            "seed": 140514, "simulated": {
                "power_proportional": 0.83, "power_room": 0.87, "identical_loss": 0.036,
                "identical_loss_upper": 0.041, "no_loss_at_drop": 0.021,
                "no_loss_at_drop_upper": 0.025}},
        "figures": {"main": figure, "sensitivity": figure},
        "code_guard": {"lost": [], "off_only_sometimes": [], "skipped": []},
        "cleared_guard": {"decides": False, "named": []},
        "noise_floor": {"state": "computed", "points": 8.5, "seed": 140514, "numpy": "2.4.6"},
        "arms_differed_in": ["prerun_checks"], "inert": [], "untested_between_turns": [],
        "shown": [{"name": "fit and axial-stack calls per run", "off": 3.1, "on": 2.4,
                   "estimate": -0.7, "lower": -1.3, "upper": -0.1, "level": 0.95,
                   "excludes_zero": True}],
    })


def test_pane_study_ledger_sample_preserves_fractional_intervals_and_shown_measure():
    sample = ledger_sample()
    parsed = verdict.PaneStudy.model_validate(sample)
    assert parsed.figures.main.recall.lower == -0.05
    assert parsed.approval.alpha == 0.025
    assert parsed.shown[0].excludes_zero is True
    assert parsed.model_dump(mode="json") == sample


def test_section_eight_minimal_off_only_sometimes_entry_reads_with_its_explanation():
    sample = ledger_sample()
    sample["code_guard"]["off_only_sometimes"] = [
        {"package_id": "case-02", "defect_id": "C-1"}]
    parsed = verdict.PaneStudy.model_validate(sample)
    assert refs(parsed.code_guard.off_only_sometimes) == {("case-02", "C-1")}
    assert parsed.code_guard.off_only_sometimes[0].reason == (
        "the off arm detected it only sometimes")


@pytest.mark.parametrize("path", [(), ("approval",), ("approval", "simulated"),
                                  ("figures",), ("figures", "main"),
                                  ("figures", "main", "recall"), ("code_guard",),
                                  ("cleared_guard",), ("noise_floor",), ("shown", 0)])
def test_pane_study_ledger_models_refuse_unknown_nested_fields(path):
    sample = ledger_sample()
    target = sample
    for part in path:
        target = target[part]
    target["unexpected_field"] = "fictional"
    with pytest.raises(ValidationError, match="unexpected_field"):
        verdict.PaneStudy.model_validate(sample)


def test_refused_or_private_pane_study_can_carry_no_verdict_approval_or_figures():
    sample = ledger_sample()
    sample.update(verdict=None, refusal="the on arm has no run", approval=None, figures=None,
                  code_guard=None, cleared_guard=None)
    parsed = verdict.PaneStudy.model_validate(sample)
    assert parsed.verdict is parsed.approval is parsed.figures is parsed.code_guard is (
        parsed.cleared_guard) is None
    assert parsed.refusal == "the on arm has no run"


@pytest.mark.parametrize("decides", [False, True])
@pytest.mark.parametrize("floor", [1, 34])
def test_compact_judge_matches_named_reports_on_mixed_stopped_and_guard_studies(decides, floor):
    from swreview.benchmark import simulate

    scenario = simulate.Scenario(
        "compact-mixed", "uniform", 1, 1, 0.5, stop_rate=0.2,
        clearance_count=6, clearance_rate=0.15, code_count=2, code_rate=0.8,
    )
    drawn = simulate.draw_studies(
        scenario, seed=230111, sims=200, reps=3,
        layout=simulate.Layout((2, 1, 2, 1, 0, 0)),
    )
    prepared = verdict.prepare_judge(drawn)
    for alpha in simulate.ALPHA_LADDER:
        rules = verdict.VerdictRules(alpha, decides, floor=floor)
        named = verdict.judge(drawn, rules)
        compact = verdict.judge(prepared, rules, named=False)
        np.testing.assert_array_equal(
            compact.quality_loss, [row.verdict == "quality loss" for row in named],
        )
        np.testing.assert_array_equal(
            compact.no_loss, [row.verdict == "no 10-point loss" for row in named],
        )
        np.testing.assert_array_equal(
            compact.main_recall_loss, [row.figures.main.recall.loss for row in named],
        )


def test_prepared_judge_reuses_package_moments_without_building_named_models(monkeypatch):
    data = verdict.study_stats(study())
    expected = verdict.judge(data, RULES)[0]
    prepared = verdict.prepare_judge(data)

    def unexpected(*args, **kwargs):
        pytest.fail("prepared numerical judging repeated moment work or allocated report models")

    monkeypatch.setattr(stats, "prepare_package_intervals", unexpected)
    monkeypatch.setattr(verdict, "StudyVerdict", unexpected)
    monkeypatch.setattr(verdict, "PairedInterval", unexpected)
    for alpha in (0.025, 0.01, 0.0025):
        compact = verdict.judge(prepared, replace(RULES, alpha=alpha), named=False)
        assert compact.quality_loss.tolist() == [False]
    compact = verdict.judge(prepared, RULES, named=False)
    assert compact.no_loss.tolist() == [expected.verdict == "no 10-point loss"]


def test_package_grouping_preserves_existing_order_for_more_than_two_defects():
    # A report can have more defects per package than a reference simulation.
    values = np.array([[[1e16, 1.0, -1e16, 0.25], [0.0, 0.0, 0.0, 0.5]]])
    packages = np.array([0, 0, 0, 1])
    expected = np.einsum(
        "sfd,dk->sfk", values, (packages[:, None] == np.arange(3)).astype(float),
    )
    np.testing.assert_array_equal(verdict._group_packages(values, packages, 3), expected)
