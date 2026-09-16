"""Intent: which features have no description, and what the equation manager actually holds.

The two readings the judgement phase is offered, and neither of them decides anything. The
planner never invents description prose (`data-model.md` section 1.8) and never proposes a
global on its own; this module says **where** a proposal would be admissible and **what
evidence exists for one**, and the model proposes into that space through the curated tools.

**Absence is not emptiness.** A description read as `None` is unreadable and one read as `""`
is absent, and the gap list keeps them apart because the difference decides whether the
change may be attempted at all: an unreadable description has no recoverable inverse - there
is nothing to write back on a rollback - so it is refused as a change target up front (FR-024
and section 1.8), while an absent one inverts to `""`. A description that was read and is
blank is *absent*: it was read, so the inverse exists, and there is nothing in it to lose.

**The equation inventory is tri-state, like everything else here.** It reports the rows that
exist, the rows the manager calls globals, the rows that reference a name nothing declares -
broken - and the rows it cannot judge either way. A row whose `GlobalVariable(i)` or
`Value(i)` could not be read is never counted as healthy (Principle I), and a reference this
package cannot resolve is `unresolved` rather than `broken`: calling an equation broken
because the IR does not carry dimensions would be the planner blaming the part for the
extractor's profile. `broken` and `unresolved` are disjoint, so a row is counted once, and a
named missing reference wins - it explains the unreadable value beside it rather than being
explained by it.

**What may justify a global** (FR-030, owner decision OQ-2). The IR carries `equations[]` and
**no sketch dimensions**, so a proposal may name only a feature-data field the package
actually carries: a hole diameter, a shell thickness, a fillet radius. A hard-coded sketch
value can never appear as a proposal, because there is nothing in the package to read it
from - that is a structural property of the IR and not a rule this module enforces. Of the
three admissible parameters only `default_radius` has a source row under the `model_check`
profile the planner receives, which is why `global_candidates` is short; the other two become
reachable when a `full` package is planned, and naming them here keeps the admissibility rule
in one place rather than growing a second one later.

**And a v1 global drives nothing.** `GlobalEvidence` records why the number is what it is;
nothing in the copy is rewired to it (FR-030), and the report says so in those words.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from swreview.checks.rms.equations import DIMENSION_MARKER
from swreview.checks.rms_types import RmsTypeTable
from swreview.ir.models import Equation, Feature

__all__ = [
    "ADMISSIBLE_PARAMETERS",
    "BrokenEquation",
    "DescriptionGap",
    "EquationInventory",
    "GlobalCandidate",
    "UnresolvedEquation",
    "description_gaps",
    "equation_inventory",
    "global_candidates",
    "is_admissible_parameter",
]

ADMISSIBLE_PARAMETERS: tuple[str, ...] = ("hole_diameter", "shell_thickness", "default_radius")
"""The feature-data fields a `GlobalEvidence` row may name (`data-model.md` section 1.9).
Nothing else is admissible, and in particular no dimension: the IR carries none."""

_REFERENCE = re.compile(r'"([^"]*)"')
"""SOLIDWORKS equation syntax quotes every reference: `"width" * 2`, `"D1@Sketch1"`. A
reference carrying `@` is a dimension, and a bare one is a global (`research.md` R2, the
same reading `checks/rms/equations.py` makes of the left side)."""


# --- descriptions -----------------------------------------------------------------


@dataclass(frozen=True)
class DescriptionGap:
    """One content feature that carries no usable description, and why it carries none."""

    feature_id: str
    name: str
    kind: Literal["unreadable", "absent"]
    proposable: bool
    """False for an unreadable description: refused as a change target before it is tried."""

    reason: str


def description_gaps(
    features: Sequence[Feature], table: RmsTypeTable
) -> tuple[DescriptionGap, ...]:
    """The content features with no description, in tree order.

    Content only: a folder, an end-tag marker, an excluded default name and a tolerated type
    are not held to the intent rules, and `RmsTypeTable.is_content` is the one place that is
    decided (feature 003's `contracts/rules.md`, "Content features").
    """
    gaps: list[DescriptionGap] = []
    for row in sorted(features, key=lambda row: row.index):
        if not table.is_content(row):
            continue
        if row.description is None:
            gaps.append(
                DescriptionGap(
                    feature_id=row.id,
                    name=row.name,
                    kind="unreadable",
                    proposable=False,
                    reason=(
                        "IFeature.Description could not be read, so this feature is refused "
                        "as a change target: a description with no recorded previous text has "
                        "no recoverable inverse"
                    ),
                )
            )
        elif not row.description.strip():
            gaps.append(
                DescriptionGap(
                    feature_id=row.id,
                    name=row.name,
                    kind="absent",
                    proposable=True,
                    reason=(
                        "the description was read and is blank, so it may be written and the "
                        'inverse is the recorded previous text ("")'
                    ),
                )
            )
    return tuple(gaps)


# --- the equation inventory -------------------------------------------------------


@dataclass(frozen=True)
class BrokenEquation:
    """A row referencing a name nothing in this manager declares."""

    index: int
    text: str
    missing: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class UnresolvedEquation:
    """A row this package cannot judge either way, with the reading that is missing."""

    index: int
    text: str
    reason: str


@dataclass(frozen=True)
class EquationInventory:
    """One document's equation manager as the planner reads it.

    `rows` is every row in index order; the other four are views of it. `globals` and
    `dimension_driven` are what the manager says it holds, `broken` and `unresolved` are
    what it can and cannot be judged on, and the last two are disjoint.
    """

    rows: tuple[Equation, ...]
    globals: tuple[Equation, ...]
    dimension_driven: tuple[Equation, ...]
    broken: tuple[BrokenEquation, ...]
    unresolved: tuple[UnresolvedEquation, ...]
    declared_globals: frozenset[str]


def equation_inventory(equations: Sequence[Equation]) -> EquationInventory:
    """Inventory one document's equation manager. No document, no LLM, no I/O.

    An empty manager is an answer, not a gap: it reports no rows, no globals, nothing broken
    and nothing unresolved, exactly as feature 003's equation rules already treat it.
    """
    rows = tuple(sorted(equations, key=lambda row: row.index))
    declared = frozenset(row.lhs for row in rows if row.is_global)
    uncertain = frozenset(row.lhs for row in rows if row.is_global is None)

    broken: list[BrokenEquation] = []
    unresolved: list[UnresolvedEquation] = []
    for row in rows:
        references = _global_references(row.text)
        missing = tuple(name for name in references if name not in declared | uncertain)
        if missing:
            broken.append(
                BrokenEquation(
                    index=row.index,
                    text=row.text,
                    missing=missing,
                    reason=(
                        f"references {', '.join(missing)}, which no equation in this manager "
                        "declares as a global"
                    ),
                )
            )
            continue
        reason = _unresolved_reason(row, references, uncertain)
        if reason is not None:
            unresolved.append(UnresolvedEquation(index=row.index, text=row.text, reason=reason))

    return EquationInventory(
        rows=rows,
        globals=tuple(row for row in rows if row.is_global),
        dimension_driven=tuple(row for row in rows if DIMENSION_MARKER in row.lhs),
        broken=tuple(broken),
        unresolved=tuple(unresolved),
        declared_globals=declared,
    )


def _global_references(text: str) -> tuple[str, ...]:
    """The bare quoted names on the right of the first `=`, in order and without repeats.

    Bare, because a quoted name carrying `@` is a dimension, and the IR carries no
    dimensions to check one against.
    """
    _, _, right = text.partition("=")
    names = [
        name
        for name in _REFERENCE.findall(right)
        if name and DIMENSION_MARKER not in name
    ]
    return tuple(dict.fromkeys(names))


def _unresolved_reason(
    row: Equation, references: Sequence[str], uncertain: frozenset[str]
) -> str | None:
    """Why this row cannot be judged, or `None` when it can."""
    unreadable_references = [name for name in references if name in uncertain]
    if unreadable_references:
        return (
            f"references {', '.join(unreadable_references)}, whose IEquationMgr.GlobalVariable "
            "flag could not be read, so whether this row resolves is unknown"
        )
    if row.is_global is None:
        return "IEquationMgr.GlobalVariable(i) could not be read, so this row is not evidence"
    if row.value is None:
        return "IEquationMgr.Value(i) could not be read, so this row's value is not evidence"
    return None


# --- what justifies a global ------------------------------------------------------


@dataclass(frozen=True)
class GlobalCandidate:
    """One feature-data reading a `GlobalProposal` may cite as its evidence.

    `value_m` is metres, as every length in the IR is. The conversion to the document's
    length unit happens once, in the executor, against `remodel.open`'s
    `document_length_unit` (FR-027); nothing here converts anything, because a second
    conversion site is the units trap R3.6 names.
    """

    feature_id: str
    name: str
    parameter: str
    value_m: float


def is_admissible_parameter(parameter: str) -> bool:
    """Whether a `GlobalEvidence` row may name this parameter (FR-030).

    Exact membership of `ADMISSIBLE_PARAMETERS`: a near-miss is a field nobody calibrated
    this against, and a dimension is never admissible under any spelling.
    """
    return parameter in ADMISSIBLE_PARAMETERS


def global_candidates(
    features: Sequence[Feature], table: RmsTypeTable
) -> tuple[GlobalCandidate, ...]:
    """The feature-data readings that could justify a global, in tree order.

    Under the `model_check` profile the planner receives, that is the readable simple-fillet
    radii and nothing else: holes and shells carry no feature-data row in this IR version, so
    proposing a global for one would be inventing the number it names. An unreadable radius
    yields no candidate - a gap is not a value, and `rank.py` is what reports it as
    `radius_unreadable`.
    """
    candidates: list[GlobalCandidate] = []
    for row in sorted(features, key=lambda row: row.index):
        if not table.is_content(row) or row.fillet is None:
            continue
        radius = row.fillet.default_radius
        if radius is None:
            continue
        candidates.append(
            GlobalCandidate(
                feature_id=row.id,
                name=row.name,
                parameter="default_radius",
                value_m=radius.value,
            )
        )
    return tuple(candidates)
