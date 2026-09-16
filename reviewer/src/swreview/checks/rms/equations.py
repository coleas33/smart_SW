"""The 2 equation-scope rule evaluators, and `evaluate_equations` (T040).

One pure function per rule of the equation-scope table in
`specs/003-resilient-modeling/contracts/rules.md`, each decorated `@bind("<rule id>")` and
returning `list[RuleResult]`, exactly as `part.py` does for the part scope.

Both rules grade *the document*, not a row of its equation manager, and that is what makes
this module short where `part.py` is long: there is one subject, so there is exactly one
outcome, and `subjects` stays empty while the evidence a reader needs - which equation was
unreadable, which left sides were seen - lives in the reason and the observed text.

Three conventions hold across both rules, each of them one of the contract's normative
paragraphs rather than a style choice:

- **the same two unresolved conditions.** The contract gives both rules "unresolved when
  the `equations` gap is recorded or any `is_global` is null", so `_unresolved_reason`
  decides it once. A row whose `GlobalVariable(i)` could not be read is part of the answer:
  the document is unresolved even when another row *is* a global, because a pass would be
  asserted over data nobody read (constitution Principle I).
- **no equations is an answer, not a gap.** A read equation manager that holds nothing
  fails `rms.params.global_variables_present` and warns on
  `rms.params.dimensions_driven_by_equations`; only a recorded gap turns that into
  unresolved. Neither rule ever skips.
- **a document whose tree was never read is unresolved for these rules too**
  (`rules.md`, "Unresolved part documents"). `evaluate_equations` asks `part.tree_not_read`
  - the one reading of that section - rather than grading an equation list the extractor
  never had a document open to fill.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from swreview.checks.rms.part import document_gap, tree_not_read
from swreview.checks.rms.registry import RULES, RmsRule, bind, evaluable
from swreview.checks.rms.results import RuleResult, finding, passed, unresolved
from swreview.ir.models import Equation, EvidencePackage

__all__ = [
    "DIMENSION_MARKER",
    "DocumentEquations",
    "dimensions_driven_by_equations",
    "document_equations",
    "evaluate_equations",
    "global_variables_present",
]

SCOPE = "equations"

GLOBAL_VARIABLES_PRESENT = "rms.params.global_variables_present"
DIMENSIONS_DRIVEN_BY_EQUATIONS = "rms.params.dimensions_driven_by_equations"

DIMENSION_MARKER = "@"
"""What the left side of a driven dimension carries and a global variable's does not: a
dimension is named `D1@Sketch1` - the dimension in the feature or sketch that owns it -
where a global variable is a bare name. `is_global` says which rows the equation manager
calls globals; this says which rows drive geometry (research R2)."""


# --- the equation manager a rule reads --------------------------------------------


@dataclass(frozen=True)
class DocumentEquations:
    """One part document's equation manager, with what both rules would otherwise redo.

    Built once per document by `document_equations` and handed to each rule, so a rule's
    signature says exactly what a rule may read.
    """

    document_id: str
    rows: tuple[Equation, ...]
    """The document's equations in `index` order."""

    package: EvidencePackage
    gap_reason: str | None
    """The reason of this document's `equations` gap, or `None` when none is recorded."""

    @property
    def unreadable(self) -> tuple[Equation, ...]:
        """The rows whose `is_global` could not be read (`IEquationMgr.GlobalVariable`)."""
        return tuple(row for row in self.rows if row.is_global is None)


def document_equations(
    document_id: str, equations: Sequence[Equation], package: EvidencePackage
) -> DocumentEquations:
    """Index one part document's equations for the rules; `equations` are that document's."""
    rows = tuple(sorted(equations, key=lambda row: row.index))
    for row in rows:
        if row.document_id != document_id:
            raise ValueError(
                f"equation {row.index} belongs to {row.document_id}, not to {document_id}; "
                "an equation rule evaluates one document's equation manager"
            )
    return DocumentEquations(
        document_id=document_id,
        rows=rows,
        package=package,
        gap_reason=document_gap(package, SCOPE, document_id),
    )


# --- the shape both rules share ---------------------------------------------------


def _unresolved_reason(manager: DocumentEquations) -> str | None:
    """Why this manager is not evidence, or `None` when it is.

    Both halves of the contract's condition at once, named in one reason: the gap the
    extractor recorded, then every row whose `is_global` it could not read.
    """
    reasons: list[str] = []
    if manager.gap_reason is not None:
        reasons.append(manager.gap_reason)
    reasons.extend(
        f"equation {row.index} {row.text}: is_global unreadable" for row in manager.unreadable
    )
    return "; ".join(reasons) if reasons else None


def _graded(
    rule: RmsRule,
    manager: DocumentEquations,
    *,
    matching: Sequence[Equation],
    missing: str,
    recommended_action: str,
) -> list[RuleResult]:
    """The one outcome of a document-scope equation rule.

    `matching` are the rows that satisfy the rule; one of them is the whole pass, because
    both statements read "at least one". `missing` completes the observed sentence when
    there is none, and the left sides of the rows that were read follow it as evidence.
    """
    reason = _unresolved_reason(manager)
    if reason is not None:
        return [unresolved(rule, manager.document_id, reason)]
    if matching:
        return [passed(rule, manager.document_id)]
    if manager.rows:
        left_sides = ", ".join(row.lhs for row in manager.rows)
        observed = f"none of the {len(manager.rows)} equation(s) {missing}: {left_sides}"
    else:
        observed = "the equation manager holds no equations"
    return [
        finding(
            rule,
            manager.document_id,
            (),
            observed=observed,
            recommended_action=recommended_action,
        )
    ]


# --- rms.params.global_variables_present ------------------------------------------


@bind(GLOBAL_VARIABLES_PRESENT)
def global_variables_present(manager: DocumentEquations) -> list[RuleResult]:
    """At least one global variable exists. Never skips: an empty manager is an answer."""
    return _graded(
        RULES[GLOBAL_VARIABLES_PRESENT],
        manager,
        matching=[row for row in manager.rows if row.is_global],
        missing="is a global variable",
        recommended_action=(
            "Name the part's driving values as global variables in the equation manager, "
            "and drive the dimensions from them."
        ),
    )


# --- rms.params.dimensions_driven_by_equations ------------------------------------


@bind(DIMENSIONS_DRIVEN_BY_EQUATIONS)
def dimensions_driven_by_equations(manager: DocumentEquations) -> list[RuleResult]:
    """At least one dimension is driven by an equation. Never skips."""
    return _graded(
        RULES[DIMENSIONS_DRIVEN_BY_EQUATIONS],
        manager,
        matching=[row for row in manager.rows if DIMENSION_MARKER in row.lhs],
        missing=(
            f"drives a dimension (a driven left side names one, as in D1{DIMENSION_MARKER}Sketch1)"
        ),
        recommended_action=(
            "Drive the dimensions that carry the design intent from the global variables."
        ),
    )


# --- the whole document -----------------------------------------------------------


def evaluate_equations(
    document_id: str, equations: Sequence[Equation], package: EvidencePackage
) -> list[RuleResult]:
    """Every equation-scope rule over one part document, in the contract's order.

    A document whose tree was never read - no `features[]` rows and no resolved component
    instance, or a recorded `feature_tree_unavailable` gap - is unresolved for both rules,
    naming what `part.py` names: the equation rules read the same document, and "no global
    variable" about a document nobody opened is not a finding (`rules.md`, "Unresolved
    part documents").
    """
    manager = document_equations(document_id, equations, package)
    rows = [row for row in package.features if row.document_id == document_id]
    not_read = tree_not_read(document_id, rows, package)
    if not_read is not None:
        return [
            unresolved(rule, document_id, not_read)
            for rule in evaluable()
            if rule.scope == SCOPE
        ]

    results: list[RuleResult] = []
    for rule in evaluable():
        if rule.scope != SCOPE:
            continue
        if rule.fn is None:  # pragma: no cover - this module binds every equation rule
            raise RuntimeError(f"{rule.id} has no evaluator")
        results.extend(rule.fn(manager))
    return results
