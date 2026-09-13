"""Session tools: the only tools that write, and they only write to the session.

One function per row of the "Session tools" table in contracts/agent-tools.md, plus
`record_drawing_finding` (the one non-numeric finding tool). Each of them enforces a rule
the model must not be able to talk its way around:

- `mark_coverage` cannot write the `failed` bucket - that bucket belongs to the tool
  layer, which writes it when a tool actually failed (contracts/agent-tools.md);
- `record_drawing_finding` cannot claim `demonstrated` or `checked_within_scope`: no
  calculation stands behind a drawing reading, so the strongest status it may take is
  `suspected` (constitution Principle II, FR-009);
- `request_capture` returns a capture that already exists or says `unresolved`; it never
  invents one, and the live-bridge path only opens when the bridge is wired (US3).
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import ValidationError

from swreview.findings import build_finding
from swreview.ir.models import SourceRef
from swreview.report.session import CoverageItem, CoverageScope, EvidenceRequest
from swreview.tools.context import (
    current_context,
    error_result,
    not_one_of,
    unknown_id,
)
from swreview.tools.query import ToolResult, as_json, sheet_reason

ModelCoverageBucket = Literal["checked", "skipped", "unresolved", "out_of_scope"]
MODEL_COVERAGE_BUCKETS: tuple[str, ...] = get_args(ModelCoverageBucket)
"""The buckets `mark_coverage` accepts. `failed` is written by the tool layer only."""

DrawingFindingStatus = Literal["suspected", "unresolved"]
DRAWING_FINDING_STATUSES: tuple[str, ...] = get_args(DrawingFindingStatus)
DRAWING_FINDING_CHECK = "drawing.manufacturing_inputs"
DRAWING_FINDING_SEVERITY: dict[str, str] = {"suspected": "medium", "unresolved": "low"}

CaptureView = Literal["iso", "front", "back", "left", "right", "top", "bottom", "current"]
CAPTURE_VIEWS: tuple[str, ...] = get_args(CaptureView)

TITLE_LENGTH = 80


def _title_from(observed: str) -> str:
    """A one-line title: the first sentence of `observed`, trimmed."""
    first = observed.strip().split(". ")[0].strip().rstrip(".")
    if len(first) <= TITLE_LENGTH:
        return first
    return first[: TITLE_LENGTH - 1].rstrip() + "…"


def request_evidence(what: str, why: str, entity_ids: list[str]) -> ToolResult:
    """Record something you need and the package does not have. Returns its id.

    Use this instead of assuming a missing value. The request stays open in the report
    until an engineer answers it, and the check it blocks stays unresolved.

    Args:
        what: The evidence you need, in the engineer's terms.
        why: Which check it unblocks and what you would conclude with it.
        entity_ids: Component, hole, fastener or document ids the request is about.
    """
    context = current_context()
    unknown = [
        entity_id for entity_id in entity_ids if context.entity_kind(entity_id) is None
    ]
    if unknown:
        return error_result(f"entity_ids not in this package: {unknown}")
    request = EvidenceRequest(
        id=next(context.evidence_request_ids),
        what=what,
        why=why,
        entity_ids=list(entity_ids),
        status="open",
        answer=None,
        answered_at=None,
    )
    context.session.evidence_requests.append(request)
    return {"status": "open", "evidence_request": as_json(request)}


def mark_coverage(
    check: str,
    bucket: ModelCoverageBucket,
    scope: dict[str, Any],
    reason: str,
) -> ToolResult:
    """Record what a check covered, or why it could not be run.

    Nothing is silently skipped: every checklist item ends the review with a finding or a
    coverage entry. `failed` is not available here; the tool layer writes that bucket when
    a tool fails.

    Args:
        check: Check identifier, or a checklist item id such as `fasteners`.
        bucket: One of checked, skipped, unresolved, out_of_scope.
        scope: What it covered: `component_ids`, `pairs`, `configuration`, `positions`,
            `document_ids`.
        reason: Why this bucket, in one sentence.
    """
    context = current_context()
    if bucket not in MODEL_COVERAGE_BUCKETS:
        if bucket == "failed":
            return error_result(
                "bucket 'failed' is written by the tool layer when a tool fails; "
                f"choose one of {list(MODEL_COVERAGE_BUCKETS)}"
            )
        return not_one_of("bucket", str(bucket), MODEL_COVERAGE_BUCKETS)
    try:
        coverage_scope = CoverageScope.model_validate(scope)
    except ValidationError as exc:
        return error_result(f"scope is not a valid coverage scope: {exc.errors(include_url=False)}")
    unknown = [
        entity_id
        for entity_id in [*coverage_scope.component_ids, *coverage_scope.document_ids]
        if context.entity_kind(entity_id) is None
    ]
    if unknown:
        return error_result(f"scope names ids not in this package: {unknown}")
    item = CoverageItem(check=check, scope=coverage_scope, reason=reason, error=None)
    getattr(context.session.coverage, bucket).append(item)
    return {"status": "recorded", "bucket": bucket, "coverage_item": as_json(item)}


def record_drawing_finding(
    document_id: str,
    sheet: str,
    observed: str,
    requirement: str,
    source_refs: list[SourceRef],
    status: DrawingFindingStatus,
    recommended_action: str,
) -> ToolResult:
    """Record a drawing problem that no calculation stands behind.

    For missing manufacturing inputs, ambiguous callouts and unreadable sheets. Because
    nothing numeric backs it, the strongest status available is `suspected`;
    `demonstrated` and `checked_within_scope` are not.

    Args:
        document_id: Drawing document id the finding is about.
        sheet: Sheet name on that document.
        observed: What the drawing does or does not say.
        requirement: The governing requirement and where it comes from.
        source_refs: Where on the drawing this was read; each needs a document_id and a
            sheet, annotation, persist_ref or page.
        status: suspected or unresolved.
        recommended_action: What the engineer should do next.
    """
    context = current_context()
    if context.document(document_id) is None:
        return unknown_id("document", document_id)
    if status not in DRAWING_FINDING_STATUSES:
        return error_result(
            f"status {status!r} is not available to a drawing finding; "
            f"no calculation backs it, so use one of {list(DRAWING_FINDING_STATUSES)}"
        )
    if not source_refs:
        return error_result("source_refs must name at least one place on the drawing")
    locations: list[SourceRef] = []
    for raw in source_refs:
        try:
            location = raw if isinstance(raw, SourceRef) else SourceRef.model_validate(raw)
        except ValidationError as exc:
            return error_result(f"source_ref is not valid: {exc.errors(include_url=False)}")
        if context.document(location.document_id) is None:
            return unknown_id("document", location.document_id)
        locations.append(location)

    try:
        finding = build_finding(
            finding_id=next(context.finding_ids),
            check=DRAWING_FINDING_CHECK,
            title=_title_from(observed),
            status=status,
            severity=DRAWING_FINDING_SEVERITY[status],
            package=context.ir,
            configuration=context.ir.design.active_configuration,
            observed=observed,
            requirement=requirement,
            recommended_action=recommended_action,
            drawing_locations=locations,
            coverage_limits=_drawing_coverage_limits(document_id, sheet, status),
            numeric=False,
        )
    except ValueError as exc:
        return error_result(str(exc))
    context.session.findings.append(finding)
    return {"status": "recorded", "finding": as_json(finding)}


def _drawing_coverage_limits(document_id: str, sheet: str, status: str) -> list[str]:
    """Why an unresolved drawing finding could not be settled, from the sheet itself."""
    if status != "unresolved":
        return []
    context = current_context()
    for extracted in context.ir.drawings:
        if extracted.document_id == document_id and extracted.sheet_name == sheet:
            reason = sheet_reason(context.ir, extracted)
            if reason is not None:
                return [f"{document_id} sheet {sheet}: {reason}"]
            break
    return [f"{document_id} sheet {sheet}: the drawing does not state the required value"]


def get_review_checklist() -> list[dict[str, str]]:
    """The mandatory review checklist with the bucket each item currently sits in.

    `bucket` is `finding` when a finding already covers the item, one of `checked`,
    `skipped`, `unresolved`, `out_of_scope` when a coverage entry does, and `open` when
    nothing does yet. The review is not finished while anything is `open`.
    """
    context = current_context()
    return context.checklist.buckets(context.session)


def request_capture(entity_id: str, view: CaptureView) -> ToolResult:
    """A rendered view of one entity, when the package already holds one.

    Returns an existing capture from the package. Without the live SOLIDWORKS bridge
    there is no way to make a new one, and the result is `unresolved` rather than a
    description of what the view would show.

    Args:
        entity_id: Component, hole or fastener id to look at.
        view: One of iso, front, back, left, right, top, bottom, current.
    """
    context = current_context()
    if context.entity_kind(entity_id) is None:
        return unknown_id("entity", entity_id)
    if view not in CAPTURE_VIEWS:
        return not_one_of("view", str(view), CAPTURE_VIEWS)
    captures = [
        capture for capture in context.ir.captures if entity_id in capture.component_ids
    ]
    for capture in captures:
        if capture.view == view:
            return {"status": "found", "capture": as_json(capture)}
    if captures:
        return {
            "status": "found",
            "capture": as_json(captures[0]),
            "note": f"no {view!r} capture exists for {entity_id!r}; this is the "
            f"{captures[0].view!r} view already in the package",
        }
    if context.bridge is None:
        return {"status": "unresolved", "reason": "no capture and no bridge"}
    return {
        "status": "unresolved",
        "reason": "the live SOLIDWORKS bridge is wired but capture through it is not "
        "implemented in this build",
    }
