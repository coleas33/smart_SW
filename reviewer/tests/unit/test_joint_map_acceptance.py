"""User Story 2 on the shaped fixtures: the joints are found by code (feature 010 T029).

`contracts/joint-map.md` section 9 is the number every assertion here pins, and the whole
foundational map of the big fixture is a golden, so a change to any gate, rule or id moves a
file a reviewer can read (plan RK-1). Research R4 names the recorded review's three alignment
pairs; per instance two of them are real joints the old check compared on the wrong
instances, and the third is no joint at all.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
import yaml
from pytest_regressions.file_regression import FileRegressionFixture

from swreview.checks.joints import JointMap, build_joint_map, joint_label
from swreview.ir.loader import load_package
from swreview.prerun import prerun_checks
from swreview.tools.context import build_context
from swreview.tools.registry import ToolRegistry
from tests.support.prerun import ON

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mechanical"


@pytest.fixture(scope="module")
def big() -> JointMap:
    return build_joint_map(load_package(FIXTURES / "big-assembly").package)


def joints_between(joint_map: JointMap, first: str, second: str) -> list:
    return [
        joint
        for joint in joint_map.joints
        if {item.hole_id for item in joint.instances} == {first, second}
    ]


def test_the_big_fixture_map_is_contract_section_9(big: JointMap) -> None:
    assert len(big.instances) == 132
    assert sum(len(joint.pairs) for joint in big.joints) == 47
    assert len(big.joints) == 50
    assert len(big.pattern_groups()) == 11
    assert Counter(joint.kind for joint in big.joints) == {
        "screw": 47,
        "pin": 2,
        "unclassified": 1,
    }
    faceless = [gap.subject for gap in big.gaps if "no cylinder face" in gap.reason]
    assert faceless == ["hol:0007", "hol:0009"]


def test_45_screw_joints_come_from_hole_pairs_in_six_patterns(big: JointMap) -> None:
    pairs = Counter(
        tuple(sorted({item.hole_id for item in joint.instances}))
        for joint in big.joints
        if len(joint.instances) == 2 and joint.kind == "screw"
    )

    assert pairs == {
        ("hol:0014", "hol:0019"): 15,
        ("hol:0016", "hol:0023"): 16,
        ("hol:0015", "hol:0020"): 4,
        ("hol:0012", "hol:0024"): 4,
        ("hol:0004", "hol:0010"): 3,
        ("hol:0006", "hol:0011"): 3,
    }


def test_two_screw_joints_are_a_screw_face_in_a_lone_tapped_instance(big: JointMap) -> None:
    lone = {
        joint.instances[0].id: [member.component_id for member in joint.cylinders]
        for joint in big.joints
        if len(joint.instances) == 1 and joint.kind == "screw"
    }

    assert lone == {"hol:0013#1": ["cmp:0007"], "hol:0021#1": ["cmp:0008"]}


def test_the_two_dowel_joints_sit_at_0_000_and_0_750_mm(big: JointMap) -> None:
    pins = {
        tuple(item.id for item in joint.instances): joint.offset_mm
        for joint in big.joints
        if joint.kind == "pin"
    }

    assert pins == {("hol:0017#1", "hol:0027#1"): 0.0, ("hol:0018#1", "hol:0027#2"): 0.75}


def test_the_one_unclassified_joint_is_a_6_75_mm_cylinder_in_an_m8_counterbore(
    big: JointMap,
) -> None:
    [joint] = [joint for joint in big.joints if joint.kind == "unclassified"]

    assert [item.id for item in joint.instances] == ["hol:0025#2"]
    assert [member.diameter_mm for member in joint.cylinders] == [6.75]


def test_the_two_candidates_carry_the_values_they_were_judged_on(big: JointMap) -> None:
    assert [
        (candidate.members, candidate.reason, dict(candidate.values))
        for candidate in big.candidates
    ] == [
        (
            ("hol:0018#2", "hol:0024#1"),
            "overlap_near",
            {"angle_deg": 0.0, "offset_mm": 7.006, "radius_sum_mm": 6.05, "gap_mm": 0.0},
        ),
        (
            ("hol:0018#2", "hol:0027#1"),
            "assigned_elsewhere",
            {"angle_deg": 0.0, "offset_mm": 0.75, "radius_sum_mm": 3.05, "gap_mm": 0.0},
        ),
    ]


def test_thirteen_free_faces_on_parts_with_holes_are_excluded(big: JointMap) -> None:
    counts = [int(gap.reason.split()[0]) for gap in big.gaps if "cylinder faces on" in gap.reason]

    assert sum(counts) == 13


def test_the_recorded_reviews_three_pairs_per_instance(big: JointMap) -> None:
    """Research R4: two real joints the old check compared on the wrong instances, and one
    pair at 90 degrees that is no joint."""
    four_ten = joints_between(big, "hol:0004", "hol:0010")
    assert len(four_ten) == 3
    assert {joint.offset_mm for joint in four_ten} == {0.0}
    assert [joint.offset_mm for joint in joints_between(big, "hol:0017", "hol:0027")] == [0.0]
    assert joints_between(big, "hol:0010", "hol:0024") == []


def test_the_first_instance_pairs_far_apart_along_the_axis_are_nothing(big: JointMap) -> None:
    """1.576 and 3.950 mm apart laterally, 149.0 and 147.5 mm apart along the axis."""
    far = {("hol:0014#1", "hol:0023#1"), ("hol:0015#1", "hol:0019#1")}

    in_joints = {tuple(sorted(item.id for item in joint.instances)) for joint in big.joints}
    assert far.isdisjoint(in_joints)
    assert far.isdisjoint({tuple(sorted(candidate.members)) for candidate in big.candidates})


def test_the_foundational_map_matches_its_golden(
    big: JointMap, file_regression: FileRegressionFixture
) -> None:
    text = yaml.safe_dump(big.as_json(), sort_keys=False, width=100)

    file_regression.check(
        text, basename="big-assembly", extension=".yml", encoding="utf-8", newline="\n"
    )


def test_the_small_fixture_holds_one_pin_joint_and_no_hole_pair() -> None:
    joint_map = build_joint_map(load_package(FIXTURES / "small-assembly").package)

    [joint] = joint_map.joints
    assert joint.kind == "pin"
    assert joint.offset_mm == 0.0
    assert joint.pairs == ()
    assert [
        (member.component_id, member.diameter_mm, member.overlap_mm) for member in joint.cylinders
    ] == [("cmp:0003", 3.0, 8.475)]
    assert joint_map.candidates == ()


def test_a_screw_seated_in_bore_and_counterbore_is_named_once_in_its_joint_label(
    big: JointMap,
) -> None:
    """jnt:0007's screw has two member faces - its shank in the bore, its head in the
    counterbore - on one component; the label names the joint's parts, not its faces."""
    [joint] = joints_between(big, "hol:0012", "hol:0024")[:1]
    assert [member.component_id for member in joint.cylinders] == ["cmp:0061", "cmp:0061"]

    assert joint_label(joint) == "jnt:0007 hol:0012#1+hol:0024#1+cmp:0061"


def test_with_lever_5_on_check_joints_is_a_real_step_after_the_interference_groups() -> None:
    context = build_context(load_package(FIXTURES / "small-assembly"))
    dispatch = ToolRegistry().dispatch(context)

    result = prerun_checks(context, dispatch, efficiency=ON)

    assert result is not None
    tools = [call.tool for call in result.calls]
    # Edited deliberately by feature 010 T067 and T075: the two later code-first checks
    # follow `check_joints` in `CODE_FIRST_CHECKS` order.
    assert tools[-3:] == ["check_joints", "check_mass_material", "check_hygiene"]
    assert tools.index("check_joints") > max(
        index for index, tool in enumerate(tools) if tool == "check_interference_group"
    )
    steps = context.require_session().steps
    assert [step.tool for step in steps] == tools
    assert [step.status for step in steps[-3:]] == ["ok", "ok", "ok"]
