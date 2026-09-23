"""Which components are fasteners, what size they are, and where they sit (feature 010 T040).

`contracts/fasteners.md` section 3 and `contracts/joint-map.md` section 5 are normative:

- a Toolbox `Fastener` row wins, and its name only cross-checks it;
- every other resolved component whose name parses to a screw, bolt or pin is recognised,
  one per instance, with an in-memory `Fastener` built from the name;
- its shank - the largest free cylinder face - is compared with the thread's ISO 68-1 band
  from the basic minor diameter to the major diameter, because both modelling conventions
  occur in one recorded package (research R2.12);
- it is placed by a member face, then by its component origin on an instance axis, and
  otherwise left unplaced with the reason - never by a bounding box, never guessed (R2.3).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
import trimesh
import yaml
from pytest_regressions.file_regression import FileRegressionFixture

from swreview.checks.fastener_identity import (
    CHECK_IDENTITY,
    RecognisedFastener,
    check_identity,
    recognise_fasteners,
    screw_extent,
    shank_band_mm,
)
from swreview.checks.fastener_names import parse_fastener_name
from swreview.checks.joints import build_joint_map
from swreview.ir.loader import load_package
from swreview.ir.models import Axis, EvidencePackage, Fastener, Vec3
from tests.support.mechanical import Face, Instance, PackageBuilder, cylinder_mesh
from tests.support.packages import persist_ref

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mechanical"
Z = (0.0, 0.0, 1.0)


@pytest.fixture(scope="module")
def big_package() -> EvidencePackage:
    return load_package(FIXTURES / "big-assembly").package


@pytest.fixture(scope="module")
def big_recognised(big_package: EvidencePackage) -> list[RecognisedFastener]:
    return recognise_fasteners(big_package)


def plate_and_screw(
    *,
    thread: str = "M5-0.8",
    shank_face_mm: float | None = None,
    bearing_mm: tuple[float, float, float] = (0.0, 0.0, 10.0),
    direction: tuple[float, float, float] = Z,
    tapped: str = "M5x0.8",
    head: str = "SHC",
) -> tuple[PackageBuilder, str]:
    """A plate with one blind tapped hole at the origin and one screw over it."""
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    plate = builder.document("FICT-KALOMIR-0001", "part", material="Alloy Steel")
    builder.component(plate, component_id="cmp:0001")
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size=tapped,
        thread=tapped,
        thread_depth_mm=10.0,
        end_condition="blind",
        instances=[Instance((0.0, 0.0, 0.0), Z, (Face(4.2, -12.0, 0.0),))],
    )
    document = builder.screw_document(head, thread, 16.0, serial=1)  # type: ignore[arg-type]
    screw = builder.screw(
        document,
        bearing_mm=bearing_mm,
        direction=direction,
        component_id="cmp:0002",
        shank_face_mm=shank_face_mm,
    )
    return builder, screw


# --- recognition ------------------------------------------------------------------------------


def test_the_big_fixture_recognises_68_of_68_named_screws(big_recognised) -> None:
    """SC-004: every screw named in the vendor pattern, by its file name."""
    assert len(big_recognised) == 68
    assert {item.identity_source for item in big_recognised} == {"name_parse"}
    assert {item.name.source for item in big_recognised if item.name} == {"file_name"}
    heads = Counter(item.name.head_code for item in big_recognised if item.name)
    assert heads == {"SHC": 32, "FHT": 35, "BHT": 1}


def test_a_named_screw_is_one_recognised_fastener_per_instance_with_a_valid_row() -> None:
    builder, screw = plate_and_screw()
    package = builder.build().package

    [recognised] = recognise_fasteners(package)

    assert recognised.component_id == screw
    fastener = recognised.fastener
    Fastener.model_validate(fastener.model_dump())
    assert fastener.id == f"fst:name:{screw}"
    assert (fastener.kind, fastener.identity_source) == ("screw", "name_parse")
    assert fastener.thread_designation == "M5x0.8"
    assert fastener.length is not None and fastener.length.value == 16.0
    assert (fastener.head_type, fastener.drive) == ("socket head cap", "hex_socket")
    assert fastener.material == "Alloy Steel"
    component = next(item for item in package.components if item.id == screw)
    assert fastener.persist_ref == component.persist_ref


def test_a_part_named_with_no_size_is_not_a_fastener() -> None:
    builder, _ = plate_and_screw()
    package = builder.build().package

    assert [item.component_id for item in recognise_fasteners(package)] == ["cmp:0002"]


def test_a_lightweight_named_component_is_not_recognised() -> None:
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    document = builder.screw_document("SHC", "M5-0.8", 16.0, serial=1)
    builder.component(document, component_id="cmp:0001", suppression="lightweight")

    assert recognise_fasteners(builder.build().package) == []


def test_a_toolbox_row_wins_and_its_name_only_cross_checks() -> None:
    builder, screw = plate_and_screw()
    package = builder.build().package
    component = next(item for item in package.components if item.id == screw)
    row = Fastener(
        id="fst:0001",
        persist_ref=persist_ref("fst:0001"),
        persist_ref_scope=component.persist_ref_scope,
        component_id=screw,
        kind="screw",
        identity_source="toolbox",
        thread_designation="M5x0.8",
        length=None,
        head_type="socket head cap",
        head_diameter=None,
        head_height=None,
        drive=None,
        axis=Axis(origin=Vec3(x=0.0, y=0.0, z=0.0), direction=Vec3(x=0.0, y=0.0, z=1.0)),
        material=None,
    )
    package = package.model_copy(update={"fasteners": [row]})

    [recognised] = recognise_fasteners(package)

    assert recognised.fastener is row
    assert recognised.identity_source == "toolbox"
    assert recognised.name is not None and recognised.name.designation == "M5x0.8"
    assert recognised.name_conflicts == ()


def test_a_toolbox_row_whose_name_disagrees_is_a_name_conflict() -> None:
    builder, screw = plate_and_screw(thread="M4-0.7")
    package = builder.build().package
    component = next(item for item in package.components if item.id == screw)
    row = Fastener(
        id="fst:0001",
        persist_ref=persist_ref("fst:0001"),
        persist_ref_scope=component.persist_ref_scope,
        component_id=screw,
        kind="screw",
        identity_source="toolbox",
        thread_designation="M5x0.8",
        length=None,
        head_type=None,
        head_diameter=None,
        head_height=None,
        drive=None,
        axis=Axis(origin=Vec3(x=0.0, y=0.0, z=0.0), direction=Vec3(x=0.0, y=0.0, z=1.0)),
        material=None,
    )

    [recognised] = recognise_fasteners(package.model_copy(update={"fasteners": [row]}))

    assert recognised.name_conflicts == (
        "the file name reads M4x0.7 where the fastener row reads M5x0.8",
        "the description reads M4x0.7 where the fastener row reads M5x0.8",
    )


# --- the shank band (research R2.12) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("designation", "shank", "agreement"),
    [
        ("M10x1.5", 8.5, "agrees"),
        ("M4x0.7", 3.3, "agrees"),
        ("M8x1.25", 6.75, "agrees"),
        ("M3x0.5", 3.0, "agrees"),
        ("M5x0.8", 3.3, "disagrees"),
        ("M5x0.8", 5.05, "agrees"),
        ("M5x0.8", 5.051, "disagrees"),
    ],
)
def test_the_band_admits_both_modelling_conventions(
    designation: str, shank: float, agreement: str
) -> None:
    parsed = parse_fastener_name(designation, "configuration")
    assert parsed is not None
    band = shank_band_mm(parsed.thread)

    assert band is not None
    assert (band[0] <= shank <= band[1]) == (agreement == "agrees")


def test_the_band_of_an_m5x0_8_is_from_its_basic_minor_diameter() -> None:
    parsed = parse_fastener_name("M5x0.8", "configuration")
    assert parsed is not None

    assert shank_band_mm(parsed.thread) == (pytest.approx(3.968505), pytest.approx(5.05))


def test_a_thread_with_no_pitch_forms_no_band() -> None:
    parsed = parse_fastener_name("M5", "configuration")
    assert parsed is not None

    assert shank_band_mm(parsed.thread) is None


def test_the_measured_shank_is_the_largest_free_cylinder_face(big_recognised) -> None:
    by_component = {item.component_id: item for item in big_recognised}

    assert (by_component["cmp:0018"].shank_mm, by_component["cmp:0018"].agreement) == (
        8.5,
        "agrees",
    )
    assert by_component["cmp:0007"].shank_mm == 3.3
    assert by_component["cmp:0007"].agreement == "agrees"
    assert by_component["cmp:0017"].shank_source == "face"


def test_the_screw_named_m5_with_a_3_3_mm_shank_disagrees(big_recognised) -> None:
    [named] = [item for item in big_recognised if item.agreement == "disagrees"]

    assert named.name is not None and named.name.designation == "M5x0.8"
    assert named.shank_mm == 3.3


def test_a_screw_with_no_face_is_unmeasured(big_recognised) -> None:
    unmeasured = [item for item in big_recognised if item.agreement == "unmeasured"]

    assert len(unmeasured) == 68 - 11
    assert all(item.shank_mm is None and item.shank_source is None for item in unmeasured)


# --- fastener.identity --------------------------------------------------------------------------


def test_a_disagreement_is_one_suspected_identity_finding_per_document(
    big_package, big_recognised
) -> None:
    [result] = check_identity(big_recognised, big_package)

    assert result.check == CHECK_IDENTITY
    assert (result.status, result.severity) == ("suspected", "medium")
    assert result.observed.startswith(
        "SHC_M5-0.8X20_FICT-0006.SLDPRT is named M5x0.8 but its shank measures 3.3 mm, "
        "outside the 3.968505 to 5.05 mm band of that thread"
    )
    assert result.calculation is not None
    assert result.calculation.result["agrees"] is False


def test_agreeing_and_unmeasured_screws_raise_no_identity_finding() -> None:
    builder, _ = plate_and_screw(shank_face_mm=5.0)
    package = builder.build().package

    assert check_identity(recognise_fasteners(package), package) == []


def test_a_name_conflict_is_a_suspected_identity_finding() -> None:
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    document = builder.screw_document(
        "SHC", "M4-0.7", 12.0, serial=1, description="SCREW, SOC M5-0.8 X 12 MM, FICTIONAL"
    )
    builder.component(document, component_id="cmp:0001")
    package = builder.build().package

    [recognised] = recognise_fasteners(package)
    [result] = check_identity([recognised], package)

    assert recognised.name_conflicts == (
        "the description reads M5x0.8 where the file name reads M4x0.7",
    )
    assert result.status == "suspected"
    assert "the description reads M5x0.8 where the file name reads M4x0.7" in result.observed


# --- placement (joint-map.md section 5) ---------------------------------------------------------


def test_a_screw_with_a_member_face_is_placed_by_face() -> None:
    builder, screw = plate_and_screw(shank_face_mm=5.0)
    package = builder.build().package

    joint_map = build_joint_map(package, fasteners=recognise_fasteners(package))

    [joint] = joint_map.joints
    assert joint.fastener is not None
    assert (joint.fastener.component_id, joint.fastener.placement) == (screw, "face")
    assert joint.fastener.placed_on == "hol:0001#1"
    assert joint_map.unplaced == ()


def test_a_screw_with_no_face_is_placed_by_its_origin_on_the_axis() -> None:
    builder, screw = plate_and_screw(bearing_mm=(0.15, 0.0, 10.0))
    package = builder.build().package

    joint_map = build_joint_map(package, fasteners=recognise_fasteners(package))

    [joint] = joint_map.joints
    assert joint.fastener is not None and joint.fastener.placement == "origin"
    assert joint.kind == "screw"
    assert [item.id for item in joint.instances] == ["hol:0001#1"]


def test_an_origin_off_the_axis_by_more_than_the_rule_is_unplaced() -> None:
    builder, screw = plate_and_screw(bearing_mm=(0.25, 0.0, 10.0))
    package = builder.build().package

    joint_map = build_joint_map(package, fasteners=recognise_fasteners(package))

    assert joint_map.joints == ()
    [unplaced] = joint_map.unplaced
    assert unplaced.component_id == screw
    assert unplaced.unplaced_reason == (
        "it has no face in a hole and its origin lies on no hole instance's axis"
    )


def test_an_origin_on_the_axis_with_no_basis_vector_parallel_is_unplaced() -> None:
    """On the line is not enough: a screw lying across the hole is not in it."""
    tilted = (1.0, 0.0, 1.0)
    builder, _ = plate_and_screw(direction=tilted)
    package = builder.build().package

    joint_map = build_joint_map(package, fasteners=recognise_fasteners(package))

    assert joint_map.joints == ()
    assert len(joint_map.unplaced) == 1


def _two_joints_on_one_line(*, second_tapped: bool) -> tuple[EvidencePackage, str]:
    """Two joints 100 mm apart on the x = 0, y = 0 line, and a screw whose origin is on it."""
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    for index, stem in enumerate(("FICT-KALOMIR-0001", "FICT-KALOVEN-0002", "FICT-KALOSORN-0003",
                                  "FICT-KALOTULM-0004")):
        document = builder.document(stem, "part", material="Alloy Steel")
        builder.component(document, component_id=f"cmp:{index + 1:04d}")
    clearance = {"hole_type": "clearance", "size": "M5", "end_condition": "through"}
    builder.hole("cmp:0001", **clearance, instances=[Instance((0, 0, 0), Z, (Face(5.5, 0, 6),))])
    builder.hole("cmp:0002", **clearance, instances=[Instance((0, 0, 0), Z, (Face(5.5, 6, 12),))])
    builder.hole(
        "cmp:0003", **clearance, instances=[Instance((0, 0, 0), Z, (Face(5.5, 100, 106),))]
    )
    if second_tapped:
        builder.hole(
            "cmp:0004",
            hole_type="tapped",
            size="M5x0.8",
            thread="M5x0.8",
            thread_depth_mm=10.0,
            end_condition="blind",
            instances=[Instance((0, 0, 0), Z, (Face(4.2, 94, 100),))],
        )
    else:
        builder.hole(
            "cmp:0004", **clearance, instances=[Instance((0, 0, 0), Z, (Face(5.5, 94, 100),))]
        )
    document = builder.screw_document("SHC", "M5-0.8", 16.0, serial=5)
    screw = builder.screw(
        document, bearing_mm=(0.0, 0.0, 50.0), direction=Z, component_id="cmp:0005"
    )
    return builder.build().package, screw


def test_a_screw_on_two_joints_axes_is_unplaced_naming_both() -> None:
    package, screw = _two_joints_on_one_line(second_tapped=False)

    joint_map = build_joint_map(package, fasteners=recognise_fasteners(package))

    assert len(joint_map.joints) == 2
    assert all(joint.fastener is None for joint in joint_map.joints)
    [unplaced] = joint_map.unplaced
    assert unplaced.component_id == screw
    assert unplaced.unplaced_reason == (
        "its origin lies on the axes of hol:0001#1 and hol:0003#1, in different joints, and "
        "not exactly one of them has a tapped hole"
    )


def test_a_screw_on_two_joints_axes_goes_to_the_one_with_a_tapped_instance() -> None:
    package, screw = _two_joints_on_one_line(second_tapped=True)

    joint_map = build_joint_map(package, fasteners=recognise_fasteners(package))

    [holding] = [joint for joint in joint_map.joints if joint.fastener is not None]
    assert {item.hole_id for item in holding.instances} == {"hol:0003", "hol:0004"}
    assert holding.fastener.placement == "origin"


def test_a_screw_on_a_lone_clearance_instance_forms_a_one_instance_screw_joint() -> None:
    """Kind rule 2: no tapped hole and a recognised screw placed - its tapped part is not in
    the map, and the checks that need it say so."""
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    document = builder.document("FICT-KALOMIR-0001", "part", material="6061-T6")
    builder.component(document, component_id="cmp:0001")
    builder.hole(
        "cmp:0001",
        hole_type="clearance",
        size="M5",
        end_condition="through",
        instances=[Instance((0, 0, 0), Z, (Face(5.5, 0, 6),))],
    )
    screw_document = builder.screw_document("SHC", "M5-0.8", 16.0, serial=1)
    builder.screw(screw_document, bearing_mm=(0, 0, 6), direction=Z, component_id="cmp:0002")
    package = builder.build().package

    assert build_joint_map(package).joints == ()
    [joint] = build_joint_map(package, fasteners=recognise_fasteners(package)).joints
    assert joint.kind == "screw"
    assert joint.fastener is not None and joint.fastener.placed_on == "hol:0001#1"


def test_the_big_fixture_places_57_screws_and_leaves_11_unplaced(
    big_package, big_recognised
) -> None:
    joint_map = build_joint_map(big_package, fasteners=big_recognised)

    placed = [joint.fastener for joint in joint_map.joints if joint.fastener is not None]
    assert len(placed) == 57
    assert Counter(item.placement for item in placed) == {"face": 9, "origin": 48}
    on_tapped = [
        joint for joint in joint_map.joints
        if joint.fastener is not None and any(item.is_tapped for item in joint.instances)
    ]
    assert len(on_tapped) == 48
    assert len(joint_map.unplaced) == 11
    assert len(joint_map.joints) == 59
    assert len(joint_map.pattern_groups()) == 13
    assert Counter(joint.kind for joint in joint_map.joints) == {"screw": 57, "pin": 2}


def test_the_foundational_map_is_unchanged_by_the_fasteners_argument_being_absent(
    big_package,
) -> None:
    assert build_joint_map(big_package).as_json() == build_joint_map(
        big_package, fasteners=None
    ).as_json()


@pytest.mark.parametrize("seed", [1, 7])
def test_the_map_with_fasteners_is_identical_under_any_order_of_the_package(
    big_package, seed: int
) -> None:
    """Recognition and placement read sorted ids, never array order (T011's rule, kept)."""
    from tests.unit.test_joint_map import shuffled

    expected = json.dumps(
        build_joint_map(big_package, fasteners=recognise_fasteners(big_package)).as_json(),
        sort_keys=True,
    )
    mixed = shuffled(big_package, seed)

    actual = json.dumps(
        build_joint_map(mixed, fasteners=recognise_fasteners(mixed)).as_json(), sort_keys=True
    )

    assert actual == expected


def test_the_map_with_fasteners_is_a_golden(
    big_package, big_recognised, file_regression: FileRegressionFixture
) -> None:
    joint_map = build_joint_map(big_package, fasteners=big_recognised)

    file_regression.check(
        yaml.safe_dump(joint_map.as_json(), sort_keys=False, allow_unicode=True),
        basename="big-assembly-with-fasteners",
        extension=".yml",
    )


# --- the screw's axial extent -------------------------------------------------------------------


def test_the_extent_comes_from_the_shank_face_and_says_so() -> None:
    builder, _ = plate_and_screw(shank_face_mm=5.0)
    package = builder.build().package
    [joint] = build_joint_map(package, fasteners=recognise_fasteners(package)).joints

    extent = screw_extent(joint, package, mesh=None)

    assert extent is not None
    assert (extent.low_mm, extent.high_mm, extent.source) == (-6.0, 10.0, "face")


def test_the_mesh_is_used_only_without_a_face_and_is_labelled() -> None:
    builder, _ = plate_and_screw()
    package = builder.build().package
    [joint] = build_joint_map(package, fasteners=recognise_fasteners(package)).joints
    mesh = trimesh.util.concatenate(
        [
            cylinder_mesh((0.0, 0.0, 10.0), Z, 5.0, -16.0, 0.0),
            cylinder_mesh((0.0, 0.0, 10.0), Z, 8.5, 0.0, 5.0),
        ]
    )

    extent = screw_extent(joint, package, mesh=mesh)

    assert extent is not None
    assert extent.source == "mesh"
    assert (extent.low_mm, extent.high_mm) == (pytest.approx(-6.0), pytest.approx(15.0))


def test_a_face_wins_over_a_mesh() -> None:
    builder, _ = plate_and_screw(shank_face_mm=5.0)
    package = builder.build().package
    [joint] = build_joint_map(package, fasteners=recognise_fasteners(package)).joints
    mesh = cylinder_mesh((0.0, 0.0, 10.0), Z, 5.0, -30.0, 0.0)

    extent = screw_extent(joint, package, mesh=mesh)

    assert extent is not None and extent.source == "face"


def test_no_face_and_no_mesh_is_no_extent() -> None:
    builder, _ = plate_and_screw()
    package = builder.build().package
    [joint] = build_joint_map(package, fasteners=recognise_fasteners(package)).joints

    assert screw_extent(joint, package, mesh=None) is None
