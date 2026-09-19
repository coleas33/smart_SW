"""The mandatory checklist as a file, and the tenth item the gate adds (T050).

`agent/checklist_v1.yaml` is loaded once per review and rendered into the system prompt, so
every item in it moves the cacheable prefix for every session. That makes the file worth a
test of its own rather than a paragraph inside one of the runner's: this module reads the
shipped file - never a hand-written copy of it - and asserts the properties the rest of the
product relies on.

The tenth item is `standards.release`, added by feature 007 so that standards findings close
something (FR-028, `contracts/gate.md` section 4). Its id is deliberately
`STANDARDS_FAMILY.summary_check`, which is what makes it behave exactly as
`modeling.resilience` does for the rms family: the family's summary coverage item closes it
**by id**, and any `standards.*` finding closes it **by prefix**. Two ids, two prefixes, four
closures, and nothing shared between the two families - that disjointness is asserted here
because a standards run that closed the rms item (or the reverse) would report a family as
answered that nobody graded.

`report/attention.py` may not import this loader (FR-015: the policy module stays pure), so
it carries the ids as a hand-kept tuple. The drift guard for that copy lives in
`test_attention.py`; it is repeated here from this module's side, because the file this
module owns is the one that moves.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from swreview.agent.checklist import (
    FINDING_BUCKET,
    OPEN_BUCKET,
    Checklist,
    load_checklist,
)
from swreview.checks.rms.registry import RMS_FAMILY
from swreview.checks.standards.registry import STANDARDS_FAMILY
from swreview.findings import Finding, build_finding
from swreview.report.attention import CHECKLIST_ITEM_IDS
from swreview.report.session import CoverageItem, CoverageScope, ReviewSession, Timing
from tests.support.packages import build_package

PACKAGE = build_package()
CHECKLIST = load_checklist()

SESSION_ID = UUID("6f1d1d6a-6c8a-4f29-9f3f-0b0f6f5b9e20")
STARTED = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)

EXPECTED_IDS: tuple[str, ...] = (
    "provenance",
    "drawing.manufacturing_inputs",
    "interfaces.fit",
    "interfaces.stack",
    "fasteners",
    "holes.alignment",
    "interference",
    "modeling.resilience",
    "coverage.closeout",
    "standards.release",
)
"""The ten items, in the order the file lists them.

Written out rather than derived, because the *order* is what the prompt renders and what an
engineer reads down; a test that compared the file with itself would pin nothing.
"""

STANDARDS_ITEM_ID = "standards.release"
STANDARDS_PREFIX = "standards."


# --- hand-built sessions -------------------------------------------------------------------


def empty_session() -> ReviewSession:
    """A session with nothing closed: every checklist item open, no findings."""
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
    )


def coverage_item(check: str) -> CoverageItem:
    return CoverageItem(check=check, scope=CoverageScope(), reason="written by hand", error=None)


def finding_for(check: str) -> Finding:
    return build_finding(
        finding_id="F-001",
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


def item_named(checklist: Checklist, item_id: str) -> Any:
    return next(item for item in checklist.items if item.id == item_id)


def buckets_of(session: ReviewSession) -> dict[str, str]:
    return {item.id: CHECKLIST.bucket_of(item, session) for item in CHECKLIST.items}


def pairs(values: Iterable[str]) -> list[tuple[str, str]]:
    """Every ordered pair of two different values, for the "no prefix of another" scan."""
    listed = list(values)
    return [(one, other) for one in listed for other in listed if one != other]


# --- 1. the file ----------------------------------------------------------------------------


def test_the_checklist_holds_the_ten_items_in_order() -> None:
    assert tuple(item.id for item in CHECKLIST.items) == EXPECTED_IDS


def test_every_item_carries_a_title_a_prefix_and_a_description() -> None:
    """`load_checklist` refuses an incomplete item; this says none of the ten is empty."""
    for item in CHECKLIST.items:
        assert item.title.strip(), item.id
        assert item.check_prefix.endswith("."), item.id
        assert item.description.strip(), item.id


def test_no_item_prefix_is_a_prefix_of_another() -> None:
    """Two nested prefixes would let one family's finding close another family's item.

    `coverage.` and `standards.` are the pair worth naming: the pre-run writes
    `coverage.prerun.<family>` **coverage** items, which close nothing by prefix, and the
    standards family writes `standards.*` **findings**, which close exactly one item.
    """
    prefixes = [item.check_prefix for item in CHECKLIST.items]

    assert len(set(prefixes)) == len(prefixes)
    assert not [(one, other) for one, other in pairs(prefixes) if other.startswith(one)]


def test_the_rendered_prompt_block_names_every_item_once() -> None:
    """`Checklist.render()` is part of the system prompt for every review."""
    rendered = CHECKLIST.render()

    assert rendered.startswith(f"Review checklist version {CHECKLIST.version}.")
    for item in CHECKLIST.items:
        assert rendered.count(f"- `{item.id}` - {item.title}") == 1
        assert f"Closed by a finding whose check starts with `{item.check_prefix}`" in rendered
        assert f'or by `mark_coverage(check="{item.id}", ...)`.' in rendered


def test_the_standards_item_renders_its_own_block() -> None:
    item = item_named(CHECKLIST, STANDARDS_ITEM_ID)
    rendered = CHECKLIST.render()

    assert item.title == "Release standards"
    assert item.check_prefix == STANDARDS_PREFIX
    assert item.description == (
        "The company's release checklist as the standards profile configures it. Closed by "
        "a standards finding, or by the family's summary coverage item."
    )
    assert f"- `{STANDARDS_ITEM_ID}` - Release standards" in rendered


# --- 2. the item is the standards family's summary check ------------------------------------


def test_the_standards_item_id_is_the_families_summary_check() -> None:
    """Not a literal that happens to match: the id **is** `STANDARDS_FAMILY.summary_check`,
    which is what makes the summary coverage item close the item by id."""
    assert STANDARDS_FAMILY.summary_check == STANDARDS_ITEM_ID
    assert item_named(CHECKLIST, STANDARDS_ITEM_ID).id == STANDARDS_FAMILY.summary_check


def test_the_two_families_summary_items_are_disjoint() -> None:
    """A standards run must not close the rms item, and an rms run must not close this one."""
    rms_item = item_named(CHECKLIST, RMS_FAMILY.summary_check)
    standards_item = item_named(CHECKLIST, STANDARDS_FAMILY.summary_check)

    assert rms_item.id != standards_item.id
    assert rms_item.check_prefix != standards_item.check_prefix
    assert not RMS_FAMILY.summary_check.startswith(standards_item.check_prefix)
    assert not STANDARDS_FAMILY.summary_check.startswith(rms_item.check_prefix)


def test_every_standards_check_id_sits_under_the_items_prefix() -> None:
    """The sixteen checks close the item by prefix; the summary check is not one of them."""
    from swreview.checks.standards.registry import RULES

    assert RULES
    assert all(check.startswith(STANDARDS_PREFIX) for check in RULES)
    assert STANDARDS_FAMILY.summary_check not in RULES


# --- 3. what closes it ----------------------------------------------------------------------


def test_the_standards_item_is_open_on_a_session_that_graded_nothing() -> None:
    assert buckets_of(empty_session())[STANDARDS_ITEM_ID] == OPEN_BUCKET


def test_a_standards_finding_closes_the_item_by_prefix() -> None:
    session = empty_session()
    session.findings.append(finding_for("standards.document.data_card_complete"))

    buckets = buckets_of(session)

    assert buckets[STANDARDS_ITEM_ID] == FINDING_BUCKET
    assert buckets[RMS_FAMILY.summary_check] == OPEN_BUCKET


def test_the_families_summary_coverage_item_closes_it_by_id() -> None:
    """The item the standards run writes last, in either bucket the summary moves between."""
    for bucket in ("checked", "unresolved"):
        session = empty_session()
        getattr(session.coverage, bucket).append(coverage_item(STANDARDS_FAMILY.summary_check))

        buckets = buckets_of(session)

        assert buckets[STANDARDS_ITEM_ID] == bucket
        assert buckets[RMS_FAMILY.summary_check] == OPEN_BUCKET


def test_an_rms_run_leaves_the_standards_item_open() -> None:
    """The mirror of the test above, so the disjointness is asserted from both sides."""
    session = empty_session()
    session.findings.append(finding_for("rms.sketches.fully_defined"))
    session.coverage.checked.append(coverage_item(RMS_FAMILY.summary_check))

    buckets = buckets_of(session)

    assert buckets[RMS_FAMILY.summary_check] == FINDING_BUCKET
    assert buckets[STANDARDS_ITEM_ID] == OPEN_BUCKET


def test_a_prerun_coverage_item_closes_nothing() -> None:
    """`coverage.prerun.standards` says the family was **not** evaluated; it must not close
    the item that sentence is asking the model to work on (`prerun.PRERUN_CHECK_PREFIX`)."""
    session = empty_session()
    session.coverage.skipped.append(coverage_item("coverage.prerun.standards"))

    assert buckets_of(session)[STANDARDS_ITEM_ID] == OPEN_BUCKET
    assert buckets_of(session)["coverage.closeout"] == OPEN_BUCKET


def test_every_item_opens_and_closes_independently() -> None:
    """One coverage entry per item, one at a time: nothing closes anything but itself."""
    for item in CHECKLIST.items:
        session = empty_session()
        session.coverage.checked.append(coverage_item(item.id))

        closed = [one for one, bucket in buckets_of(session).items() if bucket != OPEN_BUCKET]

        assert closed == [item.id]


# --- 4. the copy in the pure policy module --------------------------------------------------


def test_the_attention_modules_copy_of_the_ids_is_this_files_own() -> None:
    """`report/attention.py` may not import this loader (FR-015), so the copy is asserted.

    Also asserted in `test_attention.py`, from that module's side. Both are cheap and the
    failure reads differently depending on which file the author was editing.
    """
    assert CHECKLIST_ITEM_IDS == EXPECTED_IDS
    assert CHECKLIST_ITEM_IDS == tuple(item.id for item in load_checklist().items)
