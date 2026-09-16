"""Measurement tools: the only tools that read geometry (T090).

One function per row of the "Measurement tools" table in contracts/agent-tools.md. They
are deterministic Python over the entities in the package - `swreview.geometry` does the
arithmetic - and they return plain dicts with units, never a `Finding`: a measurement is
evidence, and what it means is the check tool's job.

Three rules run through all of them:

- every argument is an id resolved against the package, so a measurement can only be
  taken between things the extractor actually found (research R4);
- a pair the geometry module cannot model comes back `unsupported`, and a body whose mesh
  is missing comes back `unresolved` naming it. Neither is ever rounded down to "clear"
  (constitution Principle I) - a tool envelope that could not sweep a body has not
  established that the body is out of the way;
- lengths are reported in millimetres and angles in degrees, with the frame named. The IR
  stores world-frame metres and radians; the conversion happens here, once.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal, get_args

import trimesh

from swreview import units
from swreview.checks.fastener import nominal_diameter
from swreview.checks.result import round_length
from swreview.checks.tool_envelopes import ToolEnvelopes, load_envelopes
from swreview.geometry.axis import axis_distance, face_gap
from swreview.geometry.envelope import envelope_raycast
from swreview.geometry.mesh import load_mesh
from swreview.ir.models import BBox3D, BodyRef, FaceGeometry, Quantity, Vec3
from swreview.tools.bridge import fetch_bodies_through_bridge
from swreview.tools.context import (
    ToolContext,
    current_context,
    error_result,
    not_one_of,
    unknown_id,
)
from swreview.tools.query import ToolResult

__all__ = [
    "DRIVING_TOOLS",
    "bounding_box",
    "check_tool_envelope",
    "measure_axis_distance",
    "measure_face_gap",
]

DrivingTool = Literal["hex_key", "socket", "screwdriver"]
DRIVING_TOOLS: tuple[str, ...] = get_args(DrivingTool)

WORLD = "world"
"""Every measurement is taken in the assembly's world frame; results say so."""


def _mm(metres: float) -> dict[str, Any]:
    return {"value": round_length(metres * 1000.0), "unit": "mm"}


def _degrees(radians: float) -> dict[str, Any]:
    return {"value": round_length(math.degrees(radians)), "unit": "deg"}


def _face(context: ToolContext, face_id: str) -> FaceGeometry | None:
    for face in context.ir.faces:
        if face.id == face_id:
            return face
    return None


def measure_axis_distance(hole_id_a: str, hole_id_b: str) -> ToolResult:
    """Closest distance and angle between the axes of two holes, in the world frame.

    Args:
        hole_id_a: First hole id.
        hole_id_b: Second hole id.

    Notes:
        For parallel axes the distance is the perpendicular distance between them; for skew
        axes it is the common-perpendicular distance. `relation` says which case this is:
        `coincident`, `parallel`, `intersecting` or `skew`.

        This is a measurement, not a verdict: comparing it with a tolerance is
        `check_hole_alignment`.
    """
    context = current_context()
    a = context.hole(hole_id_a)
    if a is None:
        return unknown_id("hole", hole_id_a)
    b = context.hole(hole_id_b)
    if b is None:
        return unknown_id("hole", hole_id_b)

    try:
        relation = axis_distance(a.axis, b.axis)
    except ValueError as exc:
        return error_result(f"ValueError: {exc}")
    return {
        "hole_id_a": hole_id_a,
        "hole_id_b": hole_id_b,
        "distance": _mm(relation.distance_m),
        "angle": _degrees(relation.angle_rad),
        "relation": relation.relation,
        "frame": WORLD,
    }


def measure_face_gap(face_id_a: str, face_id_b: str) -> ToolResult:
    """Signed gap between two parallel planes or two coaxial cylinders.

    Args:
        face_id_a: First face id.
        face_id_b: Second face id.

    Notes:
        For planes the gap is measured along face A's normal, so it is positive when B lies
        on the side A faces. For cylinders it is the radius difference B - A, negative when B
        is the smaller of the two - the shaft-in-bore convention.

        Any other pair - non-parallel planes, offset cylinders, a cone or a torus, a face
        whose surface the extractor did not record - comes back `unsupported` with the reason.
        That is unresolved coverage, not a measurement of zero.
    """
    context = current_context()
    a = _face(context, face_id_a)
    if a is None:
        return unknown_id("face", face_id_a)
    b = _face(context, face_id_b)
    if b is None:
        return unknown_id("face", face_id_b)

    try:
        gap = face_gap(a, b)
    except ValueError as exc:
        return error_result(f"ValueError: {exc}")
    if gap == "unsupported":
        return {
            "status": "unsupported",
            "face_id_a": face_id_a,
            "face_id_b": face_id_b,
            "kinds": [a.kind, b.kind],
            "reason": (
                f"a {a.kind} and a {b.kind} face: this measurement models two parallel "
                "planes or two coaxial cylinders only, and will not approximate the rest"
            ),
        }
    assert isinstance(gap, Quantity)
    return {
        "status": "measured",
        "face_id_a": face_id_a,
        "face_id_b": face_id_b,
        "kinds": [a.kind, b.kind],
        "gap": {"value": round_length(gap.value), "unit": gap.unit},
        "frame": WORLD,
        "sign_convention": (
            "positive when face B lies on the side face A's normal points at"
            if a.kind == "plane"
            else "positive when cylinder B is the larger radius"
        ),
    }


def bounding_box(component_id: str) -> ToolResult:
    """World axis-aligned bounding box of one component, from its extracted faces.

    Args:
        component_id: Component instance id.

    Notes:
        The box is the union of the world bounding boxes the extractor recorded per face, so
        it covers the faces that were extracted and nothing else: with `--faces needed` that
        is a subset of the part, and the result says how many faces went into it. A component
        with no extracted face geometry is `unresolved`, never a zero-sized box.
    """
    context = current_context()
    if context.component(component_id) is None:
        return unknown_id("component", component_id)

    boxes = [face.bbox for face in context.ir.faces if face.component_id == component_id]
    if not boxes:
        return {
            "status": "unresolved",
            "component_id": component_id,
            "reason": (
                f"no face geometry was extracted for {component_id}, so its extent is "
                "unknown; re-export the package with the faces this component needs"
            ),
        }

    low = _corner(boxes, minimum=True)
    high = _corner(boxes, minimum=False)
    return {
        "status": "measured",
        "component_id": component_id,
        "frame": WORLD,
        "unit": "mm",
        "min": low,
        "max": high,
        "size": {axis: round_length(high[axis] - low[axis]) for axis in ("x", "y", "z")},
        "face_count": len(boxes),
        "coverage_limit": (
            "the box spans the faces the extractor recorded for this component, which "
            "may be fewer than all of them"
        ),
    }


def _corner(boxes: list[BBox3D], minimum: bool) -> dict[str, float]:
    pick = min if minimum else max
    corners: list[Vec3] = [box.min if minimum else box.max for box in boxes]
    return {
        axis: round_length(pick(getattr(corner, axis) for corner in corners) * 1000.0)
        for axis in ("x", "y", "z")
    }


def _mesh_for(
    context: ToolContext, body: BodyRef
) -> tuple[trimesh.Trimesh | None, str | None]:
    """`body`'s mesh in world metres, or `None` and the reason it could not be loaded."""
    path = Path(context.package.resolve(body.mesh_file))
    try:
        return load_mesh(path), None
    except (FileNotFoundError, ValueError) as exc:
        return None, (
            f"{body.component_id} body {body.id}: {type(exc).__name__}: {exc}"
        )


def check_tool_envelope(
    fastener_id: str, tool: DrivingTool, length: Quantity
) -> ToolResult:
    """Sweep a driving tool back from a fastener head and report what it runs into.

    Args:
        fastener_id: Fastener whose head the tool reaches for.
        tool: hex_key, socket or screwdriver.
        length: How far back from the head the tool needs, with its unit.

    Notes:
        The envelope is a cylinder whose radius comes from `checks/tool_envelopes.yaml` - a
        multiple of the fastener's nominal thread diameter, plus a clearance - swept from the
        head plane along the fastener axis, away from the tip, for `length`. The result lists
        every component the sweep hits and how far away the first hit is.

        The bodies swept are the ones whose exported mesh could be loaded, excluding the
        fastener's own. Any body whose mesh is missing makes the result `unresolved` and is
        named: a sweep that could not test a body has not shown it is out of the way.
    """
    context = current_context()
    fastener = context.fastener(fastener_id)
    if fastener is None:
        return unknown_id("fastener", fastener_id)
    if tool not in DRIVING_TOOLS:
        return not_one_of("tool", str(tool), DRIVING_TOOLS)

    try:
        quantity = length if isinstance(length, Quantity) else Quantity(**dict(length))
        length_mm = units.as_mm(quantity)
    except (TypeError, ValueError) as exc:
        return error_result(f"{type(exc).__name__}: {exc}")
    if length_mm <= 0.0:
        return error_result(f"length must be positive, got {length_mm} mm")

    envelopes: ToolEnvelopes = load_envelopes()
    designation = fastener.thread_designation
    diameter = None if designation is None else nominal_diameter(designation)
    if diameter is None:
        reason = (
            f"the nominal thread diameter of fastener {fastener_id} is unknown "
            f"(thread designation {designation!r}), so the tool envelope has no size"
        )
        return {
            "status": "unresolved",
            "fastener_id": fastener_id,
            "tool": tool,
            "hits": [],
            "unresolved": [reason],
            "reason": reason,
        }

    radius_mm = envelopes.radius_mm(tool, diameter.value)
    meshes: list[tuple[str, trimesh.Trimesh]] = []
    # Lever 10a. With `extraction.meshes` eager - every run before the lever, and every run
    # with it off - this returns an empty list without touching anything, and the sweep
    # below is exactly the sweep it always was. With it lazy the package carries no bodies
    # until the fetch has run, and every component the fetch could not pull back is named
    # here rather than quietly missing from the sweep.
    unresolved: list[str] = fetch_bodies_through_bridge(
        context, exclude_component_id=fastener.component_id
    )
    for body in context.ir.bodies:
        if body.component_id == fastener.component_id:
            continue
        mesh, reason = _mesh_for(context, body)
        if mesh is None:
            assert reason is not None
            unresolved.append(reason)
        else:
            meshes.append((body.component_id, mesh))
    if not meshes:
        # Principle I: a sweep that tested no body has established nothing. Without this
        # the result of a package carrying no body mesh - `dump --meshes none` - reads
        # `status: "checked", bodies_swept: 0, hits: []`, which is a false clear.
        unresolved.append(
            f"the tool envelope for fastener {fastener_id} swept no body, so it has not "
            f"established that anything is out of the way"
        )

    try:
        result = envelope_raycast(
            fastener.axis,
            radius_m=radius_mm / 1000.0,
            length_m=length_mm / 1000.0,
            meshes=list(meshes),
        )
    except ValueError as exc:
        return error_result(f"ValueError: {exc}")

    return {
        "status": "unresolved" if unresolved else "checked",
        "fastener_id": fastener_id,
        "tool": tool,
        "radius": {"value": round_length(radius_mm), "unit": "mm"},
        "length": {"value": round_length(length_mm), "unit": "mm"},
        "envelope_source": envelopes.tools[tool].source,
        "bodies_swept": len(meshes),
        "hits": [
            {
                "component_id": hit.component_id,
                "first_hit_distance": _mm(hit.first_hit_distance_m),
            }
            for hit in result.hits
        ],
        "unresolved": unresolved,
        "coverage_limit": (
            "the envelope is a straight cylinder sampled on its circle and its axis; the "
            "swing arc of a wrench and the taper of a bit are not modelled"
        ),
    }
