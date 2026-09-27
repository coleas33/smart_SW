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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from swreview.bridge.client import BridgeError, DrawingReadMode
from swreview.checks.drawing_context import (
    CANDIDATE_CONFIRM,
    CANDIDATES_BLOCK,
    CLOSED_BY_CODE,
    CONFORMANCE_CHECK,
    CONTEXT_CHECK,
    DRAWING_STATES,
    CandidateFile,
    QuestionSpec,
    candidate_files,
    candidate_question,
    run_drawing_context,
)
from swreview.checks.questions import already_asked
from swreview.checks.result import DocumentResult
from swreview.drawings.brief import BriefRefused, build_brief
from swreview.drawings.evidence import DrawingIndex
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import CoverageItem, CoverageScope, EvidenceRequest
from swreview.tools.checks_mechanical import review_profile
from swreview.tools.context import ToolContext, current_context, error_result
from swreview.tools.joint_context import joint_analysis
from swreview.tools.query import ToolResult
from swreview.tools.recording import record_result
from swreview.tools.session import record_evidence_request

if TYPE_CHECKING:
    from swreview.checks.part_roles import PartRoles  # 013 T018, lane P

__all__ = [
    "CONFIRMED_OPEN_CHECK",
    "DRAWINGS_TOOL",
    "NO_CONNECTION",
    "PART_ROLES_ATTRIBUTE",
    "TEN_DRAWINGS",
    "ConfirmedRead",
    "check_drawings",
    "drawing_evidence",
    "get_drawing_brief",
    "read_confirmed_candidates",
]

DRAWINGS_TOOL = "check_drawings"
"""The family's check, named once for the pre-run's plan, its re-call key and lever 13."""

COVERAGE_BUCKETS: tuple[str, ...] = ("checked", "skipped", "unresolved")
"""The buckets a `drawing.context` item lands in."""

PART_ROLES_ATTRIBUTE = "part_roles"
"""The context attribute `start_review` attaches the review's part roles under (013
`contracts/part-roles.md` section 5), beside the standards run's.

**A stand-in, for the integrator.** 013 T022 (lane S) defines it as
`tools/registry.PART_ROLES_ATTRIBUTE`, which this lane does not edit; until then no review
attaches roles and every part and assembly is a drawing subject, as before 013.
`test_tools_check_drawings.py` asserts the two names equal once T022 lands; then this constant
should give way to the registry's, imported where it is read (the registry imports this module,
so a module-level import would be circular)."""


def drawing_evidence(package: EvidencePackage) -> bool:
    """Whether the package carries drawing evidence: the one condition the family is offered
    and planned on."""
    return bool(package.drawing_records or package.drawing_candidates)


def _review_roles(context: ToolContext) -> PartRoles | None:
    """The part roles attached to the review, or `None` on a context that never classified - a
    test, a golden case, the command line - where every part and assembly is a drawing subject.
    Read, never computed: the roles are classified once, at `start_review` (013 `part-roles.md`
    section 5)."""
    return getattr(context, PART_ROLES_ATTRIBUTE, None)


def _read_mode(
    context: ToolContext, index: DrawingIndex, roles: PartRoles | None
) -> DrawingReadMode:
    """What the host's `drawing.read` can do (013 `contracts/drawing-capability.md` section 2).

    Asked only when a custom or unclear document has a candidate, so a package without one - the
    replay fixtures, a review with no drawing beside a custom part - never pings; `none` with no
    bridge. The bridge pings once and caches (`BridgeClient.drawing_read_mode`).

    **A stand-in, for the integrator.** 013 T077 (lane S) gives `ToolContext.drawing_read_mode()`,
    lazy, cached and recorded on the session as `drawing_read`; this then becomes
    `context.drawing_read_mode()` behind the same candidate test. `test_tools_check_drawings.py`
    fails once T077 lands and this still asks the bridge itself.
    """
    if not candidate_files(index, roles) or context.bridge is None:
        return "none"
    mode: DrawingReadMode = context.bridge.drawing_read_mode()
    return mode


def _closing_rows_only(context: ToolContext) -> bool:
    """Whether the session holds rows of `drawing.manufacturing_inputs` and every one is this
    check's own closing row (`CLOSED_BY_CODE`): the state just left "closed by code" - a confirmed
    read attached a drawing - and the model, refused while it was closed, has written none."""
    coverage = context.require_session().coverage
    held = [
        item
        for bucket in COVERAGE_BUCKETS
        for item in getattr(coverage, bucket)
        if item.check == CANDIDATES_BLOCK
    ]
    return bool(held) and all(item.reason.startswith(CLOSED_BY_CODE) for item in held)


def _record(context: ToolContext) -> dict[str, Any]:
    """Record the drawing context into `context`'s session and count what it recorded.

    The coverage stands for the current state of every reviewed document, so a second call
    restates it rather than adding to it, and a question already on the session is never asked
    twice - even with no re-call guard in front of the tool (FR-035, SC-008).

    While no attached drawing shows a custom or unclear document the checklist's
    `drawing.manufacturing_inputs` item is closed here by code (013
    `contracts/drawing-capability.md` section 5): its rows are withdrawn and the closing row
    recorded - the model is refused the item in that state, so a row of its own can only predate
    the change that closed it. Once a drawing is attached the model owns the item, and only this
    check's own closing row is withdrawn, never a row the model wrote.
    """
    session = context.require_session()
    index = DrawingIndex.for_package(context.ir)
    roles = _review_roles(context)
    result = run_drawing_context(
        context.ir,
        profile=review_profile(context),
        index=index,
        roles=roles,
        mode=_read_mode(context, index, roles),
    )
    restated = [CONTEXT_CHECK, CONFORMANCE_CHECK]
    if result.closing is not None or _closing_rows_only(context):
        restated.append(CANDIDATES_BLOCK)
    context.withdraw_coverage(tuple(restated), COVERAGE_BUCKETS)
    counts = dict.fromkeys(COVERAGE_BUCKETS, 0)
    for coverage in result.coverage:
        context.record_coverage(coverage.status, coverage.coverage_item())
        counts[coverage.status] += 1
    if result.closing is not None:
        context.record_coverage(*result.closing)
        counts[result.closing[0]] += 1
    for bucket, item in result.conformance.coverage:
        context.record_coverage(bucket, item)
    finding_ids = _record_conformance(context, result.conformance.findings)
    if isinstance(finding_ids, dict):
        return finding_ids
    for spec in result.questions:
        if already_asked(session.evidence_requests, spec):
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
    states = [state.state for state in result.states.values()]
    return {
        "status": "recorded",
        "drawings": len(context.ir.drawing_records),
        "candidates": len(candidate_files(index, roles)),
        "questions": len(result.questions),
        "findings": len(finding_ids),
        "finding_ids": finding_ids,
        "states": {state: states.count(state) for state in DRAWING_STATES},
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
            review_profile(context),
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


@dataclass(frozen=True)
class ConfirmedRead:
    """One candidate file's confirmed read (013 `contracts/drawing-capability.md` section 4): the
    host was asked once for the file, and each of its documents got one `drawing.confirmed_open`
    item carrying `outcome`."""

    file_name: str
    document_ids: tuple[str, ...]
    """Every document the file sits beside, in id order; the host was asked with the first."""
    outcome: str
    """The items' reason: what the host did, or its refusal, the bridge error, the ten-drawing
    bound, no connection, or a read the package could not be reloaded after - the words the
    resumed message's "Drawing {file}: {outcome}" line carries (section 6)."""
    read: bool
    """The host read it and the package was reloaded: the items are `checked`, not unresolved."""


def read_confirmed_candidates(
    context: ToolContext, answered: Sequence[EvidenceRequest], run_dir: Path
) -> list[ConfirmedRead]:
    """Read every confirmed candidate file through the bridge, then reload the package.

    Called by `ReviewRun.answer_evidence_batch` after the answers are marked and before the
    resumed turn (`contracts/confirmed-open.md` section 1). It acts only on an answered request
    that is this package's candidate question answered `CANDIDATE_CONFIRM` - the question rebuilt
    with the review's roles and the host's mode as they are now, which are the ones it was asked
    with (013 `contracts/part-roles.md` section 9: this runs before any regrade), so nothing
    happens unless the host opens closed drawings. Then it asks
    `context.bridge.drawing_read(run_id, document_id)` **once per candidate file** (013 section
    4), in the files' order, with the file's first document id and the run folder's own name as
    `run_id`, never a path, while the package holds fewer than ten drawing records; the host's
    merge removes every candidate row of the path it read, so the file's other documents are
    never read a second time. The host (the add-in) opens, reads, appends and closes; this side
    only asks, records one `drawing.confirmed_open` coverage item per document of each file from
    that file's one outcome, and reloads `run_dir/package.json` into `context` when a read
    succeeded. Returns one `ConfirmedRead` per file, in order; nothing else in the session
    changes.
    """
    index = DrawingIndex.for_package(context.ir)
    roles = _review_roles(context)
    spec = candidate_question(index, roles, _read_mode(context, index, roles))
    if not any(_is_confirmed_candidate(request, spec) for request in answered):
        return []
    held = len(context.ir.drawing_records)
    outcomes: list[tuple[CandidateFile, str, str | None, bool]] = []
    for file in candidate_files(index, roles):
        if context.bridge is None:
            outcomes.append((file, NO_CONNECTION, None, False))
            continue
        if held >= MAX_DRAWINGS:
            outcomes.append((file, TEN_DRAWINGS, None, False))
            continue
        try:
            result = context.bridge.drawing_read(run_dir.name, file.document_ids[0])
        except BridgeError as error:
            outcomes.append((file, str(error), type(error).__name__, False))
            continue
        held += 1
        outcomes.append((file, _read_outcome(result), None, True))

    reload_error = None
    if any(read for *_, read in outcomes):
        try:
            context.reload_package(load_package(run_dir))
        except (OSError, ValueError) as error:
            reload_error = f"{type(error).__name__}: {error}"
    reads: list[ConfirmedRead] = []
    for file, reason, error, read in outcomes:
        if read and reload_error is not None:
            reason = (
                f"{reason}; but the package in the run folder could not be reloaded: "
                f"{reload_error}"
            )
            error, read = reload_error, False
        for document_id in file.document_ids:
            context.record_coverage(
                "checked" if read else "unresolved", _confirmed_item(document_id, reason, error)
            )
        reads.append(ConfirmedRead(file.file_name, file.document_ids, reason, read))
    return reads
