"""Where a feature sits once its group is decided (T011).

The key is `(group_index, intra_rank, original_index)` and nothing else
(`data-model.md` section 1.2, `research.md` R6.2):

- `group_index` is the position of the target group in the six, so the groups come out in
  the method's order;
- `intra_rank` comes **straight from the rules feature 003 already grades**, imported from
  `checks/rms/part.py` rather than spelled again here, so the planner cannot aim at an
  order the checker will mark down. A class no intra-group rule names takes the base rank
  and is therefore ordered only by where it already is;
- `original_index` is the tie-break, which makes the plan stable and makes minimum
  movement the default rather than an accident.

**A fillet whose radius is unreadable is blocked, not positioned.** `largest_fillet_first`
is the only rule that orders fillets among themselves, and it needs a radius. A
variable-radius fillet, or one whose definition could not be read, has `rankable=False`,
no `intra_rank`, and no key at all: asking for one raises. `feasibility.py` puts it on the
rebuild list with reason `radius_unreadable`. The alternative - handing it the base rank -
would give it a position that looks deliberate and is not, which is the one thing
constitution Principle I forbids. The block applies in every group, because the reason the
planner cannot place it does not change when the group does.

Only Quarantine fillets are *ordered* by radius, because Quarantine is the only group
`largest_fillet_first` grades; ordering Core fillets by radius would be movement the
checker never asked for, and every move is a guarded write with a rebuild after it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from swreview import units
from swreview.checks.rms.part import (
    CHAMFERS_BEFORE_FILLETS,
    CORE,
    DETAIL,
    HOLES_LAST,
    LARGEST_FILLET_FIRST,
    MODIFY,
    QUARANTINE,
    SHELL_LAST,
    TRANSFORM_BEFORE_REPLICATE,
)
from swreview.checks.rms_types import Classification, RmsTypeTable
from swreview.ir.models import Feature

__all__ = ["BASE_RANK", "FeatureRank", "group_index", "rank_features"]

BASE_RANK = 1
"""The rank of a class no intra-group rule names. Every tier below ranks after it, which
is what each of the five rules says: the shell and the holes come last, the drafts come
before the patterns, the chamfers before the fillets."""

_TIERS: Mapping[int, tuple[tuple[Classification, str], ...]] = {
    CORE: (("shell", SHELL_LAST),),
    DETAIL: (("hole", HOLES_LAST),),
    MODIFY: (
        ("draft", TRANSFORM_BEFORE_REPLICATE),
        ("pattern", TRANSFORM_BEFORE_REPLICATE),
    ),
    QUARANTINE: (
        ("chamfer", CHAMFERS_BEFORE_FILLETS),
        ("fillet", LARGEST_FILLET_FIRST),
    ),
}
"""The classes each group's rules order, in the order those rules put them, keyed by the
group's position in `RmsTypeTable.groups` (the same positions `checks/rms/part.py` names).
A group absent here has no intra-group ordering rule at all, so every feature in it keeps
the position it already has.

One tier expands: `largest_fillet_first` gives each readable Quarantine fillet its own
rank, largest radius first. It is the last tier of its group, so the expansion cannot
collide with a tier behind it."""


class FeatureRank(BaseModel):
    """Where one feature sits (`data-model.md` section 1.2).

    `intra_rule_id` names the 003 rule that *produced* the rank, and is null when the base
    rank was taken, so the report can say which rule moved a feature and never imply one
    that did not.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    feature_id: str
    group_index: int
    intra_rank: int | None
    intra_rule_id: str | None
    original_index: int
    rankable: bool

    @property
    def sort_key(self) -> tuple[int, int, int]:
        """The total order key. Raises for a feature that was never positioned."""
        if not self.rankable or self.intra_rank is None:
            raise ValueError(
                f"{self.feature_id} has no rank and therefore no position in the plan; "
                "it belongs on the rebuild list, not in the order"
            )
        return (self.group_index, self.intra_rank, self.original_index)


def group_index(group: str, table: RmsTypeTable) -> int:
    """The position of `group` in the six, from 1.

    A name that is not one of the six is refused: `needs_judgement` is the table saying it
    cannot decide, not a seventh group, and neither it nor an invented name may reach a
    sort key.
    """
    if group not in table.groups:
        raise ValueError(
            f"{group!r} is not one of the six RMS groups {list(table.groups)}"
        )
    return table.groups.index(group) + 1


def rank_features(
    features: Sequence[Feature],
    target_groups: Mapping[str, str],
    table: RmsTypeTable,
) -> list[FeatureRank]:
    """One rank per entry of `target_groups`, in tree order.

    `target_groups` maps feature id to the group `target.py` resolved for it, so a folder,
    an end-tag marker and a feature nobody could place are simply absent and are never
    given a position by default.
    """
    rows = {row.id: row for row in features}
    unknown = sorted(set(target_groups) - set(rows))
    if unknown:
        raise ValueError(
            f"target_groups names {unknown}, which this tree does not carry; a rank is "
            "addressed by id, never by name"
        )
    indices = {group: group_index(group, table) for group in set(target_groups.values())}
    fillet_ranks = _quarantine_fillet_ranks(features, target_groups, table)

    ranked: list[FeatureRank] = []
    for row in features:
        group = target_groups.get(row.id)
        if group is None:
            continue
        ranked.append(
            _rank(row, group, indices[group], fillet_ranks, table)
        )
    return ranked


def _rank(
    row: Feature,
    group: str,
    index: int,
    fillet_ranks: Mapping[str, int],
    table: RmsTypeTable,
) -> FeatureRank:
    classification = table.classify(row.type_name)
    blocked = classification == "fillet" and _radius_mm(row) is None
    if blocked:
        return FeatureRank(
            feature_id=row.id,
            group_index=index,
            intra_rank=None,
            intra_rule_id=None,
            original_index=row.index,
            rankable=False,
        )

    intra_rank = fillet_ranks.get(row.id)
    rule_id: str | None = LARGEST_FILLET_FIRST if intra_rank is not None else None
    if intra_rank is None:
        intra_rank, rule_id = _tier_rank(classification, index - 1)
    return FeatureRank(
        feature_id=row.id,
        group_index=index,
        intra_rank=intra_rank,
        intra_rule_id=rule_id,
        original_index=row.index,
        rankable=True,
    )


def _tier_rank(classification: Classification, group: int) -> tuple[int, str | None]:
    """The rank the group's own rules give this class, or the base rank.

    `group` is the group's position in `RmsTypeTable.groups`, counted from zero as
    `checks/rms/part.py` counts it.
    """
    for position, (name, rule_id) in enumerate(_TIERS.get(group, ())):
        if name == classification:
            return BASE_RANK + 1 + position, rule_id
    return BASE_RANK, None


def _quarantine_fillet_ranks(
    features: Sequence[Feature],
    target_groups: Mapping[str, str],
    table: RmsTypeTable,
) -> dict[str, int]:
    """`largest_fillet_first`: one rank per readable Quarantine fillet, largest first.

    Radii are compared in millimetres through `swreview.units`, exactly as the rule that
    grades them does, so the planner and the checker order two fillets the same way. Equal
    radii fall back to the original index, so fillets the rule cannot separate are not
    moved past each other.
    """
    quarantine = table.groups[QUARANTINE]
    readable: list[tuple[float, int, str]] = []
    for row in features:
        if target_groups.get(row.id) != quarantine:
            continue
        if table.classify(row.type_name) != "fillet":
            continue
        radius_mm = _radius_mm(row)
        if radius_mm is None:
            continue
        readable.append((-radius_mm, row.index, row.id))

    base, _ = _tier_rank("fillet", QUARANTINE)
    return {
        feature_id: base + position
        for position, (_, _, feature_id) in enumerate(sorted(readable))
    }


def _radius_mm(row: Feature) -> float | None:
    """The fillet's default radius in millimetres; `None` when it was not read."""
    if row.fillet is None or row.fillet.default_radius is None:
        return None
    return units.as_mm(row.fillet.default_radius)
