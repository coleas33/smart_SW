"""Match saved engineering context to evidence; offline matches are never native proof."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from typing import Literal, TypeVar

from swreview.engineering_context.models import (
    AppliedForceRecord,
    BindingAssessment,
    CoordinateFrame,
    EngineeringRecord,
    EvidenceBaseline,
    ResolvedForce,
    TargetAnchor,
)
from swreview.ir.loader import (
    PACKAGE_FILE_NAME,
    AnswerKeyAccessError,
    LoadedPackage,
    merged_package_text,
    reject_answer_key_path,
)
from swreview.ir.models import ComponentInstance, EvidencePackage

Vector = tuple[float, float, float]
Matrix = tuple[tuple[float, ...], ...]


def _vector(values: Sequence[float]) -> Vector:
    if len(values) != 3 or any(
        isinstance(value, bool) or not isinstance(value, (float, int))
        or not math.isfinite(value) for value in values
    ):
        raise ValueError("a finite numeric three-vector is required")
    return (float(values[0]), float(values[1]), float(values[2]))


def normalize_direction(values: Sequence[float]) -> Vector:
    """Normalize a declared signed direction, without using it as a force magnitude."""
    vector = _vector(values)
    scale = max(abs(value) for value in vector)
    if scale == 0.0:
        raise ValueError("a zero direction is unresolved")
    # Scaling first avoids underflow or overflow for finite nonzero input vectors.
    scaled = tuple(value / scale for value in vector)
    length = math.hypot(*scaled)
    return (scaled[0] / length, scaled[1] / length, scaled[2] / length)


def validate_rigid_transform(matrix: Sequence[Sequence[float]]) -> Matrix:
    """Admit only finite affine orthonormal right-handed transforms in metres."""
    if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
        raise ValueError("a finite 4x4 transform is required")
    if any(
        isinstance(value, bool) or not isinstance(value, (float, int))
        or not math.isfinite(value) for row in matrix for value in row
    ):
        raise ValueError("a finite numeric transform is required")
    result = tuple(tuple(float(value) for value in row) for row in matrix)
    if result[3] != (0.0, 0.0, 0.0, 1.0):
        raise ValueError("transform must have affine last row [0, 0, 0, 1]")
    rotation = [row[:3] for row in result[:3]]
    for row in range(3):
        for other in range(3):
            product = sum(rotation[row][k] * rotation[other][k] for k in range(3))
            expected = 1.0 if row == other else 0.0
            if not math.isclose(product, expected, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError("scaled or sheared transforms are unresolved")
    a, b, c = rotation
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    if not math.isclose(determinant, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("reflected transforms are unresolved")
    return result


def _apply(matrix: Matrix, vector: Vector, *, point: bool) -> Vector:
    values = tuple(
        sum(matrix[row][column] * vector[column] for column in range(3))
        + (matrix[row][3] if point else 0.0)
        for row in range(3)
    )
    return _vector(values)


def transform_point_m(matrix: Sequence[Sequence[float]], point_m: Sequence[float]) -> Vector:
    """Apply a root-relative transform once, including metre translation."""
    return _apply(validate_rigid_transform(matrix), _vector(point_m), point=True)


def rotate_vector(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> Vector:
    """Rotate a vector without translation or normalization; retain its magnitude."""
    return _apply(validate_rigid_transform(matrix), _vector(vector), point=False)


T = TypeVar("T")


def _unique(rows: Sequence[T], field: str, value: str) -> T | None:
    matches = [row for row in rows if getattr(row, field) == value]
    if len(matches) > 1:
        raise ValueError("ambiguous evidence target")
    return matches[0] if matches else None


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _saved_snapshot(loaded: LoadedPackage) -> tuple[bytes, EvidencePackage]:
    directory = reject_answer_key_path(loaded.base_dir, "engineering context uses public evidence")
    package_file = reject_answer_key_path(
        directory / PACKAGE_FILE_NAME, "engineering context uses public evidence",
    )
    raw = package_file.read_bytes()
    saved = EvidencePackage.model_validate_json(raw)
    if saved.model_dump(mode="json") != loaded.package.model_dump(mode="json"):
        raise ValueError("loaded evidence differs from the saved package")
    return raw, saved


LIVE_INTERFERENCE_GAP_KINDS = frozenset({"interference", "interference_volume_unit"})
"""The gap kinds the host's live interference check reports (`InterferenceRunner.GapEntityKind`
and `VolumeUnitGapEntityKind`), which `ir.loader.append_interference_run` appends."""


def _without_live_interference(package: EvidencePackage, configuration: str) -> str:
    """The package's canonical digest without what the live interference check rewrites.

    Owner decision 107A: the check replaces the active configuration's interference rows and
    appends its gaps, and its raw rewrite also respells values, so the comparison is of the
    parsed package with exactly those removed; every other row, gap and field still counts.
    """
    data = package.model_dump(mode="json")
    data["interferences"] = [
        row for row in data["interferences"] if row.get("configuration") != configuration
    ]
    data["gaps"] = [
        gap for gap in data["gaps"] if gap.get("entity_kind") not in LIVE_INTERFERENCE_GAP_KINDS
    ]
    return _digest(data)


def same_saved_package(saved: EvidenceBaseline, current: EvidenceBaseline) -> bool:
    """Whether `current` is exactly the saved package: its bytes and identity.

    The live-free digest is derived from the bytes, so it is not compared here, and a context
    saved before owner decision 107A compares as it always did.
    """
    absent = {"without_live_interference_sha256": None}
    return saved.model_copy(update=absent) == current.model_copy(update=absent)


def _written_by_live_check(raw: bytes) -> bool:
    """Whether `raw` is spelled as `append_interference_run` writes a merged package."""
    try:
        text = raw.decode("utf-8")
        return text == merged_package_text(json.loads(text))
    except ValueError:
        return False


def same_apart_from_live_interference(
    saved: EvidenceBaseline, current: EvidenceBaseline, raw: bytes
) -> bool:
    """The exact saved package, or (owner decision 107A) the same package apart from the rows
    and gaps a review's live interference check rewrote: `raw`, the current bytes, are spelled
    as that check writes them and nothing else differs. Any other change, a re-spelling
    included, is not."""
    if same_saved_package(saved, current):
        return True
    return (
        saved.without_live_interference_sha256 is not None
        and saved.model_copy(update={"package_sha256": current.package_sha256}) == current
        and _written_by_live_check(raw)
    )


def baseline_from_package(loaded: LoadedPackage) -> EvidenceBaseline:
    """Attest exact saved package bytes; this observes no currently open CAD document."""
    raw, package = _saved_snapshot(loaded)
    return _baseline_from_snapshot(package, raw)


def _baseline_from_snapshot(package: EvidencePackage, raw: bytes) -> EvidenceBaseline:
    root = _unique(package.documents, "document_id", package.design.root_assembly_document_id)
    if root is None or root.kind == "drawing":
        raise ValueError("engineering context requires a saved part or assembly root")
    configuration = package.design.active_configuration
    if not configuration or configuration not in root.configurations:
        raise ValueError("root configuration is missing from saved evidence")
    if configuration != root.active_configuration:
        raise ValueError("root configuration differs within saved evidence")
    return EvidenceBaseline(
        package_id=package.package_id, package_sha256=hashlib.sha256(raw).hexdigest(),
        schema_version=package.schema_version, root_document_id=root.document_id,
        configuration=configuration,
        without_live_interference_sha256=_without_live_interference(package, configuration),
    )


def _component_fields(component: ComponentInstance | None) -> dict[str, object]:
    if component is None:
        return {}
    return {
        "document_id": component.document_id,
        "configuration": component.referenced_configuration,
        "component_id": component.id,
        "full_path": component.full_path,
        "referenced_configuration": component.referenced_configuration,
        "transform_sha256": _digest(component.transform),
    }


def anchor_from_package(
    loaded: LoadedPackage, anchor_id: str, kind: Literal["document", "component", "face"],
    entity_id: str, component_id: str | None = None,
) -> TargetAnchor:
    """Capture a package-local locator; unavailable entities remain unresolved drafts."""
    raw, package = _saved_snapshot(loaded)
    _baseline_from_snapshot(package, raw)
    return _anchor_from_snapshot(package, anchor_id, kind, entity_id, component_id)


def _anchor_from_snapshot(
    package: EvidencePackage, anchor_id: str, kind: Literal["document", "component", "face"],
    entity_id: str, component_id: str | None = None,
) -> TargetAnchor:
    fields: dict[str, object] = {
        "anchor_id": anchor_id, "package_id": package.package_id,
        "kind": kind, "entity_id": entity_id,
    }
    if kind == "document":
        if component_id is not None:
            raise ValueError("document anchor cannot specify a component occurrence")
        document = _unique(package.documents, "document_id", entity_id)
        if document is not None:
            fields.update(
                document_id=document.document_id, configuration=document.active_configuration,
                geometry_sha256=_digest(document.model_dump(mode="json")),
            )
    elif kind == "component":
        if component_id is not None and component_id != entity_id:
            raise ValueError("component anchor entity must be its exact component occurrence")
        component = _unique(package.components, "id", entity_id)
        fields.update(_component_fields(component))
        fields["component_id"] = entity_id
        if component is not None:
            fields.update(persist_ref=component.persist_ref,
                          persist_ref_scope=component.persist_ref_scope)
    elif kind == "face":
        face = _unique(package.faces, "id", entity_id)
        if face is not None:
            if component_id is not None and face.component_id != component_id:
                raise ValueError("face belongs to a different component occurrence")
            component_id = face.component_id
        component = _unique(package.components, "id", component_id) if component_id else None
        fields.update(_component_fields(component))
        if component_id:
            fields["component_id"] = component_id
        if face is not None:
            geometry = face.model_dump(mode="json")
            fields.update(
                persist_ref=face.persist_ref, persist_ref_scope=face.persist_ref_scope,
                geometry_sha256=_digest({key: geometry[key] for key in (
                    "kind", "cylinder", "plane", "bbox", "area_m2",
                )}),
            )
    else:
        raise ValueError("unsupported engineering target kind")
    return TargetAnchor.model_validate(fields)


def _occurrence_unavailable(component: ComponentInstance, package: EvidencePackage) -> str | None:
    visited: set[str] = set()
    current = component
    while True:
        if current.id in visited:
            return "ancestor_cycle"
        visited.add(current.id)
        prefix = "target_" if current.id == component.id else "ancestor_"
        if current.suppression != "resolved":
            return prefix + current.suppression
        document = _unique(package.documents, "document_id", current.document_id)
        if document is None:
            return prefix + "document_missing"
        if current.referenced_configuration not in document.configurations:
            return ("" if current.id == component.id else "ancestor_") + "configuration_unknown"
        if current.parent_id is None:
            return None
        parent = _unique(package.components, "id", current.parent_id)
        if parent is None:
            return "ancestor_missing"
        current = parent


def _unavailable(anchor: TargetAnchor, package: EvidencePackage) -> str | None:
    rows: Sequence[object]
    key = "id"
    if anchor.kind == "document":
        rows = package.documents
        key = "document_id"
    else:
        rows = package.components if anchor.kind == "component" else package.faces
    if _unique(rows, key, anchor.entity_id) is None:
        return "target_missing"
    if anchor.kind != "document":
        component = _unique(package.components, "id", anchor.component_id or "")
        if component is None:
            return "occurrence_missing"
        unavailable = _occurrence_unavailable(component, package)
        if unavailable:
            return unavailable
    document = _unique(package.documents, "document_id", anchor.document_id or "")
    if document is None:
        return "target_document_missing"
    if anchor.configuration not in document.configurations:
        return "configuration_unknown"
    if anchor.persist_ref_scope is not None:
        if _unique(package.documents, "document_id", anchor.persist_ref_scope) is None:
            return "reference_scope_missing"
    return None


def assess_binding(
    anchor: TargetAnchor, baseline: EvidenceBaseline, loaded: LoadedPackage,
) -> BindingAssessment:
    """Match historical saved evidence conservatively, without cross-package rebinding."""
    try:
        raw, package = _saved_snapshot(loaded)
        current = _baseline_from_snapshot(package, raw)
    except (ValueError, OSError, AnswerKeyAccessError):
        return BindingAssessment(status="unresolved", reasons=("saved_snapshot_unavailable",))
    return _assess_anchor_snapshot(anchor, baseline, current, package, raw)


def _assess_anchor_snapshot(
    anchor: TargetAnchor, baseline: EvidenceBaseline, current: EvidenceBaseline,
    package: EvidencePackage, raw: bytes,
) -> BindingAssessment:
    if current.package_id != baseline.package_id or anchor.package_id != baseline.package_id:
        return BindingAssessment(status="unresolved", reasons=("package_changed",))
    if not same_apart_from_live_interference(baseline, current, raw):
        return BindingAssessment(status="mismatch", reasons=("package_digest_changed",))
    try:
        unavailable = _unavailable(anchor, package)
        if unavailable:
            return BindingAssessment(status="unresolved", reasons=(unavailable,))
        expected = _anchor_from_snapshot(
            package, anchor.anchor_id, anchor.kind, anchor.entity_id, anchor.component_id,
        )
    except ValueError:
        return BindingAssessment(status="mismatch", reasons=("occurrence_changed",))
    identity_fields = (
        "document_id", "configuration", "component_id", "full_path",
        "referenced_configuration", "persist_ref_scope",
    )
    if any(getattr(expected, field) != getattr(anchor, field) for field in identity_fields):
        return BindingAssessment(status="mismatch", reasons=("occurrence_changed",))
    dependency_fields = ("transform_sha256", "geometry_sha256", "persist_ref")
    if any(getattr(expected, field) != getattr(anchor, field) for field in dependency_fields):
        return BindingAssessment(status="mismatch", reasons=("dependency_changed",))
    return BindingAssessment(status="matched_snapshot", needs_review=False)


def frame_from_package(
    loaded: LoadedPackage, frame_id: str, component_id: str | None = None,
) -> CoordinateFrame:
    """Use existing root-relative transforms once, never recompose ancestor matrices."""
    raw, package = _saved_snapshot(loaded)
    baseline = _baseline_from_snapshot(package, raw)
    return _frame_from_snapshot(package, baseline, frame_id, component_id)


def _frame_from_snapshot(
    package: EvidencePackage, baseline: EvidenceBaseline, frame_id: str,
    component_id: str | None = None,
) -> CoordinateFrame:
    if component_id is None:
        return CoordinateFrame(
            frame_id=frame_id, document_id=baseline.root_document_id,
            transform=validate_rigid_transform((
                (1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0),
            )),
        )
    component = _unique(package.components, "id", component_id)
    if component is None:
        raise ValueError("component frame target is missing")
    unavailable = _occurrence_unavailable(component, package)
    if unavailable:
        raise ValueError("component frame is unavailable: " + unavailable)
    document = _unique(package.documents, "document_id", component.document_id)
    if document is None or component.referenced_configuration not in document.configurations:
        raise ValueError("component frame configuration is unknown")
    return CoordinateFrame(
        frame_id=frame_id, document_id=component.document_id, component_id=component.id,
        transform=validate_rigid_transform(component.transform),
    )


def force_in_root(
    force: AppliedForceRecord, frame: CoordinateFrame | None = None,
) -> ResolvedForce:
    """Convert an admitted total force and point; perform no reactions or statics."""
    from swreview.units import force_newtons

    frame = frame or force.frame
    if frame is None or force.direction is None:
        raise ValueError("force frame or direction is unknown")
    if force.frame is not None and frame != force.frame:
        raise ValueError("force frame override does not match its recorded frame")
    if force.magnitude.state != "known" or force.magnitude.value is None:
        raise ValueError("force magnitude is unknown")
    direction = normalize_direction(force.direction)
    root_direction = rotate_vector(frame.transform, direction)
    magnitude = force_newtons(force.magnitude.value, force.magnitude.unit)
    vector = _vector(tuple(value * magnitude for value in root_direction))
    point = transform_point_m(frame.transform, force.point_m) if force.point_m is not None else None
    return ResolvedForce(
        magnitude_n=magnitude, direction=root_direction, vector_n=vector, point_m=point,
    )


def assess_record_binding(
    record: EngineeringRecord, baseline: EvidenceBaseline, loaded: LoadedPackage,
) -> BindingAssessment:
    """Require target and force frame to match one exact saved evidence snapshot."""
    return assess_records_binding((record,), baseline, loaded)[record.record_id]


def assess_records_binding(
    records: Sequence[EngineeringRecord], baseline: EvidenceBaseline, loaded: LoadedPackage,
) -> dict[str, BindingAssessment]:
    """Assess records against one read/parse, with no cache beyond this call."""
    if len({record.record_id for record in records}) != len(records):
        raise ValueError("record IDs must be unique for batch binding assessment")
    if not records:
        return {}
    try:
        raw, package = _saved_snapshot(loaded)
        current = _baseline_from_snapshot(package, raw)
    except (ValueError, OSError, AnswerKeyAccessError):
        unavailable = BindingAssessment(
            status="unresolved", reasons=("saved_snapshot_unavailable",),
        )
        return {record.record_id: unavailable for record in records}
    return {
        record.record_id: _assess_record_snapshot(record, baseline, current, package, raw)
        for record in records
    }


def _assess_record_snapshot(
    record: EngineeringRecord, baseline: EvidenceBaseline, current: EvidenceBaseline,
    package: EvidencePackage, raw: bytes,
) -> BindingAssessment:
    assessment = _assess_anchor_snapshot(record.anchor, baseline, current, package, raw)
    if assessment.status != "matched_snapshot" or not isinstance(record, AppliedForceRecord):
        return assessment
    if record.frame is None:
        return BindingAssessment(status="unresolved", reasons=("frame_unknown",))
    try:
        expected = _frame_from_snapshot(
            package, current, record.frame.frame_id, record.frame.component_id,
        )
    except ValueError:
        return BindingAssessment(status="unresolved", reasons=("frame_evidence_unavailable",))
    if record.frame != expected:
        return BindingAssessment(status="mismatch", reasons=("frame_mismatch",))
    return assessment
