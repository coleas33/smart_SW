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

from typing import Any

from swreview.checks.drawing_context import (
    CONTEXT_CHECK,
    QuestionSpec,
    run_drawing_context,
)
from swreview.ir.models import EvidencePackage
from swreview.report.session import EvidenceRequest
from swreview.tools.context import ToolContext, current_context
from swreview.tools.query import ToolResult
from swreview.tools.session import record_evidence_request

__all__ = ["DRAWINGS_TOOL", "check_drawings", "drawing_evidence"]

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
    result = run_drawing_context(context.ir)
    for bucket in COVERAGE_BUCKETS:
        items = getattr(session.coverage, bucket)
        items[:] = [item for item in items if item.check != CONTEXT_CHECK]
    counts = dict.fromkeys(COVERAGE_BUCKETS, 0)
    for coverage in result.coverage:
        context.record_coverage(coverage.status, coverage.coverage_item())
        counts[coverage.status] += 1
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
        "findings": 0,
        "finding_ids": [],
        "coverage": counts,
    }


def check_drawings() -> ToolResult:
    """Check what the open drawings show about each reviewed document and ask the engineer
    what only they know.

    Notes:
        Takes no argument.
    """
    return _record(current_context())
