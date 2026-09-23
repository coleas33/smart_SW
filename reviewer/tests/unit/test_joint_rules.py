"""The joint map's thresholds are data with a source each (feature 010 T008).

`checks/joint_rules.yaml` holds every number the joint map is judged on
(`contracts/joint-map.md` section 8): a joint, a candidate or a member recorded in a report
cites these values, so an engineer who disagrees with a gate changes one line of data, not
the code, and the loader refuses a file that could not be what anyone meant.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from swreview.checks.joints import DEFAULT_JOINT_RULES_PATH, JointRules, load_joint_rules

SECTION_8 = {
    "parallel_deg": 1.0,
    "adjacency_gap_mm": 1.0,
    "member_coaxial_mm": 0.2,
    "member_diameter_allowance_mm": 0.05,
    "origin_on_axis_mm": 0.2,
    "axis_aligned_deg": 0.1,
}
MARGINS = {"angle_deg": 1.0, "overlap_mm": 1.0, "gap_mm": 1.0}


def shipped() -> dict:
    return yaml.safe_load(DEFAULT_JOINT_RULES_PATH.read_text(encoding="utf-8"))


def write(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "joint_rules.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def test_the_shipped_rules_are_the_values_of_contract_section_8() -> None:
    rules = load_joint_rules()

    assert isinstance(rules, JointRules)
    assert rules.version == 1
    assert {name: getattr(rules, name) for name in SECTION_8} == SECTION_8
    assert (
        rules.candidate_angle_deg,
        rules.candidate_overlap_mm,
        rules.candidate_gap_mm,
    ) == (MARGINS["angle_deg"], MARGINS["overlap_mm"], MARGINS["gap_mm"])


def test_every_threshold_carries_its_source() -> None:
    rules = load_joint_rules()

    expected = {*SECTION_8, *(f"candidate_margin.{name}" for name in MARGINS)}
    assert set(rules.sources) == expected
    assert all(source.strip() for source in rules.sources.values())
    assert "Assumptions" in rules.sources["parallel_deg"]


@pytest.mark.parametrize("key", [*SECTION_8, "candidate_margin"])
def test_a_missing_key_is_refused_naming_it(tmp_path: Path, key: str) -> None:
    document = shipped()
    del document[key]

    with pytest.raises(ValueError, match=key):
        load_joint_rules(write(tmp_path, document))


def test_a_missing_margin_is_refused_naming_it(tmp_path: Path) -> None:
    document = shipped()
    del document["candidate_margin"]["gap_mm"]

    with pytest.raises(ValueError, match="candidate_margin.gap_mm"):
        load_joint_rules(write(tmp_path, document))


@pytest.mark.parametrize("key", ["adjacency_gap_mm", "member_coaxial_mm", "origin_on_axis_mm"])
def test_a_negative_value_is_refused_naming_it(tmp_path: Path, key: str) -> None:
    document = shipped()
    document[key]["value"] = -0.1

    with pytest.raises(ValueError, match=key):
        load_joint_rules(write(tmp_path, document))


@pytest.mark.parametrize("key", ["parallel_deg", "axis_aligned_deg"])
def test_an_angle_of_ninety_degrees_or_more_is_refused_naming_it(tmp_path: Path, key: str) -> None:
    document = shipped()
    document[key]["value"] = 90.0

    with pytest.raises(ValueError, match=key):
        load_joint_rules(write(tmp_path, document))


def test_a_margin_angle_that_would_reach_ninety_degrees_is_refused(tmp_path: Path) -> None:
    document = shipped()
    document["candidate_margin"]["angle_deg"]["value"] = 89.5

    with pytest.raises(ValueError, match="candidate_margin.angle_deg"):
        load_joint_rules(write(tmp_path, document))


def test_a_value_without_a_source_is_refused(tmp_path: Path) -> None:
    document = shipped()
    document["member_coaxial_mm"] = {"value": 0.2}

    with pytest.raises(ValueError, match="member_coaxial_mm"):
        load_joint_rules(write(tmp_path, document))


def test_an_unknown_key_is_refused_naming_it(tmp_path: Path) -> None:
    document = shipped()
    document["paralel_deg"] = {"value": 1.0, "source": "typo"}

    with pytest.raises(ValueError, match="paralel_deg"):
        load_joint_rules(write(tmp_path, document))


def test_the_loader_caches_per_resolved_path(tmp_path: Path) -> None:
    path = write(tmp_path, shipped())

    assert load_joint_rules(path) is load_joint_rules(path)
    assert load_joint_rules() is load_joint_rules(DEFAULT_JOINT_RULES_PATH)
