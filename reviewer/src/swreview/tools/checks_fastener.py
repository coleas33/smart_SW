"""Check tools for fastener joints and hole alignment (T090).

Two rows of the "Check tools" table in contracts/agent-tools.md. The arithmetic is in
`swreview.checks.fastener` and `swreview.checks.hole_alignment`; what this module does is
turn the ids the model chose into the entities those checks need, without inventing any
of the values the package does not carry.

**Where a clamped layer's thickness comes from.** The honest answer is that the offline
package cannot measure it: the thickness that matters is the distance along the fastener
axis between the two faces of the component the screw passes through, and nothing in an
exported package identifies that pair of faces. So the rule is stated here, applied in
one place, and reported with every result:

1. the `Thickness` custom property of the component's document, read as millimetres. A
   value an engineer put on the part beats anything derived;
2. otherwise the extent of the component's extracted bounding box along the fastener
   axis. This is right for a flat plate the screw passes through squarely and wrong for a
   bracket with a flange, so it is labelled as derived wherever it appears;
3. otherwise `None`, which leaves the joint `unresolved` naming that component. There is
   no third guess (constitution Principle I).

**Washers are found, not declared.** Any `washer` fastener coaxial with this one (within
`WASHER_AXIS_TOLERANCE_MM` and `WASHER_ANGLE_TOLERANCE_DEG`) is under this head. A washer
whose thickness the package does not state joins the clamped stack with an unknown
thickness rather than being dropped: a stack missing a washer would clear a joint that
bottoms.

**An unsupported joint kind is coverage, not a finding.** `check_fastener_joint` returns a
single `fastener.unsupported` result for a pin or a rivet; that goes into the
`out_of_scope` bucket, where the report shows it as seen and not evaluated (FR-024).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from swreview.checks import fastener as joint_check
from swreview.checks import hole_alignment as alignment_check
from swreview.checks.result import round_length
from swreview.geometry.axis import axial_extent, axis_distance
from swreview.ir.models import Axis, ComponentInstance, Fastener, Quantity, SourceRef
from swreview.tools.context import (
    ToolContext,
    current_context,
    error_result,
    unknown_id,
)
from swreview.tools.query import ToolResult, as_json
from swreview.tools.recording import out_of_scope, record_result, record_results
from swreview.tools.refs import resolve_dimension

__all__ = [
    "THICKNESS_PROPERTY",
    "WASHER_ANGLE_TOLERANCE_DEG",
    "WASHER_AXIS_TOLERANCE_MM",
    "check_fastener_joint",
    "check_hole_alignment",
]

THICKNESS_PROPERTY = "Thickness"
"""The custom property an engineer can put on a part to state its clamped thickness."""

WASHER_AXIS_TOLERANCE_MM = 0.1
WASHER_ANGLE_TOLERANCE_DEG = 5.0
"""How far off a `washer` fastener may sit and still count as under this head. Loose
enough for a washer modelled with a little play, tight enough that the washer of the next
screw along is not counted."""

_RESOLUTION_ERRORS = (LookupError, ValidationError, TypeError)


@dataclass(frozen=True)
class _Layer:
    """One clamped component: its thickness and where that thickness came from."""

    component_id: str
    thickness: Quantity | None
    source: str
    material: str | None

    def as_json(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "thickness": None if self.thickness is None else as_json(self.thickness),
            "source": self.source,
        }


def _material_of(context: ToolContext, component: ComponentInstance) -> str | None:
    document = context.document(component.document_id)
    return None if document is None else document.material


def _stated_thickness(context: ToolContext, component: ComponentInstance) -> float | None:
    """The `Thickness` custom property in millimetres, or `None` if it is not usable."""
    document = context.document(component.document_id)
    if document is None:
        return None
    properties = {
        **document.custom_properties,
        **document.config_properties.get(component.referenced_configuration, {}),
    }
    for name, value in properties.items():
        if name.strip().lower() != THICKNESS_PROPERTY.lower():
            continue
        try:
            thickness = float(str(value).strip())
        except ValueError:
            return None
        return thickness if thickness > 0.0 else None
    return None


def _bbox_extent_mm(context: ToolContext, component_id: str, axis: Axis) -> float | None:
    """The extent of the component's extracted face boxes along `axis`, in millimetres."""
    boxes = [face.bbox for face in context.ir.faces if face.component_id == component_id]
    try:
        low, high = axial_extent(boxes, axis, f"the fastener axis over {component_id}")
    except ValueError:
        # No direction to project along, or no face to project: the extent is unknown, not
        # zero.
        return None
    return round_length((high - low) * 1000.0)


def _layer_for(context: ToolContext, component_id: str, axis: Axis) -> _Layer:
    component = context.component(component_id)
    assert component is not None  # callers validate the id first
    material = _material_of(context, component)

    stated = _stated_thickness(context, component)
    if stated is not None:
        return _Layer(
            component_id=component_id,
            thickness=Quantity(value=stated, unit="mm"),
            source=(
                f"{THICKNESS_PROPERTY} custom property of document {component.document_id}"
            ),
            material=material,
        )

    derived = _bbox_extent_mm(context, component_id, axis)
    if derived is not None:
        return _Layer(
            component_id=component_id,
            thickness=Quantity(value=derived, unit="mm"),
            source=(
                "derived: extent of the component's extracted face bounding box along the "
                "fastener axis; correct for a flat layer the screw passes through squarely"
            ),
            material=material,
        )

    return _Layer(
        component_id=component_id,
        thickness=None,
        source=(
            f"unknown: document {component.document_id} states no {THICKNESS_PROPERTY} "
            f"property and no face geometry was extracted for {component_id}"
        ),
        material=material,
    )


def _is_coaxial(a: Axis, b: Axis) -> bool:
    try:
        relation = axis_distance(a, b)
    except ValueError:
        return False
    return (
        relation.distance_m * 1000.0 <= WASHER_AXIS_TOLERANCE_MM
        and math.degrees(relation.angle_rad) <= WASHER_ANGLE_TOLERANCE_DEG
    )


def _washers(context: ToolContext, fastener: Fastener) -> list[Fastener]:
    """Every `washer` fastener sitting on this fastener's axis."""
    return [
        item
        for item in context.ir.fasteners
        if item.kind == "washer"
        and item.id != fastener.id
        and _is_coaxial(fastener.axis, item.axis)
    ]


def _washer_thickness(washer: Fastener) -> Quantity | None:
    """A washer's thickness: its `length` if the extractor got one, else its head height."""
    return washer.length if washer.length is not None else washer.head_height


def check_fastener_joint(
    fastener_id: str, hole_id: str, clamped_component_ids: list[str]
) -> ToolResult:
    """Check one screw-in-tapped-hole joint: bottoming, engagement, thread, head clearance.

    Args:
        fastener_id: The screw or bolt, as `list_fasteners` reports it.
        hole_id: The tapped hole it goes into.
        clamped_component_ids: The components the screw clamps, from the head down.

    Notes:
        Returns one finding per check. The clamped stack is the components you name, in order
        from the head; each layer's thickness comes from its `Thickness` custom property, or
        from its extracted bounding box measured along the fastener axis, or is unknown - and
        the result says which for every layer. Washers coaxial with the fastener are found in
        the package and added to the stack; you do not name them.

        A screw whose usable thread depth the package does not carry leaves bottoming and
        engagement `unresolved`: drill depth is not thread depth and is never used as one.
        Head clearance stays `unresolved` until `check_tool_envelope` has swept the meshes.

        A joint kind this phase does not model (a pin, a rivet, a nut) produces no finding at
        all: it is recorded as `out_of_scope` coverage.
    """
    context = current_context()
    fastener = context.fastener(fastener_id)
    if fastener is None:
        return unknown_id("fastener", fastener_id)
    hole = context.hole(hole_id)
    if hole is None:
        return unknown_id("hole", hole_id)
    unknown = [
        component_id
        for component_id in clamped_component_ids
        if context.component(component_id) is None
    ]
    if unknown:
        return error_result(f"clamped_component_ids not in this package: {unknown}")

    tapped_component = context.component(hole.component_id)
    hole_material = (
        None if tapped_component is None else _material_of(context, tapped_component)
    )

    layers = [
        _layer_for(context, component_id, fastener.axis)
        for component_id in clamped_component_ids
    ]
    washers = _washers(context, fastener)
    washer_thicknesses = [
        thickness
        for thickness in (_washer_thickness(washer) for washer in washers)
        if thickness is not None
    ]
    # A washer whose thickness is unknown enters the stack as an unknown layer, so the
    # joint stays unresolved naming it instead of being checked without it.
    unmeasured = [washer for washer in washers if _washer_thickness(washer) is None]
    layers.extend(
        _Layer(
            component_id=washer.component_id,
            thickness=None,
            source=f"unknown: washer {washer.id} states neither a length nor a head height",
            material=None,
        )
        for washer in unmeasured
    )

    results = joint_check.check_fastener_joint(
        fastener,
        hole,
        [
            joint_check.ClampedLayer(
                component_id=layer.component_id,
                thickness=layer.thickness,
                material=layer.material,
            )
            for layer in layers
        ],
        washers=washer_thicknesses,
        hole_material=hole_material,
        envelope=None,
    )

    component_ids = _component_ids(context, fastener, hole, clamped_component_ids)
    if len(results) == 1 and results[0].check == joint_check.CHECK_UNSUPPORTED:
        return out_of_scope(context, results[0], component_ids)

    recorded = record_results(context, results, component_ids=component_ids)
    if "error" in recorded:
        return recorded
    return {
        **recorded,
        "clamped": [layer.as_json() for layer in layers],
        "washers": [
            {
                "fastener_id": washer.id,
                "thickness": (
                    None
                    if _washer_thickness(washer) is None
                    else as_json(_washer_thickness(washer))
                ),
            }
            for washer in washers
        ],
        "hole_material": hole_material,
    }


def _component_ids(
    context: ToolContext,
    fastener: Fastener,
    hole: object,
    clamped_component_ids: Sequence[str],
) -> list[str]:
    """The component instances a joint finding is about, in a stable order, deduplicated."""
    candidates = [
        fastener.component_id,
        getattr(hole, "component_id", None),
        *clamped_component_ids,
    ]
    seen: list[str] = []
    for component_id in candidates:
        if (
            component_id is not None
            and component_id not in seen
            and context.component(component_id) is not None
        ):
            seen.append(component_id)
    return seen


def check_hole_alignment(
    hole_id_a: str, hole_id_b: str, tolerance: SourceRef | None = None
) -> ToolResult:
    """Compare the offset between two hole axes with a coaxiality tolerance off a drawing.

    Args:
        hole_id_a: First hole id.
        hole_id_b: Second hole id.
        tolerance: Where the position tolerance is drawn - document id, sheet and
            annotation - or null when the package carries none.

    Notes:
        The offset is the closest distance between the axes as modelled, with the angle
        between them reported alongside. `tolerance` names the drawing dimension that governs
        the pair; its nominal is a zone that permits half of it as offset. Without one the
        offset is still measured and the finding is `unresolved` - the number is evidence,
        the verdict is not available.

        This compares modelled axes, not GD&T: no datum reference frame, no material
        condition, no form error, and no allowance for component position or mate play.
    """
    context = current_context()
    a = context.hole(hole_id_a)
    if a is None:
        return unknown_id("hole", hole_id_a)
    b = context.hole(hole_id_b)
    if b is None:
        return unknown_id("hole", hole_id_b)

    dimension = None
    if tolerance is not None:
        try:
            dimension = resolve_dimension(context.ir, tolerance)
        except _RESOLUTION_ERRORS as exc:
            return error_result(f"{type(exc).__name__}: {exc}")

    try:
        result = alignment_check.check_hole_alignment(a, b, dimension)
    except (TypeError, ValueError) as exc:
        return error_result(f"{type(exc).__name__}: {exc}")

    component_ids = [
        component_id
        for component_id in dict.fromkeys([a.component_id, b.component_id])
        if context.component(component_id) is not None
    ]
    return record_result(
        context,
        result,
        component_ids=component_ids,
        drawing_locations=[] if dimension is None else [dimension.source],
    )
