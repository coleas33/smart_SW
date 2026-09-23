"""The mass and hygiene families close their checklist items with one summary row (010 T108).

Research R2.25, `contracts/mass-material.md` section 3, `contracts/hygiene.md` section 2. The
checklist closes an item on a finding under its prefix or on a coverage row whose check *is*
the item's id - never by prefix - and both tools wrote per-check rows only, so a run with no
finding left the item open and the review ended saying it "ended without a finding or a
coverage entry", which is false: the family ran. Each tool now ends with one `checked` row
under its item's id (the family module's `SUMMARY_CHECK`), as the RMS and standards families
do, counting what the call wrote and found; a repeat leaves one; the tool's result does not
change. One parametrized module for the two families, so the rule is stated once.

**The row's bucket** (T108 as amended 2026-09-23): `checked` only when the call wrote at least
one `checked` per-check row or recorded a finding; otherwise `skipped`, with the same counts in
its reason, so a run that checked nothing - no standards profile, every part lightweight -
reads "not reached" on the Review summary's goal line instead of "checked". A call whose
finding is refused writes the row `failed`, never `checked`, whatever it recorded before the
refusal. The bucket is pinned here on scripted family runs, so each case is exactly the one
named, and on real packages for the cases the defect was found on.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from swreview.agent.checklist import OPEN_BUCKET, ChecklistItem, load_checklist
from swreview.checks import hygiene, mass
from swreview.checks.result import CheckResult, DocumentResult
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.attention import rank
from swreview.report.session import CoverageItem, CoverageScope
from swreview.report.summary import GoalLine, load_words, review_summary
from swreview.tools import checks_mechanical
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
    goal: str
    """The Review summary goal whose `items` name the summary row (`review_words_v1.yaml`)."""
    runner: tuple[ModuleType, str]
    """Where the tool looks its plain run function up, so a test can script the run."""
    checks_type: type
    """The run function's plain value: findings, checked rows, skipped rows, documents."""
    passing_rule: str
    """A rule of the family whose passes are a `checked` per-check row."""

    @property
    def item(self) -> ChecklistItem:
        """The item as `checklist_v1.yaml` holds it once T099 lands; built here so this
        module does not wait for the file."""
        return ChecklistItem(
            id=self.item_id, title=self.item_id, check_prefix=self.prefix, description=""
        )


FAMILIES = (
    Family(
        mass,
        check_mass_material,
        "mass.material",
        "mass.",
        "mass_and_material",
        (checks_mechanical, "run_mass_checks"),
        mass.MassChecks,
        mass.CHECK_MATERIAL_ASSIGNED,
    ),
    Family(
        hygiene,
        check_hygiene,
        "hygiene",
        "hygiene.",
        "hygiene",
        (hygiene, "run_hygiene_checks"),
        hygiene.HygieneChecks,
        hygiene.CHECK_REVISION,
    ),
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


def counts_reason(checked: int, skipped: int, documents: int, findings: int) -> str:
    return (
        f"{checked} checked, {skipped} skipped coverage item(s) over "
        f"{documents} document(s); {findings} finding(s)"
    )


def expected_reason(result: dict[str, Any]) -> str:
    coverage = result["coverage"]
    return counts_reason(
        coverage["checked"], coverage["skipped"], result["documents"], result["findings"]
    )


def goal_line(context: ToolContext, family: Family) -> GoalLine:
    """The family's goal line on the Review summary of the session the tool wrote."""
    session = context.require_session()
    summary = review_summary(rank(session), session, context.ir)
    return next(line for line in summary.goals if line.goal == family.goal)


def goal_state(line: GoalLine) -> tuple[str, str | None, str | None]:
    return (line.state_label, line.reason, line.detail)


WORDS = load_words()
NOT_REACHED = WORDS.goal_states["not_reached"]
CHECKED = WORDS.goal_states["checked"]
ISSUES = WORDS.goal_states["issues"]
SKIPPED_REASON = WORDS.goal_reasons["skipped"]
FAILED_REASON = WORDS.goal_reasons["failed"]


def every_part_lightweight() -> EvidencePackage:
    """The small fixture with every component lightweight: no part is read, so the mass
    family evaluates nothing and writes only its skipped `mass.coverage` row."""
    package = load_package(FIXTURES / "small-assembly").package
    return package.model_copy(
        update={
            "components": [
                component.model_copy(update={"suppression": "lightweight"})
                for component in package.components
            ]
        }
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
    Before the summary row the item stayed open; the row alone closes it now. It closes it
    `skipped`, not `checked`: every property check was skipped for want of a profile and
    the component check found nothing, so nothing was checked (T108 as amended)."""
    family = FAMILIES[1]
    context, result = ran(family, context_for(prerun_package()))
    session = context.require_session()
    checklist = load_checklist()

    assert (result["findings"], result["coverage"]["checked"]) == (0, 0)
    assert checklist.bucket_of(family.item, session) == "skipped"
    session.coverage.skipped[:] = [i for i in session.coverage.skipped if i.check != "hygiene"]
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


# --- the bucket: checked only when something was checked or found (T108 as amended) -------------

SCRIPTED_DOCUMENTS = 3


def scripted_finding(
    context: ToolContext, family: Family, *, refused: bool = False
) -> DocumentResult:
    """One document-scope result on the root. `refused` makes it an unresolved result with
    no coverage limit, which `build_finding` refuses, so the tool returns its error."""
    root = context.ir.design.root_assembly_document_id
    return DocumentResult(
        result=CheckResult(
            check=family.passing_rule,
            status="unresolved" if refused else "demonstrated",
            severity="low",
            observed=f"a scripted {family.item_id} result",
            requirement="a scripted requirement",
            inputs=[root],
            calculation=None,
            coverage_limits=[],
            recommended_action="Nothing: this result is scripted.",
        ),
        documents=(root,),
        component_ids=(),
    )


def script_run(
    monkeypatch: pytest.MonkeyPatch,
    family: Family,
    context: ToolContext,
    *,
    checked: int,
    findings: Sequence[str],
) -> None:
    """Make the family's run return `checked` passing rows, one skipped row, and one
    scripted result per entry of `findings` ("ok" or "refused")."""
    run = family.checks_type(
        findings=tuple(
            scripted_finding(context, family, refused=kind == "refused") for kind in findings
        ),
        checked=tuple(
            CoverageItem(
                check=family.passing_rule,
                scope=CoverageScope(),
                reason="scripted passes",
                error=None,
            )
            for _ in range(checked)
        ),
        skipped=(
            CoverageItem(
                check=family.module.CHECK_COVERAGE,
                scope=CoverageScope(),
                reason="scripted: what was not read",
                error=None,
            ),
        ),
        documents=SCRIPTED_DOCUMENTS,
    )
    module, name = family.runner
    monkeypatch.setattr(module, name, lambda *args, **kwargs: run)


@dataclass(frozen=True)
class Case:
    """One scripted run, the summary row it must write, and the goal line that follows."""

    checked: int
    findings: tuple[str, ...]
    bucket: str
    goal_label: str
    goal_reason: str | None
    """The goal line's short reason; its detail is then the summary row's reason."""


CASES = {
    # Nothing checked, nothing found: the row is skipped and the goal is not reached, its
    # reason "skipped" and its detail the row's counts.
    "all_skipped": Case(0, (), "skipped", NOT_REACHED, SKIPPED_REASON),
    # One passing per-check row is enough for checked.
    "one_checked": Case(1, (), "checked", CHECKED, None),
    # A finding with no passing row is checked too; issues outrank it on the goal line.
    "findings_only": Case(0, ("ok",), "checked", ISSUES, None),
    # A refused finding is failed, never checked; the goal line says a check failed.
    "refused": Case(0, ("refused",), "failed", NOT_REACHED, FAILED_REASON),
    # ... whatever the run would have checked: its rows are never written.
    "refused_with_passes": Case(1, ("refused",), "failed", NOT_REACHED, FAILED_REASON),
    # ... and whatever it recorded before the refusal: that finding is the goal's issue.
    "refused_after_a_finding": Case(0, ("ok", "refused"), "failed", ISSUES, None),
}
cases = pytest.mark.parametrize("case", CASES.values(), ids=list(CASES))


@families
@cases
def test_the_summary_bucket_and_the_goal_line_follow_what_the_run_did(
    monkeypatch: pytest.MonkeyPatch, family: Family, case: Case
) -> None:
    context = build_context(load_package(FIXTURES / "small-assembly"))
    script_run(monkeypatch, family, context, checked=case.checked, findings=case.findings)

    context, result = ran(family, context)

    recorded = len(context.require_session().findings)
    assert recorded == case.findings.count("ok")
    [(bucket, item)] = rows(context, family.item_id)
    assert bucket == case.bucket
    if case.bucket == "failed":
        assert set(result) == {"error"}
        assert item.error == result["error"]
        assert item.reason == counts_reason(0, 0, SCRIPTED_DOCUMENTS, recorded)
    else:
        assert item.error is None
        assert item.reason == expected_reason(result)
        assert result["coverage"] == {"checked": case.checked, "skipped": 1, "unresolved": 0}
    detail = None if case.goal_reason is None else item.reason
    assert goal_state(goal_line(context, family)) == (case.goal_label, case.goal_reason, detail)


@families
def test_a_repeat_moves_the_one_row_between_buckets(
    monkeypatch: pytest.MonkeyPatch, family: Family
) -> None:
    """`replace_coverage` clears one bucket only, so a row that moves must leave none behind."""
    context = build_context(load_package(FIXTURES / "small-assembly"))

    for name in ("one_checked", "all_skipped", "refused", "one_checked"):
        case = CASES[name]
        script_run(monkeypatch, family, context, checked=case.checked, findings=case.findings)
        ran(family, context)

        assert [bucket for bucket, _ in rows(context, family.item_id)] == [case.bucket]


def test_every_part_lightweight_leaves_mass_and_material_not_reached() -> None:
    """The defect as found: no standards profile, every part lightweight. The mass family
    reads no part, so it checks nothing and finds nothing; before the amendment its row was
    `checked` and the goal line read "checked, no issue"."""
    family = FAMILIES[0]

    context, result = ran(family, context_for(every_part_lightweight()))

    assert (result["findings"], result["coverage"]) == (
        0,
        {"checked": 0, "skipped": 1, "unresolved": 0},
    )
    [(bucket, item)] = rows(context, family.item_id)
    assert (bucket, item.reason) == ("skipped", expected_reason(result))
    assert goal_state(goal_line(context, family)) == (NOT_REACHED, SKIPPED_REASON, item.reason)


def test_every_part_lightweight_is_hygiene_findings_only_and_checked() -> None:
    """The same package through hygiene: its property checks are skipped with no profile,
    but every lightweight instance is a `hygiene.component_not_resolved` finding, so the row
    is `checked` on findings alone and the goal line reads issues found."""
    family = FAMILIES[1]

    context, result = ran(family, context_for(every_part_lightweight()))

    assert result["coverage"]["checked"] == 0
    assert result["findings"] > 0
    [(bucket, item)] = rows(context, family.item_id)
    assert (bucket, item.reason) == ("checked", expected_reason(result))
    assert goal_line(context, family).state_label == ISSUES


def test_a_hygiene_run_that_checked_nothing_is_not_reached_on_the_summary() -> None:
    """No profile, every component resolved: nothing checked, nothing found (the case
    `test_a_hygiene_run_with_no_finding_closes_its_item` closes the item on)."""
    family = FAMILIES[1]

    context, result = ran(family, context_for(prerun_package()))

    [(bucket, item)] = rows(context, family.item_id)
    assert (bucket, item.reason) == ("skipped", expected_reason(result))
    assert goal_state(goal_line(context, family)) == (NOT_REACHED, SKIPPED_REASON, item.reason)
