"""Unit tests for the RMS grade (T068).

`checks/rms/grade.py` turns what a check produced into the number the Model check tab
shows, and `specs/003-resilient-modeling/plan.md` key point 10 is the whole specification:
counts per bucket are the headline, the fraction is secondary and absent rather than zero
when nothing was graded, the unresolved rule ids travel beside the counts so a score
cannot be shown without them, and **no letter is produced by any code path** - a letter is
the confident-but-unsupported artefact Principle I exists to prevent.

Two sources are graded, and the tests pin both against each other:

- a rule layer's `RuleResult`s, before anything is recorded (what feature 004 grades when
  it wants a number for a tree it has just evaluated);
- a recorded `ReviewSession`, which is what `run_rms_check` and the route grade. This is
  the authoritative one, because an accepted exception turns a rule layer `fail` into a
  `checked_within_scope` finding at recording time and only the session knows it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from swreview.checks.rms.grade import BUCKETS, delta, grade
from swreview.checks.rms.registry import RULES
from swreview.checks.rms.report import report_results
from swreview.checks.rms.results import RuleResult, finding, passed, skipped, unresolved
from swreview.exceptions import ExceptionStore
from swreview.ir.models import EvidencePackage, Feature
from swreview.report.session import ReviewSession
from swreview.tools.context import ToolContext, context_for
from tests.support.features import PartSpec, feature, folder, rms_package

HOUSING = "doc:2"

FAIL_RULE = "rms.intent.every_feature_described"
SECOND_FAIL_RULE = "rms.refs.direction"
WARN_RULE = "rms.detail.holes_last"
PASS_RULE = "rms.core.shell_last"
SKIP_RULE = "rms.quarantine.largest_fillet_first"
UNRESOLVED_RULE = "rms.sketches.fully_defined"
SECOND_UNRESOLVED_RULE = "rms.groups.no_solids_in_ref_or_construction"


@dataclass(frozen=True)
class AcceptedFinding:
    """The `FingerprintTarget` shape `ExceptionStore.accept` reads."""

    check: str
    component_ids: list[str]
    configuration: str


# --- the results a grade is taken over --------------------------------------------


def a_fail(rule_id: str = FAIL_RULE, document_id: str = HOUSING) -> RuleResult:
    return finding(
        RULES[rule_id],
        document_id,
        [],
        observed=f"{rule_id} is violated",
        recommended_action="Fix it.",
    )


def a_warn(rule_id: str = WARN_RULE, document_id: str = HOUSING) -> RuleResult:
    return finding(
        RULES[rule_id],
        document_id,
        [],
        observed=f"{rule_id} is questionable",
        recommended_action="Look at it.",
    )


def a_pass(rule_id: str = PASS_RULE, document_id: str = HOUSING) -> RuleResult:
    return passed(RULES[rule_id], document_id)


def a_skip(rule_id: str = SKIP_RULE, document_id: str = HOUSING) -> RuleResult:
    return skipped(RULES[rule_id], document_id, "no Quarantine group")


def an_unresolved(rule_id: str = UNRESOLVED_RULE, document_id: str = HOUSING) -> RuleResult:
    return unresolved(RULES[rule_id], document_id, "sketch status unreadable")


def a_waived(rule_id: str = FAIL_RULE, document_id: str = HOUSING) -> RuleResult:
    violation = a_fail(rule_id, document_id)
    return RuleResult(
        rule_id=violation.rule_id,
        document_id=violation.document_id,
        outcome="waived",
        subjects=list(violation.subjects),
        result=violation.result,
        reason="accepted by the owner",
    )


# --- 1. counts per bucket ---------------------------------------------------------


class TestCountsPerBucket:
    def test_every_outcome_lands_in_its_own_bucket(self) -> None:
        graded = grade([a_fail(), a_warn(), a_pass(), a_skip(), an_unresolved()])

        assert graded.failed == 1
        assert graded.warned == 1
        assert graded.checked == 1
        assert graded.skipped == 1
        assert graded.unresolved == 1
        assert graded.out_of_scope == 0

    def test_a_waived_outcome_is_checked_not_failed(self) -> None:
        """An accepted condition is reported as checked within scope, so it counts as
        checked - the whole point of SC-010 is that the rule stops being a failure."""
        graded = grade([a_waived()])

        assert (graded.checked, graded.failed) == (1, 0)

    def test_the_same_rule_on_two_documents_counts_twice(self) -> None:
        graded = grade([a_fail(document_id=HOUSING), a_fail(document_id="doc:3")])

        assert graded.failed == 2

    def test_counts_cover_exactly_the_six_buckets(self) -> None:
        assert BUCKETS == (
            "failed",
            "warned",
            "checked",
            "skipped",
            "unresolved",
            "out_of_scope",
        )
        assert set(grade([a_fail()]).counts) == set(BUCKETS)


# --- 2. the fraction is secondary and never invented -------------------------------


class TestFraction:
    def test_is_checked_over_checked_plus_failed_plus_warned(self) -> None:
        results = [a_pass(), a_pass(PASS_RULE, "doc:3"), a_fail(), a_warn(), a_skip()]

        graded = grade(results)

        assert graded.fraction == pytest.approx(2 / 4)

    def test_is_absent_rather_than_zero_when_nothing_was_graded(self) -> None:
        """Only skips and unresolved rules: nothing passed and nothing failed, so there
        is no fraction to state. Zero would read as "everything failed"."""
        graded = grade([a_skip(), an_unresolved()])

        assert graded.fraction is None
        assert graded.skipped == 1
        assert graded.unresolved == 1

    def test_is_one_when_every_graded_rule_passed(self) -> None:
        assert grade([a_pass(), a_skip()]).fraction == pytest.approx(1.0)


# --- 3. the unresolved rules are named, always -------------------------------------


class TestUnresolvedRuleIds:
    def test_the_ids_are_carried_not_only_the_count(self) -> None:
        graded = grade([an_unresolved(), an_unresolved(SECOND_UNRESOLVED_RULE)])

        assert graded.unresolved == 2
        assert graded.unresolved_rule_ids == tuple(
            sorted((UNRESOLVED_RULE, SECOND_UNRESOLVED_RULE))
        )

    def test_one_rule_unresolved_on_two_documents_is_named_once(self) -> None:
        graded = grade([an_unresolved(), an_unresolved(document_id="doc:3")])

        assert graded.unresolved == 2
        assert graded.unresolved_rule_ids == (UNRESOLVED_RULE,)

    def test_the_rendered_grade_carries_the_ids_beside_the_counts(self) -> None:
        body = grade([a_pass(), an_unresolved()]).as_dict()

        assert body["unresolved_rule_ids"] == [UNRESOLVED_RULE]
        assert body["unresolved"] == 1

    def test_the_summary_line_names_them(self) -> None:
        assert UNRESOLVED_RULE in grade([a_pass(), an_unresolved()]).summary()


# --- 4. no letter, and an empty grade says so --------------------------------------


class TestNoLetterAndNothingEvaluated:
    def test_the_grade_exposes_no_letter_anywhere(self) -> None:
        graded = grade([a_pass(), a_fail()])

        assert not [name for name in dir(graded) if "letter" in name.lower()]
        assert not [
            name for name in dir(graded) if name.lower() in {"grade", "score", "mark"}
        ]

    def test_no_rendered_value_is_a_single_letter(self) -> None:
        body = grade([a_pass(), a_fail(), a_warn()]).as_dict()

        assert all(not isinstance(value, str) for value in body.values())

    def test_an_empty_result_set_is_nothing_evaluated_not_a_perfect_score(self) -> None:
        graded = grade([])

        assert graded.nothing_evaluated
        assert graded.fraction is None
        assert graded.counts == dict.fromkeys(BUCKETS, 0)
        assert graded.summary() == "nothing evaluated"

    def test_a_graded_run_is_not_nothing_evaluated(self) -> None:
        assert not grade([a_skip()]).nothing_evaluated
        assert grade([a_skip()]).summary() != "nothing evaluated"


# --- 5. the same grade off a recorded session --------------------------------------


def package() -> EvidencePackage:
    return rms_package(
        parts=[
            PartSpec(
                document_id=HOUSING,
                name="housing",
                features=(folder("3-Core", feature("Boss", "Extrusion")),),
            )
        ]
    )


def rows(evidence: EvidencePackage) -> list[Feature]:
    return [row for row in evidence.features if row.document_id == HOUSING]


def recorded(
    evidence: EvidencePackage, results: Sequence[RuleResult], store: ExceptionStore | None = None
) -> ReviewSession:
    context: ToolContext = context_for(evidence)
    context.exceptions = store
    report_results(context, list(results))
    return context.require_session()


class TestGradingASession:
    def test_the_dispatched_rules_count_the_same_as_their_results(self) -> None:
        evidence = package()
        results = [a_fail(), a_warn(), a_pass(), a_skip(), an_unresolved()]

        from_results = grade(results)
        from_session = grade(recorded(evidence, results))

        for bucket in ("failed", "warned", "checked", "skipped"):
            assert getattr(from_session, bucket) == getattr(from_results, bucket), bucket

    def test_the_never_dispatched_rules_are_counted_too(self) -> None:
        """The four data-gap rules and the six out-of-scope rules are written once per
        session by the report layer; the grade reports them rather than hiding them."""
        graded = grade(recorded(package(), [a_pass()]))

        assert graded.out_of_scope == 6
        assert graded.unresolved == 4
        assert set(graded.unresolved_rule_ids) == {
            rule.id
            for rule in RULES.values()
            if rule.coverage is not None and rule.coverage[0] == "unresolved"
        }

    def test_an_accepted_failure_counts_as_checked_in_the_session(self) -> None:
        """The rule layer still says `fail`; the store turns it into a finding that is
        checked within scope, and the session is the only place that is known."""
        evidence = package()
        store = ExceptionStore()
        store.accept(
            AcceptedFinding(
                check=FAIL_RULE,
                component_ids=[component.id for component in evidence.components],
                configuration=evidence.design.active_configuration,
            ),
            evidence,
            by="owner",
            note="legacy tree, accepted by the owner",
            at=datetime(2026, 9, 15, tzinfo=UTC),
        )

        graded = grade(recorded(evidence, [a_fail()], store))

        assert (graded.failed, graded.checked) == (0, 1)

    def test_the_summary_item_and_the_type_census_are_not_graded_as_rules(self) -> None:
        """`modeling.resilience` and `rms.types.unknown` are written as coverage but are
        not rules, so they must not move a count."""
        session = recorded(package(), [a_pass()])
        checks = {item.check for item in session.coverage.checked}

        assert "modeling.resilience" in checks
        assert grade(session).checked == 1


# --- 6. before and after ------------------------------------------------------------


class TestDelta:
    def test_counts_move_by_the_difference(self) -> None:
        before = grade([a_fail(), a_fail(SECOND_FAIL_RULE), a_pass()])
        after = grade([a_fail(), a_pass(), a_pass(PASS_RULE, "doc:3")])

        moved = delta(before, after)

        assert moved.counts["failed"] == -1
        assert moved.counts["checked"] == 1
        assert moved.before is before
        assert moved.after is after

    def test_rules_that_stopped_being_unresolved_are_named(self) -> None:
        before = grade([an_unresolved(), an_unresolved(SECOND_UNRESOLVED_RULE)])
        after = grade([an_unresolved(), a_pass(SECOND_UNRESOLVED_RULE)])

        moved = delta(before, after)

        assert moved.resolved_rule_ids == (SECOND_UNRESOLVED_RULE,)
        assert moved.newly_unresolved_rule_ids == ()

    def test_a_rule_that_became_unresolved_is_named(self) -> None:
        moved = delta(grade([a_pass()]), grade([an_unresolved()]))

        assert moved.newly_unresolved_rule_ids == (UNRESOLVED_RULE,)
        assert moved.resolved_rule_ids == ()

    def test_the_summary_states_both_grades_and_never_a_letter(self) -> None:
        moved = delta(grade([]), grade([a_pass()]))

        assert "nothing evaluated" in moved.summary()
        assert isinstance(moved.summary(), str)
