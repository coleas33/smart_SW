"""One review as the Review tab restores it, without a token (feature 009 research R2.15).

The engineer keeps a chip per review; choosing one renders that review's Results again
from one object - the findings and the questions in session order, the coverage as the
stream delivered it, the ranking with its summary, and the parts not loaded - through the
same functions the end of a live turn uses. The object is built here, once, and served by
three callers:

- `GET /sessions/{chat_id}/snapshot`, from the run the backend holds (with its ledger, the
  chat's state and the stream's last seq, so a page reloaded mid-turn can reopen the
  stream where the snapshot ends);
- `GET /reviews/{run_id}`, from a run folder after a backend restart, read-only with the
  words file's reason;
- the page fixture `tests/fixtures/pane/generate_pane_fixture.py` writes.

Pure: it reads its arguments (and, through the summary, the words file) and writes
nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_core import to_jsonable_python

from swreview.ir.models import EvidencePackage
from swreview.report.names import component_names
from swreview.report.summary import COVERAGE_BUCKETS, review_ranking
from swreview.report.titles import pane_finding
from swreview.report.unexamined import not_examined

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from swreview.agent.events import UsageLedger
    from swreview.report.session import ReviewSession

__all__ = ["review_snapshot"]


def review_snapshot(
    session: ReviewSession,
    package: EvidencePackage,
    *,
    run_id: str,
    usage: UsageLedger | None = None,
    chat_state: str | None = None,
    last_seq: int | None = None,
    read_only_reason: str | None = None,
) -> dict[str, Any]:
    """The body both restore routes answer (data-model section 8), as JSON-ready data.

    Every finding, request and coverage entry is exactly the body its stream event carries
    (`finding`, `evidence.requested`, `coverage`), so the page renders a restored review
    with the functions that rendered it live - a finding's with its display title
    (`report/titles.pane_finding`, feature 009 decision 2A), as the ranking's rows are.
    """
    block = not_examined(package)
    names = component_names(package)
    return {
        "run_id": run_id,
        "read_only": read_only_reason is not None,
        "read_only_reason": read_only_reason,
        "chat_state": chat_state,
        "last_seq": last_seq,
        "document": _root_document(package),
        "findings": [pane_finding(finding, names) for finding in session.findings],
        "evidence_requests": [
            request.model_dump(mode="json") for request in session.evidence_requests
        ],
        "coverage": [
            {"bucket": bucket, "item": item.model_dump(mode="json")}
            for bucket in COVERAGE_BUCKETS
            for item in getattr(session.coverage, bucket)
        ],
        "ranking": to_jsonable_python(review_ranking(session, package, usage=usage)),
        "not_examined": None if block is None else block.model_dump(mode="json"),
    }


def _root_document(package: EvidencePackage) -> dict[str, str] | None:
    """The reviewed document's `{path, configuration}`, the shape `review.started` names."""
    root = next(
        (
            document
            for document in package.documents
            if document.document_id == package.design.root_assembly_document_id
        ),
        None,
    )
    if root is None:
        return None
    return {"path": root.path, "configuration": root.active_configuration}
