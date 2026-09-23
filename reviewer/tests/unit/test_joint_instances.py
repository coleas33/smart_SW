"""A `Hole` row is a feature; the joint map works on its instances (feature 010 T010).

`HoleDumper` writes one row per Hole Wizard feature, every cylinder face of every instance
in `face_ids`, and the axis of the first face only (research R2.1). These tests pin how the
map explodes a row into instances, and every way a row yields none.
"""

from __future__ import annotations

import math

import pytest

from swreview.checks.joints import build_joint_map, native_size
from swreview.ir.models import CylinderFace, EvidencePackage, HoleWizardData, Quantity, Vec3
from tests.support.mechanical import Face, Instance, PackageBuilder

Z = (0.0, 0.0, 1.0)
TILT = (math.sin(math.radians(30.0)), 0.0, math.cos(math.radians(30.0)))


def builder_with(*suppressions: str) -> PackageBuilder:
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    for index, suppression in enumerate(suppressions, start=1):
        document = builder.document(f"FICT-KALO-000{index}", "part", material="Alloy Steel")
        builder.component(document, component_id=f"cmp:{index:04d}", suppression=suppression)  # type: ignore[arg-type]
    return builder


def row_of(point: tuple[float, float], *faces: Face, direction=Z) -> Instance:
    return Instance(origin_mm=(point[0], point[1], 0.0), direction=direction, faces=faces)


def test_a_row_with_fifteen_faces_on_fifteen_axes_is_fifteen_instances_in_face_order() -> None:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size="M3x0.5",
        thread="M3x0.5",
        end_condition="blind",
        instances=[row_of((10.0 * k, 0.0), Face(2.5, -8.0, 0.0)) for k in range(15)],
    )
    package = builder.build().package

    instances = build_joint_map(package).instances

    assert [item.id for item in instances] == [f"hol:0001#{n}" for n in range(1, 16)]
    assert [item.face_ids for item in instances] == [(f"fac:{n:04d}",) for n in range(1, 16)]
    assert instances[3].axis.origin.x == pytest.approx(0.030)
    assert {item.hole_id for item in instances} == {"hol:0001"}
    assert {item.component_id for item in instances} == {"cmp:0001"}
    assert {item.hole_type for item in instances} == {"tapped"}


def test_instances_are_numbered_by_their_smallest_face_id_not_by_position() -> None:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type="clearance",
        size="M5",
        end_condition="through",
        instances=[
            row_of((30.0, 0.0), Face(5.5, 0.0, 5.0)),
            row_of((0.0, 0.0), Face(5.5, 0.0, 5.0)),
        ],
    )
    package = builder.build().package
    # The extractor's face order is not the order ids sort in; the map sorts by id.
    shuffled = package.model_copy(
        update={
            "holes": [package.holes[0].model_copy(update={"face_ids": ["fac:0002", "fac:0001"]})]
        }
    )

    instances = build_joint_map(shuffled).instances

    assert [(item.id, item.axis.origin.x) for item in instances] == [
        ("hol:0001#1", pytest.approx(0.030)),
        ("hol:0001#2", pytest.approx(0.0)),
    ]


def test_a_counterbore_row_on_four_axes_is_four_instances_of_two_diameters() -> None:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type="counterbore",
        size="M8",
        end_condition="through",
        instances=[
            row_of((40.0 * k, 0.0), Face(9.0, 0.0, 1.4), Face(14.0, 1.4, 10.0)) for k in range(4)
        ],
    )
    package = builder.build().package

    instances = build_joint_map(package).instances

    assert len(instances) == 4
    assert {item.diameters_mm for item in instances} == {(9.0, 14.0)}
    assert {item.bore_mm for item in instances} == {9.0}
    assert all(len(item.face_ids) == 2 for item in instances)


def test_the_size_is_the_bore_from_the_faces_labelled_face() -> None:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type="clearance",
        size="Ø3.0",
        end_condition="through",
        instances=[row_of((0.0, 0.0), Face(3.1, 0.0, 6.0))],
    )
    [instance] = build_joint_map(builder.build().package).instances

    assert (instance.size_mm, instance.size_source) == (3.1, "face")


def test_a_hole_wizard_diameter_wins_over_the_faces_labelled_hole_wizard() -> None:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type="clearance",
        size="Ø3.0",
        end_condition="through",
        instances=[row_of((0.0, 0.0), Face(3.1, 0.0, 6.0))],
    )
    package = builder.build().package
    hole = package.holes[0].model_copy(update={"diameter": Quantity(value=0.125, unit="in")})

    [instance] = build_joint_map(package.model_copy(update={"holes": [hole]})).instances

    assert (instance.size_mm, instance.size_source) == (3.175, "hole_wizard")
    assert instance.bore_mm == 3.1


# IR 1.5.0 (feature 010 US8): the Hole Wizard's own sizes, by hole type, when `Hole.diameter`
# is absent; never the other type's size and never derived.


def wizard_instance(hole_type: str, **sizes: float) -> tuple[float, str]:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type=hole_type,  # type: ignore[arg-type]
        size="M4",
        end_condition="through",
        instances=[row_of((0.0, 0.0), Face(4.6, 0.0, 6.0))],
        wizard=HoleWizardData(
            **{name: Quantity(value=value, unit="m") for name, value in sizes.items()}
        ),
    )
    [instance] = build_joint_map(builder.build().package).instances
    return instance.size_mm, instance.size_source


@pytest.mark.parametrize("hole_type", ["clearance", "counterbore", "countersink", "simple"])
def test_a_wizard_through_hole_diameter_sizes_every_hole_but_a_tapped_one(hole_type: str) -> None:
    assert wizard_instance(hole_type, thru_hole_diameter=0.0045) == (4.5, "hole_wizard")


def test_a_wizard_tap_drill_sizes_a_tapped_hole() -> None:
    assert wizard_instance("tapped", tap_drill_diameter=0.0033) == (3.3, "hole_wizard")


@pytest.mark.parametrize(
    ("hole_type", "sizes"),
    [
        ("tapped", {"thru_hole_diameter": 0.0045}),
        ("clearance", {"tap_drill_diameter": 0.0033}),
        ("clearance", {}),
    ],
)
def test_a_wizard_without_its_types_size_leaves_the_face_bore(
    hole_type: str, sizes: dict[str, float]
) -> None:
    assert wizard_instance(hole_type, **sizes) == (4.6, "face")


def test_hole_diameter_wins_over_the_wizard_sizes() -> None:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type="clearance",
        size="M4",
        end_condition="through",
        instances=[row_of((0.0, 0.0), Face(4.6, 0.0, 6.0))],
        wizard=HoleWizardData(thru_hole_diameter=Quantity(value=0.0045, unit="m")),
    )
    package = builder.build().package
    hole = package.holes[0].model_copy(update={"diameter": Quantity(value=4.8, unit="mm")})

    assert native_size(hole) == Quantity(value=4.8, unit="mm")
    assert native_size(package.holes[0]) == Quantity(value=0.0045, unit="m")
    assert native_size(package.holes[0].model_copy(update={"wizard": None})) is None


def gap_reasons(package: EvidencePackage) -> dict[str, str]:
    return {gap.subject: gap.reason for gap in build_joint_map(package).gaps}


def test_a_row_with_no_cylinder_face_is_a_gap_and_no_instance() -> None:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size="M6x1.0",
        thread="M6x1.0",
        end_condition="blind",
        instances=[],
        faceless_axis=row_of((0.0, 0.0), Face(5.0, -12.0, 0.0)),
    )
    package = builder.build().package

    assert build_joint_map(package).instances == ()
    assert "no cylinder face" in gap_reasons(package)["hol:0001"]


def test_a_row_on_a_component_that_was_not_read_is_a_gap_and_no_instance() -> None:
    builder = builder_with("resolved", "lightweight")
    builder.hole(
        "cmp:0002",
        hole_type="clearance",
        size="M5",
        end_condition="through",
        instances=[row_of((0.0, 0.0), Face(5.5, 0.0, 5.0))],
    )
    package = builder.build().package

    assert build_joint_map(package).instances == ()
    reason = gap_reasons(package)["hol:0001"]
    assert "cmp:0002" in reason and "lightweight" in reason


def test_a_face_whose_axis_is_zero_length_is_a_gap_and_no_instance() -> None:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type="clearance",
        size="M5",
        end_condition="through",
        instances=[row_of((0.0, 0.0), Face(5.5, 0.0, 5.0))],
    )
    package = builder.build().package
    face = package.faces[0]
    assert face.cylinder is not None
    broken = face.model_copy(
        update={
            "cylinder": CylinderFace(
                axis_origin=face.cylinder.axis_origin,
                axis_dir=Vec3(x=0.0, y=0.0, z=0.0),
                radius_m=face.cylinder.radius_m,
            )
        }
    )

    result = build_joint_map(package.model_copy(update={"faces": [broken]}))

    assert result.instances == ()
    assert "zero-length" in gap_reasons(package.model_copy(update={"faces": [broken]}))["hol:0001"]


def test_a_face_id_missing_from_the_package_is_a_gap() -> None:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type="clearance",
        size="M5",
        end_condition="through",
        instances=[row_of((0.0, 0.0), Face(5.5, 0.0, 5.0))],
    )
    package = builder.build().package

    result = build_joint_map(package.model_copy(update={"faces": []}))

    assert result.instances == ()
    assert "fac:0001" in gap_reasons(package.model_copy(update={"faces": []}))["hol:0001"]


def test_an_axis_aligned_instance_records_no_extent_error() -> None:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type="clearance",
        size="M5",
        end_condition="through",
        instances=[row_of((0.0, 0.0), Face(5.5, 0.0, 5.0))],
    )
    [instance] = build_joint_map(builder.build().package).instances

    assert instance.axis_aligned is True
    assert instance.extent_bound_mm == 0.0


def test_an_oblique_instance_is_not_axis_aligned_and_records_the_r_sin_theta_bound() -> None:
    builder = builder_with("resolved")
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size="M5x0.8",
        thread="M5x0.8",
        end_condition="blind",
        instances=[row_of((0.0, 0.0), Face(4.2, -12.0, 0.0), direction=TILT)],
    )
    [instance] = build_joint_map(builder.build().package).instances

    assert instance.axis_aligned is False
    assert instance.extent_bound_mm == pytest.approx(2.1 * math.sin(math.radians(30.0)))
