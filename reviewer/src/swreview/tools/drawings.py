"""The drawing family: the drawing check and the per-part brief (feature 011).

`contracts/questions.md` section 1 is normative. The family is offered only when the package
carries drawing evidence (`drawing_evidence`) - a drawing record or a drawing candidate - by
`tools/registry.ToolRegistry._offered`, exactly as the standards, bridge and remodel families
are offered on their conditions. It is outside `REGISTRATIONS`, so `TOOL_FUNCTIONS`, the MCP
list and the terminal profile never see it, and a review of a package with no drawing evidence
offers, plans and pays for exactly what it did before feature 011 (FR-037).

`check_drawings` records what `checks/drawing_context.py` computes: one `drawing.context`
coverage item per reviewed document and the few questions only the engineer can answer,
written through the one evidence-request writer (`tools/session.record_evidence_request`), so
the pane's "Questions for you" panel and feature 008's batch route serve them unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from swreview.bridge.client import BridgeError
from swreview.checks.drawing_context import (
    CANDIDATE_CONFIRM,
    CONFORMANCE_CHECK,
    CONTEXT_CHECK,
    QuestionSpec,
    candidate_question,
    run_drawing_context,
)
from swreview.checks.result import DocumentResult
from swreview.drawings.brief import BriefRefused, build_brief
from swreview.drawings.evidence import DrawingIndex
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import CoverageItem, CoverageScope, EvidenceRequest
from swreview.tools.checks_mechanical import _attached_profile
from swreview.tools.context import ToolContext, current_context, error_result
from swreview.tools.joint_context import joint_analysis
from swreview.tools.query import ToolResult
from swreview.tools.recording import record_result
from swreview.tools.session import record_evidence_request

__all__ = [
    "CONFIRMED_OPEN_CHECK",
    "DRAWINGS_TOOL",
    "NO_CONNECTION",
    "TEN_DRAWINGS",
    "check_drawings",
    "drawing_evidence",
    "get_drawing_brief",
    "read_confirmed_candidates",
]

DRAWINGS_TOOL = "check_drawings"
"""The family's check, named once for the pre-run's plan, its re-call key and lever 13."""

COVERAGE_BUCKETS: tuple[str, ...] = ("checked", "skipped", "unresolved")
"""The buckets a `drawing.context` item lands in."""


def drawing_evidence(package: EvidencePackage) -> bool:
    """Whether the package carries drawing evidence: the one condition the family is offered
    and planned on."""
    return bool(package.drawing_records or package.drawing_candidates)


def _already_asked(requests: list[EvidenceRequest], spec: QuestionSpec) -> bool:
    return any(
        request.question == spec.question
        and request.what == spec.what
        and tuple(request.entity_ids) == spec.entity_ids
        for request in requests
    )


def _record(context: ToolContext) -> dict[str, Any]:
    """Record the drawing context into `context`'s session and count what it recorded.

    The coverage stands for the current state of every reviewed document, so a second call
    restates it rather than adding to it, and a question already on the session is never asked
    twice - even with no re-call guard in front of the tool (FR-035, SC-008).
    """
    session = context.require_session()
    result = run_drawing_context(context.ir, profile=_attached_profile(context))
    context.withdraw_coverage((CONTEXT_CHECK, CONFORMANCE_CHECK), COVERAGE_BUCKETS)
    counts = dict.fromkeys(COVERAGE_BUCKETS, 0)
    for coverage in result.coverage:
        context.record_coverage(coverage.status, coverage.coverage_item())
        counts[coverage.status] += 1
    for bucket, item in result.conformance.coverage:
        context.record_coverage(bucket, item)
    finding_ids = _record_conformance(context, result.conformance.findings)
    if isinstance(finding_ids, dict):
        return finding_ids
    for spec in result.questions:
        if _already_asked(session.evidence_requests, spec):
            continue
        record_evidence_request(
            context,
            spec.what,
            spec.why,
            list(spec.entity_ids),
            question=spec.question,
            options=list(spec.options),
            blocks=spec.blocks,
        )
    return {
        "status": "recorded",
        "drawings": len(context.ir.drawing_records),
        "candidates": len(context.ir.drawing_candidates),
        "questions": len(result.questions),
        "findings": len(finding_ids),
        "finding_ids": finding_ids,
        "coverage": counts,
    }


def _record_conformance(
    context: ToolContext, findings: Sequence[DocumentResult]
) -> list[str] | dict[str, str]:
    """Record each drawing's `drawing_profile.conformance` finding once, and return their ids,
    or the error result of a finding the session refused.

    A finding the session already holds for the same drawing, saying the same thing, is not
    recorded twice: its id is returned instead, so a repeated call adds nothing (FR-035).
    """
    session = context.require_session()
    ids: list[str] = []
    for item in findings:
        existing = next(
            (
                finding
                for finding in session.findings
                if finding.check == CONFORMANCE_CHECK
                and [entry.document_id for entry in finding.provenance] == list(item.documents)
                and finding.observed == item.result.observed
            ),
            None,
        )
        if existing is not None:
            ids.append(existing.id)
            continue
        recorded = record_result(
            context,
            item.result,
            component_ids=list(item.component_ids),
            document_ids=list(item.document_ids),
            tool_result_ids=[context.current_step_id],
        )
        if "error" in recorded:
            return recorded
        ids.append(recorded["finding"]["id"])
    return ids


def check_drawings() -> ToolResult:
    """Check what the open drawings show about each reviewed document and ask the engineer
    what only they know.

    Notes:
        Takes no argument.
    """
    return _record(current_context())


def get_drawing_brief(document_id: str) -> ToolResult:
    """A short brief of one part or assembly: what it is, its joints, the interfaces that need
    a callout, what its drawing covers, and the engineer's answers.

    Args:
        document_id: A part or assembly document id.
    """
    context = current_context()
    try:
        brief = build_brief(
            context.ir,
            context.session,
            _attached_profile(context),
            document_id,
            joint_map=joint_analysis(context).joint_map,
        )
    except BriefRefused as refusal:
        return error_result(str(refusal))
    return brief.content


# --- the confirmed read-only open (User Story 5 part B, `contracts/confirmed-open.md` 1) ---------

CONFIRMED_OPEN_CHECK = "drawing.confirmed_open"
"""The coverage `check` of one confirmed candidate's outcome: never a finding's, never a
checklist item's id, so it closes nothing."""

MAX_DRAWINGS = 10
"""The drawings one package holds at most (FR-013, FR-056): the confirmed reads stop there."""

NO_CONNECTION = (
    "no SOLIDWORKS connection in this review, so the drawing was not opened; open it and "
    "review again"
)
TEN_DRAWINGS = "the package already holds ten drawings, so this one was not opened"


def _is_confirmed_candidate(request: EvidenceRequest, spec: QuestionSpec | None) -> bool:
    """The request is exactly the candidate question this package asks, answered with
    `CANDIDATE_CONFIRM` exactly: the one answer that acts. The page recognises nothing."""
    return (
        spec is not None
        and request.status == "answered"
        and request.answer == CANDIDATE_CONFIRM
        and request.question == spec.question
        and tuple(request.options) == spec.options
        and tuple(request.entity_ids) == spec.entity_ids
    )


def _read_outcome(result: Any) -> str:
    """What the host's `drawing.read` result says happened (section 2's result shape)."""
    body = result if isinstance(result, dict) else {}
    sheets = body.get("sheets")
    counted = (
        f"{sheets} sheet" if sheets == 1 else f"{sheets} sheets" if sheets is not None else ""
    )
    if not body.get("opened"):
        return "read as it stood; it was already open, so it was left open"
    if body.get("closed"):
        return f"opened read-only, read and closed ({counted})"
    return f"opened read-only and read ({counted}), but not closed again: close it in SOLIDWORKS"


def _confirmed_item(document_id: str, reason: str, error: str | None = None) -> CoverageItem:
    return CoverageItem(
        check=CONFIRMED_OPEN_CHECK,
        scope=CoverageScope(document_ids=[document_id]),
        reason=reason,
        error=error,
    )


def read_confirmed_candidates(
    context: ToolContext, answered: Sequence[EvidenceRequest], run_dir: Path
) -> list[CoverageItem]:
    """Read every confirmed candidate through the bridge, then reload the package.

    Called by `ReviewRun.answer_evidence_batch` after the answers are marked and before the
    resumed turn (`contracts/confirmed-open.md` section 1). It acts only on an answered request
    that is this package's candidate question answered `CANDIDATE_CONFIRM`; then it asks
    `context.bridge.drawing_read(run_id, document_id)` once per candidate, in the question's
    order, with the run folder's own name as `run_id` and never a path, while the package holds
    fewer than ten drawing records. The host (the add-in) opens, reads, appends and closes;
    this side only asks, records one `drawing.confirmed_open` coverage item per candidate, and
    reloads `run_dir/package.json` into `context` when a read succeeded. Returns the items
    recorded, in the question's order; nothing else in the session changes.
    """
    spec = candidate_question(DrawingIndex.for_package(context.ir))
    if not any(_is_confirmed_candidate(request, spec) for request in answered):
        return []
    assert spec is not None
    held = len(context.ir.drawing_records)
    outcomes: list[tuple[str, str, str | None, bool]] = []
    for document_id in spec.entity_ids:
        if context.bridge is None:
            outcomes.append((document_id, NO_CONNECTION, None, False))
            continue
        if held >= MAX_DRAWINGS:
            outcomes.append((document_id, TEN_DRAWINGS, None, False))
            continue
        try:
            result = context.bridge.drawing_read(run_dir.name, document_id)
        except BridgeError as error:
            outcomes.append((document_id, str(error), type(error).__name__, False))
            continue
        held += 1
        outcomes.append((document_id, _read_outcome(result), None, True))

    reload_error = None
    if any(read for *_, read in outcomes):
        try:
            context.reload_package(load_package(run_dir))
        except (OSError, ValueError) as error:
            reload_error = f"{type(error).__name__}: {error}"
    items: list[CoverageItem] = []
    for document_id, reason, error, read in outcomes:
        if read and reload_error is not None:
            item = _confirmed_item(
                document_id,
                f"{reason}; but the package in the run folder could not be reloaded: "
                f"{reload_error}",
                reload_error,
            )
            context.record_coverage("unresolved", item)
        else:
            item = _confirmed_item(document_id, reason, error)
            context.record_coverage("checked" if read else "unresolved", item)
        items.append(item)
    return items
