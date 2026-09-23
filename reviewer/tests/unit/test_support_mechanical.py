"""The mechanical-check fixtures: the builders, the generator, and the shapes they reproduce
(feature 010 T001, `contracts/fixtures.md`).

Two committed packages, shaped like the recorded 830-02342 and 810-11249 runs, are what every
acceptance test of feature 010 reads. They are built by code from fictional strings, so
this module pins three things:

1. **the builders** make the shapes the recorded packages have - a Hole Wizard feature is one
   `Hole` row whose `face_ids` hold one cylinder face per instance (research R2.1), a
   counterbore instance is two coaxial faces, a screw is a component whose document is named
   in the vendor shape, a mesh is a GLB in world metres;
2. **the generator reproduces every committed byte**, so a drifted fixture is a red test and
   never a silent rewrite;
3. **the counts and the case rows** of `contracts/fixtures.md` section 2 hold, counted here
   straight off the package - never through `checks/joints.py`, which these fixtures exist
   to test.
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from swreview.checks.interference import group_interferences, volume_mm3
from swreview.geometry.mesh import load_mesh
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage, FaceGeometry, Hole
from tests.support import mechanical
from tests.support.mechanical import (
    FICTIONAL_ROOT,
    FIXTURE_SCHEMA_VERSION,
    Face,
    Instance,
    PackageBuilder,
    screw_description,
    screw_file_name,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mechanical"
BIG = FIXTURES / "big-assembly"
SMALL = FIXTURES / "small-assembly"
Z = (0.0, 0.0, 1.0)


def generator():
    """The generator module, loaded from its file (the fixture tree is not a package)."""
    return mechanical.load_generator(FIXTURES / "generate_fixtures.py")


@pytest.fixture(scope="module")
def big() -> EvidencePackage:
    return load_package(BIG).package


@pytest.fixture(scope="module")
def small() -> EvidencePackage:
    return load_package(SMALL).package


# --- instance counting, done here and not by the code under test -------------------------


def _unit(vector) -> np.ndarray:
    array = np.array([vector.x, vector.y, vector.z], dtype=float)
    return array / np.linalg.norm(array)


def _same_axis(a: FaceGeometry, b: FaceGeometry) -> bool:
    assert a.cylinder is not None and b.cylinder is not None
    da, db = _unit(a.cylinder.axis_dir), _unit(b.cylinder.axis_dir)
    if math.degrees(math.acos(min(1.0, abs(float(da @ db))))) > 0.01:
        return False
    between = _unit_free(b.cylinder.axis_origin) - _unit_free(a.cylinder.axis_origin)
    lateral = between - float(between @ da) * da
    return float(np.linalg.norm(lateral)) * 1000.0 <= 0.001


def _unit_free(vector) -> np.ndarray:
    return np.array([vector.x, vector.y, vector.z], dtype=float)


def instance_groups(package: EvidencePackage, hole: Hole) -> list[list[FaceGeometry]]:
    """The hole's cylinder faces grouped by shared axis: one group per instance."""
    faces = {face.id: face for face in package.faces}
    groups: list[list[FaceGeometry]] = []
    for face_id in sorted(hole.face_ids):
        face = faces[face_id]
        if face.kind != "cylinder" or face.cylinder is None:
            continue
        for group in groups:
            if _same_axis(group[0], face):
                group.append(face)
                break
        else:
            groups.append([face])
    return groups


def diameters_mm(group: list[FaceGeometry]) -> list[float]:
    return sorted({round(face.cylinder.radius_m * 2000.0, 6) for face in group if face.cylinder})


# --- 1. the builders ----------------------------------------------------------------------


def two_part_builder() -> PackageBuilder:
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    plate = builder.document("FICT-KALO-0001", "part", material="Alloy Steel")
    cover = builder.document("FICT-KALO-0002", "part", material="6061-T6")
    builder.component(plate, name="FICT-KALO-0001-1")
    builder.component(cover, name="FICT-KALO-0002-1")
    return builder


def test_a_hole_feature_is_one_row_with_one_cylinder_face_per_instance() -> None:
    builder = two_part_builder()
    instances = [
        Instance(origin_mm=(10.0 * index, 0.0, 0.0), direction=Z, faces=(Face(2.5, -8.0, 0.0),))
        for index in range(15)
    ]
    hole_id = builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size="M3x0.5",
        thread="M3x0.5",
        thread_depth_mm=6.0,
        hole_depth_mm=8.0,
        end_condition="blind",
        instances=instances,
    )
    package = builder.build().package

    [hole] = package.holes
    assert hole.id == hole_id
    assert len(hole.face_ids) == 15
    groups = instance_groups(package, hole)
    assert len(groups) == 15
    # The row's axis is the first face's, which is what the extractor writes (R2.1).
    first = next(face for face in package.faces if face.id == hole.face_ids[0])
    assert first.cylinder is not None
    assert hole.axis.origin == first.cylinder.axis_origin
    assert hole.diameter is None, "the extractor reads no Hole Wizard diameter (R2.5)"


def test_a_counterbore_instance_is_two_coaxial_faces_with_two_diameters() -> None:
    builder = two_part_builder()
    counterbore = Instance(
        origin_mm=(0.0, 0.0, 0.0),
        direction=Z,
        faces=(Face(9.0, 0.0, 1.4), Face(14.0, 1.4, 10.0)),
    )
    builder.hole(
        "cmp:0002",
        hole_type="counterbore",
        size="M8",
        end_condition="through",
        instances=[counterbore, counterbore.moved((20.0, 0.0, 0.0))],
    )
    package = builder.build().package

    groups = instance_groups(package, package.holes[0])
    assert [diameters_mm(group) for group in groups] == [[9.0, 14.0], [9.0, 14.0]]


def test_a_face_bounding_box_is_the_exact_box_of_its_cylinder() -> None:
    builder = two_part_builder()
    tilted = (math.sin(math.radians(30.0)), 0.0, math.cos(math.radians(30.0)))
    face_id = builder.cylinder_face(
        "cmp:0001",
        origin_mm=(0.0, 0.0, 0.0),
        direction=tilted,
        diameter_mm=4.0,
        lo_mm=0.0,
        hi_mm=10.0,
    )
    face = next(face for face in builder.build().package.faces if face.id == face_id)

    # Along y the cylinder's rim reaches its full radius; along x and z, r * sin of the
    # angle to that axis, beyond the two end-circle centres.
    assert face.bbox.min.y == pytest.approx(-0.002)
    assert face.bbox.max.y == pytest.approx(0.002)
    assert face.bbox.max.x == pytest.approx(0.005 + 0.002 * math.cos(math.radians(30.0)))
    assert face.bbox.min.z == pytest.approx(-0.002 * math.sin(math.radians(30.0)))


def test_a_screw_is_named_in_the_vendor_shape_with_a_mesh_and_an_optional_face(
    tmp_path: Path,
) -> None:
    builder = two_part_builder()
    document = builder.screw_document("SHC", "M4-0.7", 12.0, serial=1)
    # The screw's own origin sits on its axis at the bearing point, z axis along the screw.
    with_face = builder.screw(document, bearing_mm=(0.0, 0.0, 5.0), direction=Z, shank_face_mm=3.3)
    without_face = builder.screw(document, bearing_mm=(30.0, 0.0, 5.0), direction=Z)
    built = builder.build()
    package = built.package

    doc = next(item for item in package.documents if item.document_id == document)
    assert doc.file_name == "SHC_M4-0.7X12_FICT-0001.SLDPRT"
    assert doc.custom_properties["Description"] == "SCREW, SOC M4-0.7 X 12 MM, FICTIONAL"
    assert doc.material == "Alloy Steel"
    placed = next(item for item in package.components if item.id == with_face)
    assert [row[3] for row in placed.transform[:3]] == pytest.approx([0.0, 0.0, 0.005])
    assert [row[2] for row in placed.transform[:3]] == pytest.approx([0.0, 0.0, 1.0])
    faces_by_component = Counter(face.component_id for face in package.faces)
    assert faces_by_component[with_face] == 1
    assert faces_by_component[without_face] == 0

    bodies = {body.component_id: body for body in package.bodies}
    built.write(tmp_path)
    mesh = load_mesh(tmp_path / bodies[with_face].mesh_file)
    low, high = mesh.bounds
    # The shank runs 12 mm below the under-head plane and the socket head 4 mm above it.
    assert low[2] == pytest.approx(-0.007)
    assert high[2] == pytest.approx(0.009)


def test_the_vendor_strings_have_the_shapes_the_recorded_packages_carry() -> None:
    assert screw_file_name("FHT", "M3-0.5", 10.0, 7) == "FHT_M3-0.5X10_FICT-0007.SLDPRT"
    assert screw_description("FHT", "M3-0.5", 10.0) == "SCREW, FLT M3-0.5 X 10 MM, FICTIONAL"
    assert screw_description("BHT", "M5-0.8", 10.0) == "SCREW, BTN M5-0.8 X 10 MM, FICTIONAL"


def test_interference_rows_carry_a_volume_the_possible_flag_and_the_settings() -> None:
    builder = two_part_builder()
    builder.interference("cmp:0001", "cmp:0002", volume_mm3=0.0)
    builder.interference(
        "cmp:0001", "cmp:0002", volume_mm3=None, is_possible=True, group_key="pat:fict"
    )
    rows = builder.build().package.interferences

    assert [row.volume.value if row.volume else None for row in rows] == [0.0, None]
    assert [row.is_possible for row in rows] == [False, True]
    assert rows[0].settings == rows[1].settings
    assert rows[0].group_key == "cmp:0001|cmp:0002"


def test_the_builders_write_schema_1_4_0_whatever_the_models_default_to() -> None:
    """Pinned to the string, not `SCHEMA_VERSION`: a later IR minor must not rewrite these
    fixtures under the regeneration test (FR-028)."""
    package = two_part_builder().build().package
    assert package.schema_version == FIXTURE_SCHEMA_VERSION == "1.4.0"
    EvidencePackage.model_validate_json(package.model_dump_json())


# --- 2. the generator reproduces every committed byte ------------------------------------


def test_re_running_the_generator_reproduces_every_committed_fixture_byte_for_byte() -> None:
    rendered = generator().render_all()

    committed = {
        path.relative_to(FIXTURES).as_posix(): as_committed(path)
        for path in sorted(FIXTURES.rglob("*"))
        if path.is_file() and path.parent != FIXTURES and "__pycache__" not in path.parts
    }
    assert sorted(rendered) == sorted(committed), "the generator and the tree name different files"
    drifted = [name for name, content in rendered.items() if committed[name] != content]
    assert drifted == [], "regenerate with generate_fixtures.py; never edit a fixture by hand"


def as_committed(path: Path) -> bytes:
    """A fixture file's bytes as git stores them.

    `.gitattributes` marks `*.json` as text, so a Windows checkout with `core.autocrlf` may
    hand the file back with CRLF endings; the generator writes LF, which is what the blob
    holds. A GLB is binary and compared untouched.
    """
    content = path.read_bytes()
    return content if path.suffix == ".glb" else content.replace(b"\r\n", b"\n")


# --- 3. the big fixture: the counts of contracts/fixtures.md section 2 --------------------


def test_the_big_fixture_has_the_recorded_document_and_component_counts(
    big: EvidencePackage,
) -> None:
    kinds = Counter(document.kind for document in big.documents)
    assert len(big.documents) == 26
    assert kinds == {"part": 23, "assembly": 3}
    assert len(big.components) == 89
    assert Counter(item.suppression for item in big.components) == {
        "resolved": 86,
        "lightweight": 2,
        "suppressed": 1,
    }
    assert {entry.document_id for entry in big.manifest.entries} == {
        document.document_id for document in big.documents
    }


def test_the_big_fixture_has_27_hole_rows_and_132_instances(big: EvidencePackage) -> None:
    per_hole = {hole.id: len(instance_groups(big, hole)) for hole in big.holes}

    assert len(big.holes) == 27
    assert sum(per_hole.values()) == 132
    assert sorted(hole_id for hole_id, count in per_hole.items() if count == 0) == [
        "hol:0007",
        "hol:0009",
    ]
    assert {
        hole_id: per_hole[hole_id]
        for hole_id in ("hol:0014", "hol:0016", "hol:0019", "hol:0023", "hol:0008", "hol:0003")
    } == {
        "hol:0014": 15,
        "hol:0016": 16,
        "hol:0019": 15,
        "hol:0023": 16,
        "hol:0008": 9,
        "hol:0003": 8,
    }
    assert Counter(hole.hole_type for hole in big.holes) == {
        "tapped": 12,
        "clearance": 7,
        "counterbore": 5,
        "countersink": 3,
    }
    assert all(hole.diameter is None for hole in big.holes)


def screws(package: EvidencePackage) -> dict[str, str]:
    """`{component id: head code}` for every component whose document is vendor-named."""
    documents = {document.document_id: document for document in package.documents}
    found = {}
    for component in package.components:
        name = documents[component.document_id].file_name
        head = name.split("_", 1)[0]
        if head in {"SHC", "FHT", "BHT"}:
            found[component.id] = head
    return found


def test_the_big_fixture_names_68_screws_over_9_documents(big: EvidencePackage) -> None:
    named = screws(big)
    components = {component.id: component for component in big.components}

    assert len(named) == 68
    assert Counter(named.values()) == {"SHC": 32, "FHT": 35, "BHT": 1}
    assert len({components[item].document_id for item in named}) == 9
    documents = {document.document_id: document for document in big.documents}
    assert all(documents[components[item].document_id].material for item in named)
    not_default = [item for item in named if components[item].referenced_configuration != "Default"]
    assert len(not_default) == 36
    assert not any(component.is_toolbox for component in big.components)
    assert big.fasteners == []

    with_faces = {face.component_id for face in big.faces} & set(named)
    assert len(with_faces) == 11
    meshed = {body.component_id for body in big.bodies}
    assert set(named) <= meshed, "68 of 68 screws have a body mesh"


def test_the_big_fixture_has_two_pins_with_no_face(big: EvidencePackage) -> None:
    documents = {document.document_id: document for document in big.documents}
    pins = [
        component
        for component in big.components
        if documents[component.document_id].file_name.startswith("FICT-PIN")
    ]
    faced = {face.component_id for face in big.faces}
    assert len(pins) == 2
    assert all(pin.id not in faced for pin in pins)


def test_the_big_fixture_has_113_interference_groups_eight_of_them_positive(
    big: EvidencePackage,
) -> None:
    groups = group_interferences(big)

    def positive(group) -> bool:
        return any(
            item.volume is not None and volume_mm3(item.volume) > 1e-6
            for item in group.interferences
        )

    assert len(groups) == 113
    assert sum(1 for group in groups if positive(group)) == 8
    mixed = [
        group
        for group in groups
        if positive(group)
        and any(
            item.volume is not None and item.volume.value == 0.0 for item in group.interferences
        )
    ]
    assert len(mixed) == 1
    contacts = [group for group in groups if not positive(group)]
    assert len(contacts) == 105
    assert all(group.status == "computed" for group in groups)
    possible_only = [
        group
        for group in contacts
        if all(item.volume is None and item.is_possible for item in group.interferences)
    ]
    assert possible_only, "some contact groups carry only the possible-interference flag"
    assert {
        item.volume.unit for group in contacts for item in group.interferences if item.volume
    } == {"mm3", "in3", "m3"}


# --- 3b. the big fixture's case rows -------------------------------------------------------


def hole(package: EvidencePackage, hole_id: str) -> Hole:
    return next(item for item in package.holes if item.id == hole_id)


def test_the_dowel_holes_are_plain_diameters_of_3_0_and_3_1_mm(big: EvidencePackage) -> None:
    for hole_id, bore in (("hol:0017", 3.0), ("hol:0018", 3.1), ("hol:0027", 3.0)):
        row = hole(big, hole_id)
        assert row.size == "Ø3.0"
        assert row.hole_type == "clearance"
        assert {d for group in instance_groups(big, row) for d in diameters_mm(group)} == {bore}
    assert hole(big, "hol:0017").component_id == hole(big, "hol:0018").component_id == "cmp:0004"


def test_the_m5_tapped_hole_under_the_m4_screw_is_oblique(big: EvidencePackage) -> None:
    row = hole(big, "hol:0013")
    [group] = instance_groups(big, row)
    direction = _unit(group[0].cylinder.axis_dir)

    assert row.thread_designation == "M5x0.8"
    assert math.degrees(math.acos(abs(direction[2]))) == pytest.approx(30.0)


def test_the_thin_sheet_is_through_tapped_1_725_mm_long(big: EvidencePackage) -> None:
    row = hole(big, "hol:0021")
    [[face]] = instance_groups(big, row)

    assert (row.end_condition, row.thread_designation, row.thread_depth) == (
        "through",
        "M3x0.5",
        None,
    )
    assert (face.bbox.max.z - face.bbox.min.z) * 1000.0 == pytest.approx(1.725)


def test_the_counterbores_are_14_mm_and_12_mm_over_a_9_mm_bore(big: EvidencePackage) -> None:
    assert diameters_mm(instance_groups(big, hole(big, "hol:0024"))[0]) == [9.0, 14.0]
    assert diameters_mm(instance_groups(big, hole(big, "hol:0025"))[0]) == [9.0, 12.0]


def documents_by_stem(package: EvidencePackage) -> dict[str, object]:
    return {document.file_name.rsplit(".", 1)[0]: document for document in package.documents}


def test_the_named_m5_screw_has_a_3_3_mm_shank(big: EvidencePackage) -> None:
    documents = {document.document_id: document for document in big.documents}
    named_m5 = [
        component
        for component in big.components
        if documents[component.document_id].file_name.startswith("SHC_M5-0.8X20_")
    ]
    [component] = named_m5
    [face] = [face for face in big.faces if face.component_id == component.id]
    assert face.cylinder is not None
    assert face.cylinder.radius_m * 2000.0 == pytest.approx(3.3)


def densities(package: EvidencePackage) -> dict[str, float]:
    return {
        document.file_name: document.mass.mass_kg / document.mass.volume_m3
        for document in package.documents
        if document.kind == "part" and document.mass is not None and document.mass.volume_m3 > 0
    }


def test_the_big_fixture_carries_the_mass_and_material_cases(big: EvidencePackage) -> None:
    by_density = densities(big)
    values = sorted(round(value) for value in by_density.values())

    assert 2700 in values and 7850 in values and 1000 in values
    no_material = [
        document for document in big.documents if document.kind == "part" and not document.material
    ]
    assert len(no_material) == 4, "3 unopened and 1 surface-only"
    assert sum(1 for gap in big.gaps if gap.entity_kind == "mass_override") == 23
    assert sum(1 for gap in big.gaps if gap.entity_kind == "document") == 3
    sub = [
        document
        for document in big.documents
        if document.kind == "assembly"
        and document.mass is not None
        and document.mass.mass_kg == 2.0
    ]
    assert len(sub) == 1
    [sub_assembly] = sub
    instance = next(item for item in big.components if item.document_id == sub_assembly.document_id)
    children = [item for item in big.components if item.parent_id == instance.id]
    assert {item.suppression for item in children} == {"lightweight", "suppressed"}


def test_the_big_fixture_carries_the_hygiene_cases(big: EvidencePackage) -> None:
    part_number, summary, revision = mechanical.HYGIENE_PROPERTIES
    opened = [document for document in big.documents if document.custom_properties]
    mismatched = [
        document
        for document in opened
        if part_number in document.custom_properties
        and document.custom_properties[part_number] != document.file_name.rsplit(".", 1)[0]
    ]
    assert len(mismatched) == 1
    shared = Counter(
        document.custom_properties[summary]
        for document in opened
        if summary in document.custom_properties
    )
    assert sorted(count for count in shared.values() if count > 1) == [2]
    assert sum(1 for document in opened if revision not in document.custom_properties) == 1


def test_every_path_in_the_fixtures_is_under_the_fictional_root(
    big: EvidencePackage, small: EvidencePackage
) -> None:
    for package in (big, small):
        assert all(document.path.startswith(FICTIONAL_ROOT) for document in package.documents)
        assert all(
            entry.vault_path.startswith(FICTIONAL_ROOT) for entry in package.manifest.entries
        )


# --- 4. the small fixture ---------------------------------------------------------------


def test_the_small_fixture_has_the_recorded_counts(small: EvidencePackage) -> None:
    assert len(small.documents) == 3
    assert len(small.components) == 4
    assert len(small.holes) == 4
    assert sum(len(instance_groups(small, row)) for row in small.holes) == 16
    assert len({row.component_id for row in small.holes}) == 1, "no hole pair across parts"


def test_the_small_fixture_seats_a_3_mm_pin_in_a_3_mm_hole(small: EvidencePackage) -> None:
    row = hole(small, "hol:0004")
    first = instance_groups(small, row)[0][0]
    pin_faces = [face for face in small.faces if face.id not in row.face_ids]
    [pin] = [face for face in pin_faces if face.component_id == "cmp:0003"]
    assert first.cylinder is not None and pin.cylinder is not None

    assert pin.cylinder.radius_m == first.cylinder.radius_m == pytest.approx(0.0015)
    assert _same_axis(first, pin)
    overlap = min(first.bbox.max.z, pin.bbox.max.z) - max(first.bbox.min.z, pin.bbox.min.z)
    assert overlap * 1000.0 == pytest.approx(8.475)


def test_the_small_fixture_has_two_zero_volume_rows_between_the_pin_and_the_plate(
    small: EvidencePackage,
) -> None:
    [group] = group_interferences(small)
    assert group.component_ids == ["cmp:0001", "cmp:0003"]
    assert [item.volume.value for item in group.interferences if item.volume] == [0.0, 0.0]


def test_the_small_assembly_weighs_its_part_plus_two_pins(small: EvidencePackage) -> None:
    documents = {document.document_id: document for document in small.documents}
    root = documents[small.design.root_assembly_document_id]
    resolved = [item for item in small.components if item.suppression == "resolved"]
    total = sum(documents[item.document_id].mass.mass_kg for item in resolved)

    assert root.mass is not None
    assert root.mass.mass_kg == pytest.approx(total)
    assert sorted(documents[item.document_id].kind for item in resolved) == ["part"] * 3
