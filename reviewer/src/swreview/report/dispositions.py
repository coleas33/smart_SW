"""Apply an engineer's disposition to a finding and re-render the report (FR-012, FR-013).

`session.json` is the only source of truth (research R10): a disposition is written into
the session on disk, never into the report directly, and `report.md` is then re-rendered
from the updated session so the two never drift.

State machine (data-model.md section 5): `none -> accepted | rejected | deferred`;
`deferred -> accepted | rejected`; `accepted` and `rejected` are terminal, with one exception
(owner decision 185A): one recorded without a triage takes one once, sent again with the same
decision, and nothing else changes. A second triage is refused with a class of its own,
`TriageAlreadyRecordedError` (roadmap hole H-g-012).

A triage, one of `findings.TRIAGES`, may go with any decision and is never required (002
FR-031). A deferred finding keeps its triage when the later Accept or Reject names none.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from swreview.findings import TRIAGES, Disposition, Finding
from swreview.report.rerender import (
    REPORT_FILE_NAME,
    SESSION_FILE_NAME,
    rerender_run_folder,
)
from swreview.report.session import ReviewSession, load_session, save_session

__all__ = [
    "DECISIONS",
    "REPORT_FILE_NAME",
    "SESSION_FILE_NAME",
    "TriageAlreadyRecordedError",
    "apply_disposition",
    "find_finding",
    "set_disposition",
]

DECISIONS: frozenset[str] = frozenset({"accepted", "rejected", "deferred"})
"""The three decisions an engineer can record. Public because the chat server validates a
request body against them before it reaches `set_disposition` (`chat/server.py`)."""
_ALLOWED_FROM_DEFERRED: frozenset[str] = frozenset({"accepted", "rejected"})


class TriageAlreadyRecordedError(ValueError):
    """A second triage: the same Accept or Reject sent again with a triage when the one recorded
    holds one (roadmap hole H-g-012). 185A takes a triage once, so it is refused as any change to
    a settled finding is; a class of its own so the route can say the recorded triage stands
    (`chat/server.py`, `TriageAlreadyRecorded`), where every other refusal's sentence reads as a
    refused decision. Still a `ValueError`, so every caller that refuses one refuses this."""


def find_finding(session: ReviewSession, finding_id: str) -> Finding:
    """The finding `finding_id` names, or `KeyError`.

    Public because the CLI looks a finding up for `exceptions accept` as well; one
    implementation means both paths refuse an unknown id the same way.
    """
    for finding in session.findings:
        if finding.id == finding_id:
            return finding
    raise KeyError(f"no finding {finding_id!r} in this session")


def _validate_transition(finding: Finding, decision: str, triage: str | None) -> None:
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
    if decision == current.decision and triage is not None and current.triage is not None:
        raise TriageAlreadyRecordedError(
            f"finding {finding.id} already has a terminal disposition ({current.decision!r}) "
            f"with its triage ({current.triage!r}); a triage is recorded once and cannot be "
            "changed"
        )
    raise ValueError(
        f"finding {finding.id} already has a terminal disposition ({current.decision!r}); "
        "it cannot be changed"
    )


def _takes_a_late_triage(current: Disposition, decision: str, triage: str | None) -> bool:
    """Owner decision 185A: an Accept or Reject recorded without a triage, sent again with the
    same decision and a triage, takes the triage once. A Defer is not settled and is not covered:
    its triage comes with the later Accept or Reject."""
    return (
        current.decision != "deferred"
        and current.triage is None
        and triage is not None
        and decision == current.decision
    )


def set_disposition(
    session: ReviewSession,
    finding_id: str,
    decision: str,
    note: str,
    by: str,
    at: datetime | None = None,
    triage: str | None = None,
) -> Finding:
    """Set the disposition of `finding_id` on a session **in memory**, and hand it back.

    The validated half of `apply_disposition`, split out because a live chat cannot use
    the file-based form: its session is held by the running review and written again at
    the end of every turn, so a decision applied to a freshly loaded copy would be
    overwritten by the next finalization (`chat/sessions.py`, `record_disposition`).

    `triage` is one of `TRIAGES`, or `None` for none (owner decision 185A). A deferred finding
    keeps its triage when the later decision names none, and takes the one it names. An Accept
    or Reject recorded without one takes one once, sent with the same decision: only the triage
    is recorded, and the decision, note, `by` and `at` stay as first recorded.

    Raises `ValueError` for an unknown decision, a triage outside the four (naming them) or a
    transition the state machine forbids - a second triage as `TriageAlreadyRecordedError`, a
    `ValueError` of its own class - and `KeyError` for a finding id that is not in the session.
    Nothing is changed on any path.
    """
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}, got {decision!r}")
    # A tuple's `in` compares by equality, so a number or a list is refused here, not raised on.
    if triage is not None and triage not in TRIAGES:
        raise ValueError(f"triage must be one of {list(TRIAGES)}, got {triage!r}")

    finding = find_finding(session, finding_id)
    current = finding.disposition
    if current is not None and _takes_a_late_triage(current, decision, triage):
        finding.disposition = current.model_copy(update={"triage": triage})
        return finding
    _validate_transition(finding, decision, triage)

    # Past the transition check `current` is none or a Defer, whose triage stays unless the
    # decision names another.
    kept = current.triage if triage is None and current is not None else triage
    finding.disposition = Disposition(
        decision=decision,  # type: ignore[arg-type]
        note=note,
        by=by,
        at=at if at is not None else datetime.now(UTC),
        triage=kept,  # type: ignore[arg-type]
    )
    return finding


def apply_disposition(
    run_dir: Path,
    finding_id: str,
    decision: str,
    note: str,
    by: str,
    at: datetime | None = None,
    triage: str | None = None,
) -> ReviewSession:
    """Set the disposition of `finding_id` in `run_dir/session.json` and re-render the report.

    The re-render goes through `report/rerender.rerender_run_folder`, the one function the
    three offline commands share: rendering from the session alone - which is what this
    function used to do - turned every component name back into an id, degraded Manifest
    Discrepancies to the "not supplied" placeholder, and deleted a standards folder's
    verdict header, and it wrote no `attention.json`, so a decision recorded here left the
    folder's ranking describing the run as it stood before the decision (research R2.7).

    `triage` is recorded as `set_disposition` records it (owner decision 185A).

    Raises `ValueError` for an unknown decision, a triage outside the four or a transition the
    state machine forbids, and `KeyError` for a finding id that is not in the session; nothing
    is written on either path.
    """
    run_dir = Path(run_dir)
    session = load_session(run_dir / SESSION_FILE_NAME)

    set_disposition(session, finding_id, decision, note, by, at, triage=triage)

    save_session(session, run_dir / SESSION_FILE_NAME)
    rerender_run_folder(run_dir)

    return session
