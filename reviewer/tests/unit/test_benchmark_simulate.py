"""T230: seeded simulator mechanics and small seeded versions of the three reference searches.

The full 4,000-simulation S-7 and S-9 searches run under `-m simulation`, in
`tests/simulation/test_reference_searches.py` (owner decision 114A).
"""

from __future__ import annotations

import ast
import inspect
import json
from dataclasses import fields, replace
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from swreview.benchmark import digest, simulate, stats, verdict
from swreview.cli import app
from tests.support.simulation_reference import (
    assert_repetitions_then_growth,
    assert_search_measurements,
    assert_search_structure,
)

SEED = 20261016
DEFAULT_SCENARIOS = (
    "half-sd1.0-fa1-nb0.5",
    "uniform-sd1.0-fa1-nb0.5-clear",
    "uniform-sd1.0-fa1-nb0.5-code",
)
INPUTS = {
    "rate_distribution", "shock_sd", "marginal_rate_rule", "layout", "false_alarm_model",
    "stops", "clearances", "code_produced_defects", "drop", "shapes", "alpha_ladder",
    "deciding_rules", "sims", "seed", "cap", "floor", "numpy_version",
}


def constant_rate(rate):
    return lambda rng, shape: np.full(shape, rate, dtype=float)


SMALL_SIMS = 100
"""Small, but enough for a 5% Wilson bound to hold with room: below 52 none can, since even 0
hits of 51 bound above 5%, and at 50 no size up to 200 defects is chosen.

At this seed each of S-9's three searches still reaches the cap of 10 and then grows, as the
full ones do, in under 2 s; the independent recompute takes about 2 s more.
"""


@pytest.fixture(scope="module")
def small_results():
    """S-9's three searches at `SMALL_SIMS`, seeded, at the default cap of 10 (114A).

    The full 4,000-study searches moved to `tests/simulation/test_reference_searches.py`, run
    under `-m simulation` before any approval; they alone carry the 5% bound and 80% power
    claims, which need all 4,000 simulations.
    """
    return {
        name: simulate.search(simulate.SCENARIOS[name], seed=SEED, sims=SMALL_SIMS)
        for name in DEFAULT_SCENARIOS
    }


@pytest.fixture(scope="module")
def cli_runs():
    """Exercise the specified command with real, small searches, including reproducibility."""
    runner = CliRunner()
    arguments = [
        "benchmark", "simulate", "--scenario", DEFAULT_SCENARIOS[1],
        "--sims", "200", "--seed", str(SEED),
    ]
    captured = []
    original = simulate.search

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured.append(result)
        return result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(simulate, "search", capture)
        text = runner.invoke(app, arguments)
        repeated = runner.invoke(app, arguments)
        structured = runner.invoke(app, arguments + ["--json"])
    for response in (text, repeated, structured):
        assert response.exit_code == 0, response.output
    return text.output, repeated.output, json.loads(structured.output), captured[0]


def test_scenarios_are_exactly_the_36_factorial_cases_and_three_single_additions():
    expected = {
        f"{rate}-sd{sd}-fa{mean}-{size}"
        for rate, sd, mean, size in product(
            ("half", "uniform", "polar"), ("0", "1.0"), ("0.2", "1", "3"),
            ("nb0.5", "poisson"),
        )
    }
    extra = {f"uniform-sd1.0-fa1-nb0.5-{suffix}" for suffix in ("stop", "clear", "code")}
    assert set(simulate.SCENARIOS) == expected | extra
    assert sum(name.startswith("half-sd1.0-") for name in simulate.SCENARIOS) == 6
    for name in expected:
        scenario = simulate.SCENARIOS[name]
        assert scenario.name == name
        assert scenario.stop_rate == scenario.clearance_count == scenario.code_count == 0
        assert scenario.fa_size == (None if name.endswith("poisson") else 0.5)
    assert simulate.SCENARIOS["uniform-sd1.0-fa1-nb0.5-stop"].stop_rate == 0.05
    clear = simulate.SCENARIOS[DEFAULT_SCENARIOS[1]]
    assert (clear.clearance_count, clear.clearance_rate, clear.stop_rate, clear.code_count) == (
        10, 0.05, 0, 0,
    )
    code = simulate.SCENARIOS[DEFAULT_SCENARIOS[2]]
    assert (code.code_count, code.code_rate, code.stop_rate, code.clearance_count) == (
        10, .95, 0, 0,
    )


def test_reference_and_given_layouts_grow_by_their_own_units():
    layout = simulate.REFERENCE_LAYOUT
    assert layout.packages == (2,) * 17 + (0,) * 34
    assert (layout.defects, layout.package_count) == (34, 51)
    grown = layout.grown(3)
    assert (grown.defects, grown.package_count) == (40, 60)
    assert grown.packages.count(0) == 40
    custom = simulate.Layout((2, 1, 0), growth_unit=(2, 0))
    assert (custom.grown(2).defects, custom.grown(2).package_count) == (7, 7)


@pytest.mark.parametrize("seed", [None, True])
def test_draws_require_an_explicit_integer_seed(seed):
    with pytest.raises(ValueError, match="seed"):
        simulate.draw_studies(
            simulate.SCENARIOS[DEFAULT_SCENARIOS[0]], seed=seed, sims=1, reps=1,
            layout=simulate.Layout((1,)),
        )


def test_s1_room_redistributes_the_shortfall_until_no_rate_is_exceeded():
    rates = np.array([0, .05, .5, .9])
    np.testing.assert_allclose(simulate.drop_rates(rates, .1, "room"), [0, 0, .325, .725])
    np.testing.assert_allclose(rates, [0, .05, .5, .9])


@pytest.mark.parametrize("shape", ["room", "proportional"])
def test_s1_both_shapes_drop_the_marginal_mean_by_exactly_the_requested_amount(shape):
    rates = np.random.Generator(np.random.PCG64(SEED)).uniform(0, 1, 257)
    on = simulate.drop_rates(rates, .1, shape)
    assert on is not None
    assert np.mean(rates - on) == pytest.approx(.1, abs=1e-14)
    assert np.all((0 <= on) & (on <= rates))
    if shape == "proportional":
        np.testing.assert_allclose(rates - on, .1 * rates / rates.mean())
    assert simulate.drop_rates(np.array([0, .05, .1]), .1, shape) is None


@pytest.mark.parametrize("shape", ["room", "proportional"])
@pytest.mark.parametrize(("rate", "count"), [(.7, 3), (.1, 100)])
def test_s1_exact_drop_boundary_is_attainable_despite_mean_rounding(shape, rate, count):
    rates = np.full(count, rate)
    on = simulate.drop_rates(rates, rate, shape)
    assert on is not None
    np.testing.assert_array_equal(on, np.zeros(count))
    batched = simulate.drop_rates(np.stack((rates, rates)), rate, shape)
    assert batched is not None
    np.testing.assert_array_equal(batched, np.zeros((2, count)))


@pytest.mark.parametrize("shape", ["room", "proportional"])
@pytest.mark.parametrize(("rate", "count"), [(.7, 3), (.1, 100)])
def test_s1_one_ulp_short_of_the_drop_remains_unattainable(shape, rate, count):
    rates = np.full(count, np.nextafter(rate, 0))
    assert simulate.drop_rates(rates, rate, shape) is None


def test_s1_unattainable_drop_is_reported_without_inventing_power():
    scenario = replace(
        simulate.SCENARIOS[DEFAULT_SCENARIOS[0]], rates=constant_rate(.05), code_count=2,
    )
    result = simulate.search(scenario, seed=SEED, sims=1, cap=3)
    assert result.result is None
    assert all(row.power_room is row.power_proportional is None for row in result.tried)
    assert result.stress_case == pytest.approx(simulate.stress_case(np.full(2, .95), 3))
    printed = simulate.render_result(scenario, result, seed=SEED, sims=1, cap=3)
    assert "not attainable" in printed
    assert "stress case" in printed
    assert "alpha=none" in printed
    assert "evaluated_alpha=0.0025" in printed


@pytest.mark.parametrize("shape", ["proportional", "room"])
def test_s1_mixed_batch_judges_drop_attainability_per_study(shape):
    rates = np.array([[.01, .05], [.2, .4], [.4, .8]])
    on = simulate.drop_rates(rates, .1, shape)
    assert on is not None
    assert np.isnan(on[0]).all()
    for index in (1, 2):
        np.testing.assert_array_equal(on[index], simulate.drop_rates(rates[index], .1, shape))


def test_s1_beta_studies_report_exclusions_and_use_the_eligible_wilson_denominator():
    scenario = replace(
        simulate.SCENARIOS[DEFAULT_SCENARIOS[0]],
        rates=lambda rng, shape: rng.beta(.4, 1.6, size=shape),
    )
    evaluation = simulate._SizeEvaluation(
        scenario, simulate.REFERENCE_LAYOUT, reps=3, seed=SEED, sims=4000,
        drop=.1, floor=34,
    )
    eligible = evaluation.stream.off_rates.mean(axis=1) >= .1
    count = int(np.count_nonzero(eligible))
    assert 0 < 4000 - count < 40
    measured = evaluation.measure(.025, False, 0)
    rates, bounds = [], []
    for shape in ("proportional", "room"):
        outcomes = evaluation.outcomes(shape, .025, False)
        assert outcomes is not None
        assert outcomes.quality_loss.shape == (count,)
        assert getattr(measured, f"power_{shape}") == (
            np.count_nonzero(outcomes.recall_loss[:, 0]) / count
        )
        assert getattr(measured, f"excluded_{shape}") == (4000 - count) / 4000
        hits = int(np.count_nonzero(outcomes.no_loss))
        rates.append(hits / count)
        bounds.append(stats.mc_upper_bound(hits, count))
    assert measured.no_loss_at_drop == max(rates)
    assert measured.no_loss_at_drop_upper == max(bounds)
    printed = simulate.render_result(
        scenario, simulate.SearchResult((measured,), None, False, "fixture", None, "not reached"),
    )
    assert f"excluded_proportional={(4000 - count) / 4000:.6f}" in printed
    assert f"excluded_room={(4000 - count) / 4000:.6f}" in printed
    assert len(evaluation.outcomes("null", .025, False).quality_loss) == 4000


@pytest.mark.parametrize("rate", [0, .05, .5, .9, 1])
def test_s2_stated_rates_are_marginal_over_the_sd_one_shock(rate):
    scenario = replace(simulate.SCENARIOS[DEFAULT_SCENARIOS[0]], rates=constant_rate(rate))
    drawn = simulate.draw_studies(
        scenario, seed=SEED, sims=40000, reps=1, layout=simulate.Layout((1,)),
    )
    for arm in (0, 1):
        actual = drawn.detections[:, arm, 0, 0].mean()
        assert actual == pytest.approx(rate, abs=.007)
        if rate in (0, 1):
            assert np.all(drawn.detections[:, arm, 0, 0] == rate)


@pytest.mark.parametrize("shape", ["room", "proportional"])
def test_s2_ten_point_drop_is_marginal_instead_of_a_logit_intercept_shift(shape):
    scenario = replace(simulate.SCENARIOS[DEFAULT_SCENARIOS[0]], rates=constant_rate(.5))
    drawn = simulate.draw_studies(
        scenario, seed=SEED, sims=40000, reps=1, layout=simulate.Layout((1,)),
        drop=.1, shape=shape,
    )
    off, on = drawn.detections[:, :, 0, 0].mean(axis=0)
    assert off == pytest.approx(.5, abs=.007)
    assert on == pytest.approx(.4, abs=.007)
    assert off - on == pytest.approx(.1, abs=.01)


def test_s2_shock_is_shared_by_a_package_and_independent_across_packages():
    drawn = simulate.draw_studies(
        simulate.SCENARIOS[DEFAULT_SCENARIOS[0]], seed=SEED, sims=40000,
        reps=1, layout=simulate.Layout((2, 2)),
    )
    covariance = np.cov(drawn.detections[:, 0, 0, :], rowvar=False)
    assert covariance[0, 1] > .025
    assert abs(covariance[0, 2]) < .006


def test_s2_shocks_are_independent_between_arms():
    scenario = replace(simulate.SCENARIOS[DEFAULT_SCENARIOS[0]], rates=constant_rate(.5))
    drawn = simulate.draw_studies(
        scenario, seed=SEED, sims=40000, reps=1, layout=simulate.Layout((1,)),
        return_draws=True,
    )
    assert abs(np.cov(drawn.detections[:, :, 0, 0], rowvar=False)[0, 1]) < .006


def test_s2_shocks_are_independent_between_repetitions():
    scenario = replace(simulate.SCENARIOS[DEFAULT_SCENARIOS[0]], rates=constant_rate(.5))
    drawn = simulate.draw_studies(
        scenario, seed=SEED, sims=40000, reps=2, layout=simulate.Layout((1,)),
        return_draws=True,
    )
    assert abs(np.cov(drawn.detections[:, 0, :, 0], rowvar=False)[0, 1]) < .006


def test_s3_false_alarms_are_independent_between_arms():
    scenario = replace(simulate.SCENARIOS[DEFAULT_SCENARIOS[0]], fa_mean=3)
    drawn = simulate.draw_studies(
        scenario, seed=SEED, sims=40000, reps=1, layout=simulate.Layout((1,)),
        return_draws=True,
    )
    assert abs(np.cov(drawn.false_alarms[:, :, 0, 0], rowvar=False)[0, 1]) < 1.5


def test_reference_polar_rates_have_exact_initial_counts_and_random_placement():
    scenario = simulate.SCENARIOS["polar-sd0-fa1-poisson"]
    drawn = simulate.draw_studies(scenario, seed=SEED, sims=100, reps=1, return_draws=True)
    rates = drawn.off_rates
    assert rates.shape == (100, 34)
    for value, count in ((0, 13), (1, 13), (.5, 8)):
        np.testing.assert_array_equal((rates == value).sum(axis=1), np.full(100, count))
    assert not np.array_equal(rates[0], rates[1])
    grown = simulate.draw_studies(
        scenario, seed=SEED, sims=2000, reps=1,
        layout=simulate.REFERENCE_LAYOUT.grown(20), return_draws=True,
    ).off_rates
    for value, fraction in ((0, 3 / 8), (1, 3 / 8), (.5, 1 / 4)):
        expected = ((34 * (13 / 34 if value != .5 else 8 / 34)) + 40 * fraction) / 74
        assert np.mean(grown == value) == pytest.approx(expected, abs=.006)


@pytest.mark.parametrize("mean", [.2, 1, 3])
@pytest.mark.parametrize("size", [.5, None])
def test_s3_false_alarm_moments_cover_gamma_poisson_and_poisson(mean, size):
    rng = np.random.Generator(np.random.PCG64(SEED))
    drawn = simulate.draw_false_alarms(rng, mean, size, 200000)
    variance = mean if size is None else mean + mean**2 / size
    assert drawn.shape == (200000,)
    assert np.all(drawn >= 0)
    assert np.issubdtype(drawn.dtype, np.integer)
    assert drawn.mean() == pytest.approx(mean, rel=.025, abs=.006)
    assert drawn.var() == pytest.approx(variance, rel=.04, abs=.008)


def test_stops_leave_main_keep_zero_detections_and_thinned_alarms_in_sensitivity():
    scenario = replace(
        simulate.SCENARIOS["uniform-sd1.0-fa1-nb0.5-stop"], rates=constant_rate(1),
        stop_rate=.25, fa_mean=3,
    )
    drawn = simulate.draw_studies(
        scenario, seed=SEED, sims=10000, reps=3, layout=simulate.Layout((2, 0)),
    )
    assert drawn.package_runs[:, :, 0, :].mean() / 3 == pytest.approx(.75, abs=.006)
    assert np.all(drawn.package_runs[:, :, 1, :] == 3)
    np.testing.assert_array_equal(drawn.detections[:, :, 0, :], drawn.counted_runs[:, :, 0, :])
    np.testing.assert_array_equal(drawn.detections[:, :, 1, :], drawn.detections[:, :, 0, :])
    assert np.all(drawn.false_alarms[:, :, 1, :] >= drawn.false_alarms[:, :, 0, :])
    assert np.any(drawn.false_alarms[:, :, 1, :] > drawn.false_alarms[:, :, 0, :])
    kept_at_stop = drawn.false_alarms[:, :, 1, :] - drawn.false_alarms[:, :, 0, :]
    assert kept_at_stop.mean() / 3 == pytest.approx(.25 * 3 * .5, abs=.02)


def test_code_guard_null_detects_every_on_run_and_the_stated_off_rate():
    drawn = simulate.draw_studies(
        simulate.SCENARIOS[DEFAULT_SCENARIOS[2]], seed=SEED, sims=10000, reps=3,
    )
    np.testing.assert_array_equal(drawn.code_detections[:, 1, :], drawn.code_runs[:, 1, :])
    assert drawn.code_detections[:, 0, :].sum() / drawn.code_runs[:, 0, :].sum() == (
        pytest.approx(.95, abs=.003)
    )


@pytest.mark.parametrize(("reps", "rounded"), [(3, .729), (6, .885), (10, .936)])
def test_s5_clearance_null_and_code_stress_match_the_closed_forms(reps, rounded):
    q, p, count = .05, .95, 10
    clear_expected = 1 - (1 - (1 - (1 - q)**reps) * (1 - q)**reps)**count
    stress_expected = 1 - (1 - p**reps * (1 - p**reps))**count
    assert clear_expected == pytest.approx(rounded, abs=.001)
    assert simulate.cleared_null_rate(q, count, reps) == pytest.approx(clear_expected)
    assert simulate.stress_case(np.full(count, p), reps) == pytest.approx(stress_expected)
    scenario = replace(simulate.SCENARIOS[DEFAULT_SCENARIOS[1]], fa_mean=0)
    drawn = simulate.draw_studies(
        scenario, seed=SEED, sims=30000, reps=reps, layout=simulate.Layout((2,) * 5),
    )
    fired = np.any((drawn.clears[:, 1, :] > 0) & (drawn.clears[:, 0, :] == 0), axis=1)
    assert fired.mean() == pytest.approx(clear_expected, abs=.008)


@pytest.mark.parametrize("failing_bound", [0, 1])
def test_s6_level_search_walks_the_ladder_until_both_bounds_hold(failing_bound):
    visited = []

    def bounds(alpha):
        visited.append(alpha)
        result = [.04, .04]
        if alpha > .015:
            result[failing_bound] = .051
        return tuple(result)

    assert simulate.ALPHA_LADDER == (.025, .02, .015, .01, .005, .0025)
    assert simulate.level_search(bounds) == .015
    assert visited == [.025, .02, .015]
    assert simulate.level_search(lambda alpha: (.05, .05)) == .025
    assert simulate.level_search(lambda alpha: (.051, .04)) is None


def test_s9_measure_counts_only_main_recall_power_and_the_higher_shape(monkeypatch):
    evaluation = simulate._SizeEvaluation.__new__(simulate._SizeEvaluation)
    evaluation.reps, evaluation.sims = 3, 5
    evaluation.layout = simulate.REFERENCE_LAYOUT
    counts = {
        "proportional": SimpleNamespace(
            main_recall_loss=np.array([1, 1, 0, 0, 0], dtype=bool),
            recall_loss=np.array([[1, 1], [1, 1], [0, 1], [0, 0], [0, 0]], dtype=bool),
            quality_loss=np.array([1, 1, 1, 1, 0], dtype=bool),
            no_loss=np.array([0, 0, 1, 1, 0], dtype=bool),
        ),
        "room": SimpleNamespace(
            main_recall_loss=np.array([1, 1, 1, 0, 0], dtype=bool),
            recall_loss=np.array([[1, 1], [1, 1], [1, 1], [0, 1], [0, 0]], dtype=bool),
            quality_loss=np.ones(5, dtype=bool),
            no_loss=np.array([0, 0, 0, 1, 0], dtype=bool),
        ),
    }
    monkeypatch.setattr(evaluation, "null", lambda alpha, decides: (.0, .01))
    monkeypatch.setattr(evaluation, "outcomes", lambda shape, alpha, decides: counts[shape])
    measured = evaluation.measure(.025, False, 0)
    assert measured.power_proportional == 2 / 5
    assert measured.power_room == 3 / 5
    assert measured.no_loss_at_drop == 2 / 5
    assert measured.no_loss_at_drop_upper == stats.mc_upper_bound(2, 5)


@pytest.mark.parametrize(("proportional", "room", "expected"), [
    (.8, .8, True), (.799999, .9, False), (.9, .799999, False),
    (None, .8, True), (.8, None, True), (None, None, False),
])
def test_s9_first_size_passes_at_eighty_percent_under_every_attainable_shape(
    proportional, room, expected,
):
    measured = SimpleNamespace(power_proportional=proportional, power_room=room)
    assert simulate._enough_power(measured) is expected


def test_s4_command_prints_all_inputs_and_one_json_document(cli_runs):
    text, _, structured, _ = cli_runs
    assert len(structured["scenarios"]) == 1
    row = structured["scenarios"][0]
    assert row["name"] == DEFAULT_SCENARIOS[1]
    inputs = row["inputs"]
    assert set(inputs) == INPUTS
    for key in INPUTS:
        assert key in text or key.replace("_", " ") in text
        assert inputs[key] is not None
    assert inputs["rate_distribution"] == "uniform"
    assert inputs["shock_sd"] == 1
    assert inputs["seed"] == SEED
    assert inputs["sims"] == 200
    assert inputs["cap"] == 10
    assert inputs["floor"] == 34
    assert inputs["drop"] == .1
    assert set(inputs["shapes"]) == {"room", "proportional"}
    assert inputs["alpha_ladder"] == list(simulate.ALPHA_LADDER)
    assert inputs["numpy_version"] == np.__version__
    assert "tried" in row["result"]
    assert "named only" in text


def test_s8_same_seed_repeats_the_whole_printout_byte_for_byte(cli_runs):
    text, repeated, _, _ = cli_runs
    assert text == repeated


@pytest.mark.parametrize(("name", "expected"), [
    ("uniform-sd1.0-fa1-nb0.5-stop",
     "605d4858e5aa4f955e43adcc3e84d435b742899c41c2ee6b7ba853bbf71329de"),
    ("uniform-sd1.0-fa1-nb0.5-clear",
     "1f07c9186da3c7bcae97101ca29c189ce10599824689146e4c8044efd60b5d3b"),
    ("uniform-sd1.0-fa1-nb0.5-code",
     "e1971a132c38b560213414f610eb2d8f5cd929c5aee61a26f4a67be63bec16c7"),
])
def test_s8_small_searches_match_saved_preoptimization_reference(name, expected):
    # Captured from 111A's saved source in .pytest-tmp/sim-reference/source/src,
    # independently of _StudyDrawStream and the optimized search implementation.
    search = simulate.search(simulate.SCENARIOS[name], seed=SEED, sims=200)
    assert digest.canonical_sha256(search.as_dict()) == expected


def test_simulator_signatures_share_the_declared_seed_simulation_and_cap_defaults():
    assert simulate.DEFAULT_SEED == SEED
    assert simulate.DEFAULT_SIMS == 4000
    assert simulate.DEFAULT_CAP == 10
    for function in (simulate.search, simulate.scenario_inputs, simulate.render_result):
        parameters = inspect.signature(function).parameters
        assert parameters["seed"].default == simulate.DEFAULT_SEED
        assert parameters["sims"].default == simulate.DEFAULT_SIMS
        assert parameters["cap"].default == simulate.DEFAULT_CAP
        assert parameters["floor"].default == verdict.FLOOR
        assert parameters["drop"].default == verdict.LOSS_BOUND


def test_command_defaults_to_all_39_and_accepts_repeated_scenarios(monkeypatch, cli_runs):
    seen = []

    def search(scenario, **kwargs):
        seen.append(scenario.name)
        return cli_runs[3]

    monkeypatch.setattr(simulate, "search", search)
    runner = CliRunner()
    result = runner.invoke(app, ["benchmark", "simulate", "--json"])
    assert result.exit_code == 0, result.output
    assert len(seen) == 39
    assert set(seen) == set(simulate.SCENARIOS)
    assert {row["name"] for row in json.loads(result.output)["scenarios"]} == set(seen)
    selected = runner.invoke(app, [
        "benchmark", "simulate", "--scenario", DEFAULT_SCENARIOS[0],
        "--scenario", DEFAULT_SCENARIOS[2], "--json",
    ])
    assert selected.exit_code == 0, selected.output
    assert seen[-2:] == [DEFAULT_SCENARIOS[0], DEFAULT_SCENARIOS[2]]


def test_unknown_scenario_is_a_usage_error_naming_it():
    result = CliRunner().invoke(app, ["benchmark", "simulate", "--scenario", "fict-missing"])
    assert result.exit_code == 2
    assert "fict-missing" in result.output


def test_s7_cap_six_stops_repetitions_and_records_every_growth_unit():
    response = CliRunner().invoke(app, [
        "benchmark", "simulate", "--scenario", DEFAULT_SCENARIOS[0],
        "--seed", str(SEED), "--sims", "200", "--cap", "6", "--json",
    ])
    assert response.exit_code == 0, response.output
    scenario = json.loads(response.output)["scenarios"][0]
    tried = scenario["result"]["tried"]
    assert tried
    assert max(row["reps"] for row in tried) == 6
    assert all(3 <= row["reps"] <= 6 for row in tried)
    assert all(row["growth_units"] == (row["defects"] - 34) // 2 for row in tried)


def test_s7_small_half_at_sd_one_walks_repetitions_to_ten_then_grows(small_results):
    """The full search's shape at `SMALL_SIMS`; its full twin runs under `-m simulation`.

    Repetitions 3 to 10 at no growth, then one growth unit at a time at 10 repetitions. Whether
    the full 4,000-study search reaches its size with both 5% bounds and 80% power is
    `tests/simulation/test_reference_searches.py`'s claim, not this test's.
    """
    search = small_results[DEFAULT_SCENARIOS[0]]
    assert_repetitions_then_growth(search)


@pytest.mark.parametrize("name", DEFAULT_SCENARIOS)
def test_s9_small_searches_print_every_row_and_match_the_independent_recompute(
    name, small_results,
):
    """S-9's structure at `SMALL_SIMS`; the full 4,000-study searches run under `-m simulation`.

    `assert_search_measurements` redraws every tried size without the search's own streams and
    must agree with it exactly, here as at 4,000. The 5% bounds and 80% powers it re-derives at
    this size are only the search's own stopping rule; that the reference scenarios hold them
    needs the full 4,000 simulations, so that claim lives only in
    `tests/simulation/test_reference_searches.py`.
    """
    scenario = simulate.SCENARIOS[name]
    search = small_results[name]
    assert_search_structure(scenario, search, seed=SEED, sims=SMALL_SIMS)
    assert_search_measurements(scenario, search, seed=SEED, sims=SMALL_SIMS)


def noise_floor_data():
    """A hand-written record, independent of the model being checked."""
    return {
        "noise_floor_schema": 1, "study": "pane_defaults", "provider": "openai",
        "model": "fict-model", "runs_digest": "a" * 64, "seed": SEED, "sims": 4000,
        "numpy_version": np.__version__, "grid": [index / 2 for index in range(1, 101)],
        "result": 12.5,
    }


@pytest.mark.parametrize("result", [
    .5, 12.5, 50., "above 0.5 points", "above 30 points", "above 30.5 points",
    "above 50 points", "not attainable",
])
def test_noise_floor_record_reads_each_result_without_computing(tmp_path, result):
    data = {**noise_floor_data(), "result": result}
    path = tmp_path / "noise-floor.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    record = simulate.read_noise_floor(path)
    assert record.model_dump(mode="json") == data


@pytest.mark.parametrize("result", [
    0., -.5, .25, 30.25, 50.5, float("nan"), float("inf"), -float("inf"),
    True, False, "12.5",
    "above 0 points", "above -0.5 points", "above 0.25 points", "above 30.25 points",
    "above 50.5 points", "above nan points", "above inf points", "above 30",
    "above thirty points", "above 30.0 points", "above 030 points",
])
def test_noise_floor_record_refuses_values_outside_the_printed_grid(result):
    with pytest.raises(ValidationError, match="result"):
        simulate.NoiseFloorRecord.model_validate(noise_floor_data() | {"result": result})


@pytest.mark.parametrize("edit, name", [
    ({"noise_floor_schema": 2}, "noise_floor_schema"),
    ({"unknown": "fict"}, "unknown"),
])
def test_noise_floor_record_refuses_unsupported_schema_and_unknown_fields(tmp_path, edit, name):
    path = tmp_path / "noise-floor.json"
    path.write_text(json.dumps(noise_floor_data() | edit), encoding="utf-8")
    with pytest.raises((ValidationError, ValueError), match=name):
        simulate.read_noise_floor(path)


def test_p8_runs_digest_uses_sorted_relative_folders_and_parsed_scorecards(tmp_path):
    relative_to = tmp_path / "records"
    relative_to.mkdir()
    runs = [tmp_path / "runs" / "on-1", tmp_path / "runs" / "off-1"]
    cards = [{"z": [1, 2], "a": {"valid": 3}}, {"z": [], "a": {"valid": 4}}]
    for run, card in zip(runs, cards, strict=True):
        run.mkdir(parents=True)
        (run / "scorecard.json").write_bytes(json.dumps(card, indent=2).encode())
    expected = digest.canonical_sha256(sorted([
        ["../runs/on-1", digest.canonical_sha256(cards[0])],
        ["../runs/off-1", digest.canonical_sha256(cards[1])],
    ]))
    original = simulate.runs_digest(runs, relative_to=relative_to)
    assert original == expected
    assert simulate.runs_digest(list(reversed(runs)), relative_to=relative_to) == original
    path = runs[0] / "scorecard.json"
    reordered = {"a": {"valid": 3}, "z": [1, 2]}
    path.write_bytes(json.dumps(reordered, indent=4).replace("\n", "\r\n").encode())
    assert simulate.runs_digest(runs, relative_to=relative_to) == original
    reordered["a"]["valid"] = 5
    path.write_bytes(json.dumps(reordered).encode())
    assert simulate.runs_digest(runs, relative_to=relative_to) != original


def test_simulator_does_not_import_compare_or_pilot():
    tree = ast.parse(Path(simulate.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [alias.name for alias in node.names]
        else:
            continue
        assert not any(name.rsplit(".", 1)[-1] in {"compare", "pilot"} for name in names)


@pytest.mark.parametrize("sd, size", [(0, None), (1, 0.5)])
def test_shared_shape_stream_and_repetition_prefixes_keep_every_seeded_draw(sd, size):
    scenario = simulate.Scenario(
        "shared-mixed", "uniform", sd, 1, size, stop_rate=0.2,
        clearance_count=6, clearance_rate=0.15, code_count=2, code_rate=0.8,
    )
    layout = simulate.Layout((2, 1, 2, 1, 0, 0))
    requests = {"null": (0, "room"), "proportional": (.1, "proportional"), "room": (.1, "room")}
    stream = simulate._StudyDrawStream(
        scenario, seed=SEED, sims=17, layout=layout, requests=requests, return_draws=True,
    )
    previous = None
    for reps in (1, 3, 6):
        stream.advance(reps)
        if previous is not None:
            for field, value in previous[1].items():
                np.testing.assert_array_equal(getattr(previous[0], field), value)
        for name, (drop, shape) in requests.items():
            direct = simulate.draw_studies(
                scenario, seed=SEED, sims=17, reps=reps, layout=layout,
                drop=drop, shape=shape, return_draws=True,
            )
            shared = stream.raw(name)
            for field in fields(direct):
                expected, actual = getattr(direct, field.name), getattr(shared, field.name)
                if field.name == "stats":
                    for item in fields(expected):
                        np.testing.assert_equal(
                            getattr(actual, item.name), getattr(expected, item.name),
                        )
                elif isinstance(expected, np.ndarray):
                    np.testing.assert_array_equal(actual, expected)
                else:
                    assert actual == expected
        snapshot = stream.snapshot("null")
        previous = snapshot, {
            field.name: getattr(snapshot, field.name).copy()
            for field in fields(snapshot) if isinstance(getattr(snapshot, field.name), np.ndarray)
        }


def test_shared_shape_stream_keeps_null_when_the_drop_is_unattainable():
    scenario = replace(simulate.SCENARIOS[DEFAULT_SCENARIOS[0]], rates=constant_rate(.05))
    stream = simulate._StudyDrawStream(
        scenario, seed=SEED, sims=3, layout=simulate.REFERENCE_LAYOUT,
        requests={"null": (0, "room"), "proportional": (.1, "proportional"), "room": (.1, "room")},
    )
    stream.advance(3)
    assert stream.snapshot("null") is not None
    assert stream.snapshot("proportional") is stream.snapshot("room") is None


@pytest.mark.parametrize("sd", [0, 1])
@pytest.mark.parametrize("variants", [False, True])
def test_detection_helper_keeps_normal_then_uniform_order_and_shared_variants(sd, variants):
    package_shape = (7, 2, 2)
    defect_packages = np.array([0, 0, 1])
    intercepts = np.array([[-1., 0., 1.], [.5, -.5, 0.]])
    if variants:
        intercepts = np.stack((intercepts, intercepts + .2))[:, None, :, :]
    expected_rng, actual_rng = np.random.default_rng(SEED), np.random.default_rng(SEED)
    shocks = expected_rng.normal(0, sd, package_shape) if sd else 0
    logits = intercepts + (shocks[..., defect_packages] if sd else 0)
    probabilities = 1 / (1 + np.exp(-logits))
    expected = expected_rng.random((7, 2, 3)) < probabilities
    actual = simulate._draw_detections(
        actual_rng, intercepts, sd, package_shape, defect_packages,
    )
    np.testing.assert_array_equal(actual, expected)
    assert actual_rng.random() == expected_rng.random()


def test_stream_and_noise_floor_share_detection_and_main_figure_helpers(monkeypatch):
    calls = {"draw": 0, "assemble": 0}
    original_draw = simulate._draw_detections
    original_assemble = simulate._main_figure_stats

    def draw(*args, **kwargs):
        calls["draw"] += 1
        return original_draw(*args, **kwargs)

    def assemble(*args, **kwargs):
        calls["assemble"] += 1
        return original_assemble(*args, **kwargs)

    monkeypatch.setattr(simulate, "_draw_detections", draw)
    monkeypatch.setattr(simulate, "_main_figure_stats", assemble)
    layout = simulate.Layout((2, 2))
    simulate.draw_studies(
        simulate.Scenario("shared", "half", 1, 0, None),
        seed=SEED, sims=3, reps=2, layout=layout,
    )
    assert calls == {"draw": 2, "assemble": 1}
    monkeypatch.setattr(verdict, "judge", lambda *args, **kwargs: SimpleNamespace(
        main_recall_loss=np.ones(3, dtype=bool),
    ))
    assert simulate.noise_floor(
        layout, [.5] * 4, 1, alpha=.02, seed=SEED, reps=2, sims=3,
    ) == .5
    assert calls == {"draw": 6, "assemble": 3}


@pytest.mark.parametrize(("sd", "expected", "before_power", "power"), [
    (0, 22., 101 / 128, 103 / 128),
    (1, 23., 102 / 128, 104 / 128),
])
def test_noise_floor_direct_seeded_number_and_independent_boundary_draws(
    sd, expected, before_power, power,
):
    layout = simulate.Layout((2,) * 17, (2, 0))
    assert simulate.noise_floor(
        layout, [.5] * 34, sd, alpha=.02, seed=SEED, reps=3, sims=128,
    ) == expected
    # Independent high-order quadrature and bisection solve the marginal on
    # intercept. The oracle draws normal then uniform, and assembles its own
    # StudyStats without the simulator's two shared helpers.
    nodes, weights = np.polynomial.hermite_e.hermegauss(160)
    weights /= np.sqrt(2 * np.pi)
    defect_packages = np.repeat(np.arange(17), 2)
    observed = []
    for points in (expected - .5, expected):
        target = .5 - points / 100
        low, high = -40., 40.
        for _ in range(60):
            middle = (low + high) / 2
            marginal = np.sum(weights / (1 + np.exp(-(middle + sd * nodes))))
            if marginal < target:
                low = middle
            else:
                high = middle
        intercepts = np.array([0., (low + high) / 2])[None, :, None]
        rng = np.random.default_rng(SEED)
        detected = np.zeros((128, 2, 34), dtype=int)
        for _ in range(3):
            shock = rng.normal(0, sd, (128, 2, 17)) if sd else 0
            probability = 1 / (1 + np.exp(-(
                intercepts + (shock[..., defect_packages] if sd else 0)
            )))
            detected += rng.random((128, 2, 34)) < probability
        runs = np.full((128, 2, 2, 17), 3)
        empty = np.zeros((128, 2, 0), dtype=int)
        data = verdict.StudyStats(
            detections=np.stack((detected, detected), axis=2),
            counted_runs=runs[..., defect_packages], defect_packages=defect_packages,
            false_alarms=np.zeros_like(runs), package_runs=runs,
            code_detections=empty, code_runs=empty, clears=empty,
            clear_held_out=np.zeros(0, dtype=bool),
        )
        result = verdict.judge(data, verdict.VerdictRules(.02, False), named=False)
        observed.append(np.count_nonzero(result.main_recall_loss) / 128)
    assert observed == [before_power, power]
    assert before_power < .8 <= power


def test_noise_floor_masks_each_package_and_arm_count_and_never_detects_at_zero(monkeypatch):
    observed = []

    def judge(data, rules, *, named):
        observed.append(data)
        return SimpleNamespace(main_recall_loss=np.ones(5, dtype=bool))

    monkeypatch.setattr(verdict, "judge", judge)
    repetitions = np.array([[3, 0, 3], [1, 3, 2]])
    result = simulate.noise_floor(
        simulate.Layout((2, 2, 2)), [.5] * 6, 1,
        alpha=.02, seed=SEED, reps=repetitions, sims=5,
    )
    assert result == .5
    assert len(observed) == 2
    for data in observed:
        np.testing.assert_array_equal(
            data.counted_runs[0, :, 0], [[3, 3, 0, 0, 3, 3], [1, 1, 3, 3, 2, 2]],
        )
        np.testing.assert_array_equal(data.detections[:, 0, :, 2:4], 0)
        assert np.all(data.detections[:, 1, :, :2] <= 1)
        assert np.all(data.detections <= data.counted_runs)


def test_noise_floor_shock_is_shared_inside_a_package(monkeypatch):
    observed = []

    def judge(data, rules, *, named):
        observed.append(data.detections[:, 0, 0])
        return SimpleNamespace(main_recall_loss=np.ones(10000, dtype=bool))

    monkeypatch.setattr(verdict, "judge", judge)
    simulate.noise_floor(
        simulate.Layout((2, 2)), [.5] * 4, 1,
        alpha=.02, seed=SEED, reps=1, sims=10000,
    )
    covariance = np.cov(observed[0], rowvar=False)
    assert covariance[0, 1] > .035
    assert abs(covariance[0, 2]) < .008


def test_noise_floor_search_includes_fifty_points_and_shares_its_record_grid(monkeypatch):
    assert simulate.NOISE_FLOOR_GRID == tuple(index / 2 for index in range(1, 101))
    on_intercepts = []
    original = stats.intercept

    def intercept(table, rates):
        on_intercepts.append(np.asarray(rates))
        return original(table, rates)

    def judge(data, rules, *, named):
        at_end = np.all(on_intercepts[-1] == 0)
        return SimpleNamespace(main_recall_loss=np.full(2, at_end))

    monkeypatch.setattr(stats, "intercept", intercept)
    monkeypatch.setattr(verdict, "judge", judge)
    assert simulate.noise_floor(
        simulate.Layout((2, 2)), [.5] * 4, 0,
        alpha=.02, seed=SEED, reps=1, sims=2,
    ) == 50.
    assert len(on_intercepts) == 201


def test_noise_floor_scalar_repetitions_equal_explicit_counts():
    layout = simulate.Layout((2,) * 17)
    options = dict(alpha=.02, seed=SEED, sims=128)
    scalar = simulate.noise_floor(layout, [.5] * 34, 1, reps=3, **options)
    explicit = simulate.noise_floor(layout, [.5] * 34, 1, reps=np.full((2, 17), 3), **options)
    assert scalar == explicit == 23.


@pytest.mark.parametrize(("rates", "reps", "message"), [
    ([.5], 3, "one probability per layout defect"),
    ([[.5] * 4], 3, "one probability per layout defect"),
    ([.5] * 4, [3, 3], r"shape \(2, packages\)"),
    ([.5] * 4, [[3, 3, 3], [3, 3, 3]], r"shape \(2, packages\)"),
    ([.5] * 4, 0, "reps must be an integer at least 1"),
    ([.5] * 4, [[3, -1], [3, 3]], "reps must be an integer at least 0"),
    ([.5] * 4, [[3, 1.5], [3, 3]], "reps must be an integer at least 0"),
])
def test_noise_floor_refuses_bad_rates_and_repetition_shapes(rates, reps, message):
    with pytest.raises(ValueError, match=message):
        simulate.noise_floor(
            simulate.Layout((2, 2)), rates, 0,
            alpha=.02, seed=SEED, reps=reps, sims=2,
        )


def test_noise_floor_above_fifty_has_computable_recall_and_low_power(monkeypatch):
    computable = []
    original = verdict.judge

    def judge(data, rules, *, named):
        result = original(data, rules, named=named)
        computable.append(np.count_nonzero(result.recall_computable))
        return result

    monkeypatch.setattr(verdict, "judge", judge)
    assert simulate.noise_floor(
        simulate.Layout((2,) * 3), [.5] * 6, 0,
        alpha=.0025, seed=SEED, reps=1, sims=32,
    ) == "above 50 points"
    assert max(computable) >= 24


@pytest.mark.parametrize(("rate", "expected"), [
    (.3, "above 30 points"),
    (.305, "above 30.5 points"),
    (.004, "not attainable"),
    (0., "not attainable"),
])
def test_noise_floor_seeded_low_power_names_only_the_largest_attainable_grid_drop(
    rate, expected,
):
    assert simulate.noise_floor(
        simulate.Layout((2,) * 3), [rate] * 6, 0,
        alpha=.0025, seed=SEED, reps=1, sims=32,
    ) == expected


@pytest.mark.parametrize(("packages", "reps", "message"), [
    ((2,), 3, "fewer than two retained packages"),
    ((2, 0), 3, "fewer than two retained packages"),
    ((2, 2, 0), [[3, 0, 3], [3, 0, 3]], "fewer than two retained packages"),
    ((2, 2), [[3, 3], [0, 0]], "every on-arm run is uncounted"),
    ((2, 2), [[0, 0], [3, 3]], "no retained defect in both arms"),
    ((2, 2), [[3, 0], [0, 3]], "no retained defect in both arms"),
    ((2, 2, 0), [[3, 3, 3], [0, 0, 3]], "no retained defect in both arms"),
])
def test_noise_floor_refuses_a_structurally_uncomputable_main_recall_before_draws(
    packages, reps, message, monkeypatch,
):
    def unexpected_draw(*args, **kwargs):
        pytest.fail("an uncomputable main recall must be refused before simulation draws")

    monkeypatch.setattr(simulate, "_draw_detections", unexpected_draw)
    layout = simulate.Layout(packages)
    with pytest.raises(ValueError, match=f"main recall is not computable: {message}"):
        simulate.noise_floor(
            layout, [.5] * layout.defects, 0,
            alpha=.02, seed=SEED, reps=reps, sims=2,
        )


def test_grown_search_checks_the_guard_when_only_added_defects_can_clear():
    scenario = simulate.Scenario(
        "zero-original", "half", 0, 0, None, clearance_count=34,
        clearance_rate=(0,) * 34, growth_clearance_rate=.1,
    )
    result = simulate.search(
        scenario, layout=simulate.Layout((2,) * 17), floor=36,
        seed=SEED, sims=100, cap=3, drop=.4,
    )
    assert result.result.growth_units == 1
    assert result.cleared_guard_decides is False
    assert result.cleared_guard_reason == (
        "no ladder level holds both 5% bounds and 80% power "
        "with the cleared guard deciding"
    )


def test_grown_search_extends_clearances_with_the_pilot_pooled_rate(monkeypatch):
    observed = []
    original = simulate._SizeEvaluation

    class Evaluation(original):
        def choose(self, decides, growth_units):
            observed.append((self.scenario, self.layout, decides))
            passed = growth_units >= 1
            return simulate.SizeResult(
                self.reps, self.layout.package_count, self.layout.defects,
                growth_units, .02, .9 if passed else .5, .9 if passed else .5,
                0, .01, 0, .01,
            )

    monkeypatch.setattr(simulate, "_SizeEvaluation", Evaluation)
    scenario = simulate.Scenario(
        "pilot", "half", 0, 0, None, clearance_count=34,
        clearance_rate=(0.,) * 33 + (1 / 3,), growth_clearance_rate=1 / 102,
    )
    result = simulate.search(scenario, layout=simulate.Layout((2,) * 17), cap=3, sims=2)
    assert result.result.growth_units == 1
    grown, layout, deciding = observed[-1]
    assert deciding is True
    assert grown.clearance_count == 36
    assert grown.clearance_rate == (0.,) * 33 + (1 / 3, 1 / 102, 1 / 102)
    drawn = simulate.draw_studies(grown, seed=SEED, sims=20000, reps=3, layout=layout)
    for arm in (0, 1):
        assert np.mean(drawn.clears[:, arm, -2:]) / 3 == pytest.approx(1 / 102, abs=.001)
    expected_null = 1 - (
        (1 - (1 - (2 / 3)**3) * (2 / 3)**3)
        * (1 - (1 - (101 / 102)**3) * (101 / 102)**3)**2
    )
    fired = np.any((drawn.clears[:, 1] > 0) & (drawn.clears[:, 0] == 0), axis=1)
    assert fired.mean() == pytest.approx(expected_null, abs=.01)


def test_reference_structure_assertions_are_shared_by_small_and_full_searches(small_results):
    from tests.support import simulation_reference

    search = small_results[DEFAULT_SCENARIOS[0]]
    simulation_reference.assert_repetitions_then_growth(search)
    simulation_reference.assert_search_structure(
        simulate.SCENARIOS[DEFAULT_SCENARIOS[0]], search, seed=SEED, sims=SMALL_SIMS,
    )
    broken = replace(search, tried=(search.tried[1], search.tried[0], *search.tried[2:]))
    with pytest.raises(AssertionError):
        simulation_reference.assert_repetitions_then_growth(broken)
