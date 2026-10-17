"""T228's measurement contract and T239's fictional pilot estimator and command cases."""

from __future__ import annotations

import ast
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from swreview.benchmark import answer_key, compare, digest, matching, pilot, sets, simulate, verdict
from tests.support import local_paths
from tests.support.answer_keys import write_key
from tests.support.findings import make_finding
from tests.support.studies import PanePackage, pane_run, write_pane_study

COMPUTED_BLOCKS = ("identity", "pilot_runs", "smoke_runs", "measured", "sizing")


def measurement_data():
    """A hand-written, fictional record, independent of the measurement models."""
    run = {
        "folder": "off-1", "arm": "off", "repetition": 1,
        "started_at": "2026-10-14T12:00:00Z", "commit": "fict-commit",
    }
    defect = {"package_id": "fict-core", "defect_id": "D-1"}
    simulated = {
        "power_proportional": 0.83, "power_room": 0.87,
        "identical_loss": 0.036, "identical_loss_upper": 0.041,
        "no_loss_at_drop": 0.021, "no_loss_at_drop_upper": 0.025,
    }
    return {
        "identity": {
            "pilot_schema": 1, "study": "pane_defaults", "provider": "openai",
            "model": "fict-model", "commit": "fict-commit", "set_digest": "a" * 64,
            "scoring_rules_version": 4,
        },
        "pilot_runs": [run, {**run, "folder": "off-2", "repetition": 2}],
        "smoke_runs": [
            {**run, "folder": "smoke-off"},
            {**run, "folder": "smoke-on", "arm": "on"},
        ],
        "measured": {
            "defect_counts": [
                {**defect, "x": 1, "n": 2},
                {**defect, "defect_id": "D-2", "x": 0, "n": 0},
                {**defect, "defect_id": "D-3", "x": 0, "n": 1},
            ],
            "dropped_defects": [{**defect, "defect_id": "D-2"}],
            "dropped_defect_count": 1,
            "variance_excluded_defects": [{**defect, "defect_id": "D-3"}],
            "variance_excluded_count": 1,
            "beta_fit": {
                "mu": 0.5, "variance": None, "variance_computable": False,
                "distribution": "constant", "a": None, "b": None,
                "reason": "fewer than two defects with at least two counted runs",
            },
            "comovement": {
                "grid": [{"sd": 0.0, "log_likelihood": -4.5},
                         {"sd": 0.25, "log_likelihood": -4.0}],
                "estimate": 0.25, "used": 0.25,
            },
            "code_defects": [{**defect, "defect_id": "D-4", "x": 2, "n": 2}],
            "stops": {"x": 1, "n": 4},
            "clearances": [{**defect, "x": 0, "n": 2}],
            "false_alarm_fit": {
                "mean": 1.5, "variance": 3.0, "distribution": "negative_binomial", "k": 1.5,
            },
            "cost_time": {
                "mean_cost": 0.125, "mean_wall_clock_s": 20.5,
                "unknown_cost_runs": [{"run": "off-2", "package_id": "fict-core"}],
                "unknown_cost_count": 1,
            },
            "never_detected": [{
                **defect, "defect_id": "D-2", "findings": [{
                    "run": "off-1", "finding_id": "F-001", "check": "fict.other",
                    "status": "suspected", "title": "Fictional observation",
                    "observed": "A fictional symptom", "component_ids": ["cmp:0001"],
                    "document_ids": ["doc:0001"],
                }],
            }],
        },
        "sizing": {
            "cap": 10, "floor": 34, "seed": 140514, "sims": 4000,
            "ladder": [0.025, 0.02],
            "tried": [{
                "reps": 3, "packages": 47, "held_out_model_defects": 36,
                "growth_units": 0, "alpha": 0.02, "cleared_guard_decides": False,
                "simulated": simulated,
            }],
            "pilot_packages": ["fict-core", "fict-twin"], "growth_units": 0, "jobs": 2,
            "projected_wall_clock": {
                "off_run_s": 60.5, "on_run_s": 30.25, "study_s": 272.25,
                "smoke_ratio": 0.5, "smoke_off_s": 40.5, "smoke_on_s": 20.25,
                "mean_tokens_per_minute": 1234.5, "unknown_packages": [],
            },
            "result": {
                "reps": 3, "packages": 47, "held_out_model_defects": 36, "alpha": 0.02,
                "deciding_rules": ["recall", "false_alarms", "code_guard"],
                "cleared_guard_decides": False, "simulated": simulated,
                "stress_case": 0.729, "estimated_study_cost": 35.25,
            },
        },
        "sizing_digest": "b" * 64,
        "approval": {"approved": False, "approved_at": None},
    }


def write_record(tmp_path, data, *, newline="\n"):
    path = tmp_path / "pilot-measurement.json"
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_bytes((text.replace("\n", newline) + newline).encode("utf-8"))
    return path


def test_hand_written_measurement_reads_as_the_strict_model(tmp_path):
    data = measurement_data()
    measurement = pilot.read_measurement(write_record(tmp_path, data))
    assert isinstance(measurement, pilot.PilotMeasurement)
    assert pilot.PILOT_SCHEMA == 1
    assert measurement.model_dump(mode="json") == data
    assert isinstance(measurement.measured.beta_fit, pilot.BetaFit)
    assert isinstance(measurement.measured.comovement, pilot.CoMovement)
    assert isinstance(measurement.measured.false_alarm_fit, pilot.FalseAlarmFit)
    assert isinstance(measurement.measured.never_detected[0], pilot.NeverDetected)
    assert measurement.sizing.jobs == 2
    assert measurement.sizing.projected_wall_clock.model_dump() == (
        data["sizing"]["projected_wall_clock"]
    )
    # The reader loads data only; none of the listed run folders need exist.
    assert sorted(path.name for path in tmp_path.iterdir()) == ["pilot-measurement.json"]


def object_paths(value, path=()):
    """Visit every record, including records nested inside lists."""
    if isinstance(value, dict):
        yield path
        for key, child in value.items():
            yield from object_paths(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from object_paths(child, (*path, index))


@pytest.mark.parametrize("location", list(object_paths(measurement_data())))
def test_an_unknown_field_anywhere_is_refused_naming_it(tmp_path, location):
    data = measurement_data()
    block = data
    for key in location:
        block = block[key]
    block["unexpected_field"] = "fictional"
    with pytest.raises(ValidationError) as caught:
        pilot.read_measurement(write_record(tmp_path, data))
    assert any(error["loc"] == (*location, "unexpected_field")
               and error["type"] == "extra_forbidden" for error in caught.value.errors())


@pytest.mark.parametrize("version", [0, 2, "1", True])
def test_an_unsupported_or_untyped_pilot_schema_is_refused_naming_it(tmp_path, version):
    data = measurement_data()
    data["identity"]["pilot_schema"] = version
    with pytest.raises(ValidationError, match="pilot_schema"):
        pilot.read_measurement(write_record(tmp_path, data))


@pytest.mark.parametrize("block", ["pilot_runs", "smoke_runs"])
@pytest.mark.parametrize("folder", [
    "/fictional/runs/off", "C:/Fictional/runs/off", r"C:\Fictional\runs\off",
    r"\\fictional-host\share\off", "//fictional-host/share/off", r"\fictional\off",
    "C:fictional/off",
])
def test_run_folders_must_be_relative_on_every_platform(tmp_path, block, folder):
    data = measurement_data()
    data[block][0]["folder"] = folder
    with pytest.raises(ValidationError) as caught:
        pilot.read_measurement(write_record(tmp_path, data))
    assert any(error["loc"] == (block, 0, "folder") for error in caught.value.errors())
    assert folder in str(caught.value) or repr(folder) in str(caught.value)


@pytest.mark.parametrize("folder", ["../pilot/off-1", "./off-1", r"..\pilot\off-1"])
def test_a_relative_folder_keeps_its_spelling(tmp_path, folder):
    data = measurement_data()
    data["pilot_runs"][0]["folder"] = folder
    measurement = pilot.read_measurement(write_record(tmp_path, data))
    assert measurement.pilot_runs[0].folder == folder


@pytest.mark.parametrize("jobs", [0, -1, "2", True])
def test_sizing_jobs_is_a_strict_positive_integer(tmp_path, jobs):
    data = measurement_data()
    data["sizing"]["jobs"] = jobs
    with pytest.raises(ValidationError, match="jobs"):
        pilot.read_measurement(write_record(tmp_path, data))


def test_unknown_projection_values_read_as_null_never_zero(tmp_path):
    data = measurement_data()
    projection = data["sizing"]["projected_wall_clock"]
    for field in ("off_run_s", "on_run_s", "study_s", "smoke_ratio",
                  "smoke_off_s", "smoke_on_s", "mean_tokens_per_minute"):
        projection[field] = None
    projection["unknown_packages"] = ["fict-core"]
    measurement = pilot.read_measurement(write_record(tmp_path, data))
    assert measurement.sizing.projected_wall_clock.model_dump() == projection


def test_sizing_digest_hashes_exactly_the_five_parsed_computed_blocks(tmp_path):
    data = measurement_data()
    measurement = pilot.read_measurement(write_record(tmp_path, data))
    expected = digest.canonical_sha256({block: data[block] for block in COMPUTED_BLOCKS})
    assert pilot.sizing_digest(measurement) == expected

    # Deliberately stale stored digests are read so compare can name its C-6 refusal.
    changed = deepcopy(data)
    changed["sizing_digest"] = "c" * 64
    changed["approval"] = {"approved": True, "approved_at": "2026-10-15"}
    assert pilot.sizing_digest(pilot.PilotMeasurement.model_validate(changed)) == expected


@pytest.mark.parametrize(("block", "location", "replacement"), [
    ("identity", ("model",), "fict-model-2"),
    ("pilot_runs", (0, "repetition"), 3),
    ("smoke_runs", (0, "folder"), "other-smoke-off"),
    ("measured", ("beta_fit", "mu"), 0.6),
    ("sizing", ("projected_wall_clock", "study_s"), 300.5),
])
def test_a_change_to_each_computed_block_changes_its_digest(tmp_path, block, location, replacement):
    data = measurement_data()
    original = pilot.read_measurement(write_record(tmp_path, data))
    value = data[block]
    for key in location[:-1]:
        value = value[key]
    value[location[-1]] = replacement
    changed = pilot.read_measurement(write_record(tmp_path, data))
    assert pilot.sizing_digest(changed) != pilot.sizing_digest(original)


def reverse_keys(value):
    if isinstance(value, dict):
        return {key: reverse_keys(child) for key, child in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reverse_keys(child) for child in value]
    return value


def test_line_endings_and_key_order_do_not_change_the_digest(tmp_path):
    data = measurement_data()
    data["measured"]["never_detected"][0]["findings"][0]["title"] = "Fictional piñon"
    path = write_record(tmp_path, data)
    original = pilot.sizing_digest(pilot.read_measurement(path))
    path = write_record(tmp_path, reverse_keys(data), newline="\r\n")
    assert b"\r\n" in path.read_bytes()
    assert pilot.sizing_digest(pilot.read_measurement(path)) == original


def test_approval_defaults_to_unapproved_when_built_or_read(tmp_path):
    data = measurement_data()
    del data["approval"]
    for measurement in (
        pilot.PilotMeasurement.model_validate(data),
        pilot.read_measurement(write_record(tmp_path, data)),
    ):
        assert measurement.approval.model_dump() == {"approved": False, "approved_at": None}


def test_beta_fit_removes_binomial_noise_before_fitting_moments():
    """P-1: identical observed rates have no spread after the correction."""
    fitted = pilot.beta_fit({"fict-a/D-1": (1, 2), "fict-b/D-1": (2, 4)})
    assert fitted.mu == 0.5
    assert fitted.distribution == "constant"


def test_pilot_command_is_registered():
    """P-5/P-6: the measurement command is part of the benchmark group."""
    from typer.testing import CliRunner

    from swreview.cli import app

    result = CliRunner().invoke(app, ["benchmark", "pilot", "--help"])
    assert result.exit_code == 0, result.output
    assert "--smoke" in result.output


def test_beta_moments_recover_simulated_rates_and_shrink_each_named_defect():
    """P-1: the experiment here generates independent Beta/binomial observations."""
    rng = np.random.default_rng(239)
    rates = rng.beta(2, 5, 20000)
    observed = rng.binomial(20, rates)
    counts = {f"case-{i}/D-1": (int(x), 20) for i, x in enumerate(observed)}
    fit = pilot.beta_fit(counts)
    assert fit.distribution == "beta"
    assert fit.a == pytest.approx(2, rel=0.05)
    assert fit.b == pytest.approx(5, rel=0.05)
    shrunk = pilot.shrunk_rates(counts, fit)
    for name in list(counts)[:3]:
        x, n = counts[name]
        assert shrunk[name] == pytest.approx((fit.a + x) / (fit.a + fit.b + n))


def test_beta_limits_and_one_or_zero_counted_runs_are_explicit():
    constant = pilot.beta_fit({"a": (1, 2), "b": (2, 4)})
    assert constant.distribution == "constant"
    assert pilot.shrunk_rates({"a": (1, 2), "b": (2, 4)}, constant) == {"a": 0.5, "b": 0.5}
    polar = pilot.beta_fit({"a": (0, 3), "b": (3, 3)})
    assert polar.distribution == "polarised"
    assert polar.mu == 0.5
    sparse = pilot.beta_fit({"zero": (0, 0), "once": (1, 1), "twice": (0, 2)})
    assert sparse.mu == pytest.approx(1 / 3)
    assert sparse.variance is None
    assert sparse.variance_computable is False
    assert sparse.distribution == "constant"
    assert "fewer than two" in sparse.reason


def test_beta_shrinkage_keeps_a_zero_count_defect_at_the_prior_mean():
    fit = pilot.BetaFit(mu=2 / 7, variance=0.02, variance_computable=True,
                        distribution="beta", a=2, b=5, reason=None)
    rates = pilot.shrunk_rates({"observed": (1, 3), "missing": (0, 0)}, fit)
    assert rates == {"observed": 0.3, "missing": 2 / 7}


@pytest.mark.parametrize(("counts", "mean", "variance", "distribution", "k"), [
    ([0, 0, 0, 8], 2, 16, "negative_binomial", 2 / 7),
    ([1, 1, 1], 1, 0, "poisson", None),
    ([0, 0, 0], 0, 0, "poisson", None),
])
def test_false_alarm_fit_uses_the_stated_moments(counts, mean, variance, distribution, k):
    fit = pilot.false_alarm_fit(counts)
    assert fit.mean == mean
    assert fit.variance == variance
    assert fit.distribution == distribution
    assert fit.k == pytest.approx(k) if k is not None else fit.k is None


def simulated_vectors(sd, seed):
    """P-2 creates vectors in the test; default simulator draws stay unchanged (115A).

    All 34 defects have a known marginal rate .5. Each adjacent pair belongs to one
    package and shares one independently drawn shock per run. The Gaussian symmetry
    gives intercept zero without calling the production intercept implementation.
    """
    rng = np.random.default_rng(seed)
    shock = rng.normal(0, sd, (5, 17))
    probability = 1 / (1 + np.exp(-np.repeat(shock, 2, axis=1)))
    detected = rng.uniform(size=(5, 34)) < probability
    runs = [pane_run(f"off-{rep + 1}", "off", [
        PanePackage(f"core-{package:02d}", matched=tuple(
            f"D-{defect + 1}" for defect in range(2)
            if detected[rep, package * 2 + defect]
        )) for package in range(17)
    ]) for rep in range(5)]
    return verdict.study_stats(runs)


@pytest.mark.parametrize("sd", [0.0, 1.0])
def test_comovement_recovers_the_simulated_shock_with_one_grid_step(sd):
    sample = simulated_vectors(sd, 118)
    fit = pilot.BetaFit(mu=0.5, variance=0, variance_computable=True,
                        distribution="constant", a=None, b=None, reason="known common rate")
    result = pilot.comovement(sample, fit)
    assert [point.sd for point in result.grid] == list(np.arange(0, 2.51, 0.25))
    assert abs(result.estimate - sd) <= 0.25
    maximum = max(point.log_likelihood for point in result.grid)
    allowed = [point.sd for point in result.grid
               if 2 * (maximum - point.log_likelihood) <= 1.6424]
    assert result.used == max(allowed)
    assert result.used >= result.estimate


def test_comovement_reads_only_the_named_arm_and_refuses_absent_vectors():
    off = simulated_vectors(0, 118)
    on = simulated_vectors(2, 118)
    fit = pilot.beta_fit(pilot.defect_counts(off, "off"))
    both = replace(
        off,
        detections=np.concatenate((off.detections[:, :1], on.detections[:, :1]), axis=1),
        counted_runs=np.concatenate((off.counted_runs[:, :1], on.counted_runs[:, :1]), axis=1),
        package_run_detections=verdict.PackageRunDetections(
            detected=np.concatenate((off.package_run_detections.detected[:, :1],
                                     on.package_run_detections.detected[:, :1]), axis=1),
            counted=np.concatenate((off.package_run_detections.counted[:, :1],
                                    on.package_run_detections.counted[:, :1]), axis=1),
        ),
    )
    assert pilot.comovement(both, fit) == pilot.comovement(off, fit)
    assert pilot.comovement(both, fit, "on") != pilot.comovement(both, fit)
    with pytest.raises(ValueError, match="package_run_detections"):
        pilot.comovement(replace(off, package_run_detections=None), fit)


def keyed_folders(tmp_path, monkeypatch, *, packages=None, reps=3):
    """Fictional scorecards and sessions, with real format-2 keys and saved sets."""
    monkeypatch.setattr(sets, "REPO_ROOT", tmp_path)
    if packages is None:
        packages = (PanePackage("core", matched=("D-1",)),
                    PanePackage("twin", model_held_out=(), matched=()))
    folders = write_pane_study(tmp_path / "pilot", [
        pane_run(f"off-{rep}", "off", packages) for rep in range(1, reps + 1)
    ])
    smoke = write_pane_study(tmp_path / "smoke", [
        pane_run(f"{arm}-1", arm, packages) for arm in ("off", "on")
    ])
    keys = {}
    for package in packages:
        key = write_key(tmp_path / "benchmarks" / "answer_keys", package.package_id,
                        known_defects=[{
                            "id": defect, "check": "hygiene.revision_present",
                            "tag": tag, "producer": producer,
                            "component_ids": [f"cmp:{number:04d}"],
                        } for number, (producer, tag, defect) in enumerate(
                            [("model", "held_out", d) for d in package.model_held_out]
                            + [("code", "held_out", d) for d in package.code_held_out]
                            + [("model", "tuned_on", d) for d in package.model_tuned_on]
                            + [("code", "tuned_on", d) for d in package.code_tuned_on], start=1)],
                        key_only=True)
        keys[package.package_id] = key
    for folder in (*folders, *smoke):
        saved = json.loads((folder / "benchmark-set.json").read_bytes())
        for entry in saved["packages"]:
            entry["key"] = keys[entry["package_id"]].relative_to(tmp_path).as_posix()
            if entry["package_id"] == "twin":
                entry["twin_of"] = "core"
            elif entry["package_id"].endswith("-twin"):
                entry["twin_of"] = entry["package_id"].removesuffix("-twin")
        set_file = folder / "benchmark-set.json"
        set_file.write_text(json.dumps(saved), encoding="utf-8")
        provenance = json.loads((folder / "run-provenance.json").read_bytes())
        provenance["set_digest"] = digest.sha256_of(set_file)
        (folder / "run-provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    return folders, smoke


def invoke_pilot(folders, smoke, out, *options):
    from typer.testing import CliRunner

    from swreview.cli import app

    arguments = ["benchmark", "pilot", *map(str, folders)]
    for folder in smoke:
        arguments.extend(("--smoke", str(folder)))
    arguments.extend(("--out", str(out), "--seed", "239", "--cap", "3", *options))
    return CliRunner().invoke(app, arguments)


def invoke_records(monkeypatch, records, smoke, out, *options):
    """Exercise the command with mutated views of genuinely loaded fictional folders."""
    calls = []

    def run_records(folders, **kwargs):
        calls.append(list(folders))
        return records if list(folders) == [record.folder for record in records] else smoke

    monkeypatch.setattr(compare, "run_records", run_records)
    result = invoke_pilot([record.folder for record in records],
                          [record.folder for record in smoke], out, *options)
    assert len(calls) == 2
    return result


def small_search(monkeypatch, *, growth=0, power=0.82, reached=True):
    """P-11's orchestration gets a known result; estimator and small-search tests are real."""
    calls = []

    def search(scenario, **kwargs):
        calls.append((scenario, kwargs))
        layout = kwargs["layout"].grown(growth)
        size = simulate.SizeResult(
            reps=3, packages=layout.package_count, defects=layout.defects,
            growth_units=growth, alpha=0.02, power_proportional=power, power_room=0.84,
            identical_loss=0.01, identical_loss_upper=0.02,
            no_loss_at_drop=0.01, no_loss_at_drop_upper=0.02,
        )
        return simulate.SearchResult((size,), size if reached else None, False,
                                     "fictional named only", 0.25,
                                     "reached" if reached else "not reached")

    monkeypatch.setattr(simulate, "search", search)
    return calls


def test_layout_reads_saved_order_and_a_core_with_its_named_twin(tmp_path, monkeypatch):
    folders, _ = keyed_folders(tmp_path, monkeypatch)
    layout = pilot.study_layout(compare.run_records(folders))
    assert layout.packages == (2, 0)
    assert layout.growth_unit == (2, 0)


@pytest.mark.parametrize(("jobs", "seconds"), [(1, 110), (2, 60), (3, 40), (5, 40), (8, 40)])
def test_projection_uses_list_scheduling_and_alternates_complete_runs(jobs, seconds):
    projection = pilot.project_wall_clock(
        dict(zip(("a", "b", "c", "d", "e"), (10, 40, 20, 30, 10), strict=True)),
        on_ratio=0.5, jobs=jobs, repetitions=3, growth=0,
    )
    assert projection.off_run_s == seconds
    assert projection.on_run_s == seconds / 2
    assert projection.study_s == 3 * seconds * 1.5


def test_projection_growth_uses_the_mean_and_missing_times_stay_unknown():
    grown = pilot.project_wall_clock({"core": 10, "twin": 30}, on_ratio=2,
                                     jobs=1, repetitions=3, growth=2)
    assert grown.off_run_s == 80
    assert grown.on_run_s == 160
    missing = pilot.project_wall_clock({"core": None, "twin": 30}, on_ratio=2,
                                      jobs=1, repetitions=3, growth=0)
    assert missing.off_run_s is None
    assert missing.on_run_s is None
    assert missing.study_s is None
    assert missing.unknown_packages == ["core"]


@pytest.mark.parametrize("growth", [0, 1])
def test_command_writes_the_cost_gate_and_unapproved_relative_atomic_record(
    tmp_path, monkeypatch, growth,
):
    folders, smoke = keyed_folders(tmp_path, monkeypatch)
    calls = small_search(monkeypatch, growth=growth)
    from swreview import atomic
    writes = []
    real_write = atomic.write_atomic

    def write(path, data):
        writes.append(path)
        return real_write(path, data)

    monkeypatch.setattr(atomic, "write_atomic", write)
    # The source may import the writer directly; patch that public seam as well.
    if hasattr(pilot, "write_atomic"):
        monkeypatch.setattr(pilot, "write_atomic", write)
    out = tmp_path / "pilot" / "pilot-measurement.json"
    result = invoke_pilot(folders, smoke, out, "--jobs", "2")
    assert result.exit_code == 0, result.output
    measurement = pilot.read_measurement(out)
    assert writes == [out]
    assert measurement.approval.model_dump() == {"approved": False, "approved_at": None}
    assert measurement.sizing_digest == pilot.sizing_digest(measurement)
    assert local_paths.scan_file(out) == []
    assert measurement.sizing.pilot_packages == ["core", "twin"]
    assert measurement.sizing.growth_units == growth
    assert measurement.sizing.jobs == 2
    assert measurement.sizing.result.packages == 2 + 2 * growth
    assert len(calls) == 1
    assert calls[0][1]["cap"] == 3
    assert calls[0][1]["seed"] == 239
    assert {run.folder for run in measurement.pilot_runs} == {f"off-{rep}" for rep in (1, 2, 3)}
    assert {run.folder for run in measurement.smoke_runs} == {"../smoke/off-1", "../smoke/on-1"}
    for text in ("repetitions", "alpha", "cleared", "stress", "cost", "wall", "growth", "rules"):
        assert text in result.output.lower()
    assert "6" in result.output  # six package runs have synthetic/unknown monetary cost
    assert measurement.measured.cost_time.unknown_cost_count == 6
    assert {row.package_id for row in measurement.measured.cost_time.unknown_cost_runs} == {
        "core", "twin",
    }
    assert "core" in result.output and "twin" in result.output


def test_never_detected_uses_the_key_loader_and_target_overlap_for_any_final_finding(
    tmp_path, monkeypatch,
):
    folders, _ = keyed_folders(tmp_path, monkeypatch, packages=(
        PanePackage("core", matched=()), PanePackage("twin", model_held_out=(), matched=()),
    ))
    records = compare.run_records(folders)
    key_file = tmp_path / "benchmarks" / "answer_keys" / "core.json"
    data = json.loads(key_file.read_bytes())
    data["known_defects"][1]["component_ids"] = []
    data["known_defects"][1]["document_ids"] = ["doc:1"]
    key_file.write_text(json.dumps(data), encoding="utf-8")
    findings = [
        make_finding(finding_id="F-001", check="rms.folders.present", status="unresolved",
                     coverage_limits=["fictional missing evidence"]),
        make_finding(finding_id="F-002", check="hygiene.description_present",
                     component_ids=[], document_ids=["doc:1"]),
        make_finding(finding_id="F-003", component_ids=["cmp:0002"]),
    ]
    records = [replace(record, sessions={
        **record.sessions,
        "core": record.sessions["core"].model_copy(update={"findings": findings}),
    }) for record in records]
    loaded, compared = [], []
    real_load, real_overlap = answer_key.load_answer_key, matching.targets_overlap

    def load(path, **kwargs):
        loaded.append(path)
        return real_load(path, **kwargs)

    def overlap(finding, entry):
        compared.append((finding.id, entry.id))
        return real_overlap(finding, entry)

    monkeypatch.setattr(answer_key, "load_answer_key", load)
    monkeypatch.setattr(matching, "targets_overlap", overlap)
    sample = verdict.study_stats([record.study_run for record in records])
    result = pilot.never_detected(records, sample)
    by_id = {row.defect_id: row for row in result}
    assert set(by_id) == {"D-1", "D-2"}
    assert [finding.finding_id for finding in by_id["D-1"].findings] == ["F-001"] * 3
    assert [finding.finding_id for finding in by_id["D-2"].findings] == ["F-002"] * 3
    assert loaded and key_file in loaded
    assert ("F-001", "D-1") in compared and ("F-002", "D-2") in compared


def test_never_detected_includes_held_out_code_defects_and_leaves_out_tuned_on(
    tmp_path, monkeypatch,
):
    packages = (
        PanePackage("core", matched=("D-1", "D-2"),
                    code_held_out=("D-3",), code_tuned_on=("D-4",)),
        PanePackage("twin", model_held_out=(), matched=()),
    )
    folders, _ = keyed_folders(tmp_path, monkeypatch, packages=packages)
    records = compare.run_records(folders)
    sample = verdict.study_stats([record.study_run for record in records])
    result = pilot.never_detected(records, sample)
    assert {(item.package_id, item.defect_id) for item in result} == {("core", "D-3")}


def test_measure_names_zero_and_one_count_defects_without_dividing_by_zero(tmp_path, monkeypatch):
    packages = (PanePackage("core"), PanePackage("once"), PanePackage("zero"),
                PanePackage("twin", model_held_out=(), matched=()),
                PanePackage("once-twin", model_held_out=(), matched=()),
                PanePackage("zero-twin", model_held_out=(), matched=()))
    folders, smoke = keyed_folders(tmp_path, monkeypatch, packages=packages)
    records = compare.run_records(folders)
    adjusted = []
    for rep, record in enumerate(records):
        sparse = [replace(package, status="behavioural")
                  if package.package_id == "zero" or (package.package_id == "once" and rep)
                  else package for package in packages]
        adjusted.append(replace(record, study_run=pane_run(record.study_run.run, "off", sparse)))
    small_search(monkeypatch)
    out = tmp_path / "measurement.json"
    result = invoke_records(monkeypatch, adjusted, compare.run_records(smoke), out)
    assert result.exit_code == 0, result.output
    measurement = pilot.read_measurement(out)
    measured = measurement.measured
    assert {(row.package_id, row.defect_id) for row in measured.dropped_defects} == {
        ("zero", "D-1"), ("zero", "D-2"),
    }
    assert measured.dropped_defect_count == 2
    assert {(row.package_id, row.defect_id) for row in measured.variance_excluded_defects} == {
        ("once", "D-1"), ("once", "D-2"),
    }
    assert measured.variance_excluded_count == 2
    counts = {(row.package_id, row.defect_id): (row.x, row.n) for row in measured.defect_counts}
    assert counts["once", "D-1"] == (1, 1)
    assert counts["zero", "D-1"] == (0, 0)
    assert measurement.sizing.projected_wall_clock.off_run_s is None
    assert measurement.sizing.projected_wall_clock.unknown_packages == ["zero"]


def test_other_estimators_share_verdict_counts_and_keep_individual_rates(tmp_path, monkeypatch):
    packages = (PanePackage("core", code_held_out=("D-3", "D-4")),
                PanePackage("twin", model_held_out=(), matched=()))
    folders, smoke = keyed_folders(tmp_path, monkeypatch, packages=packages)
    records = compare.run_records(folders)
    adjusted = []
    for rep, record in enumerate(records):
        core = replace(packages[0], matched=("D-1", "D-3", "D-4") if rep < 2 else (),
                       cleared=("D-2", "D-4") if rep == 0 else (),
                       score_overrides={
                           "wall_clock_s": 10 + rep * 10,
                           "cost": {"amount": rep + 1, "missing": [],
                                    "basis": ["fictional price"], "synthetic": False},
                       })
        twin = replace(packages[1], status="behavioural" if rep == 0 else "completed",
                       score_overrides={"wall_clock_s": 40})
        adjusted.append(replace(
            record, study_run=pane_run(record.study_run.run, "off", [core, twin]),
        ))
    calls = small_search(monkeypatch)
    out = tmp_path / "measurement.json"
    result = invoke_records(monkeypatch, adjusted, compare.run_records(smoke), out)
    assert result.exit_code == 0, result.output
    measurement = pilot.read_measurement(out)
    measured = measurement.measured
    assert {(row.defect_id, row.x, row.n) for row in measured.code_defects} == {
        ("D-3", 2, 3), ("D-4", 2, 3),
    }
    assert measured.stops.model_dump() == {"x": 1, "n": 6}
    clear = next(row for row in measured.clearances if row.defect_id == "D-2")
    assert (clear.x, clear.n) == (1, 3)
    assert measured.cost_time.mean_wall_clock_s == 28
    assert measured.cost_time.mean_cost == 2
    assert measurement.sizing.result.estimated_study_cost == 24
    assert calls[0][0].code_rate == (2 / 3, 2 / 3)
    assert calls[0][0].clearance_rate == (0, 1 / 3, 0, 1 / 3)
    # A stopped and an infrastructure package add neither code detections nor counted runs.
    extra = [pane_run("off-4", "off", [replace(packages[0], status="behavioural")]),
             pane_run("off-5", "off", [replace(packages[0], status="infrastructure")])]
    sample = verdict.study_stats([record.study_run for record in adjusted] + extra)
    assert sample.code_runs[0, 0].tolist() == [3, 3]
    assert sample.code_detections[0, 0].tolist() == [2, 2]


@pytest.mark.parametrize("approved", [False, True])
def test_existing_output_is_refused_without_loading_or_changing_anything(
    tmp_path, monkeypatch, approved,
):
    out = tmp_path / "pilot-measurement.json"
    original = json.dumps({"approval": {"approved": approved}}).encode()
    out.write_bytes(original)

    def forbidden(*args, **kwargs):
        pytest.fail("an existing output must refuse before loading runs")

    monkeypatch.setattr(compare, "run_records", forbidden)
    result = invoke_pilot([tmp_path / "missing"], [tmp_path / "a", tmp_path / "b"], out)
    assert result.exit_code == 1
    message = (f"{out} exists: one study has one measurement; "
               "delete the unapproved file to size again")
    assert message in result.output
    assert out.read_bytes() == original
    assert list(tmp_path.iterdir()) == [out]


@pytest.mark.parametrize("case", [
    "on", "other-study", "one-repetition", "unscored", "mixed-commits", "keyless",
])
def test_pilot_command_refuses_each_invalid_pilot_input(tmp_path, monkeypatch, case):
    folders, smoke = keyed_folders(tmp_path, monkeypatch)
    expected = case
    if case == "on":
        folders = [smoke[1]]
        expected = "off"
    elif case == "other-study":
        for folder in folders:
            path = folder / "run-provenance.json"
            data = json.loads(path.read_bytes())
            data["lever"] = "parallel_tool_calls"
            path.write_text(json.dumps(data), encoding="utf-8")
        expected = "pane_defaults"
    elif case == "one-repetition":
        folders = folders[:1]
        expected = "co-movement needs at least two runs of a package"
    elif case == "unscored":
        card = json.loads((folders[0] / "scorecard.json").read_bytes())
        card["unscored_packages"] = [{
            "package_id": "core", "kind": "infrastructure", "class": "provider_error",
            "error_class": "FictionalFailure", "attempts": 1, "folder": "attempts/core/1",
            "graded_items": card["per_package"][0]["graded_items"],
        }]
        (folders[0] / "scorecard.json").write_text(json.dumps(card), encoding="utf-8")
        expected = "unscored"
    elif case == "mixed-commits":
        path = folders[1] / "run-provenance.json"
        data = json.loads(path.read_bytes())
        data["commit"] = "different-fictional-commit"
        path.write_text(json.dumps(data), encoding="utf-8")
        expected = "commit"
    elif case == "keyless":
        for folder in (*folders, *smoke):
            path = folder / "benchmark-set.json"
            data = json.loads(path.read_bytes())
            for entry in data["packages"]:
                del entry["key"]
            path.write_text(json.dumps(data), encoding="utf-8")
            provenance = folder / "run-provenance.json"
            data = json.loads(provenance.read_bytes())
            data["set_digest"] = digest.sha256_of(path)
            provenance.write_text(json.dumps(data), encoding="utf-8")
        expected = "--answer-keys"
    out = tmp_path / "pilot-measurement.json"
    result = invoke_pilot(folders, smoke, out)
    assert result.exit_code == 1, result.output
    assert expected in result.output
    assert not out.exists()


@pytest.mark.parametrize("count", [0, 1, 3])
def test_smoke_must_be_given_exactly_twice(tmp_path, monkeypatch, count):
    folders, smoke = keyed_folders(tmp_path, monkeypatch)
    result = invoke_pilot(folders, (smoke * 2)[:count], tmp_path / "measurement.json")
    assert result.exit_code == 1
    assert "--smoke" in result.output


def test_jobs_below_one_is_a_usage_error(tmp_path):
    result = invoke_pilot([tmp_path / "off"], [tmp_path / "a", tmp_path / "b"],
                          tmp_path / "measurement.json", "--jobs", "0")
    assert result.exit_code == 2
    assert "--jobs" in result.output


@pytest.mark.parametrize("field", ["arm", "lever", "provider", "model", "effort", "commit",
                                   "saved_set", "unscored_packages", "kept"])
def test_smoke_refusals_name_the_folder_and_field(tmp_path, monkeypatch, field):
    folders, smoke_folders = keyed_folders(tmp_path, monkeypatch)
    records, smoke = compare.run_records(folders), compare.run_records(smoke_folders)
    bad = smoke[1]
    if field == "arm":
        bad = replace(bad, provenance=bad.provenance.model_copy(update={"arm": "off"}))
    elif field in {"lever", "provider", "model", "effort", "commit"}:
        bad = replace(bad, provenance=bad.provenance.model_copy(update={field: "fictional-other"}))
    elif field == "saved_set":
        entry = bad.saved_set.packages[0].model_copy(update={"package_id": "not-in-pilot"})
        bad = replace(bad, saved_set=bad.saved_set.model_copy(update={"packages": [entry]}))
    else:
        card = bad.study_run.scorecard
        if field == "unscored_packages":
            unscored = pane_run("on-1", "on", [PanePackage("core", status="infrastructure")])
            card = card.model_copy(update={
                "unscored_packages": unscored.scorecard.unscored_packages,
            })
        else:
            card = card.model_copy(update={"per_package": card.per_package[:1]})
        bad = replace(bad, study_run=replace(bad.study_run, scorecard=card))
    result = invoke_records(monkeypatch, records, [smoke[0], bad], tmp_path / "measurement.json")
    assert result.exit_code == 1
    assert str(bad.folder) in result.output
    expected = {"saved_set": "package", "unscored_packages": "unscored",
                "kept": "kept"}.get(field, field)
    assert expected in result.output


def test_smoke_is_a_time_input_only_and_projection_records_its_sums(tmp_path, monkeypatch):
    folders, smoke_folders = keyed_folders(tmp_path, monkeypatch)
    records, smoke = compare.run_records(folders), compare.run_records(smoke_folders)
    small_search(monkeypatch)
    first = tmp_path / "original.json"
    original_result = invoke_records(monkeypatch, records, smoke, first)
    assert original_result.exit_code == 0, original_result.output
    original = pilot.read_measurement(first)
    changed = []
    for record in smoke:
        scores = [score.model_copy(update={
            "wall_clock_s": 10 if record.study_run.arm == "off" else 5,
            "matched_defect_ids": [], "flagged_defect_ids": [],
            "cleared_defect_ids": ["D-1"], "false_alarm_finding_ids": [],
        })
                  for score in record.study_run.scorecard.per_package]
        card = record.study_run.scorecard.model_copy(update={"per_package": scores})
        changed.append(replace(record, study_run=replace(record.study_run, scorecard=card)))
    out = tmp_path / "changed.json"
    invocation = invoke_records(monkeypatch, records, changed, out, "--jobs", "2")
    assert invocation.exit_code == 0, invocation.output
    result = pilot.read_measurement(out)
    assert result.measured == original.measured
    projection = result.sizing.projected_wall_clock
    assert projection.smoke_off_s == 20
    assert projection.smoke_on_s == 10
    assert projection.smoke_ratio == 0.5
    assert projection.off_run_s == 500
    assert projection.on_run_s == 250
    assert projection.study_s == 2250
    assert projection.mean_tokens_per_minute == pytest.approx((400000 + 18000) / 500 * 60)


def test_pilot_and_simulator_import_no_compare_module():
    for module in (pilot, simulate):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "swreview.benchmark.compare"
                if node.module == "swreview.benchmark":
                    assert "compare" not in {alias.name for alias in node.names}
            elif isinstance(node, ast.Import):
                assert "swreview.benchmark.compare" not in {alias.name for alias in node.names}


def test_pilot_simulator_can_clear_a_held_out_code_defect_with_its_own_rate():
    scenario = simulate.Scenario(
        "pilot-code-clearance", "half", 0, 0, None,
        code_count=1, code_rate=(1.0,), clearance_count=3, clearance_rate=(0.0, 0.0, 1.0),
    )
    sample = simulate.draw_studies(scenario, seed=239, sims=2, reps=3,
                                   layout=simulate.Layout((2,), (2, 0)))
    assert sample.clears.shape == (2, 2, 3)
    assert np.all(sample.clears[..., :2] == 0)
    assert np.all(sample.clears[..., 2] == 3)


def test_pilot_simulator_can_keep_clear_only_targets_without_code_detection_estimates():
    scenario = simulate.Scenario(
        "pilot-clear-only", "half", 0, 0, None,
        clearance_count=3, clearance_rate=(0.0, 0.0, 1.0),
    )
    sample = simulate.draw_studies(scenario, seed=239, sims=2, reps=3,
                                   layout=simulate.Layout((2,), (2, 0)))
    assert sample.code_runs.shape[-1] == 0
    assert sample.clears.shape == (2, 2, 3)
    assert sample.clear_held_out.tolist() == [True, True, True]
    assert np.all(sample.clears[..., 2] == 3)


@pytest.mark.parametrize(("field", "values"), [
    ("code_rate", (0.2,)), ("clearance_rate", (0.2,)),
    ("code_rate", (-0.2, 0.2)), ("clearance_rate", (0.2, 1.2)),
])
def test_pilot_simulator_refuses_bad_individual_probability_vectors(field, values):
    kwargs = {"code_count": 2, "clearance_count": 2, field: values}
    with pytest.raises(ValueError, match=field):
        simulate.Scenario("pilot-invalid", "half", 0, 0, None, **kwargs)


def test_command_prints_not_reached_when_last_alpha_has_insufficient_power(tmp_path, monkeypatch):
    folders, smoke = keyed_folders(tmp_path, monkeypatch)
    small_search(monkeypatch, power=0.79, reached=False)
    result = invoke_pilot(folders, smoke, tmp_path / "measurement.json")
    assert result.exit_code == 0, result.output
    assert "not reached" in result.output


def test_growth_projection_uses_core_and_twin_mean_without_anchor_times(tmp_path, monkeypatch):
    packages = (
        PanePackage("core", score_overrides={"wall_clock_s": 10}),
        PanePackage("twin", model_held_out=(), matched=(), score_overrides={"wall_clock_s": 30}),
        PanePackage("anchor", model_held_out=(), matched=(),
                    score_overrides={"wall_clock_s": 1000}),
    )
    folders, smoke = keyed_folders(tmp_path, monkeypatch, packages=packages)
    small_search(monkeypatch, growth=1)
    out = tmp_path / "measurement.json"
    result = invoke_pilot(folders, smoke, out)
    assert result.exit_code == 0, result.output
    projection = pilot.read_measurement(out).sizing.projected_wall_clock
    assert projection.off_run_s == 1080  # 10 + 30 + 1000 + two growth packages at 20
    assert projection.on_run_s == 1080
    assert projection.study_s == 6480


def test_measured_inputs_feed_a_real_small_seeded_search(tmp_path, monkeypatch):
    folders, smoke = keyed_folders(tmp_path, monkeypatch)
    calls = small_search(monkeypatch)
    result = invoke_pilot(folders, smoke, tmp_path / "measurement.json")
    assert result.exit_code == 0, result.output
    scenario = calls[0][0]
    # Starting at the permitted upper size gives one real size evaluation. This
    # checks fitted value inputs and judge integration without a full size sweep.
    monkeypatch.undo()
    searched = simulate.search(scenario, seed=239, sims=8, cap=3,
                               layout=simulate.Layout((2,) * 100, (2, 0)))
    assert len(searched.tried) == 1
    assert searched.tried[0].defects == 200
    assert searched.tried[0].reps == 3


def test_never_detected_findings_keep_distinct_folders_with_the_same_basename(
    tmp_path, monkeypatch,
):
    folders, smoke_folders = keyed_folders(tmp_path, monkeypatch)
    records = compare.run_records(folders)
    smoke = compare.run_records(smoke_folders)
    changed = []
    for parent, record in zip(("a", "b", "c"), records, strict=True):
        session = record.sessions["core"].model_copy(update={
            "findings": [make_finding(finding_id="F-001", component_ids=["cmp:0002"])],
        })
        changed.append(replace(
            record, folder=tmp_path / parent / "off",
            study_run=replace(record.study_run, run="off"),
            sessions={**record.sessions, "core": session},
        ))
    small_search(monkeypatch)
    out = tmp_path / "measurement.json"
    result = invoke_records(monkeypatch, changed, smoke, out)
    assert result.exit_code == 0, result.output
    measured = pilot.read_measurement(out).measured
    defect = next(item for item in measured.never_detected if item.defect_id == "D-2")
    assert {finding.run for finding in defect.findings} == {"a/off", "b/off", "c/off"}


def test_tried_sizes_keep_the_rules_used_before_the_final_cleared_guard_check(
    tmp_path, monkeypatch,
):
    folders, smoke = keyed_folders(tmp_path, monkeypatch)
    small_search(monkeypatch)
    named_search = simulate.search

    def search(scenario, **kwargs):
        named = named_search(scenario, **kwargs)
        deciding = replace(named.result, power_proportional=0.9)
        return replace(named, result=deciding, cleared_guard_decides=True)

    monkeypatch.setattr(simulate, "search", search)
    out = tmp_path / "measurement.json"
    result = invoke_pilot(folders, smoke, out)
    assert result.exit_code == 0, result.output
    sizing = pilot.read_measurement(out).sizing
    assert sizing.tried[0].cleared_guard_decides is False
    assert sizing.tried[0].simulated.power_proportional == 0.82
    assert sizing.result.cleared_guard_decides is True
    assert sizing.result.simulated.power_proportional == 0.9


def test_stopped_code_package_keeps_its_clearance_without_inventing_detection_rate(
    tmp_path, monkeypatch,
):
    packages = (
        PanePackage("core"), PanePackage("twin", model_held_out=(), matched=()),
        PanePackage("code-only", model_held_out=(), code_held_out=("D-1",),
                    matched=(), cleared=("D-1",), status="behavioural"),
    )
    folders, smoke = keyed_folders(tmp_path, monkeypatch, packages=packages)
    calls = small_search(monkeypatch)
    out = tmp_path / "measurement.json"
    result = invoke_pilot(folders, smoke, out)
    assert result.exit_code == 0, result.output
    measured = pilot.read_measurement(out).measured
    code = next(row for row in measured.code_defects if row.package_id == "code-only")
    assert (code.x, code.n) == (0, 0)
    cleared = next(row for row in measured.clearances if row.package_id == "code-only")
    assert (cleared.x, cleared.n) == (3, 3)
    assert calls[0][0].code_count == 0
    assert calls[0][0].clearance_rate == (1, 0, 0)
