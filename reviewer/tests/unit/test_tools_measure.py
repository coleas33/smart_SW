"""Unit tests for the measurement tools (T090).

The four rows of the "Measurement tools" table in contracts/agent-tools.md. They are the
only tools that read geometry, so these tests pin what makes that safe:

- every argument is an id resolved against the package; an id that names nothing comes
  back as an error result, never as a measurement;
- a pair the model cannot handle is `unsupported`, and a body whose mesh is missing is
  `unresolved` naming it - neither is ever rounded down to "clear" (Principle I);
- every number carries its unit, and the frame it was measured in.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import trimesh
from anthropic.lib.tools import ToolError

from swreview.ir.models import (
    Axis,
    BBox3D,
    BodyRef,
    CylinderFace,
    EvidencePackage,
    FaceGeometry,
    Fastener,
    Hole,
    PlaneFace,
    Quantity,
    Vec3,
)
from swreview.tools import measure
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.registry import RecordedTool, ToolRegistry
from tests.support.packages import persist_ref

MakePackage = Callable[..., EvidencePackage]

MESH_DIR = "meshes"


def vec(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Vec3:
    return Vec3(x=x, y=y, z=z)


def axis(origin: Vec3, direction: Vec3) -> Axis:
    return Axis(origin=origin, direction=direction)


def hole(hole_id: str, component_id: str, hole_axis: Axis) -> Hole:
    return Hole(
        id=hole_id,
        persist_ref=persist_ref(hole_id),
        persist_ref_scope="doc:2",
        component_id=component_id,
        feature_name=f"{hole_id} feature",
        hole_type="clearance",
        standard=None,
        size=None,
        thread_designation=None,
        thread_depth=None,
        hole_depth=Quantity(value=10.0, unit="mm"),
        end_condition="through",
        diameter=Quantity(value=6.6, unit="mm"),
        axis=hole_axis,
        face_ids=[],
    )


def plane_face(face_id: str, component_id: str, z_m: float) -> FaceGeometry:
    return FaceGeometry(
        id=face_id,
        persist_ref=persist_ref(face_id),
        persist_ref_scope="doc:2",
        component_id=component_id,
        body_id="bod:1",
        kind="plane",
        cylinder=None,
        plane=PlaneFace(origin=vec(z=z_m), normal=vec(z=1.0)),
        bbox=BBox3D(min=vec(-0.05, -0.05, z_m), max=vec(0.05, 0.05, z_m)),
        area_m2=0.01,
    )


def cylinder_face(face_id: str, component_id: str, radius_m: float) -> FaceGeometry:
    return FaceGeometry(
        id=face_id,
        persist_ref=persist_ref(face_id),
        persist_ref_scope="doc:2",
        component_id=component_id,
        body_id="bod:1",
        kind="cylinder",
        cylinder=CylinderFace(axis_origin=vec(), axis_dir=vec(z=1.0), radius_m=radius_m),
        plane=None,
        bbox=BBox3D(min=vec(-radius_m, -radius_m, 0.0), max=vec(radius_m, radius_m, 0.02)),
        area_m2=0.001,
    )


def cone_face(face_id: str, component_id: str) -> FaceGeometry:
    return FaceGeometry(
        id=face_id,
        persist_ref=persist_ref(face_id),
        persist_ref_scope="doc:2",
        component_id=component_id,
        body_id="bod:1",
        kind="cone",
        cylinder=None,
        plane=None,
        bbox=BBox3D(min=vec(), max=vec(0.01, 0.01, 0.01)),
        area_m2=0.0005,
    )


def body(body_id: str, component_id: str, mesh_file: str) -> BodyRef:
    return BodyRef(
        id=body_id,
        persist_ref=persist_ref(body_id),
        persist_ref_scope="doc:1",
        component_id=component_id,
        mesh_file=mesh_file,
        triangle_count=12,
        is_solid=True,
    )


def screw(
    fastener_id: str,
    component_id: str,
    fastener_axis: Axis,
    designation: str | None,
) -> Fastener:
    return Fastener(
        id=fastener_id,
        persist_ref=persist_ref(fastener_id),
        persist_ref_scope="doc:1",
        component_id=component_id,
        kind="screw",
        identity_source="toolbox",
        thread_designation=designation,
        length=Quantity(value=20.0, unit="mm"),
        head_type="socket head cap",
        head_diameter=Quantity(value=10.0, unit="mm"),
        head_height=Quantity(value=6.0, unit="mm"),
        drive="hex",
        axis=fastener_axis,
        material=None,
    )


def geometry_package(make_package: MakePackage) -> EvidencePackage:
    """`make_package` plus the holes, faces, bodies and fasteners these tests measure."""
    up = vec(z=1.0)
    return make_package(
        holes=[
            hole("hole:a", "cmp:0001", axis(vec(), up)),
            # 2 mm away and parallel.
            hole("hole:b", "cmp:0002", axis(vec(x=0.002), up)),
            # Rotated 90 degrees about x and offset: skew.
            hole("hole:c", "cmp:0002", axis(vec(x=0.004, z=0.01), vec(y=1.0))),
            hole("hole:d", "cmp:0002", axis(vec(), vec())),
        ],
        faces=[
            plane_face("face:a", "cmp:0001", 0.0),
            plane_face("face:b", "cmp:0002", 0.005),
            cylinder_face("face:c", "cmp:0001", 0.02),
            cylinder_face("face:d", "cmp:0002", 0.0205),
            cone_face("face:e", "cmp:0002"),
        ],
        bodies=[
            body("bod:1", "cmp:0001", f"{MESH_DIR}/blocker.glb"),
            body("bod:2", "cmp:0001", f"{MESH_DIR}/absent.glb"),
        ],
        fasteners=[
            # Head at z = 20 mm looking down: the tool sweeps up, away from the tip.
            screw("fst:m6", "cmp:0002", axis(vec(z=0.02), vec(z=-1.0)), "M6x1.0"),
            screw("fst:unknown", "cmp:0002", axis(vec(z=0.02), vec(z=-1.0)), None),
        ],
    )


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    """A package directory holding one body mesh: a box across the tool's path."""
    meshes = tmp_path / MESH_DIR
    meshes.mkdir(parents=True, exist_ok=True)
    blocker = trimesh.creation.box(
        bounds=[[-0.05, -0.05, 0.030], [0.05, 0.05, 0.035]]
    )
    blocker.export(meshes / "blocker.glb")
    return tmp_path


@pytest.fixture
def context(make_package: MakePackage, package_dir: Path) -> Iterator[ToolContext]:
    tool_context = context_for(geometry_package(make_package), base_dir=package_dir)
    with use_context(tool_context):
        yield tool_context


def recorded(context: ToolContext, name: str) -> RecordedTool:
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}
    assert name in tools, f"{name} is not registered; known: {sorted(tools)}"
    return tools[name]


# --- measure_axis_distance --------------------------------------------------------


def test_measure_axis_distance_reports_the_offset_and_the_angle(context: ToolContext) -> None:
    result = measure.measure_axis_distance("hole:a", "hole:b")

    assert result["distance"] == {"value": 2.0, "unit": "mm"}
    assert result["angle"] == {"value": 0.0, "unit": "deg"}
    assert result["relation"] == "parallel"
    assert result["frame"] == "world"


def test_measure_axis_distance_reports_skew_axes(context: ToolContext) -> None:
    result = measure.measure_axis_distance("hole:a", "hole:c")

    assert result["relation"] == "skew"
    assert result["distance"]["value"] == pytest.approx(4.0)
    assert result["angle"]["value"] == pytest.approx(90.0)


def test_measure_axis_distance_rejects_an_unknown_hole(context: ToolContext) -> None:
    assert measure.measure_axis_distance("hole:a", "hole:zz") == {
        "error": "unknown hole id 'hole:zz'"
    }


def test_a_degenerate_axis_is_an_error_result_not_a_crash(context: ToolContext) -> None:
    result = measure.measure_axis_distance("hole:a", "hole:d")

    assert "zero-length" in result["error"]


def test_measure_axis_distance_is_registered_and_records_a_step(context: ToolContext) -> None:
    tool = recorded(context, "measure_axis_distance")

    payload = json.loads(tool.call({"hole_id_a": "hole:a", "hole_id_b": "hole:b"}))

    assert payload["distance"]["value"] == 2.0
    assert [step.tool for step in context.session.steps] == ["measure_axis_distance"]


# --- measure_face_gap -------------------------------------------------------------


def test_measure_face_gap_between_parallel_planes_is_signed(context: ToolContext) -> None:
    result = measure.measure_face_gap("face:a", "face:b")

    assert result["status"] == "measured"
    assert result["gap"] == {"value": 5.0, "unit": "mm"}

    reversed_result = measure.measure_face_gap("face:b", "face:a")
    assert reversed_result["gap"]["value"] == -5.0


def test_measure_face_gap_between_coaxial_cylinders_is_the_radius_difference(
    context: ToolContext,
) -> None:
    result = measure.measure_face_gap("face:c", "face:d")

    assert result["gap"]["value"] == pytest.approx(0.5)


def test_a_pair_the_model_cannot_handle_is_unsupported_not_a_number(
    context: ToolContext,
) -> None:
    result = measure.measure_face_gap("face:a", "face:e")

    assert result["status"] == "unsupported"
    assert "gap" not in result
    assert "cone" in result["reason"]


def test_measure_face_gap_rejects_an_unknown_face(context: ToolContext) -> None:
    assert measure.measure_face_gap("face:a", "face:zz") == {
        "error": "unknown face id 'face:zz'"
    }


# --- bounding_box -----------------------------------------------------------------


def test_bounding_box_unions_the_faces_of_the_component(context: ToolContext) -> None:
    result = measure.bounding_box("cmp:0001")

    assert result["status"] == "measured"
    assert result["unit"] == "mm"
    assert result["frame"] == "world"
    assert result["min"] == {"x": -50.0, "y": -50.0, "z": 0.0}
    assert result["max"] == {"x": 50.0, "y": 50.0, "z": 20.0}
    assert result["size"] == {"x": 100.0, "y": 100.0, "z": 20.0}
    assert result["face_count"] == 2


def test_bounding_box_of_a_component_with_no_face_geometry_is_unresolved(
    make_package: MakePackage, package_dir: Path
) -> None:
    package = geometry_package(make_package)
    with use_context(context_for(package, base_dir=package_dir)):
        package.faces.clear()
        result = measure.bounding_box("cmp:0001")

    assert result["status"] == "unresolved"
    assert "cmp:0001" in result["reason"]


def test_bounding_box_rejects_an_unknown_component(context: ToolContext) -> None:
    assert measure.bounding_box("cmp:9999") == {"error": "unknown component id 'cmp:9999'"}


# --- check_tool_envelope ----------------------------------------------------------


def mm(value: float) -> dict[str, Any]:
    return {"value": value, "unit": "mm"}


def test_check_tool_envelope_reports_the_body_in_the_way(context: ToolContext) -> None:
    result = measure.check_tool_envelope("fst:m6", "hex_key", Quantity(value=40.0, unit="mm"))

    assert result["status"] == "unresolved"  # one body's mesh is missing
    assert [hit["component_id"] for hit in result["hits"]] == ["cmp:0001"]
    assert result["hits"][0]["first_hit_distance"]["value"] == pytest.approx(10.0)
    assert result["radius"]["value"] == pytest.approx(0.6 * 6.0 / 2.0 + 0.5)
    assert result["tool"] == "hex_key"
    assert any("bod:2" in reason for reason in result["unresolved"])
    assert result["envelope_source"]


def test_a_short_envelope_does_not_reach_the_body(context: ToolContext) -> None:
    result = measure.check_tool_envelope("fst:m6", "socket", Quantity(value=5.0, unit="mm"))

    assert result["hits"] == []


def test_check_tool_envelope_is_unresolved_when_no_mesh_loads(
    make_package: MakePackage, tmp_path: Path
) -> None:
    with use_context(context_for(geometry_package(make_package), base_dir=tmp_path)):
        result = measure.check_tool_envelope(
            "fst:m6", "socket", Quantity(value=40.0, unit="mm")
        )

    assert result["status"] == "unresolved"
    assert result["hits"] == []
    assert len(result["unresolved"]) == 2


def test_an_unreadable_thread_designation_leaves_the_envelope_unresolved(
    context: ToolContext,
) -> None:
    result = measure.check_tool_envelope(
        "fst:unknown", "socket", Quantity(value=40.0, unit="mm")
    )

    assert result["status"] == "unresolved"
    assert "nominal" in result["reason"]


def test_check_tool_envelope_rejects_an_unknown_tool(context: ToolContext) -> None:
    result = measure.check_tool_envelope(
        "fst:m6", "spanner", Quantity(value=40.0, unit="mm")
    )

    assert "spanner" in result["error"]


def test_check_tool_envelope_rejects_a_non_positive_length(context: ToolContext) -> None:
    result = measure.check_tool_envelope("fst:m6", "socket", Quantity(value=0.0, unit="mm"))

    assert "positive" in result["error"]


def test_check_tool_envelope_rejects_an_unknown_fastener(context: ToolContext) -> None:
    result = measure.check_tool_envelope(
        "fst:nope", "socket", Quantity(value=40.0, unit="mm")
    )

    assert result == {"error": "unknown fastener id 'fst:nope'"}


def test_check_tool_envelope_through_the_registry_records_a_step(
    context: ToolContext,
) -> None:
    tool = recorded(context, "check_tool_envelope")

    payload = json.loads(
        tool.call({"fastener_id": "fst:m6", "tool": "hex_key", "length": mm(40.0)})
    )

    assert payload["tool"] == "hex_key"
    assert [step.tool for step in context.session.steps] == ["check_tool_envelope"]


def test_an_unknown_id_through_the_registry_is_failed_coverage(context: ToolContext) -> None:
    tool = recorded(context, "bounding_box")

    with pytest.raises(ToolError):
        tool.call({"component_id": "cmp:9999"})

    assert [item.check for item in context.session.coverage.failed] == ["tool.bounding_box"]
