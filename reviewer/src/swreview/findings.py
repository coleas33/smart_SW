"""Findings: the reviewer's output, and the rules every finding has to satisfy.

Shapes follow data-model.md section 3 and `contracts/review-session.schema.json`.
`build_finding` is the only constructor the checks and tools use, so the evidence rules
live in one place (constitution Principles I and V).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
)

from swreview.ids import SequentialIdAllocator
from swreview.ir.models import (
    Angle,
    Dimension,
    EvidencePackage,
    ManifestEntry,
    Quantity,
    SourceRef,
    omit_when_null,
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

    carried_over_from: UUID | None = Field(default=None, strict=False)
    """The session that **produced** this verdict, when this run carried it rather than
    computing it (lever 11a, `swreview.carry_over`). This is the machine-readable signal;
    the other two fields are for a human reading the report.

    Optional, and absent from `required` in `review-session.schema.json`, for the reason
    `provider_info` and `retry_of` are on the session: a finding written before the field
    existed loads unchanged. `None` is the normal case and means this run computed it.
    """

    carried_over_at: datetime | None = Field(default=None, strict=False)
    """When the carry-over decision was made - not when the verdict was first produced."""

    carry_over_key: str | None = None
    """The key that justified the carry, stored so the decision is reproducible by hand
    against the package (`carry_over.carry_over_key`)."""

    @model_serializer(mode="wrap")
    def _omit_null_carry_over_fields(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Leave the three lever 11a fields out when they are null (`omit_when_null`).

        Every run with `carry_over_rms` off computes every finding it reports, so all three
        are null on that arm and the finding serializes to the bytes it did before the
        lever existed - in `session.json`, in the `finding` event and in the tool payload
        the model is charged for.
        """
        return omit_when_null(
            handler, self, "carried_over_from", "carried_over_at", "carry_over_key"
        )


def carried_count(findings: Iterable[Finding]) -> int:
    """How many of `findings` this run carried rather than computed (lever 11a).

    One definition, three readers - the report's coverage line, `PackageScore`'s
    `carried_findings`, and the workstation harness's per-arm counter (FR-104) - so no two
    of them can come to disagree about what "carried" means. It lives here rather than in
    `carry_over.py` because it reads nothing but the field, and because a report that had
    to import the carry-over machinery to count three findings would pull the whole check
    registry in behind it.
    """
    return sum(1 for finding in findings if finding.carried_over_from is not None)


def carried_and_computed(findings: Sequence[Finding]) -> tuple[int, int]:
    """`(carried, computed)` over `findings`: the pair the report states (FR-102)."""
    carried = carried_count(findings)
    return carried, len(findings) - carried


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
