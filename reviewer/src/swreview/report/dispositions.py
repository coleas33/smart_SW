"""Apply an engineer's disposition to a finding and re-render the report (FR-012, FR-013).

`session.json` is the only source of truth (research R10): a disposition is written into
the session on disk, never into the report directly, and `report.md` is then re-rendered
from the updated session so the two never drift.

State machine (data-model.md section 5): `none -> accepted | rejected | deferred`;
`deferred -> accepted | rejected`; `accepted` and `rejected` are terminal, with one exception
(owner decision 185A): one recorded without a triage takes one once, sent again with the same
decision, its decision, `by` and `at` unchanged. A second triage is refused with a class of its
own, `TriageAlreadyRecordedError` (roadmap hole H-g-012). Owner decision 198A: that late triage
keeps a note sent with it when none is recorded, and a Defer recorded without a triage takes one
the same way, sent again with Defer, and stays deferred. Sent again with no triage, a flagged
finding's decision recorded without one is refused with `OutcomeNeededError`, which names the
repair (roadmap hole H-c-010), and a pass's as before (cycle 15's Tier 2 review). 002 cycle 23:
the decision recorded, sent again with nothing new to record, is refused with
`DecisionAlreadyRecordedError`, and Defer again on a Defer that holds a triage with
`AlreadyDeferredError`, so the route can say what is recorded where it said to reload; a
different decision on an Accept or a Reject stays a plain `ValueError`.

A triage, one of `findings.TRIAGES`, may go with any decision and is never required (002
FR-031). A deferred finding keeps its triage when the later Accept or Reject names none.

A pass takes no triage but `findings.MISS`, `wrong`, the miss (owner decision 187A): any other is
refused with `TriageOnAPassError` before anything changes, whatever the decision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from swreview.findings import MISS, TRIAGES, Disposition, Finding
from swreview.report.attention import SUPPRESSED_STATUS
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
    "AlreadyDeferredError",
    "DecisionAlreadyRecordedError",
    "OutcomeNeededError",
    "TriageAlreadyRecordedError",
    "TriageOnAPassError",
    "apply_disposition",
    "find_finding",
    "refuse_a_triage_a_pass_does_not_take",
    "set_disposition",
    "takes_triage",
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


class OutcomeNeededError(ValueError):
    """The decision recorded without a triage, sent again with none (roadmap hole H-c-010): the
    repair press a card's no-triage line names, made with no outcome picked. A flagged finding's
    alone: a pass has no such line, so it is refused as before (cycle 15's Tier 2 review). A class
    of its own so the route can name the repair (`chat/server.py`, `OutcomeNeeded`), where
    `IllegalTransition`'s sentence said to reload the review, which loses a note typed for the
    retry. Still a `ValueError`, so every caller that refuses one refuses this."""


class DecisionAlreadyRecordedError(ValueError):
    """The decision recorded, sent again with nothing new to record (002 cycle 23): a pass's
    decision recorded without a triage, sent again with none - not `OutcomeNeededError`, a pass's
    card having no no-triage line and its one outcome the miss (cycle 15's Tier 2 review) - or a
    decision that holds a triage, sent again with none, its triage let go. A class of its own so
    the route can say it is already recorded (`chat/server.py`, `DecisionAlreadyRecorded`), where
    `IllegalTransition`'s sentence said to reload the review, which loses a note typed for the
    press. Still a `ValueError`, so every caller that refuses one refuses this."""


class AlreadyDeferredError(ValueError):
    """Defer again, with a triage or none, on a Defer that holds one (002 cycle 23): not a second
    triage, since the later Accept or Reject keeps it or takes another (198A). A class of its own
    so the route can say what that later decision does (`chat/server.py`, `AlreadyDeferred`), where
    `IllegalTransition`'s sentence said to reload the review. Still a `ValueError`, so every caller
    that refuses one refuses this."""


class TriageOnAPassError(ValueError):
    """A triage a pass does not take (owner decision 187A; 002 FR-031): a pass - a
    `checked_within_scope` finding, 'Checked, no issue' - takes no triage but `MISS`, `wrong`,
    the miss. A class of its own so the live route answers it as it answers a triage outside the
    four, `400 InvalidTriage` (`chat/server.py`), and the console names it. Still a `ValueError`,
    so every caller that refuses one refuses this."""


def takes_triage(finding: Finding, triage: str) -> bool:
    """Whether `finding` takes `triage` (owner decision 187A): a flagged finding any of the four,
    and a pass - `SUPPRESSED_STATUS`, which the page draws in 'Checked, no issue' - `MISS` alone."""
    return finding.status != SUPPRESSED_STATUS or triage == MISS


def refuse_a_triage_a_pass_does_not_take(finding: Finding, triage: str | None) -> None:
    """Raise `TriageOnAPassError` when `finding` is a pass and `triage` is not `MISS` (owner
    decision 187A). The record calls it before anything changes, and the live route before it
    reads the chat's state."""
    if triage is not None and not takes_triage(finding, triage):
        raise TriageOnAPassError(
            f"finding {finding.id} is a pass ('Checked, no issue'), which takes no triage but "
            f"{MISS!r}, a miss; got {triage!r}"
        )


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
    # Not on a pass: it has no no-triage line naming this repair, and its one outcome is the miss.
    if (
        decision == current.decision
        and triage is None
        and current.triage is None
        and finding.status != SUPPRESSED_STATUS
    ):
        raise OutcomeNeededError(
            f"finding {finding.id} is {current.decision} with no triage recorded; send "
            f"{decision!r} again with a triage to record one"
        )
    if current.decision == "deferred" and decision in _ALLOWED_FROM_DEFERRED:
        return
    held = f" with its triage ({current.triage!r})" if current.triage is not None else ""
    if current.decision == "deferred" and current.triage is not None:
        # Defer again, with a triage or none. Not a second triage: a later Accept or Reject may
        # still replace a Defer's triage (198A).
        raise AlreadyDeferredError(
            f"finding {finding.id} is deferred{held}; it can only move to accepted or rejected, "
            f"not {decision!r} again, and either keeps that triage unless it names another"
        )
    if decision != current.decision:
        raise ValueError(
            f"finding {finding.id} already has a terminal disposition ({current.decision!r}); "
            "it cannot be changed"
        )
    if triage is not None:
        raise TriageAlreadyRecordedError(
            f"finding {finding.id} already has a terminal disposition ({current.decision!r}) "
            f"with its triage ({current.triage!r}); a triage is recorded once and cannot be "
            "changed"
        )
    # The same decision with no triage, past the repair and the late triage above: a pass's, or
    # one whose triage the press let go.
    raise DecisionAlreadyRecordedError(
        f"finding {finding.id} is already {current.decision}{held}; {decision!r} again with no "
        "triage changes nothing"
    )


def _takes_a_late_triage(current: Disposition, decision: str, triage: str | None) -> bool:
    """Owner decision 185A: an Accept or Reject recorded without a triage, sent again with the
    same decision and a triage, takes the triage once. Owner decision 198A: so does a Defer, Defer
    sent again with one, which stays deferred; sent again with none, it is refused as before."""
    return current.triage is None and triage is not None and decision == current.decision


def _late_note(recorded: str, sent: str) -> str:
    """The note a late triage leaves (owner decision 198A): the one recorded, or, when none is,
    the one sent with it, such as the date 188A asks for. A blank note is none, so a blank one
    recorded gives way to the note sent, and a blank one sent changes nothing."""
    if recorded.strip() or not sent.strip():
        return recorded
    return sent


def set_disposition(
    session: ReviewSession,
    finding_id: str,
    decision: str,
    note: str | None,
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
    keeps its triage when the later decision names none, and takes the one it names. A decision
    recorded without one takes one once, sent again with the same decision - an Accept, a Reject,
    or a Defer, which stays deferred (owner decision 198A): the triage is recorded, the decision,
    `by` and `at` stay as first recorded, and so does the note, unless none is recorded, when
    the note sent with the triage is kept (198A, `_late_note`). A `note` of `None` is the note
    already recorded, none before a first decision: `swreview disposition`'s `--note` left out.

    A pass takes no triage but `MISS` (owner decision 187A): any other is refused before the
    state machine is read, a late triage included.

    Raises `ValueError` for an unknown decision, a triage outside the four (naming them), a
    triage a pass does not take - `TriageOnAPassError` - or a transition the state machine
    forbids - a second triage on an Accept or Reject as `TriageAlreadyRecordedError`, the
    decision recorded without a triage sent again with none, on a flagged finding, as
    `OutcomeNeededError`, the decision recorded sent again with nothing new to record otherwise
    as `DecisionAlreadyRecordedError`, and Defer again on a Defer that holds a triage as
    `AlreadyDeferredError` (002 cycle 23) - each a `ValueError` of its own class, a different
    decision on an Accept or a Reject a plain one, and `KeyError` for a finding id that is not in
    the session. Nothing is changed on any path.
    """
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}, got {decision!r}")
    # A tuple's `in` compares by equality, so a number or a list is refused here, not raised on.
    if triage is not None and triage not in TRIAGES:
        raise ValueError(f"triage must be one of {list(TRIAGES)}, got {triage!r}")

    finding = find_finding(session, finding_id)
    refuse_a_triage_a_pass_does_not_take(finding, triage)
    current = finding.disposition
    if note is None:
        note = current.note if current is not None else ""
    if current is not None and _takes_a_late_triage(current, decision, triage):
        finding.disposition = current.model_copy(
            update={"triage": triage, "note": _late_note(current.note, note)}
        )
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
    note: str | None,
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

    `triage` is recorded as `set_disposition` records it (owner decision 185A), and a `note` of
    `None` keeps the note recorded.

    Raises `ValueError` for an unknown decision, a triage outside the four, a triage a pass does
    not take or a transition the state machine forbids, and `KeyError` for a finding id that is
    not in the session; nothing is written on either path.
    """
    run_dir = Path(run_dir)
    session = load_session(run_dir / SESSION_FILE_NAME)

    set_disposition(session, finding_id, decision, note, by, at, triage=triage)

    save_session(session, run_dir / SESSION_FILE_NAME)
    rerender_run_folder(run_dir)

    return session
