"""T228: the measurement's data contract; estimators arrive with the pilot slice."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from swreview.benchmark import digest, pilot

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
