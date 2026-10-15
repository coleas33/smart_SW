"""Strict, immutable sidecar records; confirmation is separate from CAD binding."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

from swreview.ir.models import PersistRef

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("engineering text and labels cannot be blank")
    return value


Label = Annotated[str, StringConstraints(min_length=1, max_length=256), AfterValidator(_nonblank)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=2048), AfterValidator(_nonblank)]
Vector3 = tuple[float, float, float]
Transform = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


class ContextModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)


class EvidenceBaseline(ContextModel):
    package_id: UUID
    package_sha256: Digest
    schema_version: Label
    root_document_id: Label
    configuration: Label
    scope: Literal["saved_snapshot"] = "saved_snapshot"
    without_live_interference_sha256: Digest | None = None
    """Owner decision 107A: the package's digest without what the review's live interference
    check rewrites - the active configuration's interference rows and the check's gaps - so
    that rewrite alone keeps saved inputs matched. Absent on a context saved before it, which
    then compares exact bytes only; omitted when absent, so its digests are unchanged."""

    @model_serializer(mode="wrap")
    def _omit_absent_live_digest(self, handler: SerializerFunctionWrapHandler) -> dict:
        data = handler(self)
        if self.without_live_interference_sha256 is None:
            data.pop("without_live_interference_sha256", None)
        return data


class TargetAnchor(ContextModel):
    anchor_id: Identifier
    package_id: UUID
    kind: Literal["document", "component", "face"]
    entity_id: Label
    document_id: Label | None = None
    configuration: Label | None = None
    component_id: Label | None = None
    full_path: Text | None = None
    referenced_configuration: Label | None = None
    persist_ref: PersistRef | None = None
    persist_ref_scope: Label | None = None
    transform_sha256: Digest | None = None
    geometry_sha256: Digest | None = None


class Provenance(ContextModel):
    kind: Literal["engineer", "extracted", "catalogue", "derived", "ai_proposal", "unknown"]
    source: Label
    reason: Text | None = None


class ForceQuantity(ContextModel):
    state: Literal["known", "unknown"]
    value: float | None = None
    unit: Literal["N", "kN", "lbf"]
    reason: Text | None = None

    @model_validator(mode="after")
    def consistent_value(self) -> ForceQuantity:
        if self.state == "known" and (self.value is None or self.value < 0):
            raise ValueError("known force magnitude requires a nonnegative finite value")
        if self.state == "unknown" and (self.value is not None or not self.reason):
            raise ValueError("unknown force requires a reason and no value")
        return self


class CoordinateFrame(ContextModel):
    frame_id: Identifier
    document_id: Label
    component_id: Label | None = None
    transform: Transform

    @model_validator(mode="after")
    def rigid(self) -> CoordinateFrame:
        from swreview.engineering_context.binding import validate_rigid_transform

        validate_rigid_transform(self.transform)
        return self


class Record(ContextModel):
    record_id: Identifier
    revision: int = Field(ge=1, le=2_147_483_647)
    anchor: TargetAnchor
    provenance: Provenance
    assumptions: tuple[Text, ...] = Field(default=(), max_length=20)


class RequirementRecord(Record):
    kind: Literal["requirement"] = "requirement"
    text: Text


class AppliedForceRecord(Record):
    kind: Literal["applied_force"] = "applied_force"
    magnitude: ForceQuantity
    direction: Vector3 | None = None
    frame: CoordinateFrame | None = None
    application: Literal["component_total", "face_total"]
    point_m: Vector3 | None = None

    @model_validator(mode="after")
    def target_kind(self) -> AppliedForceRecord:
        expected = "face" if self.application == "face_total" else "component"
        if self.anchor.kind != expected:
            raise ValueError("force application must match the anchor kind")
        if self.direction is not None and not any(self.direction):
            raise ValueError("force direction cannot be zero")
        return self


EngineeringRecord = Annotated[RequirementRecord | AppliedForceRecord, Field(discriminator="kind")]


class ConfirmationReceipt(ContextModel):
    receipt_id: UUID
    record_id: Identifier
    record_revision: int = Field(ge=1, le=2_147_483_647)
    record_digest: Digest
    dependency_digest: Digest
    actor: Label
    confirmed_at: datetime
    decision: Literal["confirmed", "rejected"] = "confirmed"

    @model_validator(mode="after")
    def timestamp(self) -> ConfirmationReceipt:
        if self.confirmed_at.tzinfo is None or self.confirmed_at.utcoffset() is None:
            raise ValueError("confirmation timestamp requires a timezone")
        return self


class ContextArtifact(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context_id: UUID
    revision: int = Field(ge=1, le=2_147_483_647)
    previous_digest: Digest | None = None
    baseline: EvidenceBaseline
    records: tuple[EngineeringRecord, ...] = Field(default=(), max_length=500)
    confirmations: tuple[ConfirmationReceipt, ...] = Field(default=(), max_length=5000)
    updated_at: datetime

    @model_validator(mode="after")
    def consistent_history(self) -> ContextArtifact:
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("context timestamp requires a timezone")
        if (self.revision == 1) != (self.previous_digest is None):
            raise ValueError("context predecessor must correspond to its revision")
        by_id = {record.record_id: record for record in self.records}
        if len(by_id) != len(self.records):
            raise ValueError("record IDs must be unique")
        if len({receipt.receipt_id for receipt in self.confirmations}) != len(self.confirmations):
            raise ValueError("receipt IDs must be unique")
        for record in self.records:
            if record.anchor.package_id != self.baseline.package_id:
                raise ValueError("record anchor must belong to the context baseline")
        for receipt in self.confirmations:
            record = by_id.get(receipt.record_id)
            if record is None or receipt.record_revision > record.revision:
                raise ValueError("confirmation must refer to an existing record revision")
        return self


class BindingAssessment(ContextModel):
    status: Literal["matched_snapshot", "not_verified", "unresolved", "mismatch"]
    reasons: tuple[str, ...] = ()
    needs_review: bool = True


class ResolvedForce(ContextModel):
    magnitude_n: float
    direction: Vector3
    vector_n: Vector3
    point_m: Vector3 | None = None


def canonical_bytes(model: BaseModel) -> bytes:
    return json.dumps(
        model.model_dump(mode="json", warnings=False),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def record_digest(record: Record) -> str:
    return hashlib.sha256(canonical_bytes(record)).hexdigest()


def context_digest(artifact: ContextArtifact) -> str:
    return hashlib.sha256(canonical_bytes(artifact)).hexdigest()


def dependency_digest(baseline: EvidenceBaseline, record: Record) -> str:
    # Conservative baseline binding: a new extraction never silently inherits approval.
    payload = {
        "baseline": baseline.model_dump(mode="json"),
        "anchor": record.anchor.model_dump(mode="json"),
    }
    if isinstance(record, AppliedForceRecord):
        payload["frame"] = record.frame.model_dump(mode="json") if record.frame else None
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def decision_state(artifact: ContextArtifact, record: Record) -> str:
    history = [r for r in artifact.confirmations if r.record_id == record.record_id]
    if not history:
        return "draft"
    last = history[-1]
    if (
        last.record_revision == record.revision
        and last.record_digest == record_digest(record)
        and last.dependency_digest == dependency_digest(artifact.baseline, record)
    ):
        return last.decision
    return "needs_review"
