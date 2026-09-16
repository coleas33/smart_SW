"""Pins, non-contiguous groups and the rebuild list (T017).

`research.md` R6.4 and R6.7: stage 1's honest output is not "the part was reorganized",
it is a **partition with reasons**. Three lists come out of this module and each answers a
question an engineer actually asks:

- **pins**: which feature could not reach the position the method wants for it, and
  **which dependency edge** holds it there. A pin with no named edge is a bug, not a pin
  (`data-model.md` section 1.4), so a feature that merely shifted because something else
  moved is not a pin - only a feature an inverted edge holds is;
- **non-contiguous groups**: which group cannot be folded, and which interloper splits the
  run. Folders need contiguous members, so this is the difference between a group that
  becomes a folder and one that does not;
- **the rebuild list**: every content feature the reorganize stage could not place, each
  with exactly one reason from the closed taxonomy of eight (FR-014) and the edge,
  interloper, span or cycle behind it.

**The taxonomy is closed at eight and `RebuildEntry` enforces it.** A feature that matches
none of the eight is a planner defect, and the plan fails rather than inventing a ninth
reason at runtime, so the reason is validated where the entry is built and not where it is
printed.

**One reason per feature, resolved in a stated precedence** (`RESOLUTION_ORDER`): evidence
that was never read comes first (`graph_unreadable`, `unclassified`, `ambiguous_name`,
`radius_unreadable`), because "we did not read it" is the strongest thing that can be said
about a feature and it is what constitution Principle I makes terminal; then the
structural impossibility `cycle`; then the specific edge `backward_reference` and the
specific sketch `shared_sketch`; and last `splits_group`, which is usually a consequence of
one of the others rather than a fact about the feature itself.

Two boundaries are deliberate and are tested as such:

- **an RMS-named folder holding the wrong members is not a reason here.** It is the scope
  refusal `rms_named_folder_wrong_members` (`data-model.md` sections 1.6 and 4.2), reached
  from `ScopeSignals` alone so that it lands **before anything is copied**; `IModelDoc2.
  EditDelete` is not in the stage-1 allowlist, so there is no dissolve path and the whole
  part is refused. `scope.py` and `folders.py` own that token; this module never spells it;
- **`cycle` names a dependency cycle, the one `order.py` refused.** R6.5 describes the
  reason as a cycle in the *condensed group graph*, but a single backward edge already
  closes a cycle there on almost any real part - a Quarantine fillet depends on the Core
  feature it rounds, so `Core -> Quarantine -> Detail -> ...` and one backward edge form a
  loop - and reporting those as `cycle` would swallow `backward_reference`, which names an
  edge an engineer can actually go and look at. So a group-level inversion is reported as
  `backward_reference` on the held feature, and `cycle` is kept for the case where no legal
  order exists at all.

What this module is handed, rather than re-deriving: the target groups (`target.py`), the
desired and achievable orders (`rank.py` and `order.py`), and `names.py`'s `NamePlan.blocked`
- the duplicates it could **not** safely repair, carried across entry for entry rather than
rebuilt here, because most duplicates are renamed before any reorder and are not rebuild
entries at all, so re-deriving "two features share a name" would file every one of them.
What it reads from the package itself is only what no other module decides: a fillet whose
`default_radius` is unreadable, a sketch's consumers, a feature's parents, and a type name
the table does not carry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, get_args

from swreview.checks.rms.part import PartTree
from swreview.ir.models import Feature
from swreview.remodel.names import AMBIGUOUS_NAME, AmbiguousName

__all__ = [
    "REBUILD_REASONS",
    "RESOLUTION_ORDER",
    "Edge",
    "FeasibilityReport",
    "NonContiguousGroup",
    "Pin",
    "RebuildEntry",
    "RebuildReason",
    "assess",
]

RebuildReason = Literal[
    "backward_reference",
    "shared_sketch",
    "splits_group",
    "cycle",
    "radius_unreadable",
    "ambiguous_name",
    "unclassified",
    "graph_unreadable",
]
"""The closed taxonomy of FR-014, in the requirement's order."""

REBUILD_REASONS: tuple[RebuildReason, ...] = get_args(RebuildReason)
"""`RebuildReason` as a value; `data-model.md` section 1.5 calls this set closed."""

RESOLUTION_ORDER: tuple[RebuildReason, ...] = (
    "graph_unreadable",
    "unclassified",
    "ambiguous_name",
    "radius_unreadable",
    "cycle",
    "backward_reference",
    "shared_sketch",
    "splits_group",
)
"""Which reason wins when a feature matches more than one: the four things that were never
read, then the order that cannot exist, then the edge, the sketch and finally the span."""


@dataclass(frozen=True)
class Edge:
    """One dependency edge, named in the direction SOLIDWORKS builds it."""

    parent_id: str
    child_id: str


@dataclass(frozen=True)
class Pin:
    """A feature an edge holds away from the position the method wants for it."""

    feature_id: str
    desired_index: int
    achievable_index: int
    blocking_edge: Edge
    reason: str
    """Prose for the report, derived from the edge."""


@dataclass(frozen=True)
class RebuildEntry:
    """One feature the reorganize stage could not place (`data-model.md` section 1.5)."""

    feature_id: str
    name: str
    reason: RebuildReason
    detail: str
    """Names the interloper, the second consumer, the unknown type name, or the cycle."""

    blocking_edge: Edge | None = None

    def __post_init__(self) -> None:
        if self.reason not in REBUILD_REASONS:
            raise ValueError(
                f"{self.reason!r} is not a rebuild reason; the taxonomy is closed at "
                f"{list(REBUILD_REASONS)} (FR-014)"
            )
        if not self.detail:
            raise ValueError(f"{self.feature_id} carries {self.reason} with no evidence")


@dataclass(frozen=True)
class NonContiguousGroup:
    """A group that cannot be folded, and what splits it."""

    group: str
    member_ids: tuple[str, ...]
    """The group's features, in achievable order."""

    first_id: str
    last_id: str
    """The ends of the span the folder would have to cover."""

    interloper_ids: tuple[str, ...]
    """The features inside that span that belong to another group, in achievable order."""


@dataclass(frozen=True)
class FeasibilityReport:
    pins: tuple[Pin, ...]
    non_contiguous: tuple[NonContiguousGroup, ...]
    rebuild: tuple[RebuildEntry, ...]


def assess(
    tree: PartTree,
    *,
    target_groups: Mapping[str, str | None],
    desired: Sequence[str],
    achievable: Sequence[str],
    cycle: Sequence[str] | None = None,
    ambiguous_names: Sequence[AmbiguousName] = (),
) -> FeasibilityReport:
    """What stage 1 can and cannot do to one part, with a reason for everything it cannot.

    Args:
        tree: the part document, as every feature 003 rule reads it.
        target_groups: feature id to the group the planner resolved for it, `None` when it
            resolved none. Every row of the tree carries an entry, folders included, exactly
            as `RemodelPlan.targets` does.
        desired: the content features in the order the method wants them (`rank.py`).
        achievable: the content features in the order `order.py` reached; empty, and only
            empty, when `cycle` is not `None`.
        cycle: the dependency cycle `order.py` refused on, if it did. There is no
            achievable order in that case, so there are no pins and no spans.
        ambiguous_names: `names.py`'s `NamePlan.blocked`: the duplicates it could **not**
            safely repair, each already carrying the sentence that says why. Every other
            duplicate is renamed before any reorder and is not a rebuild entry.

    Raises:
        ValueError: a row of the tree has no `target_groups` entry, a content feature is
            missing from `desired` or `achievable`, a refused order carries both a cycle
            and an achievable order, an empty cycle, or a blocked name naming a feature
            this tree does not carry.
    """
    _refuse_incomplete(tree, target_groups, desired, achievable, cycle, ambiguous_names)

    desired_at = {feature_id: index for index, feature_id in enumerate(desired)}
    achievable_at = {feature_id: index for index, feature_id in enumerate(achievable)}

    candidates: list[RebuildEntry] = _unread(tree)
    candidates.extend(_ambiguous(tree, ambiguous_names))
    if cycle is not None:
        candidates.extend(_cycle_entries(tree, cycle))
        return FeasibilityReport(
            pins=(), non_contiguous=(), rebuild=_resolve(tree, candidates)
        )

    pins = _pins(tree, target_groups, desired_at, achievable_at)
    non_contiguous = _non_contiguous(tree, target_groups, achievable)
    candidates.extend(_backward_references(tree, target_groups))
    candidates.extend(_shared_sketches(tree))
    candidates.extend(_splits(tree, non_contiguous, achievable_at))
    return FeasibilityReport(
        pins=pins, non_contiguous=non_contiguous, rebuild=_resolve(tree, candidates)
    )


# --- validation -------------------------------------------------------------------


def _refuse_incomplete(
    tree: PartTree,
    target_groups: Mapping[str, str | None],
    desired: Sequence[str],
    achievable: Sequence[str],
    cycle: Sequence[str] | None,
    ambiguous_names: Sequence[AmbiguousName],
) -> None:
    """Refuse an input the report would otherwise be silently partial over.

    A feature missing from the orders is not a feature that stays put: it is a feature
    nothing decided about, and a report that skipped it would read as "nothing to say".
    """
    reasons: list[str] = []
    untargeted = sorted(row.id for row in tree.rows if row.id not in target_groups)
    if untargeted:
        reasons.append(f"{', '.join(untargeted)} have no target-group entry")

    content = {row.id for row in tree.content}
    for name, order in (("desired", desired), ("achievable", achievable)):
        if name == "achievable" and cycle is not None:
            continue
        missing = sorted(content - set(order))
        if missing:
            reasons.append(f"the {name} order does not name {', '.join(missing)}")

    if cycle is not None and achievable:
        reasons.append(
            "a refused order carries a cycle and no achievable order; this call carries both"
        )
    if cycle is not None and not cycle:
        reasons.append("a cycle names the features it runs through; this one names none")

    stray = sorted(
        blocked.feature_id
        for blocked in ambiguous_names
        if blocked.feature_id not in tree.by_id
    )
    if stray:
        reasons.append(f"the name plan blocks {', '.join(stray)}, which are not in this tree")
    if reasons:
        raise ValueError("; ".join(reasons))


# --- what was never read ----------------------------------------------------------


def _unread(tree: PartTree) -> list[RebuildEntry]:
    """The three reasons this module reads off the package itself.

    `ambiguous_name` is the fourth of the evidence-absence reasons and is not here: it is
    `names.py`'s finding, carried across by `_ambiguous`.
    """
    entries: list[RebuildEntry] = []
    for row in tree.content:
        if row.child_ids is None and row.parent_ids is None:
            entries.append(
                _entry(
                    row,
                    "graph_unreadable",
                    "GetChildren and GetParents both failed: nothing is known about what "
                    "this feature depends on or what depends on it",
                )
            )
        if tree.class_of(row) == "unknown":
            entries.append(
                _entry(
                    row,
                    "unclassified",
                    f"GetTypeName2 returned {row.type_name!r}, which rms_types.yaml does "
                    "not carry: the feature is unresolved and is never moved",
                )
            )
        if row.fillet is not None and row.fillet.default_radius is None:
            entries.append(
                _entry(
                    row,
                    "radius_unreadable",
                    "DefaultRadius is unreadable (a variable-radius fillet, or a radius "
                    "that did not read), so largest_fillet_first cannot rank it",
                )
            )
    return entries


def _ambiguous(
    tree: PartTree, ambiguous_names: Sequence[AmbiguousName]
) -> list[RebuildEntry]:
    """`names.py`'s blocked duplicates, entry for entry.

    The sentence is the one the name plan wrote: it names the rows that share the name and
    why this one could not be renamed first, which is more than this module could say from
    the tree, and re-deriving it here would be a second answer to one question.
    """
    return [
        RebuildEntry(
            feature_id=blocked.feature_id,
            name=blocked.name,
            reason=AMBIGUOUS_NAME,
            detail=blocked.detail,
        )
        for blocked in ambiguous_names
    ]


def _cycle_entries(tree: PartTree, cycle: Sequence[str]) -> list[RebuildEntry]:
    """Every content feature of the cycle `order.py` refused on, with the cycle named."""
    named = " -> ".join(
        tree.by_id[feature_id].name if feature_id in tree.by_id else feature_id
        for feature_id in (*cycle, cycle[0])
    )
    return [
        _entry(
            tree.by_id[feature_id],
            "cycle",
            f"dependency cycle {named}: no legal order exists for these features",
        )
        for feature_id in cycle
        if feature_id in tree.by_id and tree.table.is_content(tree.by_id[feature_id])
    ]


# --- what the edges do ------------------------------------------------------------


def _pins(
    tree: PartTree,
    target_groups: Mapping[str, str | None],
    desired_at: Mapping[str, int],
    achievable_at: Mapping[str, int],
) -> tuple[Pin, ...]:
    """Every feature an edge holds after a feature the method wanted after **it**."""
    wanted = _wanted_at(tree, desired_at)
    pins: list[Pin] = []
    for row in tree.content:
        parent = _worst_parent(tree, row, desired_at, wanted)
        if parent is None:
            continue
        pins.append(
            Pin(
                feature_id=row.id,
                desired_index=desired_at[row.id],
                achievable_index=achievable_at[row.id],
                blocking_edge=Edge(parent_id=parent.id, child_id=row.id),
                reason=(
                    f"{row.name} must follow {parent.name} "
                    f"({_group(target_groups, parent.id)}), which the method puts after it"
                    if parent.id in desired_at
                    else (
                        f"{row.name} must follow {parent.name}, which the method does not "
                        "grade and this stage never moves, so it cannot rise above the "
                        "tree position that row holds"
                    )
                ),
            )
        )
    return tuple(pins)


def _wanted_at(tree: PartTree, desired_at: Mapping[str, int]) -> dict[str, int]:
    """Where each row of the tree sits in the desired **content** order.

    A content feature sits where `desired_at` puts it. A row the method does not grade is
    never moved, so it sits where it already is: after the content features that currently
    precede it, and the count of those is its position in the same index space. That is what
    makes a reference plane comparable with the features around it without the method ever
    having ranked it.
    """
    wanted = dict(desired_at)
    content = {row.id for row in tree.content}
    seen = 0
    for row in tree.rows:
        if row.id in content:
            seen += 1
        else:
            wanted[row.id] = seen
    return wanted


def _group(target_groups: Mapping[str, str | None], feature_id: str) -> str:
    """A feature's target group as a reason says it; an unresolved group says so."""
    return target_groups.get(feature_id) or "no resolved group"


def _worst_parent(
    tree: PartTree,
    row: Feature,
    desired_at: Mapping[str, int],
    wanted_at: Mapping[str, int],
) -> Feature | None:
    """The parent that pushes `row` furthest past where the method wants it, or `None`.

    The parent with the highest wanted position is the one that decides where the feature
    can land at the earliest, so it is the edge the report names; ties go to the earlier
    row in the tree, so the same part always names the same edge.

    A parent the method does not grade counts too, at the position `_wanted_at` gives it: it
    is not moved, so it holds a feature built on it exactly as a content parent does, and a
    pin nobody reported is a move the plan claimed and SOLIDWORKS would refuse.
    """
    held = [
        parent
        for parent_id in (row.parent_ids or ())
        if (parent := tree.by_id.get(parent_id)) is not None
        and parent.id in wanted_at
        and wanted_at[parent.id] > desired_at[row.id]
    ]
    if not held:
        return None
    return max(held, key=lambda parent: (wanted_at[parent.id], -parent.index))


def _backward_references(
    tree: PartTree, target_groups: Mapping[str, str | None]
) -> list[RebuildEntry]:
    """A feature with a parent in a later group: R6.5's `backward_reference`."""
    rank = {group: index for index, group in enumerate(tree.table.groups)}
    entries: list[RebuildEntry] = []
    for row in tree.content:
        group = target_groups.get(row.id)
        if group is None or group not in rank:
            continue
        offenders = [
            parent
            for parent_id in (row.parent_ids or ())
            if (parent := tree.by_id.get(parent_id)) is not None
            and (parent_group := target_groups.get(parent.id)) is not None
            and parent_group in rank
            and rank[parent_group] > rank[group]
        ]
        if not offenders:
            continue
        worst = max(
            offenders,
            key=lambda parent: (rank[target_groups[parent.id] or ""], -parent.index),
        )
        entries.append(
            _entry(
                row,
                "backward_reference",
                f"{row.name} belongs in {group} but depends on {worst.name} in "
                f"{target_groups[worst.id]}, which the method puts after it",
                Edge(parent_id=worst.id, child_id=row.id),
            )
        )
    return entries


def _shared_sketches(tree: PartTree) -> list[RebuildEntry]:
    """A sketch with more than one consumer can be contiguous with only one of them."""
    entries: list[RebuildEntry] = []
    for row in tree.content:
        if row.sketch is None or row.sketch.consumer_ids is None:
            continue
        consumers = row.sketch.consumer_ids
        if len(consumers) <= 1:
            continue
        named = ", ".join(
            tree.by_id[consumer_id].name if consumer_id in tree.by_id else consumer_id
            for consumer_id in consumers
        )
        entries.append(
            _entry(
                row,
                "shared_sketch",
                f"{row.name} is consumed by {len(consumers)} features ({named}); it can "
                "be contiguous with only one of them",
            )
        )
    return entries


# --- what the spans do ------------------------------------------------------------


def _non_contiguous(
    tree: PartTree, target_groups: Mapping[str, str | None], achievable: Sequence[str]
) -> tuple[NonContiguousGroup, ...]:
    """Every group whose achievable span holds a feature belonging to another group.

    Contiguity is judged over the **content** features of the achievable order: the six
    folders do not exist yet at this point in the plan (`data-model.md` section 1.11, C3
    before C4), and `folders.py` proves the run contiguous again, on the real tree, before
    anything is created.
    """
    content = {row.id for row in tree.content}
    ordered = [feature_id for feature_id in achievable if feature_id in content]
    splits: list[NonContiguousGroup] = []
    for group in tree.table.groups:
        members = [
            feature_id for feature_id in ordered if target_groups.get(feature_id) == group
        ]
        if len(members) < 2:
            continue
        first, last = ordered.index(members[0]), ordered.index(members[-1])
        interlopers = tuple(
            feature_id
            for feature_id in ordered[first + 1 : last]
            if target_groups.get(feature_id) != group
        )
        if interlopers:
            splits.append(
                NonContiguousGroup(
                    group=group,
                    member_ids=tuple(members),
                    first_id=members[0],
                    last_id=members[-1],
                    interloper_ids=interlopers,
                )
            )
    return tuple(splits)


def _splits(
    tree: PartTree,
    non_contiguous: Sequence[NonContiguousGroup],
    achievable_at: Mapping[str, int],
) -> list[RebuildEntry]:
    """Both halves of a split group: the interloper, and the members it keeps unfolded.

    The interloper is R6.5's subject - it sits inside another group's span - and each
    member is spec.md US1 scenario 5's: the group gets no folder, so every one of its
    features is on the rebuild list with the interloper named.
    """
    entries: list[RebuildEntry] = []
    for split in non_contiguous:
        span = f"{tree.by_id[split.first_id].name} .. {tree.by_id[split.last_id].name}"
        for interloper_id in split.interloper_ids:
            row = tree.by_id[interloper_id]
            entries.append(
                _entry(
                    row,
                    "splits_group",
                    f"{row.name} sits inside the {split.group} span ({span}), so that "
                    "group cannot be folded",
                    _holding_edge(tree, row, split, achievable_at),
                )
            )
        named = ", ".join(tree.by_id[other].name for other in split.interloper_ids)
        for member_id in split.member_ids:
            member = tree.by_id[member_id]
            entries.append(
                _entry(
                    member,
                    "splits_group",
                    f"{split.group} cannot be made contiguous: {named} sits inside its "
                    f"span ({span})",
                )
            )
    return entries


def _holding_edge(
    tree: PartTree,
    row: Feature,
    split: NonContiguousGroup,
    achievable_at: Mapping[str, int],
) -> Edge | None:
    """The edge that keeps an interloper inside the span, when one does.

    A parent inside the span is what stops the interloper moving before it; a child inside
    the span is what stops it moving after. Neither is `None` rather than a guess: an
    interloper no edge explains is a planner defect worth seeing as an absent edge.
    """
    first, last = achievable_at[split.first_id], achievable_at[split.last_id]
    for parent_id in row.parent_ids or ():
        if first <= achievable_at.get(parent_id, -1) <= last:
            return Edge(parent_id=parent_id, child_id=row.id)
    for child_id in row.child_ids or ():
        if first <= achievable_at.get(child_id, -1) <= last:
            return Edge(parent_id=row.id, child_id=child_id)
    return None


# --- one reason per feature -------------------------------------------------------


def _entry(
    row: Feature, reason: RebuildReason, detail: str, edge: Edge | None = None
) -> RebuildEntry:
    return RebuildEntry(
        feature_id=row.id, name=row.name, reason=reason, detail=detail, blocking_edge=edge
    )


def _resolve(tree: PartTree, candidates: Sequence[RebuildEntry]) -> tuple[RebuildEntry, ...]:
    """One entry per feature - the highest-precedence reason - in tree order.

    Two candidates carrying the same reason keep the first, which is the one detected from
    the more specific evidence: the interloper's own entry before the entry it produces for
    each member of the group it splits.

    Every row of the tree is walked, not only the content features, because a duplicate
    name the rename plan could not repair can name a folder, and a list that dropped it
    would answer a question the name plan already answered.
    """
    best: dict[str, RebuildEntry] = {}
    for entry in candidates:
        current = best.get(entry.feature_id)
        if current is None or RESOLUTION_ORDER.index(entry.reason) < RESOLUTION_ORDER.index(
            current.reason
        ):
            best[entry.feature_id] = entry
    return tuple(best[row.id] for row in tree.rows if row.id in best)
