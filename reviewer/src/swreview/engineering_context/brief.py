"""Bounded read-only projections of saved engineering inputs, never native approval.

Every field is selected explicitly. Private paths, native references, raw provenance
sources and engineer identities remain in the artifact rather than in model payloads.
Engineering prose is data: neither projection interprets it or changes a decision.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from swreview.engineering_context.binding import (
    assess_record_binding,
    assess_records_binding,
    force_in_root,
)
from swreview.engineering_context.models import (
    AppliedForceRecord,
    BindingAssessment,
    ContextArtifact,
    RequirementRecord,
    context_digest,
    decision_state,
    dependency_digest,
    record_digest,
)
from swreview.ir.loader import LoadedPackage

SUMMARY_MAX_BYTES = 6_000
RECORD_MAX_BYTES = 6_000
RECORD_LIMIT = 20
TEXT_LIMIT = 200
LIST_LIMIT = 10

_QUOTED_PATH = re.compile(r"([\"'])(?:[A-Za-z]:[\\/]|\\\\|/)[^\r\n]*\1")
# Whitespace is legal in file names. An unquoted path has no reliable end boundary,
# so conservatively omit the remainder of its line rather than leak trailing segments.
_PATH = re.compile(r"(?<!\w)[A-Za-z]:[\\/][^\r\n]*|\\\\[^\r\n]*|(?<![\w:/])/[^\r\n]*")
_NATIVE_REF = re.compile(
    r"\b(?:persist_ref|persistent_reference|native_reference)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)


class ContextBriefRefused(ValueError):
    """A requested record does not belong to the explicitly supplied context."""


def compact_json(payload: Any) -> str:
    """Canonical projection encoding, also used to measure its UTF-8 byte bound."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class _Projection:
    def __init__(self) -> None:
        self.omitted: dict[str, int] = {}
        self.lists: dict[str, list[Any]] = {}

    def text(self, text: str | None) -> str | None:
        if text is None:
            return None
        safe, refs = _NATIVE_REF.subn("[native reference omitted]", text)
        safe, quoted_paths = _QUOTED_PATH.subn("[private path omitted]", safe)
        safe, unquoted_paths = _PATH.subn("[private path omitted]", safe)
        paths = quoted_paths + unquoted_paths
        if paths:
            self.omitted["private_paths"] = self.omitted.get("private_paths", 0) + paths
        if refs:
            self.omitted["native_references"] = self.omitted.get("native_references", 0) + refs
        lost = max(0, len(safe) - TEXT_LIMIT)
        if lost:
            self.omitted["text_characters"] = self.omitted.get("text_characters", 0) + lost
        return safe[:TEXT_LIMIT]

    def sequence(self, values: list[Any], name: str, limit: int = LIST_LIMIT) -> list[Any]:
        kept = values[:limit]
        self.omitted[name] = len(values) - len(kept)
        self.lists[name] = kept
        return kept

    def identifier(self, value: str | None) -> str | None:
        """Keep a whole identifier or omit it; a shortened ID must never name a target."""
        if value is None:
            return None
        if _PATH.search(value) or _NATIVE_REF.search(value) or len(value.encode("utf-8")) > 160:
            self.omitted["identifier_fields"] = self.omitted.get("identifier_fields", 0) + 1
            return None
        return value

    def finish(self, payload: dict[str, Any], byte_limit: int) -> dict[str, Any]:
        payload["omitted"] = self.omitted
        while len(compact_json(payload).encode("utf-8")) > byte_limit:
            candidates = [(name, rows) for name, rows in self.lists.items() if rows]
            if not candidates:
                raise ValueError("engineering context projection metadata exceeds its bound")
            # Remove from the longest encoded list; deterministic names break equal sizes.
            name, rows = min(
                candidates,
                key=lambda item: (-len(compact_json(item[1]).encode("utf-8")), item[0]),
            )
            rows.pop()
            self.omitted[name] += 1
        return payload


def _assessment(
    artifact: ContextArtifact,
    record: RequirementRecord | AppliedForceRecord,
    loaded: LoadedPackage | None,
) -> BindingAssessment:
    if loaded is None:
        return BindingAssessment(
            status="not_verified", reasons=("no_evidence_snapshot_supplied",), needs_review=True
        )
    return assess_record_binding(record, artifact.baseline, loaded)


def _binding(assessment: BindingAssessment, projection: _Projection) -> dict[str, Any]:
    return {
        "status": assessment.status,
        "needs_review": assessment.needs_review,
        "reasons": projection.sequence(list(assessment.reasons), "binding.reasons"),
    }


def _header(artifact: ContextArtifact, projection: _Projection) -> dict[str, Any]:
    return {
        "projection_version": 1,
        "context_id": str(artifact.context_id),
        "context_digest": context_digest(artifact),
        "revision": artifact.revision,
        "evidence_scope": "saved_snapshot",
        "native_model_state": "not_observed",
        "engineering_text_role": "input_data",
        "structural_assessment": "not_performed",
        "baseline": {
            "package_id": str(artifact.baseline.package_id),
            "root_document_id": projection.identifier(artifact.baseline.root_document_id),
            "configuration": projection.identifier(artifact.baseline.configuration),
        },
    }


def _counts(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _root_force(
    artifact: ContextArtifact,
    record: AppliedForceRecord,
    assessment: BindingAssessment,
    projection: _Projection,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "unresolved",
        "root_document_id": projection.identifier(artifact.baseline.root_document_id),
        "reason": None,
        "magnitude_n": None,
        "direction": None,
        "vector_n": None,
        "point_m": None,
    }
    if assessment.status != "matched_snapshot":
        result["reason"] = "saved_snapshot_binding_not_matched"
    elif record.magnitude.state == "unknown":
        result["reason"] = "force_magnitude_unknown"
    elif record.direction is None or record.frame is None:
        result["reason"] = "force_direction_or_frame_unknown"
    else:
        try:
            resolved = force_in_root(record)
        except (ValueError, ArithmeticError):
            result["reason"] = "force_conversion_unavailable"
        else:
            result.update(
                status="resolved_for_saved_snapshot",
                magnitude_n=resolved.magnitude_n,
                direction=list(resolved.direction),
                vector_n=list(resolved.vector_n),
                point_m=list(resolved.point_m) if resolved.point_m is not None else None,
            )
    return result


def build_summary(
    artifact: ContextArtifact, loaded: LoadedPackage | None = None
) -> dict[str, Any]:
    """Summarize all inputs with exact counts and a bounded, deterministically sorted list."""
    projection = _Projection()
    records = sorted(artifact.records, key=lambda record: record.record_id)
    assessments = (
        assess_records_binding(records, artifact.baseline, loaded) if loaded is not None else None
    )
    rows = []
    decisions, bindings, review_count = [], [], 0
    for record in records:
        decision = decision_state(artifact, record)
        assessment = (
            assessments[record.record_id]
            if assessments is not None
            else _assessment(artifact, record, None)
        )
        needs_review = assessment.needs_review or decision == "needs_review"
        decisions.append(decision)
        bindings.append(assessment.status)
        review_count += int(needs_review)
        rows.append(
            {
                "record_id": record.record_id,
                "revision": record.revision,
                "record_digest": record_digest(record),
                "dependency_digest": dependency_digest(artifact.baseline, record),
                "kind": record.kind,
                "decision": decision,
                "binding": assessment.status,
                "needs_review": needs_review,
                "target": {
                    "kind": record.anchor.kind,
                    "document_id": projection.identifier(record.anchor.document_id),
                    "configuration": projection.identifier(record.anchor.configuration),
                    "component_id": projection.identifier(record.anchor.component_id),
                    "entity_id": projection.identifier(record.anchor.entity_id),
                    "referenced_configuration": projection.identifier(
                        record.anchor.referenced_configuration
                    ),
                },
                "text": projection.text(record.text)
                if isinstance(record, RequirementRecord)
                else None,
            }
        )
    payload = {
        **_header(artifact, projection),
        "counts": {
            "records": len(records),
            "by_kind": _counts([record.kind for record in records]),
            "by_decision": _counts(decisions),
            "by_binding": _counts(bindings),
            "needs_review": review_count,
            "unknown_force_magnitudes": sum(
                isinstance(record, AppliedForceRecord) and record.magnitude.state == "unknown"
                for record in records
            ),
        },
        "records": projection.sequence(rows, "records", RECORD_LIMIT),
    }
    return projection.finish(payload, SUMMARY_MAX_BYTES)


def build_record_detail(
    artifact: ContextArtifact, record_id: str, loaded: LoadedPackage | None = None
) -> dict[str, Any]:
    """Read one exact record's bounded input and receipt states, without confirming it."""
    record = next((record for record in artifact.records if record.record_id == record_id), None)
    if record is None:
        raise ContextBriefRefused("record does not belong to this engineering context")
    projection = _Projection()
    decision = decision_state(artifact, record)
    assessment = _assessment(artifact, record, loaded)
    payload: dict[str, Any] = {
        **_header(artifact, projection),
        "record": {
            "record_id": record.record_id,
            "revision": record.revision,
            "record_digest": record_digest(record),
            "dependency_digest": dependency_digest(artifact.baseline, record),
            "kind": record.kind,
            "decision": decision,
            "needs_review": assessment.needs_review or decision == "needs_review",
            "binding": _binding(assessment, projection),
            "target": {
                "anchor_id": record.anchor.anchor_id,
                "package_id": str(record.anchor.package_id),
                "kind": record.anchor.kind,
                "entity_id": projection.identifier(record.anchor.entity_id),
                "document_id": projection.identifier(record.anchor.document_id),
                "configuration": projection.identifier(record.anchor.configuration),
                "component_id": projection.identifier(record.anchor.component_id),
                "referenced_configuration": projection.identifier(
                    record.anchor.referenced_configuration
                ),
            },
            "provenance_kind": record.provenance.kind,
            "assumptions": projection.sequence(
                [projection.text(text) for text in record.assumptions],
                "assumptions",
            ),
        },
    }
    body = payload["record"]
    if isinstance(record, RequirementRecord):
        body["text"] = projection.text(record.text)
    else:
        body["magnitude"] = {
            "state": record.magnitude.state,
            "value": record.magnitude.value,
            "unit": record.magnitude.unit,
            "reason": projection.text(record.magnitude.reason),
        }
        body["direction"] = list(record.direction) if record.direction is not None else None
        body["application"] = record.application
        body["point_m"] = list(record.point_m) if record.point_m is not None else None
        body["frame"] = (
            {
                "frame_id": record.frame.frame_id,
                "document_id": projection.identifier(record.frame.document_id),
                "component_id": projection.identifier(record.frame.component_id),
                "transform": [list(row) for row in record.frame.transform]
                if record.frame.transform is not None
                else None,
            }
            if record.frame is not None
            else None
        )
        body["root_frame_force"] = _root_force(artifact, record, assessment, projection)
    # Stored order is the decision history; an actor's clock must not reorder receipts.
    receipts = [
        receipt for receipt in reversed(artifact.confirmations) if receipt.record_id == record_id
    ]
    body["confirmation_history_order"] = "latest_recorded_first"
    body["confirmation_history"] = projection.sequence(
        [
            {
                "receipt_id": str(receipt.receipt_id),
                "record_revision": receipt.record_revision,
                "record_digest": receipt.record_digest,
                "dependency_digest": receipt.dependency_digest,
                "decision": receipt.decision,
                "confirmed_at": receipt.confirmed_at.isoformat(),
                "covers_this_input_revision": (
                    receipt.record_revision == record.revision
                    and receipt.record_digest == body["record_digest"]
                    and receipt.dependency_digest == body["dependency_digest"]
                ),
            }
            for receipt in receipts
        ],
        "confirmation_history",
    )
    return projection.finish(payload, RECORD_MAX_BYTES)
