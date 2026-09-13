"""Findings: the reviewer's output, and the rules every finding has to satisfy.

Shapes follow data-model.md section 3 and `contracts/review-session.schema.json`.
`build_finding` is the only constructor the checks and tools use, so the evidence rules
live in one place (constitution Principles I and V).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from swreview.ids import SequentialIdAllocator
from swreview.ir.models import (
    Angle,
    Dimension,
    EvidencePackage,
    ManifestEntry,
    Quantity,
    SourceRef,
)

FindingStatus = Literal["demonstrated", "suspected", "unresolved", "checked_within_scope"]
Severity = Literal["high", "medium", "low", "info"]

NUMERIC_STATUSES: tuple[FindingStatus, ...] = ("demonstrated", "checked_within_scope")
NON_NUMERIC_STATUSES: tuple[FindingStatus, ...] = ("suspected", "unresolved")


class ReviewModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Calculation(ReviewModel):
    """What a deterministic check computed, and what it did not consider."""

    model: str
    inputs: dict[str, Quantity | Angle | str]
    assumptions: list[str]
    excluded_effects: list[str]
    result: dict[str, Quantity | bool | str | float]
    units_out: str
    function: str
    function_version: str


class Disposition(ReviewModel):
    """The engineer's decision on a finding. Never written by the reviewer."""

    decision: Literal["accepted", "rejected", "deferred"]
    note: str
    by: str
    at: datetime = Field(strict=False)


class FindingGroup(ReviewModel):
    """One finding standing for a repeated condition (FR-011)."""

    key: str
    member_component_ids: Annotated[list[str], Field(min_length=2)]


class Finding(ReviewModel):
    id: Annotated[str, StringConstraints(pattern=r"^F-[0-9]{3,}$")]
    check: str
    title: str
    status: FindingStatus
    severity: Severity
    component_ids: list[str]
    drawing_locations: list[SourceRef]
    provenance: Annotated[list[ManifestEntry], Field(min_length=1)]
    configuration: str
    observed: str
    requirement: str
    inputs: list[Dimension | Quantity | str]
    calculation: Calculation | None
    tool_result_ids: list[int]
    coverage_limits: list[str]
    recommended_action: str
    group: FindingGroup | None
    capture_ids: list[str]
    disposition: Disposition | None
    exception_id: str | None


class FindingIdAllocator(SequentialIdAllocator):
    """Yields `F-001`, `F-002`, ... within one session."""

    def __init__(self, start: int = 1) -> None:
        super().__init__(prefix="F", start=start)


def _referenced_document_ids(
    package: EvidencePackage,
    component_ids: Sequence[str],
    drawing_locations: Sequence[SourceRef],
) -> list[str]:
    by_id = {component.id: component for component in package.components}
    document_ids: list[str] = []
    for component_id in component_ids:
        component = by_id.get(component_id)
        if component is None:
            raise ValueError(f"unknown component id {component_id!r}")
        if component.document_id not in document_ids:
            document_ids.append(component.document_id)
    for location in drawing_locations:
        if location.document_id not in document_ids:
            document_ids.append(location.document_id)
    return document_ids


def _provenance(package: EvidencePackage, document_ids: Iterable[str]) -> list[ManifestEntry]:
    entries = {entry.document_id: entry for entry in package.manifest.entries}
    provenance: list[ManifestEntry] = []
    for document_id in document_ids:
        entry = entries.get(document_id)
        if entry is None:
            raise ValueError(
                f"no manifest entry for document {document_id!r}; a finding cannot cite a "
                "document without its version, revision and configuration"
            )
        provenance.append(entry)
    return provenance


def build_finding(
    *,
    finding_id: str,
    check: str,
    title: str,
    status: FindingStatus,
    severity: Severity,
    package: EvidencePackage,
    configuration: str,
    observed: str,
    requirement: str,
    recommended_action: str,
    component_ids: Sequence[str] = (),
    drawing_locations: Sequence[SourceRef] = (),
    inputs: Sequence[Dimension | Quantity | str] = (),
    calculation: Calculation | None = None,
    tool_result_ids: Sequence[int] = (),
    coverage_limits: Sequence[str] = (),
    group: FindingGroup | None = None,
    capture_ids: Sequence[str] = (),
    exception_id: str | None = None,
    numeric: bool = True,
) -> Finding:
    """Build a validated `Finding`, attaching provenance from the package manifest.

    `numeric=False` marks a finding that no deterministic calculation backs - a drawing
    reading, for example - and restricts it to `suspected` or `unresolved`.
    Raises `ValueError` when the evidence rules of data-model.md section 3 are not met.
    """
    if not component_ids and not drawing_locations:
        raise ValueError("a finding must name at least one of component_ids, drawing_locations")
    if not numeric and status not in NON_NUMERIC_STATUSES:
        raise ValueError(
            f"status {status!r} is not available to a non-numeric finding; "
            f"expected one of {NON_NUMERIC_STATUSES}"
        )
    if status in NUMERIC_STATUSES and calculation is None and not tool_result_ids:
        raise ValueError(
            f"status {status!r} requires a calculation or at least one tool_result_id"
        )
    if status == "unresolved" and not coverage_limits:
        raise ValueError("status 'unresolved' requires at least one entry in coverage_limits")

    document_ids = _referenced_document_ids(package, component_ids, drawing_locations)
    return Finding(
        id=finding_id,
        check=check,
        title=title,
        status=status,
        severity=severity,
        component_ids=list(component_ids),
        drawing_locations=list(drawing_locations),
        provenance=_provenance(package, document_ids),
        configuration=configuration,
        observed=observed,
        requirement=requirement,
        inputs=list(inputs),
        calculation=calculation,
        tool_result_ids=list(tool_result_ids),
        coverage_limits=list(coverage_limits),
        recommended_action=recommended_action,
        group=group,
        capture_ids=list(capture_ids),
        disposition=None,
        exception_id=exception_id,
    )
