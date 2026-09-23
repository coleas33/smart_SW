"""The mass and hygiene families close their checklist items with one summary row (010 T108).

Research R2.25, `contracts/mass-material.md` section 3, `contracts/hygiene.md` section 2. The
checklist closes an item on a finding under its prefix or on a coverage row whose check *is*
the item's id - never by prefix - and both tools wrote per-check rows only, so a run with no
finding left the item open and the review ended saying it "ended without a finding or a
coverage entry", which is false: the family ran. Each tool now ends with one `checked` row
under its item's id (the family module's `SUMMARY_CHECK`), as the RMS and standards families
do, counting what the call wrote and found; a repeat leaves one; the tool's result does not
change. One parametrized module for the two families, so the rule is stated once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from swreview.agent.checklist import OPEN_BUCKET, ChecklistItem, load_checklist
from swreview.checks import hygiene, mass
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.loader import load_package
from swreview.report.session import CoverageItem, CoverageScope
from swreview.tools.checks_mechanical import check_hygiene, check_mass_material
from swreview.tools.context import ToolContext, build_context, context_for, use_context
from swreview.tools.standards_checks import StandardsRun, attach_standards_run
from tests.support.prerun import prerun_package

REVIEWER = Path(__file__).resolve().parents[2]
FIXTURES = REVIEWER / "tests" / "fixtures" / "mechanical"
PROFILE_A = REVIEWER / "tests" / "fixtures" / "standards" / "profile-a.yaml"
BUCKETS = ("checked", "skipped", "unresolved", "failed", "out_of_scope")


@dataclass(frozen=True)
class Family:
    """One family, its tool, and the checklist item its summary row closes."""

    module: ModuleType
    tool: Callable[[], dict[str, Any]]
    item_id: str
    prefix: str

    @property
    def item(self) -> ChecklistItem:
        """The item as `checklist_v1.yaml` holds it once T099 lands; built here so this
        module does not wait for the file."""
        return ChecklistItem(
            id=self.item_id, title=self.item_id, check_prefix=self.prefix, description=""
        )


FAMILIES = (
    Family(mass, check_mass_material, "mass.material", "mass."),
    Family(hygiene, check_hygiene, "hygiene", "hygiene."),
)
families = pytest.mark.parametrize("family", FAMILIES, ids=[f.item_id for f in FAMILIES])
fixtures = pytest.mark.parametrize("fixture", ["big-assembly", "small-assembly"])


def ran(family: Family, context: ToolContext) -> tuple[ToolContext, dict[str, Any]]:
    with use_context(context):
        return context, family.tool()


def on_fixture(family: Family, fixture: str) -> tuple[ToolContext, dict[str, Any]]:
    return ran(family, build_context(load_package(FIXTURES / fixture)))


def rows(context: ToolContext, check: str) -> list[tuple[str, CoverageItem]]:
    coverage = context.require_session().coverage
    return [
        (bucket, item)
        for bucket in BUCKETS
        for item in getattr(coverage, bucket)
        if item.check == check
    ]


def expected_reason(result: dict[str, Any]) -> str:
    coverage = result["coverage"]
    return (
        f"{coverage['checked']} checked, {coverage['skipped']} skipped coverage item(s) over "
        f"{result['documents']} document(s); {result['findings']} finding(s)"
    )


# --- the constant --------------------------------------------------------------------------------


@families
def test_the_summary_check_is_the_checklist_items_id_and_no_rule_row(family: Family) -> None:
    assert family.module.SUMMARY_CHECK == family.item_id
    assert "SUMMARY_CHECK" in family.module.__all__
    rule_rows = {getattr(family.module, n) for n in family.module.__all__ if n.startswith("CHECK_")}
    assert family.item_id not in rule_rows


# --- the row -------------------------------------------------------------------------------------


@families
@fixtures
def test_the_tool_writes_one_checked_summary_row_counting_what_it_wrote(
    family: Family, fixture: str
) -> None:
    context, result = on_fixture(family, fixture)

    [(bucket, item)] = rows(context, family.item_id)
    assert bucket == "checked"
    assert item.reason == expected_reason(result)
    assert item.scope == CoverageScope(configuration=context.ir.design.active_configuration)
    assert item.error is None


def test_the_hygiene_row_is_written_with_a_profile_too() -> None:
    family = FAMILIES[1]
    context = build_context(load_package(FIXTURES / "big-assembly"))
    profile = load_profile(PROFILE_A)
    attach_standards_run(
        context, StandardsRun(profile=profile, documents=graded_documents(context.ir, profile))
    )

    context, result = ran(family, context)

    assert result["profile"] == "attached"
    assert result["coverage"]["checked"] > 0
    [(bucket, item)] = rows(context, family.item_id)
    assert (bucket, item.reason) == ("checked", expected_reason(result))


@families
def test_a_repeated_call_leaves_one_row(family: Family) -> None:
    context, _ = on_fixture(family, "small-assembly")

    context, result = ran(family, context)

    [(bucket, item)] = rows(context, family.item_id)
    assert (bucket, item.reason) == ("checked", expected_reason(result))


@families
@fixtures
def test_the_result_counts_the_per_check_rows_and_not_the_summary(
    family: Family, fixture: str
) -> None:
    context, result = on_fixture(family, fixture)
    coverage = context.require_session().coverage

    per_check = {
        bucket: sum(1 for item in getattr(coverage, bucket) if item.check != family.item_id)
        for bucket in ("checked", "skipped", "unresolved")
    }
    assert result["coverage"] == per_check
    assert "summary" not in result


# --- what it closes ------------------------------------------------------------------------------


def test_a_hygiene_run_with_no_finding_closes_its_item() -> None:
    """The earlier lane's case: no profile, every component resolved - no finding at all.
    Before the summary row the item stayed open; the row alone closes it now."""
    family = FAMILIES[1]
    context, result = ran(family, context_for(prerun_package()))
    session = context.require_session()
    checklist = load_checklist()

    assert result["findings"] == 0
    assert checklist.bucket_of(family.item, session) == "checked"
    session.coverage.checked[:] = [i for i in session.coverage.checked if i.check != "hygiene"]
    assert checklist.bucket_of(family.item, session) == OPEN_BUCKET


@families
def test_the_row_closes_the_item_without_a_finding(family: Family) -> None:
    context, _ = on_fixture(family, "small-assembly")
    session = context.require_session()
    session.findings.clear()
    checklist = load_checklist()

    assert checklist.bucket_of(family.item, session) == "checked"
    session.coverage.checked[:] = [
        item for item in session.coverage.checked if item.check != family.item_id
    ]
    assert checklist.bucket_of(family.item, session) == OPEN_BUCKET
