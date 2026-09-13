"""Adapters that let the golden harness run the fastener checks over a fixture (T091).

`tests/golden/test_golden.py` calls `module:function(package, **kwargs)` with the kwargs
read from `case.json`, so `check_fastener_joint` cannot be named there directly: it takes
IR entities and a clamped stack, not JSON. These adapters resolve ids against the package
- the same resolution the `check_fastener_joint` tool performs - and return the results as
JSON-ready data.

Two things come from `case.json` rather than from the package, because the IR has nowhere
to put them: the thickness of each clamped layer (no plate-thickness entity exists yet)
and the tool envelope's radius and length (chosen per drive type by the caller). The
material of each layer and of the tapped part is read from the package, never typed.

`envelope_case` builds its obstruction bodies from the world AABB stored on a
`FaceGeometry`: the harness hands a case only the package, with no directory to resolve
`BodyRef.mesh_file` against, so a fixture cannot load a real mesh.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import trimesh
from pydantic_core import to_jsonable_python

from swreview.checks.fastener import ClampedLayer, check_fastener_joint
from swreview.checks.result import CheckResult, round_length
from swreview.geometry.envelope import EnvelopeResult, envelope_raycast
from swreview.ir.models import EvidencePackage, Fastener, Hole, Quantity

__all__ = ["envelope_case", "joint_case"]

LayerArg = Mapping[str, Any]


def _jsonable_envelope(envelope: EnvelopeResult) -> dict[str, Any]:
    """The raycast result, with hit distances rounded so a baseline is not float noise."""
    return {
        "hits": [
            {
                "component_id": hit.component_id,
                "first_hit_distance_m": round_length(hit.first_hit_distance_m),
            }
            for hit in envelope.hits
        ],
        "unresolved": list(envelope.unresolved),
    }


def _fastener(package: EvidencePackage, fastener_id: str) -> Fastener:
    for fastener in package.fasteners:
        if fastener.id == fastener_id:
            return fastener
    raise LookupError(f"no fastener {fastener_id!r} in the package")


def _hole(package: EvidencePackage, hole_id: str) -> Hole:
    for hole in package.holes:
        if hole.id == hole_id:
            return hole
    raise LookupError(f"no hole {hole_id!r} in the package")


def _material(package: EvidencePackage, component_id: str) -> str | None:
    """The material of the part a component instance refers to, or `None` if unrecorded."""
    documents = {document.document_id: document for document in package.documents}
    for component in package.components:
        if component.id == component_id:
            document = documents.get(component.document_id)
            return None if document is None else document.material
    raise LookupError(f"no component {component_id!r} in the package")


def _layers(package: EvidencePackage, clamped: Sequence[LayerArg]) -> list[ClampedLayer]:
    return [
        ClampedLayer(
            component_id=layer["component_id"],
            thickness=(
                None
                if layer.get("thickness_mm") is None
                else Quantity(value=float(layer["thickness_mm"]), unit="mm")
            ),
            material=_material(package, layer["component_id"]),
        )
        for layer in clamped
    ]


def _run(
    package: EvidencePackage,
    fastener_id: str,
    hole_id: str,
    clamped: Sequence[LayerArg],
    washers_mm: Sequence[float],
    hole_material: str | None,
    envelope: EnvelopeResult | None,
) -> list[CheckResult]:
    hole = _hole(package, hole_id)
    return check_fastener_joint(
        _fastener(package, fastener_id),
        hole,
        _layers(package, clamped),
        washers=[Quantity(value=float(value), unit="mm") for value in washers_mm],
        hole_material=hole_material or _material(package, hole.component_id),
        envelope=envelope,
    )


def joint_case(
    package: EvidencePackage,
    fastener_id: str,
    hole_id: str,
    clamped: Sequence[LayerArg] = (),
    washers_mm: Sequence[float] = (),
    hole_material: str | None = None,
) -> list[dict[str, Any]]:
    """Run `check_fastener_joint` over one joint named by id in the package.

    `clamped` is a list of `{"component_id": ..., "thickness_mm": ...}`; a `null`
    thickness stands for a layer whose thickness the package does not carry.
    `hole_material` overrides the material read from the tapped component's document.
    """
    results = _run(package, fastener_id, hole_id, clamped, washers_mm, hole_material, None)
    return [to_jsonable_python(result) for result in results]


def envelope_case(
    package: EvidencePackage,
    fastener_id: str,
    hole_id: str,
    obstruction_face_ids: Sequence[str],
    radius_mm: float,
    length_mm: float,
    clamped: Sequence[LayerArg] = (),
    washers_mm: Sequence[float] = (),
    hole_material: str | None = None,
) -> dict[str, Any]:
    """Sweep the tool envelope against the named bodies, then run the joint checks with it.

    Each id in `obstruction_face_ids` names a `FaceGeometry` whose `bbox` is taken as the
    world extent of the obstructing body. The pure-Python intersector is used so the
    baseline does not depend on the optional `embreex` wheel.
    """
    fastener = _fastener(package, fastener_id)
    faces = {face.id: face for face in package.faces}
    meshes: list[tuple[str, trimesh.Trimesh | None]] = []
    for face_id in obstruction_face_ids:
        face = faces.get(face_id)
        if face is None:
            raise LookupError(f"no face {face_id!r} in the package")
        bounds = [
            [face.bbox.min.x, face.bbox.min.y, face.bbox.min.z],
            [face.bbox.max.x, face.bbox.max.y, face.bbox.max.z],
        ]
        meshes.append((face.component_id, trimesh.creation.box(bounds=bounds)))

    envelope = envelope_raycast(
        fastener.axis,
        radius_m=radius_mm / 1000.0,
        length_m=length_mm / 1000.0,
        meshes=meshes,
        use_embree=False,
    )
    results = _run(package, fastener_id, hole_id, clamped, washers_mm, hole_material, envelope)
    return {
        "envelope": _jsonable_envelope(envelope),
        "results": [to_jsonable_python(result) for result in results],
    }
