"""The one catalogue of standards checks: `contracts/rules.md`, typed out.

Sixteen ids - seven assembly-scope, four part-scope, four drawing-scope and one
document-scope - each with the scope it is evaluated in, the macro's severity, and the
statement a finding reports as its requirement. The evaluators, the report layer, the check
tool, the command line and the tab read this catalogue and never a second list.

Every one of the sixteen is **evaluable**: it carries a severity from this family's
vocabulary and an evaluator bound by `checks/standards/{assembly,part,drawing,document}.py`.
This family has no coverage-only check, which is a statement about the catalogue rather than
about the machinery: the row type admits one (`checks/rules/registry.py`), and the invariant
that a rule carries either a severity or a coverage reason holds here with the severity half
taken every time.

**`standards.release` is not a seventeenth check.** It is the family's summary coverage item
(`STANDARDS_FAMILY.summary_check`, the standards counterpart of the rms family's
`modeling.resilience`): one aggregated `CoverageItem` per run carrying the verdict state and
the counts per bucket, excluded from the sixteen-row `checks[]` array and from every waiver.
It is deliberately absent from `RULES`, so no code path can grade a document against it.

**Out of scope is not an outcome and not a row here.** A check whose scope does not match a
graded document's kind is written as an `out_of_scope` `CoverageItem` by
`checks/standards/report.py`, which walks (every check) x (every graded document) after the
results are aggregated. Nothing in this module or in `checks/rules/` knows about that loop.

**What this family is, as facts.** `STANDARDS_FAMILY` is this catalogue's `CheckFamily`: the
summary check id, the scope and severity vocabularies, the severity map, the high-severity
ids and the waiver labels that `checks/rules/` reads instead of hard-coding them. It lives
here, beside the catalogue it describes, because everything on it is a statement about these
sixteen checks.

The row type, the binder and the three partitions come from `checks/rules/registry.py`: a
rule row is the same shape in every family, and only the rows themselves are this one's.
"""

from __future__ import annotations

from typing import Literal

from swreview.checks.rules.family import CheckFamily
from swreview.checks.rules.registry import (
    Rule,
    RuleFn,
    binder,
    catalogue,
)
from swreview.checks.rules.registry import by_scope as _by_scope
from swreview.checks.rules.registry import evaluable as _evaluable

__all__ = [
    "CHECK_TOOL",
    "HIGH_SEVERITY_CHECKS",
    "NO_EVALUATOR",
    "RULES",
    "RULES_VERSION",
    "STANDARDS_FAMILY",
    "RuleFn",
    "RuleScope",
    "RuleSeverity",
    "StandardsRule",
    "bind",
    "by_scope",
    "evaluable",
    "rules_in",
]

RuleScope = Literal["assembly", "part", "drawing", "document"]
"""What a check is evaluated over: one graded document of that kind, or - for the
document scope - a graded document of any of the three kinds."""

RuleSeverity = Literal["error", "warning"]
"""The macro's own grading, mapped to a `Finding` status and severity by
`STANDARDS_FAMILY.status_by_severity`: `error` to `demonstrated`, `warning` to `suspected`.
Only `error` checks are waivable (`contracts/rules.md`, "Waivable checks"), which is that
map read for `WAIVABLE_STATUS` rather than a second fact."""

StandardsRule = Rule
"""One check of `contracts/rules.md` (data-model section 3).

The family-neutral row of `checks/rules/registry.py` under this family's name: `scope` is a
`RuleScope` and `severity` a `RuleSeverity` for every row below. Mutable in exactly one
respect - `fn` is filled in by `bind` after construction, because the evaluator modules
import this one and not the other way round.
"""

RULES_VERSION = "1"
"""This catalogue's version: the standards family's `Calculation.function_version`.

These checks read a model and produce no calculation, so their findings have nowhere to
carry one; feature 005's carry-over key reads this instead, because a verdict reused from an
earlier run is a claim that **this** implementation would conclude the same thing.

**Bump it whenever a check's verdict over an unchanged document could change**: a check
added or removed, a severity changed, an evaluator's condition edited. Nothing detects an
unbumped change, so the bump is part of editing a check rather than an afterthought.
"""

CHECK_TOOL = "check_standards"
"""The one review-only tool the whole run is dispatched as (FR-035).

The rms family has one tool per scope because its three scopes read different evidence and
are selectable from the command line. Here all sixteen checks run on every run and the
document kinds decide which apply, so there is one call to record and every scope names it.
"""

HIGH_SEVERITY_CHECKS: frozenset[str] = frozenset(
    {
        "standards.assembly.mate_references",
        "standards.assembly.rebuild_errors",
        "standards.part.rebuild_errors",
        "standards.drawing.dimensions_not_overridden",
    }
)
"""The four data-integrity checks reported `high` rather than `medium` (data-model section
3): a lost mate reference, a rebuild error either side, and an overridden dimension each
mean the model or the drawing is stating something that is not true of the geometry, where
the other error checks describe a document that is correct and not yet release-ready."""

RULES: dict[str, StandardsRule] = catalogue(
    # Assembly scope: one evaluation per assembly document the traversal reaches - the root
    # assembly and every sub-assembly, not only the root (difference v).
    StandardsRule(
        id="standards.assembly.not_exploded",
        scope="assembly",
        severity="error",
        statement="An assembly is not left in an exploded state.",
    ),
    StandardsRule(
        id="standards.assembly.rebuild_errors",
        scope="assembly",
        severity="error",
        statement="An assembly carries no rebuild errors.",
    ),
    StandardsRule(
        id="standards.assembly.mate_references",
        scope="assembly",
        severity="error",
        statement="No mate has lost a reference.",
    ),
    StandardsRule(
        id="standards.assembly.one_fixed",
        scope="assembly",
        severity="error",
        statement="At most one component of an assembly is fixed.",
    ),
    StandardsRule(
        id="standards.assembly.fully_mated",
        scope="assembly",
        severity="error",
        statement=(
            "Every under-constrained component is fully mated, or carries the minimum "
            "mates its library class requires."
        ),
    ),
    StandardsRule(
        id="standards.assembly.not_transparent",
        scope="assembly",
        severity="error",
        statement="No component is left in a transparent state.",
    ),
    StandardsRule(
        id="standards.assembly.not_hidden",
        scope="assembly",
        severity="error",
        statement="No component is left hidden.",
    ),
    # Part scope: one evaluation per part document the traversal reaches.
    StandardsRule(
        id="standards.part.sketches_fully_defined",
        scope="part",
        severity="error",
        statement="Every sketch is fully defined.",
    ),
    StandardsRule(
        id="standards.part.rebuild_errors",
        scope="part",
        severity="error",
        statement="A part carries no rebuild errors.",
    ),
    StandardsRule(
        id="standards.part.material_assigned",
        scope="part",
        severity="error",
        statement=(
            "A part has a material assigned, or a deliberately overridden mass - and not both."
        ),
    ),
    StandardsRule(
        id="standards.part.cut_list_excluded",
        scope="part",
        severity="error",
        statement="Every cut-list item is excluded from the cut list.",
    ),
    # Drawing scope: one evaluation per drawing document, over its native sheets.
    StandardsRule(
        id="standards.drawing.dimensions_not_overridden",
        scope="drawing",
        severity="error",
        statement="No display dimension carries a manual override.",
    ),
    StandardsRule(
        id="standards.drawing.annotations_not_dangling",
        scope="drawing",
        severity="error",
        statement="No annotation is dangling.",
    ),
    StandardsRule(
        id="standards.drawing.revision_matches",
        scope="drawing",
        severity="warning",
        statement=(
            "The revision table, the drawing's revision property and every referenced "
            "model's revision property agree."
        ),
    ),
    StandardsRule(
        id="standards.drawing.no_itar_statement",
        scope="drawing",
        severity="warning",
        statement="No export-control statement appears in the drawing's notes.",
    ),
    # Document scope: one evaluation per graded document, whatever its kind.
    StandardsRule(
        id="standards.document.data_card_complete",
        scope="document",
        severity="error",
        statement=(
            "The data card is complete on every document whose file name follows the "
            "part-number convention."
        ),
    ),
)
"""The sixteen checks, in contract order: assembly, part, drawing, document."""

STANDARDS_FAMILY = CheckFamily(
    name="standards",
    summary_check="standards.release",
    rules_version=RULES_VERSION,
    scopes=frozenset({"assembly", "part", "drawing", "document"}),
    tools=dict.fromkeys(("assembly", "part", "drawing", "document"), CHECK_TOOL),
    check_file_family="standards",
    severities=frozenset({"error", "warning"}),
    status_by_severity={
        "error": ("demonstrated", "medium"),
        "warning": ("suspected", "low"),
    },
    high_severity=HIGH_SEVERITY_CHECKS,
    waiver_labels={
        "unknown": "invalid (unknown check)",
        "warning": "invalid (warning check)",
    },
)
"""This family, as the facts `checks/rules/` reads instead of hard-coding them.

`summary_check` is the one aggregated coverage item that carries the release verdict for a
run; it is never one of the sixteen and no document is graded against it.

`waiver_labels` are the lines `swreview exceptions accept-standards` prints for an id it
cannot accept (`contracts/cli.md`), keyed by the reason: `unknown` for an id the catalogue
does not hold, and the check's own **severity** for a check whose severity is not waivable.
This catalogue has no coverage-only check, so unlike the rms family it needs no bucket
labels - an id that is not one of the sixteen is `unknown` and nothing else.
"""

bind = binder(RULES, "contracts/rules.md")
"""Register a check's evaluator, as a decorator in that scope's evaluator module.

Bound late rather than passed to `StandardsRule` so that the evaluator modules import this
one and not the reverse; importing `swreview.checks.standards`, which imports all four of
them, is what completes the `fn` half of the invariant.

Raises `KeyError` for an unknown id, and `ValueError` for a check that already has an
evaluator.
"""


def by_scope() -> dict[str, tuple[StandardsRule, ...]]:
    """The catalogue partitioned by scope, in contract order; every scope is a key."""
    return _by_scope(RULES, STANDARDS_FAMILY.scopes)


def evaluable() -> tuple[StandardsRule, ...]:
    """The checks that are dispatched, in contract order - here, all sixteen.

    Read from `coverage`, not from `fn`, so that an evaluator module can ask which ids it
    owes a function while it is still binding them.
    """
    return _evaluable(RULES)


NO_EVALUATOR = (
    "{ids} in scope {scope!r} carr{y} no evaluator; importing swreview.checks.standards is "
    "what binds every check of the catalogue, and a scope entry point that dispatched the "
    "rest would grade a document against fewer checks than the contract holds"
)


def rules_in(scope: str) -> tuple[StandardsRule, ...]:
    """The checks of one scope, in contract order, with every evaluator bound.

    What the four scope entry points of `checks/standards/` walk. It is here rather than
    once per evaluator module because "the checks of this scope, and each of them has a
    function to call" was four copies of one invariant, and a copy of an invariant is the
    one that goes out of date (constitution Principle V).

    Raises `KeyError` for a scope this family does not have, and `ValueError` - **before
    any check of the scope is dispatched**, rather than part of the way through it - when
    one of them was never bound.
    """
    rules = by_scope()[scope]
    unbound = [rule.id for rule in rules if rule.fn is None]
    if unbound:
        raise ValueError(
            NO_EVALUATOR.format(
                ids=", ".join(unbound), scope=scope, y="y" if len(unbound) == 1 else "ies"
            )
        )
    return rules
