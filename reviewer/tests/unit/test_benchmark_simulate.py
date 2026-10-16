"""T230: seeded simulator mechanics and the three default reference searches."""

from __future__ import annotations

import ast
import json
from dataclasses import fields, replace
from itertools import product
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from swreview.benchmark import digest, simulate
from swreview.cli import app

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


@pytest.fixture(scope="module")
def reference_results():
    """Exactly three 4,000-study searches belong in the default suite (S-9)."""
    return {
        name: simulate.search(simulate.SCENARIOS[name], seed=SEED, sims=4000)
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


def test_s7_half_at_sd_one_reaches_ten_then_grows(reference_results):
    search = reference_results[DEFAULT_SCENARIOS[0]]
    assert search.result is not None
    assert search.result.reps == 10
    assert search.result.growth_units >= 1
    first_growth = next(index for index, row in enumerate(search.tried) if row.growth_units)
    assert [row.reps for row in search.tried[:first_growth]] == list(range(3, 11))
    assert all(row.reps == 10 for row in search.tried[first_growth:])


@pytest.mark.parametrize("name", DEFAULT_SCENARIOS)
def test_s9_three_full_searches_hold_both_bounds_and_both_powers(name, reference_results):
    search = reference_results[name]
    result = search.result
    assert result is not None, name
    assert result.alpha in simulate.ALPHA_LADDER
    assert result.identical_loss <= result.identical_loss_upper <= .05
    assert result.no_loss_at_drop <= result.no_loss_at_drop_upper <= .05
    assert result.power_room >= .8
    assert result.power_proportional >= .8
    assert all(row.reps >= 3 and row.defects >= 34 for row in search.tried)
    assert result.defects == 34 + 2 * result.growth_units
    assert result.packages == 51 + 3 * result.growth_units
    if name.endswith("-clear"):
        assert search.cleared_guard_decides is False
        assert search.cleared_guard_reason
    if name.endswith("-code"):
        assert search.stress_case == pytest.approx(simulate.stress_case(
            np.full(10, .95), result.reps,
        ))


def noise_floor_data():
    """A hand-written record, independent of the model being checked."""
    return {
        "noise_floor_schema": 1, "study": "pane_defaults", "provider": "openai",
        "model": "fict-model", "runs_digest": "a" * 64, "seed": SEED, "sims": 4000,
        "numpy_version": np.__version__, "grid": [index / 2 for index in range(1, 101)],
        "result": 12.5,
    }


@pytest.mark.parametrize("result", [12.5, "above 50 points", "not attainable"])
def test_noise_floor_record_reads_each_result_without_computing(tmp_path, result):
    data = {**noise_floor_data(), "result": result}
    path = tmp_path / "noise-floor.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    record = simulate.read_noise_floor(path)
    assert record.model_dump(mode="json") == data


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
