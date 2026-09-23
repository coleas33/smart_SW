"""The joint map on small hand-built packages (feature 010 T011, `contracts/joint-map.md`).

Every gate at its boundary, the one-partner rule, the candidates, the cylinder members,
the kinds in order, and the map's determinism under any order of the package's arrays.
The shaped fixtures' numbers are `test_joint_map_acceptance.py`'s.
"""

from __future__ import annotations

import json
import math
import random

import pytest

from swreview.checks.joints import JointMap, build_joint_map
from swreview.ir.models import EvidencePackage
from tests.support.mechanical import Face, Instance, PackageBuilder

Z = (0.0, 0.0, 1.0)


def tilted(degrees: float, about: str = "y") -> tuple[float, float, float]:
    radians = math.radians(degrees)
    if about == "y":
        return (math.sin(radians), 0.0, math.cos(radians))
    return (0.0, math.sin(radians), math.cos(radians))


def parts(count: int) -> PackageBuilder:
    """A builder with `count` resolved parts at `cmp:0001` onward, none with a hole yet."""
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    for index in range(1, count + 1):
        document = builder.document(f"FICT-KALO-{index:04d}", "part", material="Alloy Steel")
        builder.component(document, component_id=f"cmp:{index:04d}")
    return builder


def one(point: tuple[float, float, float], *faces: Face, direction=Z) -> list[Instance]:
    return [Instance(origin_mm=point, direction=direction, faces=faces)]


def tapped(
    builder: PackageBuilder,
    component: str,
    point=(0.0, 0.0, 0.0),
    *,
    lo: float = -8.0,
    hi: float = 0.0,
    thread: str = "M3x0.5",
    bore: float = 2.5,
    direction=Z,
) -> str:
    return builder.hole(
        component,
        hole_type="tapped",
        size=thread,
        thread=thread,
        end_condition="blind",
        instances=one(point, Face(bore, lo, hi), direction=direction),
    )


def clearance(
    builder: PackageBuilder,
    component: str,
    point=(0.0, 0.0, 0.0),
    *,
    lo: float = 0.0,
    hi: float = 3.0,
    bore: float = 3.4,
    size: str = "M3",
    direction=Z,
    hole_type: str = "clearance",
) -> str:
    return builder.hole(
        component,
        hole_type=hole_type,
        size=size,  # type: ignore[arg-type]
        end_condition="through",
        instances=one(point, Face(bore, lo, hi), direction=direction),
    )


def mapped(builder: PackageBuilder) -> JointMap:
    return build_joint_map(builder.build().package)


def reasons(joint_map: JointMap) -> list[str]:
    return [candidate.reason for candidate in joint_map.candidates]


# --- the three gates, each at its boundary ------------------------------------------------


@pytest.mark.parametrize(
    ("degrees", "joints", "candidates"),
    [(0.0, 1, []), (1.0, 1, []), (1.5, 0, ["angle_near"]), (2.0, 0, ["angle_near"]), (2.5, 0, [])],
)
def test_the_parallel_gate_passes_to_one_degree_and_lists_the_next_degree(
    degrees: float, joints: int, candidates: list[str]
) -> None:
    builder = parts(2)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0002", direction=tilted(degrees))

    joint_map = mapped(builder)

    assert (len(joint_map.joints), reasons(joint_map)) == (joints, candidates)


@pytest.mark.parametrize(
    ("offset", "joints", "candidates"),
    [
        (0.0, 1, []),
        (2.949, 1, []),
        (2.95, 0, ["overlap_near"]),
        (3.95, 0, ["overlap_near"]),
        (3.96, 0, []),
    ],
)
def test_the_overlap_gate_passes_below_the_radius_sum_and_lists_the_next_millimetre(
    offset: float, joints: int, candidates: list[str]
) -> None:
    """Radius sum 1.25 + 1.7 = 2.95 mm: strictly below it the projections overlap."""
    builder = parts(2)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0002", (offset, 0.0, 0.0))

    joint_map = mapped(builder)

    assert (len(joint_map.joints), reasons(joint_map)) == (joints, candidates)
    if candidates:
        assert joint_map.candidates[0].values["radius_sum_mm"] == 2.95
        assert joint_map.candidates[0].values["offset_mm"] == offset


@pytest.mark.parametrize(
    ("gap", "joints", "candidates"),
    [
        (-2.0, 1, []),
        (0.0, 1, []),
        (0.999, 1, []),
        (1.0, 0, ["gap_near"]),
        (2.0, 0, ["gap_near"]),
        (2.001, 0, []),
    ],
)
def test_the_adjacency_gate_passes_below_one_millimetre_and_lists_the_next(
    gap: float, joints: int, candidates: list[str]
) -> None:
    builder = parts(2)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0002", lo=gap, hi=gap + 3.0)

    joint_map = mapped(builder)

    assert (len(joint_map.joints), reasons(joint_map)) == (joints, candidates)
    if candidates:
        assert joint_map.candidates[0].values["gap_mm"] == gap


def test_a_near_miss_on_two_gates_is_nothing() -> None:
    builder = parts(2)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0002", (3.5, 0.0, 0.0), lo=1.5, hi=4.5)

    joint_map = mapped(builder)

    assert (joint_map.joints, joint_map.candidates) == ((), ())


def test_pairs_on_the_same_component_are_never_considered() -> None:
    builder = parts(1)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0001")

    joint_map = mapped(builder)

    assert (joint_map.joints, joint_map.candidates) == ((), ())


def test_every_joint_records_the_values_its_pairs_were_judged_on() -> None:
    builder = parts(2)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0002", (0.4, 0.0, 0.0), lo=0.5, hi=3.5)

    [joint] = mapped(builder).joints
    [pair] = joint.pairs

    assert (pair.a, pair.b) == ("hol:0001#1", "hol:0002#1")
    assert (pair.angle_deg, pair.offset_mm, pair.radius_sum_mm, pair.gap_mm) == (
        0.0,
        0.4,
        2.95,
        0.5,
    )
    assert joint.offset_mm == 0.4
    assert joint.reference == "hol:0001#1", "measured along the tapped instance"


def test_oblique_axes_pair_on_their_own_axis_and_the_joint_is_not_axis_aligned() -> None:
    direction = tilted(30.0)
    builder = parts(2)
    tapped(builder, "cmp:0001", direction=direction, bore=4.2, thread="M5x0.8")
    clearance(builder, "cmp:0002", direction=direction, bore=5.5, size="M5")

    [joint] = mapped(builder).joints

    assert joint.kind == "screw"
    assert joint.axis_aligned is False


# --- one partner per component --------------------------------------------------------------


def test_one_partner_per_component_keeps_the_nearest_and_lists_the_loser() -> None:
    builder = parts(2)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0002", (0.75, 0.0, 0.0), lo=-3.0, hi=0.0)  # below, 0.75 off
    clearance(builder, "cmp:0002", (0.0, 0.0, 0.0), lo=0.0, hi=3.0)  # above, on axis

    joint_map = mapped(builder)

    [joint] = joint_map.joints
    assert [item.id for item in joint.instances] == ["hol:0001#1", "hol:0003#1"]
    [loser] = joint_map.candidates
    assert (loser.members, loser.reason) == (("hol:0001#1", "hol:0002#1"), "assigned_elsewhere")
    assert loser.values["offset_mm"] == 0.75


def test_equal_offsets_are_decided_by_the_lower_instance_id() -> None:
    builder = parts(2)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0002", (0.5, 0.0, 0.0), lo=0.0, hi=3.0)
    clearance(builder, "cmp:0002", (-0.5, 0.0, 0.0), lo=-3.0, hi=0.0)

    joint_map = mapped(builder)

    assert [item.id for item in joint_map.joints[0].instances] == ["hol:0001#1", "hol:0002#1"]
    assert joint_map.candidates[0].members == ("hol:0001#1", "hol:0003#1")


def test_a_screw_through_two_clamped_plates_is_one_joint_of_three_instances() -> None:
    builder = parts(3)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0002", lo=0.0, hi=5.0)
    clearance(builder, "cmp:0003", lo=5.0, hi=8.0)

    joint_map = mapped(builder)

    [joint] = joint_map.joints
    assert [item.id for item in joint.instances] == ["hol:0001#1", "hol:0002#1", "hol:0003#1"]
    assert joint.component_ids == ("cmp:0001", "cmp:0002", "cmp:0003")
    assert joint_map.candidates == (), "the tapped hole and the top plate are 5 mm apart"


# --- cylinder members (section 4) ---------------------------------------------------------


def screw_part(builder: PackageBuilder) -> str:
    document = builder.document("FICT-SCREW-0009", "part", material="Alloy Steel")
    return builder.component(document, component_id="cmp:0009")


def face(
    builder: PackageBuilder,
    component: str,
    diameter: float,
    lo: float,
    hi: float,
    point=(0.0, 0.0, 0.0),
) -> str:
    return builder.cylinder_face(
        component, origin_mm=point, direction=Z, diameter_mm=diameter, lo_mm=lo, hi_mm=hi
    )


@pytest.mark.parametrize("diameter", [2.387, 2.5, 3.0, 3.05])
def test_a_screw_face_between_its_minor_and_major_diameter_sits_in_a_tapped_bore(
    diameter: float,
) -> None:
    builder = parts(1)
    tapped(builder, "cmp:0001")
    screw = screw_part(builder)
    face(builder, screw, diameter, -6.0, 4.0)

    [joint] = mapped(builder).joints

    [member] = joint.cylinders
    assert (member.component_id, member.role, member.diameter_mm) == (screw, "in_bore", diameter)
    assert (member.offset_mm, member.overlap_mm) == (0.0, 6.0)
    assert joint.kind == "screw"


def test_a_face_larger_than_the_major_diameter_plus_the_allowance_is_no_member() -> None:
    builder = parts(1)
    tapped(builder, "cmp:0001")
    face(builder, screw_part(builder), 3.06, -6.0, 4.0)

    assert mapped(builder).joints == ()


def test_a_face_off_the_axis_by_more_than_the_member_tolerance_is_no_member() -> None:
    builder = parts(1)
    tapped(builder, "cmp:0001")
    face(builder, screw_part(builder), 3.0, -6.0, 4.0, point=(0.21, 0.0, 0.0))

    assert mapped(builder).joints == ()


def test_a_face_that_does_not_overlap_the_hole_along_its_axis_is_no_member() -> None:
    builder = parts(1)
    tapped(builder, "cmp:0001")
    face(builder, screw_part(builder), 3.0, 0.0, 4.0)

    assert mapped(builder).joints == ()


def test_a_head_in_a_counterbore_is_a_member_in_the_counterbore() -> None:
    builder = parts(2)
    tapped(builder, "cmp:0001", lo=-20.0, hi=0.0, thread="M8x1.25", bore=6.8)
    builder.hole(
        "cmp:0002",
        hole_type="counterbore",
        size="M8",
        end_condition="through",
        instances=one((0.0, 0.0, 0.0), Face(9.0, 0.0, 1.4), Face(14.0, 1.4, 10.0)),
    )
    screw = screw_part(builder)
    face(builder, screw, 13.0, 1.4, 9.4)

    [joint] = mapped(builder).joints

    [member] = joint.cylinders
    assert (member.role, member.instance_id) == ("in_counterbore", "hol:0002#1")


def test_a_head_larger_than_the_counterbore_is_no_member() -> None:
    builder = parts(1)
    builder.hole(
        "cmp:0001",
        hole_type="counterbore",
        size="M8",
        end_condition="through",
        instances=one((0.0, 0.0, 0.0), Face(9.0, 0.0, 1.4), Face(12.0, 1.4, 10.0)),
    )
    face(builder, screw_part(builder), 13.0, 10.0, 18.0)

    assert mapped(builder).joints == ()


def test_a_member_coaxial_with_two_instances_of_one_joint_is_counted_once() -> None:
    builder = parts(2)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0002")
    face(builder, screw_part(builder), 3.0, -6.0, 3.0)

    [joint] = mapped(builder).joints

    assert len(joint.cylinders) == 1
    assert joint.cylinders[0].instance_id == "hol:0001#1"


def test_a_free_face_on_a_part_with_holes_is_a_gap_and_never_a_member() -> None:
    """The package does not say whether such a face is a bore or a boss (research R2.3)."""
    builder = parts(2)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0002", (50.0, 0.0, 0.0))
    face(builder, "cmp:0002", 3.0, -6.0, 3.0)
    face(builder, "cmp:0002", 5.0, 0.0, 3.0, point=(80.0, 0.0, 0.0))

    joint_map = mapped(builder)

    assert joint_map.joints == ()
    [gap] = [gap for gap in joint_map.gaps if gap.subject == "cmp:0002"]
    assert "2 cylinder faces" in gap.reason


def test_a_cylinder_in_an_instance_with_no_partner_forms_a_one_instance_joint() -> None:
    builder = parts(1)
    clearance(builder, "cmp:0001", size="Ø3.0", bore=3.0, lo=0.0, hi=10.0)
    pin = screw_part(builder)
    face(builder, pin, 3.0, 1.525, 12.0)

    [joint] = mapped(builder).joints

    assert joint.kind == "pin"
    assert [item.id for item in joint.instances] == ["hol:0001#1"]
    assert joint.cylinders[0].overlap_mm == 8.475


# --- the kinds, first rule that matches (section 6) ----------------------------------------


def test_a_tapped_instance_with_a_clearance_instance_is_a_screw_joint() -> None:
    builder = parts(2)
    tapped(builder, "cmp:0001")
    clearance(builder, "cmp:0002")

    assert mapped(builder).joints[0].kind == "screw"


def test_two_clearance_instances_sized_as_a_plain_diameter_are_a_pin_joint() -> None:
    builder = parts(2)
    clearance(builder, "cmp:0001", size="Ø3.0", bore=3.0, lo=-6.0, hi=0.0)
    clearance(builder, "cmp:0002", size="Ø3.0", bore=3.1, lo=0.0, hi=6.0)

    assert mapped(builder).joints[0].kind == "pin"


def test_two_clearance_instances_sized_as_a_thread_are_a_through_bolt_joint() -> None:
    builder = parts(2)
    clearance(builder, "cmp:0001", size="M8", bore=9.0, lo=-6.0, hi=0.0)
    clearance(builder, "cmp:0002", size="M8", bore=9.0, lo=0.0, hi=6.0, hole_type="counterbore")

    assert mapped(builder).joints[0].kind == "through_bolt"


def test_one_clearance_instance_sized_as_a_thread_with_a_cylinder_is_unclassified() -> None:
    builder = parts(1)
    clearance(builder, "cmp:0001", size="M8", bore=9.0, lo=0.0, hi=10.0)
    face(builder, screw_part(builder), 6.75, -6.0, 10.0)

    assert mapped(builder).joints[0].kind == "unclassified"


def test_clearance_instances_whose_sizes_disagree_in_kind_are_unclassified() -> None:
    builder = parts(2)
    clearance(builder, "cmp:0001", size="Ø3.0", bore=3.0, lo=-6.0, hi=0.0)
    clearance(builder, "cmp:0002", size="M3", bore=3.4, lo=0.0, hi=6.0)

    assert mapped(builder).joints[0].kind == "unclassified"


def test_instances_of_unknown_type_are_unclassified() -> None:
    builder = parts(2)
    clearance(builder, "cmp:0001", hole_type="unknown", lo=-6.0, hi=0.0)
    clearance(builder, "cmp:0002", hole_type="unknown", lo=0.0, hi=6.0)

    assert mapped(builder).joints[0].kind == "unclassified"


# --- ids, patterns and determinism ------------------------------------------------------


def pattern_package() -> EvidencePackage:
    builder = parts(2)
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size="M3x0.5",
        thread="M3x0.5",
        end_condition="blind",
        instances=[Instance((10.0 * k, 0.0, 0.0), Z, (Face(2.5, -8.0, 0.0),)) for k in range(3)],
    )
    builder.hole(
        "cmp:0002",
        hole_type="countersink",
        size="M3",
        end_condition="through",
        instances=[Instance((10.0 * k, 0.0, 0.0), Z, (Face(3.4, 0.0, 2.5),)) for k in (2, 0, 1)],
    )
    screw = screw_part(builder)
    face(builder, screw, 3.0, -6.0, 2.0, point=(10.0, 0.0, 0.0))
    return builder.build().package


def test_joint_ids_follow_the_smallest_member_instance_and_share_one_pattern() -> None:
    joint_map = build_joint_map(pattern_package())

    assert [joint.id for joint in joint_map.joints] == ["jnt:0001", "jnt:0002", "jnt:0003"]
    assert [[item.id for item in joint.instances] for joint in joint_map.joints] == [
        ["hol:0001#1", "hol:0002#2"],
        ["hol:0001#2", "hol:0002#3"],
        ["hol:0001#3", "hol:0002#1"],
    ]
    assert len({joint.pattern_key for joint in joint_map.joints}) == 1, (
        "a screw face in one joint of a pattern does not split the pattern"
    )
    assert joint_map.pattern_groups() == {
        joint_map.joints[0].pattern_key: ("jnt:0001", "jnt:0002", "jnt:0003")
    }


def shuffled(package: EvidencePackage, seed: int) -> EvidencePackage:
    rng = random.Random(seed)

    def mixed(items: list) -> list:
        copy = list(items)
        rng.shuffle(copy)
        return copy

    holes = [hole.model_copy(update={"face_ids": mixed(hole.face_ids)}) for hole in package.holes]
    return package.model_copy(
        update={
            "holes": mixed(holes),
            "faces": mixed(package.faces),
            "components": mixed(package.components),
            "documents": mixed(package.documents),
        }
    )


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_map_is_byte_identical_under_any_order_of_the_package_arrays(seed: int) -> None:
    package = pattern_package()

    expected = json.dumps(build_joint_map(package).as_json(), sort_keys=True)
    actual = json.dumps(build_joint_map(shuffled(package, seed)).as_json(), sort_keys=True)

    assert actual == expected


def test_a_package_with_no_hole_row_is_an_empty_map_with_one_gap() -> None:
    joint_map = mapped(parts(2))

    assert (joint_map.instances, joint_map.joints, joint_map.candidates) == ((), (), ())
    assert [(gap.subject, gap.reason) for gap in joint_map.gaps] == [
        ("package", "no hole was extracted")
    ]


def test_a_model_check_package_is_an_empty_map_with_one_gap() -> None:
    builder = parts(2)
    tapped(builder, "cmp:0001")
    package = builder.build().package
    model_check = package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"profile": "model_check"})}
    )

    joint_map = build_joint_map(model_check)

    assert (joint_map.instances, joint_map.joints) == ((), ())
    assert [(gap.subject, gap.reason) for gap in joint_map.gaps] == [
        ("package", "the hole phase did not run (profile model_check)")
    ]


def test_the_map_carries_the_rules_it_was_built_with() -> None:
    joint_map = mapped(parts(1))

    assert joint_map.rules.version == 1
    assert joint_map.unplaced == ()
