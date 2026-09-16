"""Unit tests for the two equation-scope RMS rule evaluators (T039).

`specs/003-resilient-modeling/contracts/rules.md` is normative: one test class per rule,
covering every row of its line in the equation-scope table - the pass, the fail or warn,
and both unresolved conditions the contract words ("unresolved when the `equations` gap is
recorded or any `is_global` is null") - plus the cross-cutting section "Unresolved part
documents", which holds every equation-scope rule exactly as it holds every part-scope one.

Three things are asserted throughout, because they are the contract's shape rather than
any one rule's detail:

- **the subject is the document.** Both rules grade the document, never an equation row,
  so `subjects` is empty in every outcome and a reason names the row in its text instead;
- **one `RuleResult` per outcome reached**, and for a document-scope rule that means
  exactly one result: `by_outcome` refuses a second result in the same bucket and the
  tests assert the list of buckets reached;
- **a missing input is unresolved, never a pass and never a fail** (constitution
  Principle I). An unreadable `is_global` leaves the document unresolved even when another
  row is a global, because the rows that could not be read are part of the answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from swreview.checks.rms import RULES, evaluable
from swreview.checks.rms.equations import document_equations, evaluate_equations
from swreview.checks.rms.results import RuleResult
from swreview.checks.rms_types import load_table
from swreview.ir.models import Equation, EvidencePackage, Gap
from tests.support.features import (
    EquationSpec,
    InstanceSpec,
    PartSpec,
    equation,
    feature,
    folder,
    rms_package,
)

DOCUMENT = "doc:2"
OTHER_DOCUMENT = "doc:3"
CORE = load_table().groups[2]

EQUATION_RULE_IDS = tuple(rule.id for rule in evaluable() if rule.scope == "equations")
GLOBALS_PRESENT = "rms.params.global_variables_present"
DIMENSIONS_DRIVEN = "rms.params.dimensions_driven_by_equations"


# --- helpers ----------------------------------------------------------------------


def build(
    equations: Sequence[EquationSpec] = (),
    *,
    instances: Sequence[InstanceSpec] | None = None,
    gaps: Sequence[Gap] = (),
) -> EvidencePackage:
    """A one-part package carrying `equations`; its tree is read unless a test says so."""
    return rms_package(
        parts=[
            PartSpec(
                document_id=DOCUMENT,
                name="housing",
                equations=equations,
                instances=instances,
            )
        ],
        gaps=gaps,
    )


def rows(package: EvidencePackage, document_id: str = DOCUMENT) -> list[Equation]:
    return [row for row in package.equations if row.document_id == document_id]


def equations_gap(entity_id: str | None = DOCUMENT) -> Gap:
    """The gap `EquationDumper` records when the equation manager could not be read."""
    return Gap(
        kind="not_extracted",
        entity_kind="equations",
        entity_id=entity_id,
        reason="The equation manager of housing.SLDPRT was not read.",
        error=None,
    )


def run(rule_id: str, equations: Sequence[EquationSpec] = (), **kwargs: Any) -> list[RuleResult]:
    """Evaluate one rule through the registry, which also pins that it is bound."""
    rule = RULES[rule_id]
    assert rule.fn is not None, f"{rule_id} has no evaluator"
    package = build(equations, **kwargs)
    return rule.fn(document_equations(DOCUMENT, rows(package), package))


def evaluate(equations: Sequence[EquationSpec] = (), **kwargs: Any) -> list[RuleResult]:
    """Every equation rule over the document, as `check_rms_equations` will call it."""
    package = build(equations, **kwargs)
    return evaluate_equations(DOCUMENT, rows(package), package)


def by_outcome(results: Sequence[RuleResult]) -> dict[str, RuleResult]:
    """The results keyed by outcome, refusing two results in one bucket."""
    keyed: dict[str, RuleResult] = {}
    for result in results:
        assert result.outcome not in keyed, (
            f"{result.rule_id} returned two {result.outcome} results for one document"
        )
        assert result.document_id == DOCUMENT
        assert result.subjects == [], "the subject of an equation rule is the document"
        keyed[result.outcome] = result
    return keyed


GLOBAL = equation('"width" = 40', is_global=True)
DIMENSION = equation('"D1@Sketch1" = "width"')
UNREADABLE = equation('"depth" = 20', is_global=None)


# --- rms.params.global_variables_present ------------------------------------------


class TestGlobalVariablesPresent:
    RULE = GLOBALS_PRESENT

    def test_one_global_variable_passes(self) -> None:
        keyed = by_outcome(run(self.RULE, [GLOBAL, DIMENSION]))

        assert list(keyed) == ["pass"]
        assert keyed["pass"].result is None

    def test_no_equations_at_all_fails(self) -> None:
        keyed = by_outcome(run(self.RULE))

        assert list(keyed) == ["fail"]
        result = keyed["fail"].result
        assert result is not None
        assert result.check == self.RULE
        assert result.status == "demonstrated"
        assert result.severity == "medium"
        assert result.requirement == RULES[self.RULE].statement
        assert "no equations" in result.observed
        assert result.inputs == []

    def test_equations_without_a_global_fail_and_name_them(self) -> None:
        keyed = by_outcome(run(self.RULE, [DIMENSION, equation('"D2@Sketch1" = 12')]))

        assert list(keyed) == ["fail"]
        result = keyed["fail"].result
        assert result is not None
        assert "2 equation(s)" in result.observed
        assert "D1@Sketch1" in result.observed
        assert "D2@Sketch1" in result.observed
        assert result.recommended_action

    @pytest.mark.parametrize("entity_id", [DOCUMENT, None])
    def test_the_equations_gap_is_unresolved(self, entity_id: str | None) -> None:
        # The gap names this document, or names nothing at all when no equation manager
        # was read (`--equations off`); either way the rows are not evidence of absence.
        keyed = by_outcome(run(self.RULE, gaps=[equations_gap(entity_id)]))

        assert list(keyed) == ["unresolved"]
        assert keyed["unresolved"].reason == equations_gap().reason

    def test_a_gap_naming_another_document_does_not_speak_for_this_one(self) -> None:
        keyed = by_outcome(run(self.RULE, [GLOBAL], gaps=[equations_gap(OTHER_DOCUMENT)]))

        assert list(keyed) == ["pass"]

    def test_an_unreadable_is_global_is_unresolved_even_beside_a_global(self) -> None:
        # Principle I: a row whose `GlobalVariable(i)` threw is part of the answer, so the
        # document is unresolved rather than passing on the row that was readable.
        keyed = by_outcome(run(self.RULE, [GLOBAL, UNREADABLE]))

        assert list(keyed) == ["unresolved"]
        reason = keyed["unresolved"].reason
        assert reason is not None
        assert '"depth" = 20' in reason
        assert "is_global" in reason

    def test_an_unreadable_is_global_is_unresolved_rather_than_failing(self) -> None:
        keyed = by_outcome(run(self.RULE, [DIMENSION, UNREADABLE]))

        assert list(keyed) == ["unresolved"]

    def test_the_gap_and_the_unreadable_row_are_named_in_one_reason(self) -> None:
        keyed = by_outcome(run(self.RULE, [UNREADABLE], gaps=[equations_gap()]))

        assert list(keyed) == ["unresolved"]
        reason = keyed["unresolved"].reason
        assert reason is not None
        assert equations_gap().reason in reason
        assert '"depth" = 20' in reason


# --- rms.params.dimensions_driven_by_equations ------------------------------------


class TestDimensionsDrivenByEquations:
    RULE = DIMENSIONS_DRIVEN

    def test_a_dimension_driven_by_an_equation_passes(self) -> None:
        keyed = by_outcome(run(self.RULE, [GLOBAL, DIMENSION]))

        assert list(keyed) == ["pass"]
        assert keyed["pass"].result is None

    def test_globals_alone_warn(self) -> None:
        keyed = by_outcome(run(self.RULE, [GLOBAL, equation('"depth" = 20', is_global=True)]))

        assert list(keyed) == ["warn"]
        result = keyed["warn"].result
        assert result is not None
        assert result.check == self.RULE
        assert result.status == "suspected"
        assert result.severity == "low"
        assert result.requirement == RULES[self.RULE].statement
        assert "2 equation(s)" in result.observed
        assert "width" in result.observed
        assert result.recommended_action

    def test_no_equations_at_all_warn(self) -> None:
        keyed = by_outcome(run(self.RULE))

        assert list(keyed) == ["warn"]
        assert keyed["warn"].result is not None
        assert "no equations" in keyed["warn"].result.observed

    @pytest.mark.parametrize("entity_id", [DOCUMENT, None])
    def test_the_equations_gap_is_unresolved(self, entity_id: str | None) -> None:
        keyed = by_outcome(run(self.RULE, gaps=[equations_gap(entity_id)]))

        assert list(keyed) == ["unresolved"]
        assert keyed["unresolved"].reason == equations_gap().reason

    def test_an_unreadable_is_global_is_unresolved_even_beside_a_dimension(self) -> None:
        keyed = by_outcome(run(self.RULE, [DIMENSION, UNREADABLE]))

        assert list(keyed) == ["unresolved"]
        reason = keyed["unresolved"].reason
        assert reason is not None
        assert '"depth" = 20' in reason


# --- evaluate_equations -----------------------------------------------------------


class TestEvaluateEquations:
    def test_every_equation_rule_is_reported_once_in_contract_order(self) -> None:
        results = evaluate([GLOBAL, DIMENSION])

        assert [result.rule_id for result in results] == list(EQUATION_RULE_IDS)
        assert {result.outcome for result in results} == {"pass"}

    def test_a_failing_and_a_warning_rule_are_reported_side_by_side(self) -> None:
        keyed = {result.rule_id: result for result in evaluate()}

        assert keyed[GLOBALS_PRESENT].outcome == "fail"
        assert keyed[DIMENSIONS_DRIVEN].outcome == "warn"

    def test_a_document_with_no_rows_and_no_resolved_instance_is_unresolved(self) -> None:
        results = evaluate(
            [GLOBAL, DIMENSION],
            instances=[InstanceSpec("housing-1", suppression="lightweight")],
        )

        assert [result.rule_id for result in results] == list(EQUATION_RULE_IDS)
        assert {result.outcome for result in results} == {"unresolved"}
        assert {result.reason for result in results} == {
            "component housing-1 lightweight; tree not read"
        }
        assert all(result.subjects == [] for result in results)

    @pytest.mark.parametrize("entity_id", [DOCUMENT, None])
    def test_a_resolved_instance_whose_tree_was_not_read_is_unresolved(
        self, entity_id: str | None
    ) -> None:
        # The other half of "Unresolved part documents": the equation rules read the same
        # document as the part rules, and must not report "no global variable" about a
        # document nobody opened.
        results = evaluate(
            gaps=[
                Gap(
                    kind="not_extracted",
                    entity_kind="feature_tree_unavailable",
                    entity_id=entity_id,
                    reason="The feature tree of housing.SLDPRT was not read: the walk failed.",
                    error=None,
                )
            ]
        )

        assert {result.outcome for result in results} == {"unresolved"}
        assert {result.reason for result in results} == {
            "The feature tree of housing.SLDPRT was not read: the walk failed."
        }

    def test_a_read_tree_with_no_equations_is_graded(self) -> None:
        # A part with no equations at all is a real answer, not a missing one.
        package = rms_package(
            parts=[
                PartSpec(
                    document_id=DOCUMENT,
                    name="housing",
                    features=[folder(CORE, feature("Boss1", "Extrusion"))],
                )
            ]
        )
        results = evaluate_equations(DOCUMENT, rows(package), package)

        assert {result.outcome for result in results} == {"fail", "warn"}

    def test_equations_of_another_document_are_refused(self) -> None:
        package = build([GLOBAL])

        with pytest.raises(ValueError, match=OTHER_DOCUMENT):
            evaluate_equations(OTHER_DOCUMENT, rows(package), package)

    def test_only_this_documents_equations_are_read(self) -> None:
        package = rms_package(
            parts=[
                PartSpec(document_id=DOCUMENT, name="housing", equations=[DIMENSION]),
                PartSpec(document_id=OTHER_DOCUMENT, name="cover", equations=[GLOBAL]),
            ]
        )
        keyed = {
            result.rule_id: result
            for result in evaluate_equations(DOCUMENT, rows(package), package)
        }

        assert keyed[GLOBALS_PRESENT].outcome == "fail"
        assert keyed[DIMENSIONS_DRIVEN].outcome == "pass"

    def test_no_part_scope_rule_is_reported(self) -> None:
        results = evaluate([GLOBAL, DIMENSION])

        assert {RULES[result.rule_id].scope for result in results} == {"equations"}
