"""The one catalogue of Resilient Modeling rules: `contracts/rules.md`, typed out.

34 ids, each with the scope it is evaluated in, the method's severity, the statement a
finding reports as its requirement, and either an evaluator or a reason it cannot be
evaluated at all. The checklist, the tools, the CLI and the docs read this registry and
never a second list (plan.md, design point 3).

Two kinds of rule live here and the difference is the invariant of data-model section 2:

- an **evaluable** rule carries a `severity` (`fail` or `warn`) and an evaluator bound by
  `checks/rms/{part,assembly,equations}.py`; it is dispatched per subject document and
  returns one `RuleResult` per outcome it reaches;
- a **coverage-only** rule carries a `(bucket, reason)` pair instead, and no severity and
  no function: the data it needs is not extracted, or the judgement is not decidable from
  extracted data. It is never dispatched and is emitted once per review as a `CoverageItem`
  in that bucket, so a reader sees that the rule was not silently dropped.

`fn` is present exactly when `severity` is present exactly when `coverage` is null. The
severity half of that invariant is enforced on construction; the `fn` half is completed by
`bind`, which the three evaluator modules apply when `swreview.checks.rms` is imported.

**What this family is, as facts.** `RMS_FAMILY` is this catalogue's `CheckFamily`: the
summary check id, the scope and severity vocabularies, the severity map, the high-severity
ids and the waiver labels that `checks/rules/` reads instead of hard-coding them
(`specs/006-standards-check/research.md` R7). It lives here, beside the catalogue it
describes, because everything on it is a statement about these 34 rules; the rest of the
family reads it from here rather than restating any of it.

The row type, the binder and the three partitions come from `checks/rules/registry.py`: a
rule row is the same shape in every family, and only the rows themselves are this one's.
"""

from __future__ import annotations

from typing import Literal

from swreview.checks.rules.family import CheckFamily
from swreview.checks.rules.registry import (
    Rule,
    RuleCoverageBucket,
    RuleFn,
    binder,
    catalogue,
)
from swreview.checks.rules.registry import by_scope as _by_scope
from swreview.checks.rules.registry import coverage_only as _coverage_only
from swreview.checks.rules.registry import evaluable as _evaluable

__all__ = [
    "HIGH_SEVERITY_RULES",
    "HIGH_SEVERITY_RULE_PREFIX",
    "RMS_FAMILY",
    "RULES",
    "RULES_VERSION",
    "RmsRule",
    "RuleCoverageBucket",
    "RuleFn",
    "RuleScope",
    "RuleSeverity",
    "bind",
    "by_scope",
    "coverage_only",
    "evaluable",
]

RuleScope = Literal["part", "assembly", "equations", "drawing", "advisory"]
"""What a rule is evaluated over: a part document, the root assembly, a part's equations,
or - for the rules this version does not evaluate - drawings and judgement calls."""

RuleSeverity = Literal["fail", "warn"]
"""The method's own grading, mapped to a `Finding` status and severity by
`RMS_FAMILY.status_by_severity` (data-model section 2): `fail` to `demonstrated`, `warn` to
`suspected`. Only `fail` rules are waivable (`contracts/rules.md`, "Waivable rules")."""

RmsRule = Rule
"""One rule of `contracts/rules.md` (data-model section 2).

The family-neutral row of `checks/rules/registry.py` under this family's name: `scope` is a
`RuleScope` and `severity` a `RuleSeverity` for every row below. Mutable in exactly one
respect - `fn` is filled in by `bind` after construction, because the evaluator modules
import this one and not the other way round.
"""

RULES_VERSION = "1"
"""This catalogue's version: the rms family's `Calculation.function_version`.

The deterministic checks each carry a module-level `FUNCTION_VERSION` (`checks/fit.py`,
`checks/fastener.py` and the rest) that rides into every finding's `Calculation` and says
which implementation produced the number. The rms rules produce no calculation
(`checks/rules/results.py`), so their findings have nowhere to carry one - and feature 005's
carry-over key needs exactly that fact, because a verdict reused from an earlier run is a
claim that **this** implementation would conclude the same thing (guard 5,
`carry_over.carry_over_key`).

**Bump it whenever a rule's verdict over an unchanged tree could change**: a rule added or
removed, a severity changed, an evaluator's condition edited. Nothing detects an unbumped
change, which is the honest cost of there being no calculation to version; the direction of
the error is a carried verdict, so the bump is part of editing a rule, not an afterthought.
"""

HIGH_SEVERITY_RULE_PREFIX = "rms.refs."
HIGH_SEVERITY_RULES: frozenset[str] = frozenset({"rms.sketches.not_over_defined"})
"""The `fail` rules reported `high` rather than `medium` (data-model section 2): a
reference that points the wrong way and an over-defined sketch both break a rebuild,
where the other `fail` rules describe a tree that works but will not survive editing.

The prefix is the rule and not a shorthand: every `rms.refs.*` rule is one of them, and a
future one is high without anybody remembering to list it. `RMS_FAMILY.high_severity` is
that rule read over this catalogue once, because a family carries the ids and not the test
that produced them - an id set can be printed and asserted, where a predicate can only be
called.
"""

RULES: dict[str, RmsRule] = catalogue(
    # Part scope: one evaluation per part document.
    RmsRule(
        id="rms.folders.present",
        scope="part",
        severity="warn",
        statement="Every one of the six groups exists as a folder.",
    ),
    RmsRule(
        id="rms.folders.ordered",
        scope="part",
        severity="fail",
        statement=(
            "Group folders appear once each, in the order Reference, Construction, Core, "
            "Detail, Modify, Quarantine."
        ),
    ),
    RmsRule(
        id="rms.grouping.all_features_in_a_group",
        scope="part",
        severity="fail",
        statement="Every content feature lives inside a group.",
    ),
    RmsRule(
        id="rms.groups.no_solids_in_ref_or_construction",
        scope="part",
        severity="fail",
        statement=(
            "Reference and Construction contain no material (solids, cuts, holes; "
            "ambiguous counts as material)."
        ),
    ),
    RmsRule(
        id="rms.core.shell_last",
        scope="part",
        severity="fail",
        statement="The shell is the last feature in Core.",
    ),
    RmsRule(
        id="rms.detail.holes_last",
        scope="part",
        severity="warn",
        statement="Holes are the trailing block of Detail (sketches ignored).",
    ),
    RmsRule(
        id="rms.modify.transform_before_replicate",
        scope="part",
        severity="warn",
        statement="Drafts precede patterns in Modify.",
    ),
    RmsRule(
        id="rms.quarantine.chamfers_before_fillets",
        scope="part",
        severity="fail",
        statement="Chamfers precede fillets in Quarantine.",
    ),
    RmsRule(
        id="rms.quarantine.largest_fillet_first",
        scope="part",
        severity="fail",
        statement="Fillet radii in Quarantine are non-increasing.",
    ),
    RmsRule(
        id="rms.quarantine.only_fillets_and_chamfers",
        scope="part",
        severity="fail",
        statement="Quarantine holds only fillets and chamfers.",
    ),
    RmsRule(
        id="rms.refs.direction",
        scope="part",
        severity="fail",
        statement=(
            "No feature depends on a feature in a later group (a dependent lives in the "
            "same or a later group than what it depends on)."
        ),
    ),
    RmsRule(
        id="rms.refs.quarantine_has_no_children",
        scope="part",
        severity="fail",
        statement="Nothing depends on a Quarantine feature.",
    ),
    RmsRule(
        id="rms.detail.no_internal_references",
        scope="part",
        severity="fail",
        statement=(
            "Detail features do not depend on other Detail features, except (a) a sketch "
            "consumed by exactly one feature, and (b) a pair of features sharing the same "
            "derived subfolder inside Detail (the coupled-pair exception)."
        ),
    ),
    RmsRule(
        id="rms.intent.every_feature_described",
        scope="part",
        severity="fail",
        statement="Every content feature carries a description.",
    ),
    RmsRule(
        id="rms.sketches.fully_defined",
        scope="part",
        severity="fail",
        statement="Every sketch is fully defined. Only under_defined fails.",
    ),
    RmsRule(
        id="rms.sketches.not_over_defined",
        scope="part",
        severity="fail",
        statement=(
            "No sketch is over defined or in solver error. Only over_defined and "
            "solver_error fail."
        ),
    ),
    RmsRule(
        id="rms.sketches.one_sketch_per_feature",
        scope="part",
        severity="fail",
        statement="No sketch is consumed by more than one feature.",
    ),
    RmsRule(
        id="rms.detail.individually_suppressible",
        scope="part",
        severity="fail",
        statement="Each Detail feature can be suppressed alone without rebuild errors.",
    ),
    # Equation scope: per part document.
    RmsRule(
        id="rms.params.global_variables_present",
        scope="equations",
        severity="fail",
        statement="At least one global variable exists.",
    ),
    RmsRule(
        id="rms.params.dimensions_driven_by_equations",
        scope="equations",
        severity="warn",
        statement="At least one dimension is driven by an equation.",
    ),
    # Assembly scope: the root assembly document only.
    RmsRule(
        id="rms.assembly.mates_to_reference_geometry",
        scope="assembly",
        severity="fail",
        statement=(
            "Mates reference planes, axes, points, or coordinate systems, not faces, "
            "edges, or vertices."
        ),
    ),
    RmsRule(
        id="rms.assembly.first_component_fixed",
        scope="assembly",
        severity="fail",
        statement="The first component is fixed, or fully constrained.",
    ),
    RmsRule(
        id="rms.assembly.mate_chain_depth",
        scope="assembly",
        severity="warn",
        statement="No component is more than limit mates from the fixed root (default 3).",
    ),
    RmsRule(
        id="rms.assembly.toolbox_parts_not_configurations",
        scope="assembly",
        severity="warn",
        statement="Toolbox hardware is inserted as parts, not as configurations of one file.",
    ),
    # Data not yet extracted: unresolved coverage, once per review.
    RmsRule(
        id="rms.assembly.no_sibling_in_context_refs",
        scope="assembly",
        statement="No in-context references between sibling parts.",
        coverage=("unresolved", "external references not extracted"),
    ),
    RmsRule(
        id="rms.assembly.positions_driven_by_globals",
        scope="assembly",
        statement=(
            "Component positions are driven by assembly global variables where they are "
            "parametric."
        ),
        coverage=("unresolved", "assembly equations not extracted"),
    ),
    RmsRule(
        id="rms.assembly.mates_described",
        scope="assembly",
        statement="Mates are named for intent through their description.",
        coverage=("unresolved", "mate descriptions not extracted"),
    ),
    RmsRule(
        id="rms.assembly.subassemblies",
        scope="assembly",
        statement="The assembly rules hold for each subassembly as for the root.",
        coverage=(
            "unresolved",
            "subassembly mates not extracted; assembly rules evaluated for the root "
            "document only",
        ),
    ),
    # Out of scope in this version: out_of_scope coverage, once per review.
    RmsRule(
        id="rms.drawing.model_items_preferred",
        scope="drawing",
        statement="Drawings use model items; the scheme is not re-dimensioned in the drawing.",
        coverage=(
            "out_of_scope",
            "drawing-owned vs model dimensions not extracted; advisory by decision",
        ),
    ),
    RmsRule(
        id="rms.advisory.structural_vs_cosmetic_fillets",
        scope="advisory",
        statement="Structural fillets belong in Core or Detail; cosmetic fillets in Quarantine.",
        coverage=("out_of_scope", "judgement-only; not decidable from extracted data"),
    ),
    RmsRule(
        id="rms.advisory.core_shaping_cuts",
        scope="advisory",
        statement="A cut in Core shapes the core; a cut that adds detail belongs in Detail.",
        coverage=("out_of_scope", "judgement-only; not decidable from extracted data"),
    ),
    RmsRule(
        id="rms.advisory.description_quality",
        scope="advisory",
        statement="Descriptions state intent, not the feature type.",
        coverage=("out_of_scope", "judgement-only; not decidable from extracted data"),
    ),
    RmsRule(
        id="rms.advisory.sketch_plane_choice",
        scope="advisory",
        statement="Sketches sit on reference planes, not on model faces.",
        coverage=("out_of_scope", "judgement-only; sketch planes not extracted"),
    ),
    RmsRule(
        id="rms.advisory.avoid_multibody",
        scope="advisory",
        statement="Parts stay single-body unless multibody is the intent.",
        coverage=("out_of_scope", "judgement-only; body intent not decidable"),
    ),
)
"""Every rule of `contracts/rules.md`, in the contract's order, keyed by id."""

RMS_FAMILY = CheckFamily(
    name="rms",
    summary_check="modeling.resilience",
    rules_version=RULES_VERSION,
    scopes=frozenset({"part", "assembly", "equations", "drawing", "advisory"}),
    tools={
        "part": "check_rms_part",
        "assembly": "check_rms_assembly",
        "equations": "check_rms_equations",
    },
    check_file_family="rms",
    severities=frozenset({"fail", "warn"}),
    status_by_severity={
        "fail": ("demonstrated", "medium"),
        "warn": ("suspected", "low"),
    },
    high_severity=frozenset(
        rule_id
        for rule_id in RULES
        if rule_id.startswith(HIGH_SEVERITY_RULE_PREFIX) or rule_id in HIGH_SEVERITY_RULES
    ),
    waiver_labels={
        "unknown": "invalid (unknown rule)",
        "warn": "invalid (warn rule)",
        "unresolved": "invalid (data-gap rule)",
        "out_of_scope": "invalid (out-of-scope rule)",
    },
)
"""This family, as the facts `checks/rules/` reads instead of hard-coding them.

`summary_check` is the checklist item these rules answer; its coverage item is the one-line
verdict on the whole method for this review (`agent/checklist_v1.yaml`).

`waiver_labels` are the lines `swreview exceptions accept-rms` prints for an id it cannot
accept, keyed by the reason: `unknown` for an id the catalogue does not hold, the rule's own
severity when it has one, and its coverage bucket when it has not. `contracts/rules.md`
("Waivable rules") names exactly these three refusals - a `warn` rule, a data-gap rule and
an out-of-scope rule - and each is reported as itself rather than folded into one label: a
waiver for `rms.assembly.mates_described` is refused because the data is not extracted, and
telling an engineer it is a `warn` rule would send them looking for a severity to argue
with.
"""

bind = binder(RULES, "contracts/rules.md")
"""Register a rule's evaluator, as a decorator in that scope's evaluator module.

Bound late rather than passed to `RmsRule` so that the evaluator modules import the
registry and not the reverse; importing `swreview.checks.rms`, which imports all three of
them, is what completes the invariant.

Raises `KeyError` for an unknown id, and `ValueError` for a coverage-only rule (which is
never dispatched) or a rule that already has an evaluator.
"""


def by_scope() -> dict[str, tuple[RmsRule, ...]]:
    """The catalogue partitioned by scope, in contract order; every scope is a key."""
    return _by_scope(RULES, RMS_FAMILY.scopes)


def evaluable() -> tuple[RmsRule, ...]:
    """The rules that are dispatched, in contract order.

    Read from `coverage`, not from `fn`, so that an evaluator module can ask which ids it
    owes a function while it is still binding them.
    """
    return _evaluable(RULES)


def coverage_only() -> tuple[RmsRule, ...]:
    """The rules that are never dispatched and are emitted as coverage, in contract order."""
    return _coverage_only(RULES)
