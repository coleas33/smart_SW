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

DECISIONS: frozenset[str] = frozenset({"accepted", "rejected", "deferred"})
"""The three decisions an engineer can record. Public because the chat server validates a
request body against them before it reaches `set_disposition` (`chat/server.py`)."""
_ALLOWED_FROM_DEFERRED: frozenset[str] = frozenset({"accepted", "rejected"})


def find_finding(session: ReviewSession, finding_id: str) -> Finding:
    """The finding `finding_id` names, or `KeyError`.

    Public because the CLI looks a finding up for `exceptions accept` as well; one
    implementation means both paths refuse an unknown id the same way.
    """
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


def set_disposition(
    session: ReviewSession,
    finding_id: str,
    decision: str,
    note: str,
    by: str,
    at: datetime | None = None,
) -> Finding:
    """Set the disposition of `finding_id` on a session **in memory**, and hand it back.

    The validated half of `apply_disposition`, split out because a live chat cannot use
    the file-based form: its session is held by the running review and written again at
    the end of every turn, so a decision applied to a freshly loaded copy would be
    overwritten by the next finalization (`chat/sessions.py`, `record_disposition`).

    Raises `ValueError` for an unknown decision or a transition the state machine forbids,
    and `KeyError` for a finding id that is not in the session. Nothing is changed on
    either path.
    """
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}, got {decision!r}")

    finding = find_finding(session, finding_id)
    _validate_transition(finding, decision)

    finding.disposition = Disposition(
        decision=decision,  # type: ignore[arg-type]
        note=note,
        by=by,
        at=at if at is not None else datetime.now(UTC),
    )
    return finding


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
    run_dir = Path(run_dir)
    session = load_session(run_dir / SESSION_FILE_NAME)

    set_disposition(session, finding_id, decision, note, by, at)

    save_session(session, run_dir / SESSION_FILE_NAME)
    (run_dir / REPORT_FILE_NAME).write_text(render_report(session), encoding="utf-8")

    return session


__all__ = ["DECISIONS", "apply_disposition", "find_finding", "set_disposition"]
