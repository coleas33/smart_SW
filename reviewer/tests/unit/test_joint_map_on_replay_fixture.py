"""The foundational joint map over feature 008's big-assembly replay fixture (feature 010 T096).

008's generator scrambles every identifying string of the recorded package and keeps its
structure - ids, numbers, the geometry (plan RK-1). So the joint map built from the replay
fixture must reproduce research R3's counts, the numbers `contracts/joint-map.md` section 9
pins on the synthetic big fixture: 132 instances, 47 kept pairs, 50 joints in 11 pattern
groups, and the two candidates. Where the two differ is where the synthetic fixture rounded a
number the recording carries (the candidates' gaps, which faces are free); those are pinned
here as the recording has them. Test only: nothing in the map changes for this fixture.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from swreview.checks.joints import JointMap, build_joint_map, joint_label
from swreview.ir.loader import load_package

REPLAY = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "big-assembly"


@pytest.fixture(scope="module")
def replay() -> JointMap:
    return build_joint_map(load_package(REPLAY).package)


def test_the_replay_map_reproduces_research_r3s_counts(replay: JointMap) -> None:
    assert len(replay.instances) == 132
    assert sum(len(joint.pairs) for joint in replay.joints) == 47
    assert len(replay.joints) == 50
    assert len(replay.pattern_groups()) == 11
    assert Counter(joint.kind for joint in replay.joints) == {
        "screw": 47,
        "pin": 2,
        "unclassified": 1,
    }


def test_45_screw_joints_come_from_hole_pairs_in_six_patterns(replay: JointMap) -> None:
    pairs = Counter(
        tuple(sorted({item.hole_id for item in joint.instances}))
        for joint in replay.joints
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


def test_two_screw_joints_are_a_screw_face_in_a_lone_tapped_instance(replay: JointMap) -> None:
    lone = [
        joint.instances[0].id
        for joint in replay.joints
        if joint.kind == "screw" and len(joint.instances) == 1
    ]

    assert sorted(lone) == ["hol:0013#1", "hol:0021#1"]


def test_the_two_pin_joints_and_the_unclassified_one(replay: JointMap) -> None:
    """The dowel plate's two instances each pair with one clevis hole: one at 0.000 mm and
    one at 0.750 mm; the 6.75 mm cylinder in `hol:0025#2` stays unclassified."""
    others = {joint_label(joint): joint for joint in replay.joints if joint.kind != "screw"}

    assert {label: joint.kind for label, joint in others.items()} == {
        "jnt:0047 hol:0017#1+hol:0027#2": "pin",
        "jnt:0048 hol:0018#1+hol:0027#1": "pin",
        "jnt:0050 hol:0025#2+cmp:0022": "unclassified",
    }
    assert others["jnt:0047 hol:0017#1+hol:0027#2"].offset_mm == 0.0
    assert others["jnt:0048 hol:0018#1+hol:0027#1"].offset_mm == 0.75
    [cylinder] = others["jnt:0050 hol:0025#2+cmp:0022"].cylinders
    assert cylinder.diameter_mm == 6.75


def test_the_two_candidates_are_listed_and_the_stacked_first_instances_are_not(
    replay: JointMap,
) -> None:
    """The first-instance pairs 1.576 and 3.950 mm apart (the A-B stack) are neither joints
    nor candidates: only these two pairs are listed for the engineer."""
    listed = [
        (candidate.members, candidate.reason, dict(candidate.values))
        for candidate in replay.candidates
    ]

    assert listed == [
        (
            ("hol:0018#2", "hol:0024#1"),
            "overlap_near",
            {"angle_deg": 0.0, "offset_mm": 7.006187, "radius_sum_mm": 6.05, "gap_mm": 0.025},
        ),
        (
            ("hol:0018#2", "hol:0027#1"),
            "assigned_elsewhere",
            {"angle_deg": 0.0, "offset_mm": 0.75, "radius_sum_mm": 3.05, "gap_mm": 0.05},
        ),
    ]


def test_the_gaps_are_two_faceless_rows_and_13_free_faces_on_parts_with_holes(
    replay: JointMap,
) -> None:
    faceless = [gap.subject for gap in replay.gaps if "no cylinder face" in gap.reason]
    free = {
        gap.subject: int(gap.reason.split()[0])
        for gap in replay.gaps
        if "in no hole feature" in gap.reason
    }

    assert faceless == ["hol:0007", "hol:0009"]
    assert sum(free.values()) == 13
    assert len(replay.gaps) == len(faceless) + len(free)
