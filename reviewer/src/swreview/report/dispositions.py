"""Apply an engineer's disposition to a finding and re-render the report (FR-012, FR-013).

`session.json` is the only source of truth (research R10): a disposition is written into
the session on disk, never into the report directly, and `report.md` is then re-rendered
from the updated session so the two never drift.

State machine (data-model.md section 5): `none -> accepted | rejected | deferred`;
`deferred -> accepted | rejected`; `accepted` and `rejected` are terminal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from swreview.findings import Disposition, Finding
from swreview.report.markdown import render_report
from swreview.report.session import ReviewSession, load_session, save_session

SESSION_FILE_NAME = "session.json"
REPORT_FILE_NAME = "report.md"

_DECISIONS: frozenset[str] = frozenset({"accepted", "rejected", "deferred"})
_ALLOWED_FROM_DEFERRED: frozenset[str] = frozenset({"accepted", "rejected"})


def _find_finding(session: ReviewSession, finding_id: str) -> Finding:
    for finding in session.findings:
        if finding.id == finding_id:
            return finding
    raise KeyError(f"no finding {finding_id!r} in this session")


def _validate_transition(finding: Finding, decision: str) -> None:
    current = finding.disposition
    if current is None:
        return
    if current.decision == "deferred":
        if decision in _ALLOWED_FROM_DEFERRED:
            return
        raise ValueError(
            f"finding {finding.id} is deferred; it can only move to accepted or rejected, "
            f"not {decision!r}"
        )
    raise ValueError(
        f"finding {finding.id} already has a terminal disposition ({current.decision!r}); "
        "it cannot be changed"
    )


def apply_disposition(
    run_dir: Path,
    finding_id: str,
    decision: str,
    note: str,
    by: str,
    at: datetime | None = None,
) -> ReviewSession:
    """Set the disposition of `finding_id` in `run_dir/session.json` and re-render the report.

    Raises `ValueError` for an unknown decision or a transition the state machine forbids,
    and `KeyError` for a finding id that is not in the session.
    """
    if decision not in _DECISIONS:
        raise ValueError(f"decision must be one of {sorted(_DECISIONS)}, got {decision!r}")

    run_dir = Path(run_dir)
    session = load_session(run_dir / SESSION_FILE_NAME)

    finding = _find_finding(session, finding_id)
    _validate_transition(finding, decision)

    finding.disposition = Disposition(
        decision=decision,  # type: ignore[arg-type]
        note=note,
        by=by,
        at=at if at is not None else datetime.now(UTC),
    )

    save_session(session, run_dir / SESSION_FILE_NAME)
    (run_dir / REPORT_FILE_NAME).write_text(render_report(session), encoding="utf-8")

    return session


__all__ = ["apply_disposition"]
