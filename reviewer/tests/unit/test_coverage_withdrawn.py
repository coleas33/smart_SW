"""The stream says what the session drops, so the pane holds what the session holds (011 T092).

The backend restates coverage by dropping items and appending new ones. `record_coverage`
announces each append as a `coverage` event; `ToolContext.withdraw_coverage` - the one place an
announced item leaves the session - announces each drop as a `coverage.withdrawn` event naming
the checks and the buckets that lost an item (002 `contracts/chat-events.schema.json`). Applying
the two in stream order gives the session's coverage bucket for bucket and in order
(`tests/support/coverage_stream.mirror`), which is all the Review page's panel may rely on: it
keys nothing, so two items the session holds side by side - one check over one scope, skipped
and checked, or a tool that failed twice - stay two items on the page too (the review finding
of 2026-09-23 against T082's keyed replacement).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args

import pytest

from swreview.agent.providers import EventType
from swreview.checks.drawing_context import CONFORMANCE_CHECK, CONTEXT_CHECK
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import CoverageItem, CoverageScope
from swreview.tools import checks_mechanical
from swreview.tools.context import ToolContext, context_for
from swreview.tools.registry import ToolDispatch, ToolRegistry
from swreview.tools.standards_checks import StandardsRun, attach_standards_run
from tests.support.contracts import contract_validator
from tests.support.coverage_stream import COVERAGE_EVENT_TYPES, Event, held, mirror
from tests.support.prerun import STANDARDS_PROFILE, prerun_package, standards_prerun_package

TESTS = Path(__file__).resolve().parents[1]
SRC = TESTS.parent / "src" / "swreview"
PLATE_DRAWING = TESTS / "fixtures" / "drawings" / "plate-drawing"
PROFILE_A = TESTS / "fixtures" / "standards" / "profile-a.yaml"


def listening(package: EvidencePackage) -> tuple[ToolContext, list[Event]]:
    """A context over `package` whose events are kept, in order."""
    events: list[Event] = []
    context = context_for(package)
    context.emit = lambda kind, body: events.append((kind, dict(body)))
    return context, events


def dispatch(context: ToolContext) -> ToolDispatch:
    return ToolRegistry().dispatch(context)


def item(check: str, reason: str, *documents: str) -> CoverageItem:
    return CoverageItem(
        check=check, scope=CoverageScope(document_ids=list(documents)), reason=reason, error=None
    )


def withdrawals(events: list[Event]) -> list[dict[str, Any]]:
    return [dict(body) for kind, body in events if kind == "coverage.withdrawn"]


# --- 1. the one place an item leaves the session -------------------------------------------------


def test_withdraw_drops_the_checks_from_the_buckets_and_names_what_lost_an_item() -> None:
    context, events = listening(prerun_package())
    context.record_coverage("checked", item("a", "a checked"))
    context.record_coverage("unresolved", item("a", "a unresolved"))
    context.record_coverage("checked", item("b", "b checked"))
    events.clear()

    context.withdraw_coverage(("a", "c"), ("checked", "skipped"))

    coverage = context.require_session().coverage
    assert [entry.reason for entry in coverage.checked] == ["b checked"]
    assert [entry.reason for entry in coverage.unresolved] == ["a unresolved"]
    assert events == [("coverage.withdrawn", {"checks": ["a"], "buckets": ["checked"]})]


def test_withdrawing_what_the_session_does_not_hold_says_nothing() -> None:
    context, events = listening(prerun_package())
    context.record_coverage("checked", item("b", "b checked"))
    events.clear()

    context.withdraw_coverage(("a",), ("checked", "skipped", "unresolved"))

    assert events == []
    assert [entry.check for entry in context.require_session().coverage.checked] == ["b"]


def test_a_withdrawal_names_each_check_and_bucket_once_in_the_order_given() -> None:
    context, events = listening(prerun_package())
    for bucket, check in (("skipped", "b"), ("checked", "a"), ("skipped", "a"), ("checked", "b")):
        context.record_coverage(bucket, item(check, f"{check} {bucket}"))
    events.clear()

    context.withdraw_coverage(("b", "a", "b"), ("skipped", "checked", "skipped"))

    assert events == [
        ("coverage.withdrawn", {"checks": ["b", "a"], "buckets": ["skipped", "checked"]})
    ]
    assert held(context.require_session()) == mirror([])


def test_the_withdrawal_validates_as_the_events_contract_says() -> None:
    context, events = listening(prerun_package())
    context.record_coverage("failed", item("a", "a failed"))
    context.withdraw_coverage(("a",), ("failed",))
    validator = contract_validator("chat-events.schema.json")

    for seq, (kind, body) in enumerate(events, start=1):
        validator.validate({"seq": seq, "at": "2026-09-23T00:00:00Z", "type": kind, "body": body})


def test_a_withdrawal_with_no_check_or_no_bucket_is_refused_by_the_contract() -> None:
    validator = contract_validator("chat-events.schema.json")
    for body in (
        {"checks": [], "buckets": ["checked"]},
        {"checks": ["a"], "buckets": []},
        {"checks": ["a"], "buckets": ["somewhere"]},
        {"checks": ["a"], "buckets": ["checked"], "reason": "extra"},
    ):
        event = {"seq": 1, "at": "2026-09-23T00:00:00Z", "type": "coverage.withdrawn", "body": body}
        assert not validator.is_valid(event), body


# --- 2. replace: withdraw, then record -----------------------------------------------------------


def test_replace_withdraws_the_check_from_its_bucket_then_records_the_item() -> None:
    context, events = listening(prerun_package())
    context.record_coverage("checked", item("rms.x", "first pass"))
    context.record_coverage("unresolved", item("rms.x", "other bucket"))
    events.clear()

    context.replace_coverage("rms.x", "checked", item("rms.x", "second pass"))

    assert [kind for kind, _ in events] == ["coverage.withdrawn", "coverage"]
    assert events[0][1] == {"checks": ["rms.x"], "buckets": ["checked"]}
    assert [entry.reason for entry in context.require_session().coverage.unresolved] == [
        "other bucket"
    ]


def test_replace_across_buckets_moves_one_row_and_the_stream_moves_it_too() -> None:
    context, events = listening(prerun_package())
    context.record_coverage("unresolved", item("family", "was unresolved"))

    context.replace_coverage(
        "family", "checked", item("family", "now checked"), across=("checked", "unresolved")
    )

    assert withdrawals(events) == [{"checks": ["family"], "buckets": ["unresolved"]}]
    assert mirror(events) == held(context.require_session())
    assert [entry.reason for entry in context.require_session().coverage.checked] == [
        "now checked"
    ]


def test_replace_refuses_a_bucket_outside_the_buckets_it_moves_across() -> None:
    context, _ = listening(prerun_package())

    with pytest.raises(ValueError, match="skipped"):
        context.replace_coverage(
            "family", "skipped", item("family", "x"), across=("checked", "unresolved")
        )
    assert held(context.require_session()) == mirror([])


# --- 3. every path that restates coverage, through the real tools --------------------------------


def profiled(
    package: EvidencePackage, profile: StandardsProfile
) -> tuple[ToolContext, list[Event]]:
    context, events = listening(package)
    attach_standards_run(
        context, StandardsRun(profile=profile, documents=graded_documents(context.ir, profile))
    )
    return context, events


def profile_leaving_sheet_formats_empty() -> StandardsProfile:
    profile = load_profile(PROFILE_A)
    assert profile.drawing is not None
    return profile.model_copy(
        update={"drawing": profile.drawing.model_copy(update={"sheet_formats": []})}
    )


def test_one_check_over_one_scope_skipped_and_checked_is_two_items_on_the_stream_as_in_session(
) -> None:
    """`compare_with_profile` writes a drawing's conformance twice when the profile leaves a
    setting empty and the rest agree: one check, one scope, two buckets. Both are the session's,
    so both are the stream's - nothing identifies the one with the other."""
    context, events = profiled(
        load_package(PLATE_DRAWING).package, profile_leaving_sheet_formats_empty()
    )

    dispatch(context).call("check_drawings", {})

    session = context.require_session()
    conformance = {
        bucket: [entry.scope.document_ids for entry in getattr(session.coverage, bucket)
                 if entry.check == CONFORMANCE_CHECK]
        for bucket in ("checked", "skipped")
    }
    assert conformance["checked"] and conformance["checked"] == conformance["skipped"]
    assert mirror(events) == held(session)
    assert withdrawals(events) == []


def test_a_second_check_drawings_withdraws_its_two_checks_and_the_stream_follows() -> None:
    context, events = profiled(
        load_package(PLATE_DRAWING).package, profile_leaving_sheet_formats_empty()
    )
    tools = dispatch(context)
    tools.call("check_drawings", {})
    first = held(context.require_session())

    tools.call("check_drawings", {})

    assert withdrawals(events) == [
        {"checks": [CONTEXT_CHECK, CONFORMANCE_CHECK], "buckets": ["checked", "skipped"]}
    ]
    assert mirror(events) == held(context.require_session()) == first


SUMMARY_ROW_FAMILIES: frozenset[str] = frozenset({"check_mass_material", "check_hygiene"})
"""The code-first checks whose one summary row moves between buckets (feature 010 T108): a second
call withdraws it. `check_joints` records again, as a second `check_rms_part` would; answering a
repeat is the re-call guard's (`checks_mechanical`'s module docstring)."""


@pytest.mark.parametrize("tool", checks_mechanical.CODE_FIRST_CHECKS)
def test_a_code_first_check_called_twice_leaves_the_stream_equal_to_the_session(tool: str) -> None:
    context, events = listening(prerun_package())
    tools = dispatch(context)

    tools.call(tool, {})
    tools.call(tool, {})

    assert bool(withdrawals(events)) == (tool in SUMMARY_ROW_FAMILIES)
    assert mirror(events) == held(context.require_session())


@pytest.mark.parametrize("tool", ["check_rms_part", "check_rms_equations", "check_rms_assembly"])
def test_an_rms_check_called_twice_leaves_the_stream_equal_to_the_session(tool: str) -> None:
    context, events = listening(prerun_package())
    tools = dispatch(context)

    tools.call(tool, {})
    tools.call(tool, {})

    assert withdrawals(events), "the second call restates the rule items and the summary"
    assert mirror(events) == held(context.require_session())


def test_check_standards_called_twice_leaves_the_stream_equal_to_the_session() -> None:
    profile = load_profile(STANDARDS_PROFILE)
    context, events = profiled(standards_prerun_package(), profile)
    tools = dispatch(context)

    tools.call("check_standards", {})
    tools.call("check_standards", {})

    assert withdrawals(events)
    assert mirror(events) == held(context.require_session())


def test_a_tool_that_fails_twice_is_two_failed_items_on_the_stream_as_in_the_session() -> None:
    """Two failures of one tool are two items of one check over the empty scope: the session
    appends both (`SessionSink`), and nothing withdraws either."""
    context, events = listening(prerun_package())
    tools = dispatch(context)

    tools.call("get_component", {"component_id": "cmp:9999"})
    tools.call("get_component", {"component_id": "cmp:9998"})

    failed = context.require_session().coverage.failed
    assert [entry.check for entry in failed] == ["tool.get_component", "tool.get_component"]
    assert withdrawals(events) == []
    assert mirror(events) == held(context.require_session())


# --- 4. nothing else drops an announced item -----------------------------------------------------

SLICE_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][\w.]*)\[:\]\s*=", re.MULTILINE)

ALLOWED_SLICE_ASSIGNMENTS: frozenset[tuple[str, str]] = frozenset(
    {
        # The one place coverage leaves a session, and announces it.
        ("tools/context.py", "items"),
        # Finalization withdraws only the items its own previous call appended, which it never
        # announced (`finalize_session`'s docstring): the stream has nothing to take back.
        ("agent/runner.py", "review.coverage.unresolved"),
        # Not coverage: the folded findings, the pre-run's interference rows, a query's page.
        ("agent/runner.py", "session.findings"),
        ("prerun.py", "package.interferences"),
        ("tools/query.py", "page"),
    }
)
"""Every slice assignment in the package, by module and target. A new one is a list rewritten in
place, and a coverage bucket rewritten anywhere but `ToolContext.withdraw_coverage` would drop an
item the pane was told about without telling it (T092)."""


def test_every_in_place_rewrite_of_a_list_in_the_package_is_named_here() -> None:
    found = {
        (path.relative_to(SRC).as_posix(), match.group(1))
        for path in SRC.rglob("*.py")
        for match in SLICE_ASSIGNMENT.finditer(path.read_text(encoding="utf-8"))
    }

    assert found == ALLOWED_SLICE_ASSIGNMENTS


def test_every_coverage_event_type_is_one_the_contract_names() -> None:
    assert COVERAGE_EVENT_TYPES <= set(get_args(EventType))
