"""Duplicate feature names: detection and the rename plan (T013).

`IModelDocExtension.ReorderFeature` takes `String FeatureToMove, String TargetFeature`.
SOLIDWORKS permits two rows of one tree to share a name, and a name-addressed reorder is
then ambiguous with **no error code to say so**: the call returns a bare `false`, or moves
the wrong feature (research.md R3.7). Tree-wide name uniqueness is therefore a
precondition of the reorder step, not a nicety, which is why the executor applies every
rename first (data-model.md section 1.11, step C1) and why a duplicate it cannot repair
sends both rows to the rebuild list with reason `ambiguous_name` (FR-013).

The name space is the whole tree: folders and end-tag markers share it, so they are
counted even though this step never renames one.

**What cannot be safely renamed**, and why each is the run's own rule rather than a guess:

1. a row the grouping rules do not hold - a folder, an end-tag marker, one of the excluded
   default names, a tolerated system row. A folder is renamed by `folder.rename`, which
   the executor applies *after* every reorder, so renaming one here could not repair the
   ambiguity it is meant to repair; the rest are not this run's rows to rename at all;
2. a name an equation references by text (`"D1@Sketch1"` addresses the sketch by name).
   Renaming it would break the equation, and this version rewrites no equation (FR-029,
   FR-030). A referenced name blocks **every** row that carries it, because an equation
   that names a duplicated name is itself ambiguous about which row it means.

**Which row keeps the name.** The one that cannot be renamed, when exactly one cannot;
otherwise the first in tree order, so a repair moves as little as possible. Only when two
or more rows sharing a name cannot be renamed does the ambiguity survive, and then every
row carrying that name is reported - repairing one of several would leave the reorder just
as undecidable as before.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from swreview.checks.rms_types import RmsTypeTable
from swreview.ir.models import Equation, Feature

__all__ = [
    "AMBIGUOUS_NAME",
    "DUPLICATE_NAME",
    "AmbiguousName",
    "NamePlan",
    "RenamePlan",
    "duplicate_names",
    "plan_renames",
]

DUPLICATE_NAME = "duplicate_name"
"""The one reason this step renames anything (`data-model.md` section 1.7)."""

AMBIGUOUS_NAME = "ambiguous_name"
"""The rebuild-list reason for a duplicate that could not be repaired; one of the eight of
`data-model.md` section 1.5, spelled here so `feasibility.py` copies it rather than
re-deriving it."""

_FROZEN = ConfigDict(strict=True, extra="forbid", frozen=True)


class RenamePlan(BaseModel):
    """One recorded, reversible rename, applied before any reorder.

    `before_name` is what `derive_undo` writes back, so the inverse of a rename is another
    rename and never a guess at what the name used to be.
    """

    model_config = _FROZEN

    feature_id: str
    before_name: str
    after_name: str
    reason: Literal["duplicate_name"] = DUPLICATE_NAME


class AmbiguousName(BaseModel):
    """A duplicate that could not be repaired: a rebuild-list entry in waiting.

    The fields are `RebuildEntry`'s (`data-model.md` section 1.5) so `feasibility.py`
    carries one across rather than rebuilding it from the name plan.
    """

    model_config = _FROZEN

    feature_id: str
    name: str
    reason: Literal["ambiguous_name"] = AMBIGUOUS_NAME
    detail: str


class NamePlan(BaseModel):
    """The repairs and the refusals. The two lists are disjoint by construction."""

    model_config = _FROZEN

    renames: tuple[RenamePlan, ...] = ()
    blocked: tuple[AmbiguousName, ...] = ()


def duplicate_names(features: Iterable[Feature]) -> dict[str, tuple[str, ...]]:
    """Every name more than one row carries, to the ids carrying it, in tree order.

    One pass over `features[]`: the rows are read once, in the order they arrive, which is
    the order that decides which row keeps its name.
    """
    ids_by_name: dict[str, list[str]] = {}
    for row in features:
        ids_by_name.setdefault(row.name, []).append(row.id)
    return {
        name: tuple(ids)
        for name, ids in ids_by_name.items()
        if len(ids) > 1
    }


def plan_renames(
    features: Sequence[Feature],
    equations: Sequence[Equation],
    table: RmsTypeTable,
) -> NamePlan:
    """The rename plan for one document's tree, and the duplicates it cannot repair."""
    rows = {row.id: row for row in features}
    taken = {row.name for row in features}
    renames: list[RenamePlan] = []
    blocked: list[AmbiguousName] = []

    for name, ids in duplicate_names(features).items():
        refusals = {
            feature_id: reason
            for feature_id in ids
            if (reason := _unrenameable(rows[feature_id], equations, table)) is not None
        }
        if len(refusals) > 1:
            blocked.extend(_blocked(name, ids, refusals))
            continue

        keeper = next(iter(refusals), ids[0])
        for feature_id in ids:
            if feature_id == keeper:
                continue
            after_name = _free_name(name, taken)
            taken.add(after_name)
            renames.append(
                RenamePlan(
                    feature_id=feature_id, before_name=name, after_name=after_name
                )
            )

    return NamePlan(renames=tuple(renames), blocked=tuple(blocked))


def _blocked(
    name: str, ids: Sequence[str], refusals: dict[str, str]
) -> list[AmbiguousName]:
    """One entry per row carrying `name`, each naming the others and the reason.

    Every row is reported, not only the ones that refused: the reorder cannot address any
    of them, so a report that listed one would send the engineer looking for the rest.
    """
    entries: list[AmbiguousName] = []
    for feature_id in ids:
        others = [other for other in ids if other != feature_id]
        reason = refusals.get(feature_id, "it could be renamed, but the others could not")
        entries.append(
            AmbiguousName(
                feature_id=feature_id,
                name=name,
                detail=(
                    f"{name!r} is shared with {', '.join(others)} and this row cannot be "
                    f"renamed first: {reason}"
                ),
            )
        )
    return entries


def _unrenameable(
    row: Feature, equations: Sequence[Equation], table: RmsTypeTable
) -> str | None:
    """Why this row cannot be renamed by the rename step, or `None` when it can."""
    if not table.is_content(row):
        return (
            "the rename step renames content features only; a folder is renamed after "
            "every reorder, and a default plane or a tolerated system row is not this "
            "run's to rename"
        )
    referencing = [
        equation.text for equation in equations if _references(equation.text, row.name)
    ]
    if referencing:
        return (
            f"the equation {referencing[0]!r} references it by name and this version "
            "rewrites no equation"
        )
    return None


def _references(text: str, name: str) -> bool:
    """Whether `text` addresses a feature called `name`.

    A SOLIDWORKS equation names a feature after an `@`, and the reference ends at the
    closing quote or at the next `@` (`"D1@Sketch1"`, `"D1@Sketch1@bracket.SLDPRT"`). The
    boundary matters: `@Sketch10` is not a reference to `Sketch1`, and a plain substring
    test would strand a repairable duplicate on the rebuild list.
    """
    return re.search(rf"@{re.escape(name)}(?=[\"@]|$)", text) is not None


def _free_name(name: str, taken: set[str]) -> str:
    """`name` with the first `_<n>` suffix, from 2, that no row and no earlier rename has.

    Counting rather than stopping at `_2` is what keeps the repair from creating the very
    ambiguity it exists to remove.
    """
    suffix = 2
    while f"{name}_{suffix}" in taken:
        suffix += 1
    return f"{name}_{suffix}"
