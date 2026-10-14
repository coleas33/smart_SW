"""Offline entry and explicit approval of requirements and total applied forces."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from swreview.engineering_context.binding import (
    anchor_from_package,
    assess_record_binding,
    assess_records_binding,
    baseline_from_package,
    force_in_root,
    frame_from_package,
)
from swreview.engineering_context.models import (
    AppliedForceRecord,
    ContextArtifact,
    ForceQuantity,
    Provenance,
    RequirementRecord,
    context_digest,
    decision_state,
    dependency_digest,
    record_digest,
)
from swreview.engineering_context.store import ContextStore, confirm_record, put_record
from swreview.ir.loader import LoadedPackage, load_package


def store_for_package(directory: Path, loaded: LoadedPackage) -> ContextStore:
    roots = [loaded.base_dir]
    for document in loaded.package.documents:
        if document.path:
            source = Path(document.path)
            if not source.is_absolute():
                source = loaded.base_dir / source
            roots.append(source.parent)
    return ContextStore(directory, source_roots=tuple(roots))


def initialize(package_dir: Path, directory: Path) -> ContextArtifact:
    loaded = load_package(package_dir)
    artifact = ContextArtifact(
        context_id=uuid4(),
        revision=1,
        baseline=baseline_from_package(loaded),
        updated_at=datetime.now(UTC),
    )
    store_for_package(directory, loaded).publish(artifact, expected_head=None)
    return artifact


def _current(package_dir: Path, directory: Path, expected_head: str):
    loaded = load_package(package_dir)
    store = store_for_package(directory, loaded)
    artifact = store.load()
    if artifact is None:
        raise ValueError("initialize the context before adding records")
    if context_digest(artifact) != expected_head:
        raise ValueError("context head changed; inspect it before retrying")
    if baseline_from_package(loaded) != artifact.baseline:
        raise ValueError("saved evidence changed; create a new context for the new snapshot")
    return loaded, store, artifact


def _revision(artifact: ContextArtifact, record_id: str) -> int:
    return next((r.revision + 1 for r in artifact.records if r.record_id == record_id), 1)


def _anchor(
    loaded: LoadedPackage, record_id: str, kind: str, entity_id: str, component_id: str | None
):
    anchor_id = "anchor:" + hashlib.sha256(record_id.encode("utf-8")).hexdigest()[:20]
    return anchor_from_package(loaded, anchor_id, kind, entity_id, component_id)


def enter_requirement(
    package_dir: Path,
    directory: Path,
    *,
    record_id: str,
    kind: str,
    entity_id: str,
    text: str,
    expected_head: str,
    component_id: str | None = None,
    provenance_kind: str = "engineer",
    assumptions: tuple[str, ...] = (),
) -> ContextArtifact:
    loaded, store, current = _current(package_dir, directory, expected_head)
    record = RequirementRecord(
        record_id=record_id,
        revision=_revision(current, record_id),
        anchor=_anchor(loaded, record_id, kind, entity_id, component_id),
        text=text,
        provenance=Provenance(kind=provenance_kind, source="offline-entry"),
        assumptions=assumptions,
    )
    updated = put_record(current, record)
    store.publish(updated, expected_head=expected_head)
    return updated


def enter_force(
    package_dir: Path,
    directory: Path,
    *,
    record_id: str,
    kind: str,
    entity_id: str,
    magnitude: float | None,
    unit: str,
    direction: tuple[float, float, float] | None,
    expected_head: str,
    unknown_reason: str | None = None,
    component_id: str | None = None,
    frame_component_id: str | None = None,
    point_m: tuple[float, float, float] | None = None,
    provenance_kind: str = "engineer",
    assumptions: tuple[str, ...] = (),
):
    if kind not in ("component", "face"):
        raise ValueError("force target must be a component or face")
    loaded, store, current = _current(package_dir, directory, expected_head)
    quantity = ForceQuantity(
        state="unknown" if magnitude is None else "known",
        value=magnitude,
        unit=unit,
        reason=unknown_reason,
    )
    record = AppliedForceRecord(
        record_id=record_id,
        revision=_revision(current, record_id),
        anchor=_anchor(loaded, record_id, kind, entity_id, component_id),
        magnitude=quantity,
        direction=direction,
        frame=frame_from_package(loaded, "frame:input", frame_component_id),
        application="face_total" if kind == "face" else "component_total",
        point_m=point_m,
        provenance=Provenance(kind=provenance_kind, source="offline-entry"),
        assumptions=assumptions,
    )
    updated = put_record(current, record)
    store.publish(updated, expected_head=expected_head)
    return updated


def inspect_context(package_dir: Path, directory: Path) -> dict:
    loaded = load_package(package_dir)
    artifact = store_for_package(directory, loaded).load()
    if artifact is None:
        raise ValueError("context does not exist")
    rows = []
    assessments = assess_records_binding(artifact.records, artifact.baseline, loaded)
    for record in artifact.records:
        binding = assessments[record.record_id]
        row = {
            "record": record.model_dump(mode="json"),
            "record_digest": record_digest(record),
            "dependency_digest": dependency_digest(artifact.baseline, record),
            "decision": decision_state(artifact, record),
            "binding": binding.model_dump(mode="json"),
            "freshness": "current_snapshot" if not binding.needs_review else "needs_review",
        }
        if isinstance(record, AppliedForceRecord):
            try:
                row["resolved_force"] = force_in_root(record).model_dump(mode="json")
            except ValueError:
                row["resolved_force"] = None
        rows.append(row)
    return {
        **publication(artifact),
        "scope": "saved_snapshot",
        "native_model_state": "not_observed",
        "confirmation_count": len(artifact.confirmations),
        "records": rows,
    }


def approve(
    package_dir: Path,
    directory: Path,
    *,
    record_id: str,
    actor: str,
    expected_head: str,
    expected_record_digest: str,
    expected_dependency_digest: str,
):
    loaded, store, current = _current(package_dir, directory, expected_head)
    record = next((r for r in current.records if r.record_id == record_id), None)
    if record is None:
        raise ValueError("context record does not exist")
    if assess_record_binding(record, current.baseline, loaded).needs_review:
        raise ValueError("record cannot be confirmed against unresolved or changed evidence")
    updated = confirm_record(
        current,
        record_id,
        actor=actor,
        expected_record_digest=expected_record_digest,
        expected_dependency_digest=expected_dependency_digest,
    )
    store.publish(updated, expected_head=expected_head)
    return updated


def publication(artifact: ContextArtifact) -> dict:
    return {
        "context_id": str(artifact.context_id),
        "revision": artifact.revision,
        "head_digest": context_digest(artifact),
    }
