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

The eleventh and twelfth items are feature 010's (T098-T099): `mass.material` (prefix
`mass.`) and `hygiene` (prefix `hygiene.`), so what `check_mass_material` and
`check_hygiene` find closes something. Appended after `standards.release`, as that item was
appended after `coverage.closeout`, so no earlier item moves in the prompt. Each is closed by
a finding of its family, or by a coverage entry whose `check` **is** the item id - the summary
row each tool writes under its family's `SUMMARY_CHECK` (T108, research R2.25). The per-rule
coverage rows the two tools write (`mass.material_assigned`, `mass.coverage`,
`hygiene.revision_present`, `hygiene.coverage`, ...) close nothing: the checklist matches a
coverage entry by id, never by prefix. Like `standards.release`, neither item names its tool:
lever 13 withholds both once checks first has run them (008 FR-030).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from types import ModuleType
from typing import Any, NamedTuple
from uuid import UUID

import pytest

from swreview.agent.checklist import (
    COVERAGE_BUCKETS,
    FINDING_BUCKET,
    OPEN_BUCKET,
    Checklist,
    load_checklist,
)
from swreview.checks import hygiene, mass
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
    "mass.material",
    "hygiene",
)
"""The twelve items, in the order the file lists them.

Written out rather than derived, because the *order* is what the prompt renders and what an
engineer reads down; a test that compared the file with itself would pin nothing.
"""

STANDARDS_ITEM_ID = "standards.release"
STANDARDS_PREFIX = "standards."

MASS_ITEM_ID = "mass.material"
MASS_PREFIX = "mass."
HYGIENE_ITEM_ID = "hygiene"
HYGIENE_PREFIX = "hygiene."


class Family(NamedTuple):
    """One feature 010 family and the checklist item its findings close."""

    item_id: str
    prefix: str
    module: ModuleType
    finding_checks: tuple[str, ...]
    """The ids it records findings under (`contracts/mass-material.md` section 2,
    `contracts/hygiene.md` section 2); its `CHECK_COVERAGE` id is a row only."""
    tool: str
    """The check tool that runs the family, which lever 13 withholds after checks first."""

    def check_ids(self) -> list[str]:
        """Every `CHECK_*` id the module exports: the findings' ids and the rows'."""
        module = self.module
        return sorted(getattr(module, name) for name in module.__all__ if name.startswith("CHECK_"))


FAMILIES = (
    Family(
        MASS_ITEM_ID,
        MASS_PREFIX,
        mass,
        (mass.CHECK_MATERIAL_ASSIGNED, mass.CHECK_DENSITY, mass.CHECK_ASSEMBLY_OVERRIDE),
        "check_mass_material",
    ),
    Family(
        HYGIENE_ITEM_ID,
        HYGIENE_PREFIX,
        hygiene,
        (
            hygiene.CHECK_PART_NUMBER,
            hygiene.CHECK_DUPLICATE_DESCRIPTION,
            hygiene.CHECK_DUPLICATE_PART_NUMBER,
            hygiene.CHECK_REVISION,
            hygiene.CHECK_COMPONENT_NOT_RESOLVED,
        ),
        "check_hygiene",
    ),
)
family_parameters = pytest.mark.parametrize(
    "family", FAMILIES, ids=[family.item_id for family in FAMILIES]
)


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


def test_the_checklist_holds_the_twelve_items_in_order() -> None:
    assert tuple(item.id for item in CHECKLIST.items) == EXPECTED_IDS


def test_every_item_carries_a_title_a_prefix_and_a_description() -> None:
    """`load_checklist` refuses an incomplete item; this says none of the twelve is empty."""
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


# --- 5. feature 010's two items: mass and material, and hygiene (T098) ----------------------


def test_the_mass_item_reads_as_the_family_it_closes() -> None:
    item = item_named(CHECKLIST, MASS_ITEM_ID)

    assert item.title == "Mass and material"
    assert item.check_prefix == MASS_PREFIX
    assert item.description == (
        "Every part carries a material or a deliberate mass override, its density fits the "
        "material's class, and assembly mass overrides are flagged. Parts and bodies that "
        "were not read are counted in coverage, never assumed. Closed by a mass finding, or "
        "by the family's summary coverage item."
    )
    assert f"- `{MASS_ITEM_ID}` - Mass and material" in CHECKLIST.render()


def test_the_hygiene_item_reads_as_the_family_it_closes() -> None:
    item = item_named(CHECKLIST, HYGIENE_ITEM_ID)

    assert item.title == "Model hygiene"
    assert item.check_prefix == HYGIENE_PREFIX
    assert item.description == (
        "Part numbers match file names, no two documents share a description or a part "
        "number, every model carries a revision, and suppressed or lightweight components "
        "are findings. The property names come from the standards profile; without one "
        "those checks are skipped, naming the setting. Closed by a hygiene finding, or by "
        "the family's summary coverage item."
    )
    assert f"- `{HYGIENE_ITEM_ID}` - Model hygiene" in CHECKLIST.render()


@family_parameters
def test_neither_item_names_the_tool_lever_13_withholds(family: Family) -> None:
    """Once checks first has run a tool to completion it leaves the array, and nothing the
    model is sent may ask for it (008 FR-030); `standards.release` names no tool either."""
    description = item_named(CHECKLIST, family.item_id).description

    assert family.tool not in description
    assert "check_" not in description


@family_parameters
def test_the_items_id_is_the_familys_summary_row(family: Family) -> None:
    """What the tool writes under the item id closes it on a run with no finding (T108)."""
    assert family.module.SUMMARY_CHECK == family.item_id


@family_parameters
def test_every_check_id_the_family_defines_sits_under_the_items_prefix(family: Family) -> None:
    """Findings close the item by prefix, so an id outside it would close nothing; and the
    item id is none of the rules' ids: only the family's summary row, `SUMMARY_CHECK`, is
    written under it, on purpose."""
    checks = family.check_ids()

    assert set(family.finding_checks) < set(checks), "plus the family's coverage row"
    assert all(check.startswith(family.prefix) for check in checks), checks
    assert family.item_id not in checks


@family_parameters
def test_each_finding_of_the_family_closes_its_item_and_only_its_item(family: Family) -> None:
    for check in family.finding_checks:
        session = empty_session()
        session.findings.append(finding_for(check))

        buckets = buckets_of(session)

        assert [one for one, bucket in buckets.items() if bucket != OPEN_BUCKET] == [
            family.item_id
        ], check
        assert buckets[family.item_id] == FINDING_BUCKET


@family_parameters
@pytest.mark.parametrize("bucket", COVERAGE_BUCKETS)
def test_the_items_own_coverage_entry_closes_it_in_every_bucket(
    family: Family, bucket: str
) -> None:
    """The summary coverage entry - `mark_coverage(check=<item id>)` - in any of the four
    buckets that close an item, and it closes nothing else."""
    session = empty_session()
    getattr(session.coverage, bucket).append(coverage_item(family.item_id))

    buckets = buckets_of(session)

    assert buckets[family.item_id] == bucket
    assert [one for one, found in buckets.items() if found != OPEN_BUCKET] == [family.item_id]


@family_parameters
def test_a_failed_entry_under_the_item_id_does_not_close_it(family: Family) -> None:
    """`failed` never closes an item, not even the family's own summary row, which a refused
    finding writes there under the item's id (T108 as amended)."""
    session = empty_session()
    session.coverage.failed.append(coverage_item(family.item_id))

    assert buckets_of(session)[family.item_id] == OPEN_BUCKET


@family_parameters
@pytest.mark.parametrize("bucket", COVERAGE_BUCKETS)
def test_the_per_rule_rows_the_tools_write_close_nothing(family: Family, bucket: str) -> None:
    """Every `CHECK_*` id as a coverage row: matched by id, a row named
    `mass.material_assigned` or `hygiene.coverage` is not the item's entry."""
    session = empty_session()
    for check in family.check_ids():
        getattr(session.coverage, bucket).append(coverage_item(check))

    assert [found for found in buckets_of(session).values() if found != OPEN_BUCKET] == []


def test_the_standards_material_rule_closes_the_standards_item_not_the_mass_item() -> None:
    """`standards.part.material_assigned` is the release checklist's rule on the same fact;
    it answers `standards.release`, and `mass.material` stays with its own family."""
    from swreview.checks.standards.registry import RULES

    assert "standards.part.material_assigned" in RULES
    session = empty_session()
    session.findings.append(finding_for("standards.part.material_assigned"))

    buckets = buckets_of(session)

    assert buckets[STANDARDS_ITEM_ID] == FINDING_BUCKET
    assert buckets[MASS_ITEM_ID] == OPEN_BUCKET
    assert buckets[HYGIENE_ITEM_ID] == OPEN_BUCKET
