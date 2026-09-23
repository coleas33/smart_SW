"""Lever 7's stop predicate (T080), over hand-built sessions with no provider at all.

The predicate answers one question - **has this review actually finished?** - and lever 7
spends a round trip on the answer, so the edge cases are where the whole lever lives and
this is where they are cheapest: a session is a pydantic model, and every case below is
built by hand in three lines rather than acted out through an adapter.

**The predicate is deliberately stricter than finalization** (OQ-5, brief Q5). Both read
the same two sets - the open evidence requests and the checklist items nothing has closed -
but `Checklist.bucket_of` searches `("checked", "skipped", "unresolved", "out_of_scope")`
and for *finalizing* that is right: an item closed any way is closed, and the report says
in which bucket. For *stopping early* it is not: a review that skipped six of nine items
has not finished, it has given up, and withdrawing the tools would freeze that in place.
`test_the_predicate_and_finalizations_open_items_deliberately_disagree` is the guard on
that difference, because the two functions look so alike that someone will eventually
"DRY" them together and reintroduce the hole.

The one thing that *is* shared is the enumeration of open evidence requests, and
`test_finalization_reads_open_evidence_requests_through_the_same_function` pins that too:
copied, it would drift the day `status` grows a third value.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from swreview.agent import runner
from swreview.agent.checklist import load_checklist
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.findings import Finding, build_finding
from swreview.report.session import (
    CoverageItem,
    CoverageScope,
    EvidenceRequest,
    ReviewSession,
    Timing,
)
from tests.support.packages import build_package

PACKAGE = build_package()
CHECKLIST = load_checklist()

SESSION_ID = UUID("6f1d1d6a-6c8a-4f29-9f3f-0b0f6f5b9e11")
STARTED = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)

WEAK_BUCKETS: tuple[str, ...] = ("skipped", "unresolved", "out_of_scope")
"""The three buckets that close an item for finalization and not for stopping."""


# --- hand-built sessions ------------------------------------------------------------------


def empty_session(**overrides: Any) -> ReviewSession:
    """A session with nothing closed: nine open checklist items, no requests."""
    return ReviewSession(
        session_id=SESSION_ID,
        package_id=PACKAGE.package_id,
        design_id=PACKAGE.design.design_id,
        started_at=STARTED,
        model="fake-1",
        timing=Timing(
            baseline_minutes=None,
            assisted_supervision_minutes=0.0,
            assisted_verification_minutes=0.0,
            false_alarm_handling_minutes=0.0,
            unattended_runtime_minutes=0.0,
        ),
        **overrides,
    )


def coverage_item(check: str) -> CoverageItem:
    return CoverageItem(
        check=check, scope=CoverageScope(), reason="covered by hand", error=None
    )


def finding_for(check: str, index: int) -> Finding:
    """One finding whose `check` closes the checklist item with that prefix."""
    return build_finding(
        finding_id=f"F-{index:03d}",
        check=check,
        title="a finding",
        status="suspected",
        severity="medium",
        package=PACKAGE,
        configuration="Default",
        observed="observed",
        requirement="required",
        recommended_action="do something",
        component_ids=["cmp:0001"],
        tool_result_ids=[0],
    )


def closed_by_coverage(
    bucket: str = "checked",
    *,
    omit: Iterable[str] = (),
    weak: dict[str, str] | None = None,
) -> ReviewSession:
    """Every checklist item closed by a coverage entry in `bucket`.

    `omit` leaves an item open; `weak` maps an item id to a different bucket, which is how
    the "closed only by skipped" cases are built.
    """
    session = empty_session()
    left_open = set(omit)
    for item in CHECKLIST.items:
        if item.id in left_open:
            continue
        chosen = (weak or {}).get(item.id, bucket)
        getattr(session.coverage, chosen).append(coverage_item(item.id))
    return session


def closed_by_findings() -> ReviewSession:
    """Every checklist item closed by a finding under its own check prefix."""
    session = empty_session()
    session.findings.extend(
        finding_for(f"{item.check_prefix}closed", index)
        for index, item in enumerate(CHECKLIST.items, start=1)
    )
    return session


def request(status: str = "open") -> EvidenceRequest:
    return EvidenceRequest(
        id="ER-001",
        what="the usable thread depth of hole:1",
        why="fastener.engagement needs it",
        entity_ids=["cmp:0001"],
        status=status,
        answer="12 mm" if status == "answered" else None,
        answered_at=STARTED if status == "answered" else None,
    )


# --- the predicate ------------------------------------------------------------------------


def test_every_item_closed_by_a_finding_is_complete() -> None:
    """The case the lever exists for: the review found things and nothing is left open."""
    session = closed_by_findings()

    assert CHECKLIST.open_items(session) == []
    assert runner.coverage_complete(CHECKLIST, session) is True


def test_every_item_closed_by_checked_coverage_is_complete() -> None:
    """`checked` is the other closer that means the work was done."""
    assert runner.coverage_complete(CHECKLIST, closed_by_coverage("checked")) is True


def test_a_fresh_session_is_not_complete() -> None:
    assert runner.coverage_complete(CHECKLIST, empty_session()) is False


@pytest.mark.parametrize("open_item", [item.id for item in CHECKLIST.items])
def test_one_open_item_is_not_complete(open_item: str) -> None:
    """Any one of the nine left open keeps the tools on the wire."""
    session = closed_by_coverage("checked", omit=[open_item])

    assert [item.id for item in CHECKLIST.open_items(session)] == [open_item]
    assert runner.coverage_complete(CHECKLIST, session) is False


def test_one_open_evidence_request_is_not_complete() -> None:
    """The review is waiting on an engineer, which is not the same as being finished."""
    session = closed_by_coverage("checked")
    session.evidence_requests.append(request("open"))

    assert runner.coverage_complete(CHECKLIST, session) is False


def test_an_answered_evidence_request_does_not_hold_the_review_open() -> None:
    session = closed_by_coverage("checked")
    session.evidence_requests.append(request("answered"))

    assert runner.coverage_complete(CHECKLIST, session) is True


@pytest.mark.parametrize("bucket", WEAK_BUCKETS)
def test_an_item_closed_only_in_a_weak_bucket_is_not_complete(bucket: str) -> None:
    """OQ-5, the strict answer: `skipped` and `out_of_scope` do not close for stopping.

    One item in `bucket` and the other eight `checked` - the cheapest version of the run
    lever 7 must not reward, where the model closes what it did not do and stops.
    """
    session = closed_by_coverage("checked", weak={"interfaces.fit": bucket})

    assert CHECKLIST.open_items(session) == []
    assert runner.coverage_complete(CHECKLIST, session) is False


def test_a_whole_checklist_of_skipped_items_is_not_complete() -> None:
    """The nine-`mark_coverage(bucket="skipped")` run, refused outright (RK-7)."""
    assert runner.coverage_complete(CHECKLIST, closed_by_coverage("skipped")) is False


def test_a_finding_closes_an_item_a_weak_coverage_entry_also_touched() -> None:
    """A finding wins: `bucket_of` looks at findings before it looks at any bucket."""
    session = closed_by_coverage("checked", weak={"fasteners": "skipped"})
    session.findings.append(finding_for("fastener.bottoming", 1))

    assert runner.coverage_complete(CHECKLIST, session) is True


def test_failed_coverage_never_closes_an_item_for_stopping() -> None:
    """`failed` closes no item, whether written against a tool name or, by a mass or hygiene
    call whose finding was refused, against the item's own id."""
    session = closed_by_coverage("checked", omit=["interference"])
    session.coverage.failed.append(coverage_item("interference"))

    assert runner.coverage_complete(CHECKLIST, session) is False


# --- the two functions share what they may, and differ where they must -----------------


@pytest.mark.parametrize("bucket", WEAK_BUCKETS)
def test_the_predicate_and_finalizations_open_items_deliberately_disagree(bucket: str) -> None:
    """The guard on the difference, so nobody "DRY"s the hole back in.

    `open_items` is finalization's question - is anything still unrecorded? - and the
    predicate's is different: was the work actually done? A session whose items are all
    closed in a weak bucket answers yes to the first and no to the second, and it must
    stay that way.
    """
    session = closed_by_coverage(bucket)

    assert CHECKLIST.open_items(session) == []
    assert runner.coverage_complete(CHECKLIST, session) is False


def test_open_evidence_requests_are_the_ones_still_waiting() -> None:
    session = empty_session()
    session.evidence_requests.extend([request("open"), request("answered")])

    assert [item.status for item in runner.open_evidence_requests(session)] == ["open"]


def test_finalization_reads_open_evidence_requests_through_the_same_function(
    monkeypatch: pytest.MonkeyPatch,
    tmp_package_dir: Path,
    tmp_path: Path,
) -> None:
    """Shared, not copied: finalization enumerates the set through this one function.

    Asserted structurally rather than by reading the source, because the failure this
    guards against is a second implementation that agrees today and drifts later.
    """
    seen: list[ReviewSession] = []
    real = runner.open_evidence_requests

    def spy(session: ReviewSession) -> Sequence[EvidenceRequest]:
        seen.append(session)
        return real(session)

    monkeypatch.setattr(runner, "open_evidence_requests", spy)

    run = runner.start_review(
        tmp_package_dir,
        tmp_path / "out",
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-1"),
    )
    run.start()

    assert seen and seen[0] is run.session


def test_the_predicate_takes_a_checklist_and_a_session_and_nothing_else() -> None:
    """No context, no run and no provider: the reason this file needs none of them.

    It also keeps the predicate usable from the `ToolSet` wrapper and from a test alike;
    a predicate that took a `ToolContext` would drag a loaded package into every case
    above for no gain.
    """
    assert list(inspect.signature(runner.coverage_complete).parameters) == [
        "checklist",
        "session",
    ]
