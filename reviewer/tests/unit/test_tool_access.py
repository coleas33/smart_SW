"""Tool access and head fit (feature 010 T058 and T060, `contracts/tool-access.md`).

- The head is the screw's end away from its tapped hole, and the tool approaches from there.
- The head plane is the far end of the screw's mesh, else its shank face plus the head
  height from the head table (derived), else unresolved.
- The tool comes from the drive, else the head type, else unresolved naming the head code;
  radius and reach are the pilot defaults of `tool_envelopes.yaml`.
- The envelope is swept outward over every other component's mesh; a body in the way is
  named with its distance, an unloadable one makes the sweep unresolved, and with lazy
  meshes a body never fetched is named, never assumed clear.
- Head fit compares a counterbore or countersink with the largest head the standard allows.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from swreview.agent.settings import ExtractionSettings
from swreview.checks.fastener_identity import recognise_fasteners
from swreview.checks.joints import Joint, build_joint_map
from swreview.checks.tool_access import (
    CHECK_HEAD_FIT,
    check_head_fit,
    choose_tool,
    head_geometry,
    sweep_head,
)
from swreview.ir.models import Angle, EvidencePackage, HoleWizardData, Quantity
from swreview.tools.checks_mechanical import check_joints
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.joint_context import BodyMeshes
from tests.support.mechanical import Built, Face, Instance, PackageBuilder, box_mesh

Z = (0.0, 0.0, 1.0)
MINUS_Z = (0.0, 0.0, -1.0)
TILT = (math.sin(math.radians(30.0)), 0.0, math.cos(math.radians(30.0)))
Box = tuple[tuple[float, float, float], tuple[float, float, float]]


def screw_over_plate(
    *,
    head: str = "SHC",
    thread: str = "M5-0.8",
    direction: tuple[float, float, float] = Z,
    shank_face_mm: float | None = None,
    blocker: Box | None = None,
    counterbore: tuple[float, float] | None = None,
    wizard: HoleWizardData | None = None,
    directory: Path | None = None,
) -> tuple[EvidencePackage, Joint]:
    """A plate with a blind tapped hole on the axis `direction` through the origin, a 16 mm
    screw bearing 10 mm out along it, optionally a counterbored cover over the tapped hole
    (diameter, depth), and optionally a box another component occupies. With `directory`,
    the package and its meshes are written there, so a context can load the meshes."""
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    plate = builder.document("FICT-KALOMIR-0001", "part", material="Alloy Steel")
    builder.component(plate, component_id="cmp:0001")
    size = thread.replace("-", "x")
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size=size,
        thread=size,
        thread_depth_mm=10.0,
        end_condition="blind",
        instances=[Instance((0.0, 0.0, 0.0), direction, (Face(4.2, -12.0, 0.0),))],
    )
    if counterbore is not None:
        cover = builder.document("FICT-KALOSORN-0003", "part", material="6061-T6")
        builder.component(cover, component_id="cmp:0003")
        diameter, depth = counterbore
        builder.hole(
            "cmp:0003",
            hole_type="counterbore",
            size="M5",
            end_condition="through",
            instances=[
                Instance(
                    (0.0, 0.0, 0.0),
                    direction,
                    (Face(5.5, 0.0, 10.0 - depth), Face(diameter, 10.0 - depth, 10.0)),
                )
            ],
        )
    screw_document = builder.screw_document(head, thread, 16.0, serial=1)  # type: ignore[arg-type]
    unit = np.array(direction) / np.linalg.norm(direction)
    builder.screw(
        screw_document,
        bearing_mm=tuple(float(value) for value in unit * 10.0),  # type: ignore[arg-type]
        direction=direction,
        component_id="cmp:0002",
        shank_face_mm=shank_face_mm,
    )
    if blocker is not None:
        other = builder.document("FICT-KALOVEN-0009", "part", material="6061-T6")
        builder.component(other, component_id="cmp:0009")
        builder.mesh("cmp:0009", box_mesh(*blocker))
    built = builder.build()
    package = built.package
    if wizard is not None:
        holes = [
            hole.model_copy(update={"wizard": wizard}) if hole.hole_type == "counterbore" else hole
            for hole in package.holes
        ]
        package = package.model_copy(update={"holes": holes})
    if directory is not None:
        Built(package=package, meshes=built.meshes).write(directory)
    joints = build_joint_map(package, fasteners=recognise_fasteners(package)).joints
    [joint] = [item for item in joints if item.fastener is not None]
    return package, joint


def meshes(package: EvidencePackage, directory: Path) -> BodyMeshes:
    return BodyMeshes(context_for(package, base_dir=directory))


def others(package: EvidencePackage, loaded: BodyMeshes) -> list[tuple[str, Any]]:
    ids = sorted({body.component_id for body in package.bodies} - {"cmp:0002"})
    return [(cid, loaded.mesh_of(cid)) for cid in ids]


# --- the head --------------------------------------------------------------------------------


def test_the_head_plane_is_the_far_end_of_the_mesh_and_the_tool_comes_from_outside(
    tmp_path: Path,
) -> None:
    """An SHC M5x16 bearing at 10: shank to -6, head to 10 + 5 = 15 along the axis."""
    package, joint = screw_over_plate(directory=tmp_path)

    head = head_geometry(joint, package, meshes(package, tmp_path).mesh_of("cmp:0002"))

    assert not isinstance(head, str)
    assert head.source == "mesh"
    assert head.plane_mm == pytest.approx(15.0)
    assert np.allclose(head.outward, [0.0, 0.0, 1.0])


def test_the_outward_direction_points_away_from_the_tapped_hole(tmp_path: Path) -> None:
    package, joint = screw_over_plate(direction=MINUS_Z, directory=tmp_path)

    head = head_geometry(joint, package, meshes(package, tmp_path).mesh_of("cmp:0002"))

    assert not isinstance(head, str)
    assert np.allclose(head.outward, [0.0, 0.0, -1.0])
    assert head.plane_mm == pytest.approx(15.0)


def test_without_a_mesh_the_head_plane_is_the_shank_face_plus_k_labelled_derived() -> None:
    package, joint = screw_over_plate(shank_face_mm=5.0)

    head = head_geometry(joint, package, None)

    assert not isinstance(head, str)
    assert head.source == "face_plus_k"
    assert head.plane_mm == pytest.approx(10.0 + 5.0)
    assert head.description.startswith("derived: the far end of shank face")
    assert "ISO 4762" in head.description


def test_no_mesh_and_no_face_is_unresolved() -> None:
    package, joint = screw_over_plate()

    assert head_geometry(joint, package, None) == (
        "the screw has no exported mesh and no extracted face"
    )


def test_a_face_with_no_head_row_is_unresolved_naming_the_head() -> None:
    package, joint = screw_over_plate(head="FHT", shank_face_mm=5.0)

    assert head_geometry(joint, package, None) == (
        "the head of a flat head M5x0.8 screw is not in head_dimensions.yaml"
    )


def test_an_oblique_face_is_not_used_but_an_oblique_mesh_is(tmp_path: Path) -> None:
    package, joint = screw_over_plate(direction=TILT, shank_face_mm=5.0, directory=tmp_path)

    assert "oblique" in str(head_geometry(joint, package, None))
    head = head_geometry(joint, package, meshes(package, tmp_path).mesh_of("cmp:0002"))
    assert not isinstance(head, str)
    assert head.plane_mm == pytest.approx(15.0, abs=1e-3)


# --- the tool --------------------------------------------------------------------------------


def test_the_tool_comes_from_the_drive() -> None:
    socket = choose_tool(screw_over_plate()[1].fastener)  # type: ignore[arg-type]
    torx = choose_tool(screw_over_plate(head="BHT")[1].fastener)  # type: ignore[arg-type]

    assert not isinstance(socket, str) and not isinstance(torx, str)
    assert (socket.tool, socket.reason) == ("hex_key", "drive")
    assert socket.radius_mm == pytest.approx(0.6 * 5.0 / 2.0 + 0.5)
    assert socket.reach_mm == pytest.approx(25.0)
    assert socket.sources[0].startswith("pilot default")
    assert (torx.tool, torx.radius_mm) == ("torx_key", pytest.approx(1.0 * 5.0 / 2.0 + 0.5))


def test_the_tool_comes_from_the_head_type_when_no_drive_is_stated() -> None:
    placed = screw_over_plate()[1].fastener
    assert placed is not None
    worded = replace(placed, fastener=placed.fastener.model_copy(update={"drive": None}))

    tool = choose_tool(worded)

    assert not isinstance(tool, str)
    assert (tool.tool, tool.reason) == ("hex_key", "head_type")


def test_no_drive_and_no_head_tool_is_unresolved_naming_the_head_code() -> None:
    placed = screw_over_plate(head="FHT")[1].fastener
    assert placed is not None
    unknown = replace(placed, fastener=placed.fastener.model_copy(update={"drive": None}))

    assert choose_tool(unknown) == (
        "the drive of head code FHT is not stated in fastener_names.yaml, and no tool is named "
        "for its head type"
    )


def test_a_screw_whose_size_is_contradicted_gets_no_tool() -> None:
    placed = screw_over_plate(shank_face_mm=3.3)[1].fastener
    assert placed is not None and not placed.size_trusted

    assert "is not known well enough to size a tool" in str(choose_tool(placed))


# --- the sweep ----------------------------------------------------------------------------------


def test_a_body_over_the_head_is_named_with_its_distance(tmp_path: Path) -> None:
    package, joint = screw_over_plate(
        blocker=((-5.0, -5.0, 20.0), (5.0, 5.0, 25.0)), directory=tmp_path
    )
    loaded = meshes(package, tmp_path)

    sweep = sweep_head(
        joint, package, screw_mesh=loaded.mesh_of("cmp:0002"), others=others(package, loaded)
    )

    assert sweep.envelope is not None
    [hit] = sweep.envelope.hits
    assert hit.component_id == "cmp:0009"
    assert hit.first_hit_distance_m * 1000.0 == pytest.approx(5.0, abs=1e-3)
    assert sweep.inputs["tool"] == "hex_key"
    assert sweep.inputs["head_plane_source"] == (
        "the far end of the screw's exported mesh (supplementary geometry)"
    )


def test_the_screws_own_mesh_and_a_body_beside_the_envelope_are_not_hits(
    tmp_path: Path,
) -> None:
    package, joint = screw_over_plate(
        blocker=((20.0, -5.0, 10.0), (30.0, 5.0, 40.0)), directory=tmp_path
    )
    loaded = meshes(package, tmp_path)

    sweep = sweep_head(
        joint, package, screw_mesh=loaded.mesh_of("cmp:0002"), others=others(package, loaded)
    )

    assert sweep.envelope is not None
    assert sweep.envelope.hits == [] and sweep.envelope.unresolved == []


def test_a_body_beyond_the_reach_is_not_a_hit(tmp_path: Path) -> None:
    """Reach for a hex key on an M5 is 5 x 5 = 25 mm from the head plane at 15."""
    package, joint = screw_over_plate(
        blocker=((-5.0, -5.0, 41.0), (5.0, 5.0, 45.0)), directory=tmp_path
    )
    loaded = meshes(package, tmp_path)

    sweep = sweep_head(
        joint, package, screw_mesh=loaded.mesh_of("cmp:0002"), others=others(package, loaded)
    )

    assert sweep.envelope is not None and sweep.envelope.hits == []


def test_an_unloadable_mesh_is_unresolved_naming_it(tmp_path: Path) -> None:
    package, joint = screw_over_plate(directory=tmp_path)

    sweep = sweep_head(
        joint,
        package,
        screw_mesh=meshes(package, tmp_path).mesh_of("cmp:0002"),
        others=[("cmp:0009", None)],
    )

    assert sweep.envelope is not None
    assert sweep.envelope.unresolved == ["missing mesh for component cmp:0009"]


def test_a_lazy_body_never_fetched_is_named(tmp_path: Path) -> None:
    package, joint = screw_over_plate(directory=tmp_path)

    sweep = sweep_head(
        joint,
        package,
        screw_mesh=meshes(package, tmp_path).mesh_of("cmp:0002"),
        others=[],
        unfetched=["cmp:0004"],
    )

    assert sweep.envelope is not None
    assert sweep.envelope.unresolved == [
        "cmp:0004: its body was never fetched (lazy meshes, lever 10a), so it was not swept"
    ]


def test_no_head_is_a_sweep_that_says_why() -> None:
    package, joint = screw_over_plate()

    sweep = sweep_head(joint, package, screw_mesh=None, others=[])

    assert sweep.envelope is None
    assert sweep.missing == "the screw has no exported mesh and no extracted face"


# --- through check_joints ----------------------------------------------------------------------


def head_clearance(context: ToolContext) -> list:
    return [
        finding
        for finding in context.require_session().findings
        if finding.check == "fastener.head_clearance"
    ]


def run(context: ToolContext) -> None:
    with use_context(context):
        check_joints()


def test_check_joints_demonstrates_a_blocked_head_naming_the_body(tmp_path: Path) -> None:
    package, _ = screw_over_plate(
        blocker=((-5.0, -5.0, 20.0), (5.0, 5.0, 25.0)), directory=tmp_path
    )
    context = context_for(package, base_dir=tmp_path)

    run(context)

    [finding] = head_clearance(context)
    assert (finding.status, finding.severity) == ("demonstrated", "medium")
    assert "runs into cmp:0009 at 5.0 mm" in finding.observed
    assert finding.calculation.inputs["tool"] == "hex_key"
    assert finding.calculation.inputs["tool_reach"] == Quantity(value=25.0, unit="mm")


def test_a_missing_head_is_an_unresolved_head_clearance_saying_why(tmp_path: Path) -> None:
    """A mesh file that is not on disk leaves the screw with no mesh and no face."""
    package, _ = screw_over_plate()
    context = context_for(package, base_dir=tmp_path)

    run(context)

    [finding] = head_clearance(context)
    assert finding.status == "unresolved"
    assert "(the screw has no exported mesh and no extracted face)" in finding.observed


def test_a_package_with_no_body_mesh_is_one_skipped_head_clearance_item() -> None:
    package, _ = screw_over_plate(shank_face_mm=5.0)
    context = context_for(package.model_copy(update={"bodies": []}))

    run(context)

    assert head_clearance(context) == []
    [item] = [
        item
        for item in context.require_session().coverage.skipped
        if item.check == "fastener.head_clearance"
    ]
    assert "(the package holds no body mesh)" in item.reason


def test_lazy_meshes_name_the_parts_whose_bodies_were_never_fetched(tmp_path: Path) -> None:
    package, _ = screw_over_plate(directory=tmp_path)
    bodies = [body for body in package.bodies if body.component_id != "cmp:0001"]
    context = context_for(package.model_copy(update={"bodies": bodies}), base_dir=tmp_path)
    context.extraction = ExtractionSettings(meshes="lazy")

    run(context)

    [finding] = head_clearance(context)
    assert finding.status == "unresolved"
    assert any("cmp:0001: its body was never fetched" in limit for limit in finding.coverage_limits)


# --- head fit ---------------------------------------------------------------------------------


def test_a_counterbore_that_takes_the_head_passes_with_both_numbers() -> None:
    package, joint = screw_over_plate(counterbore=(9.0, 5.5))

    result = check_head_fit(joint, package)

    assert result is not None
    assert (result.check, result.status) == (CHECK_HEAD_FIT, "checked_within_scope")
    assert result.calculation is not None
    assert result.calculation.result["recess_diameter_mm"] == 9.0
    assert result.calculation.result["recess_depth_mm"] == 5.5
    assert (result.calculation.result["dk_max_mm"], result.calculation.result["k_max_mm"]) == (
        8.5,
        5.0,
    )
    assert result.calculation.inputs["recess_depth_source"] == (
        "derived: the counterbore face's axial extent"
    )


def test_a_counterbore_narrower_than_the_head_is_demonstrated() -> None:
    package, joint = screw_over_plate(counterbore=(8.0, 5.5))

    result = check_head_fit(joint, package)

    assert result is not None
    assert (result.status, result.severity) == ("demonstrated", "high")
    assert "is smaller than the 8.5 mm head" in result.observed


def test_a_counterbore_shallower_than_the_head_leaves_it_proud() -> None:
    package, joint = screw_over_plate(counterbore=(9.0, 4.0))

    result = check_head_fit(joint, package)

    assert result is not None
    assert (result.status, result.severity) == ("demonstrated", "medium")
    assert "the head stands 1.0 mm proud" in result.observed


def test_the_hole_wizard_sizes_win_over_the_faces() -> None:
    wizard = HoleWizardData(
        counterbore_diameter=Quantity(value=0.0095, unit="m"),
        counterbore_depth=Quantity(value=0.0052, unit="m"),
    )
    package, joint = screw_over_plate(counterbore=(8.0, 4.0), wizard=wizard)

    result = check_head_fit(joint, package)

    assert result is not None and result.status == "checked_within_scope"
    assert result.calculation is not None
    assert result.calculation.inputs["recess_diameter_source"] == (
        "the Hole Wizard counterbore diameter"
    )
    assert result.calculation.result["recess_depth_mm"] == 5.2


def test_an_oblique_counterbore_depth_is_unresolved() -> None:
    package, joint = screw_over_plate(direction=TILT, counterbore=(9.0, 5.5))

    result = check_head_fit(joint, package)

    assert result is not None and result.status == "unresolved"
    assert "the axis is oblique" in result.observed


def _countersunk(wizard: HoleWizardData | None = None) -> tuple[EvidencePackage, Joint]:
    """An M5 socket countersunk head (ISO 10642, dk 11.2, 90 degrees) in a countersink."""
    package, _ = screw_over_plate(counterbore=(9.0, 5.5))
    holes = [
        hole.model_copy(update={"hole_type": "countersink", "wizard": wizard})
        if hole.hole_type == "counterbore"
        else hole
        for hole in package.holes
    ]
    package = package.model_copy(update={"holes": holes})
    joints = build_joint_map(package, fasteners=recognise_fasteners(package)).joints
    [joint] = [item for item in joints if item.fastener is not None]
    placed = joint.fastener
    assert placed is not None
    countersunk = replace(
        placed,
        fastener=placed.fastener.model_copy(update={"head_type": "socket countersunk head"}),
    )
    return package, replace(joint, fastener=countersunk)


def test_a_countersink_is_unresolved_without_the_hole_wizard_diameter() -> None:
    package, joint = _countersunk()

    result = check_head_fit(joint, package)

    assert result is not None and result.status == "unresolved"
    assert "the countersink diameter of" in result.observed


@pytest.mark.parametrize(
    ("diameter_m", "angle_deg", "status"),
    [
        (0.0115, 90.0, "checked_within_scope"),
        (0.0105, 90.0, "demonstrated"),
        (0.0115, 82.0, "demonstrated"),
    ],
)
def test_a_countersink_against_the_countersunk_head(
    diameter_m: float, angle_deg: float, status: str
) -> None:
    wizard = HoleWizardData(
        countersink_diameter=Quantity(value=diameter_m, unit="m"),
        countersink_angle=Angle(value=math.radians(angle_deg), unit="rad"),
    )
    package, joint = _countersunk(wizard)

    result = check_head_fit(joint, package)

    assert result is not None and result.status == status


def test_a_head_the_table_lacks_is_unresolved_naming_it() -> None:
    package, joint = screw_over_plate(head="FHT", counterbore=(9.0, 5.5))

    result = check_head_fit(joint, package)

    assert result is not None and result.status == "unresolved"
    assert "the head of a flat head M5x0.8 screw (head_dimensions.yaml carries no row" in (
        result.observed
    )


def test_a_joint_with_no_recess_has_no_head_fit() -> None:
    package, joint = screw_over_plate()

    assert check_head_fit(joint, package) is None
