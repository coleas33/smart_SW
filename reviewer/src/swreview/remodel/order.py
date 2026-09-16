"""The achievable order and the minimal edit script that reaches it (T015).

`research.md` R6.3: Kahn's algorithm over the feature dependency graph with a priority
queue keyed by the **desired rank**, then the longest increasing subsequence of current
positions under that order for the **minimal** edit script.

The two halves answer two different questions and both have to be asked:

- *what order is legal?* Every topological order of `parent_ids` is. Among them the
  planner takes the one the method would prefer, by always releasing the ready feature
  the desired rank puts first. That is what makes the output the RMS-**closest** legal
  order rather than merely a legal one, and it is the difference between a plan that
  moves what the method wants moved and a plan that reshuffles a compliant tree;
- *what does it cost?* The features whose current positions already increase along the
  achievable order can stay where they are, and the longest such subsequence is the
  largest set that can. Everything else moves exactly once, so the script is `n - LIS`
  moves. On a 200-feature part that is tens of moves rather than 200, and every move
  saved is a guarded write and a rebuild not paid for.

Three properties this module holds to, each because something downstream depends on it:

- **the location set is closed at `before` and `after`.** `swMoveLocation_e.ToEnd = 1`,
  `ToTop = 4` and `ToFolder = 5` are the three values `contracts/guard-allowlist.md`'s
  option-composition test forbids the guard from ever composing, so a `Move` naming one
  would be a change the guard's own contract says cannot exist. `Move` refuses them at
  construction rather than trusting every call site. Kahn plus LIS needs none of them: a
  move to the end of the tree is `after` the last feature, and moving a feature into an
  existing folder is not a stage-1 operation at all;
- **a cycle is a refusal that names the cycle.** It is the one input for which no legal
  order exists, so the result carries `cycle` and an empty order rather than an arbitrary
  break, and the walk that finds it is bounded by the number of features - a planner that
  looped here would hang a dry run that is supposed to need no seat and no document;
- **nothing is defaulted.** A feature with no desired rank, an edge naming a feature that
  is not in the tree, and a tree naming one feature twice are refused, and the refusal
  names every offender rather than the first (constitution Principle I).

**Not every row in the order is a row this stage moves.** `immovable` names the ones it
does not - the rows the method does not grade, which nonetheless occupy tree positions and
are real `GetParents` parents. They are in `current` so that Kahn cannot release a feature
before one of its own parents, and they are never the subject of a `Move`:
`IModelDocExtension.ReorderFeature` cannot lift a feature past its parent, so an order that
ignored those edges would be an order SOLIDWORKS refuses.

There is no folder in this module, and no group: in stage 1 the six folders are created
**after** the reorder, over runs the achievable order has already made contiguous
(`data-model.md` section 1.11, C3 then C4). What the caller must not move - a feature on
the rebuild list, a feature whose graph could not be read - it keeps in place by giving it
its current position as its desired rank; deciding that is `feasibility.py`'s job and not
this one's.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Literal, get_args

__all__ = ["LOCATIONS", "Location", "Move", "OrderResult", "plan_order"]

Location = Literal["before", "after"]
"""Where a move puts a feature relative to its anchor; `swMoveLocation_e.Before = 2` and
`After = 3` (VERIFIED values)."""

LOCATIONS: tuple[Location, ...] = get_args(Location)
"""`Location` as a value: the closed set, in the enum's order."""


@dataclass(frozen=True)
class Move:
    """One `IModelDocExtension.ReorderFeature` call: `feature_id` goes `location` `anchor`.

    Both ends are feature ids here and are carried as persist refs in the corresponding
    `PlannedChange` (`data-model.md` section 1.3), because the name a reorder is addressed
    by changes and an index changes on every move.
    """

    feature_id: str
    anchor_feature_id: str
    location: Location

    def __post_init__(self) -> None:
        if self.location not in LOCATIONS:
            raise ValueError(
                f"{self.location!r} is not a move location; stage 1 composes only "
                f"{list(LOCATIONS)} (swMoveLocation_e.ToEnd, ToTop and ToFolder are "
                "forbidden by contracts/guard-allowlist.md)"
            )
        if self.feature_id == self.anchor_feature_id:
            raise ValueError(f"{self.feature_id} cannot be its own reorder anchor")


@dataclass(frozen=True)
class OrderResult:
    """The achievable order and what it costs (`data-model.md` section 1.3, `OrderPlan`).

    `plan.py` builds the pydantic `OrderPlan` from these fields; this is the pure record
    the algorithm produces, so the algorithm is testable without the plan.
    """

    achievable: tuple[str, ...]
    """The legal topological order closest to the desired order; empty on a cycle."""

    kept: tuple[str, ...]
    """The longest increasing subsequence of current positions under `achievable`: the
    features that are not moved, in tree order."""

    edit_script: tuple[Move, ...]
    """The complement of `kept`, in application order."""

    cycle: tuple[str, ...] | None = None
    """Non-null means the order is a refusal. The features are named as a chain: each is
    a parent of the next, and the last is a parent of the first."""

    @property
    def move_count(self) -> int:
        """`len(edit_script)`: the headline number of the dry run."""
        return len(self.edit_script)


def plan_order(
    current: Sequence[str],
    dependencies: Mapping[str, Sequence[str]],
    desired_rank: Mapping[str, int],
    *,
    immovable: Collection[str] = (),
) -> OrderResult:
    """The achievable order for one part's tree, and the minimal script that reaches it.

    Args:
        current: every feature id of the tree, in the order the tree has them now.
        dependencies: feature id to the ids it depends on (`Feature.parent_ids`). A
            feature absent from the mapping has no dependencies; a feature whose parents
            were **unreadable** is the caller's problem, not a free pass - `feasibility.py`
            reports it `graph_unreadable` and the caller keeps it where it is.
        desired_rank: feature id to its position in the desired order (0 first). Ties are
            broken by the current position, so the order is total and deterministic and
            minimum movement is the default. `rank.py` produces the
            `(group_index, intra_rank, original_index)` keys this is the sort of.
        immovable: the rows of `current` this reorder never moves - the rows the method
            does not grade, which still occupy tree positions and are still real
            `GetParents` parents. They keep their own relative order, they are always
            kept, and no `Move` ever names one as its subject; a move may still anchor to
            one, which is how a feature lands **after** a reference plane it is built on.

    Raises:
        ValueError: `current` names a feature twice, a feature has no desired rank, a
            rank, a dependency or an immovable id names a feature that is not in
            `current`.
    """
    position = _index(current)
    _refuse_unknown(position, dependencies, desired_rank, immovable)

    fixed = frozenset(immovable)
    order, cycle = _kahn(
        current, position, _with_fixed_order(current, dependencies, fixed), desired_rank
    )
    if cycle is not None:
        return OrderResult(achievable=(), kept=(), edit_script=(), cycle=cycle)

    kept = _kept(order, position, fixed)
    return OrderResult(
        achievable=tuple(order),
        kept=tuple(feature for feature in order if feature in kept),
        edit_script=_edit_script(order, kept),
        cycle=None,
    )


# --- validation -------------------------------------------------------------------


def _index(current: Sequence[str]) -> dict[str, int]:
    """Every feature's current position, refusing a tree that names one twice.

    A duplicate id is not a tree the planner may reason about: two rows with one id make
    every position, every edge and every move ambiguous.
    """
    position: dict[str, int] = {}
    repeated: list[str] = []
    for index, feature in enumerate(current):
        if feature in position:
            repeated.append(feature)
        else:
            position[feature] = index
    if repeated:
        raise ValueError(
            f"the tree names {_named(repeated)} more than once; a feature id addresses "
            "one row"
        )
    return position


def _refuse_unknown(
    position: Mapping[str, int],
    dependencies: Mapping[str, Sequence[str]],
    desired_rank: Mapping[str, int],
    immovable: Collection[str],
) -> None:
    """Refuse every feature the three inputs disagree about, naming all of them at once.

    One exception listing every reason, because a caller that fixes the first of four
    problems and runs again has learned almost nothing.
    """
    unranked = sorted(feature for feature in position if feature not in desired_rank)
    stray_ranks = sorted(feature for feature in desired_rank if feature not in position)
    stray_edges = sorted(
        {
            feature
            for child, parents in dependencies.items()
            for feature in (child, *parents)
            if feature not in position
        }
    )
    reasons: list[str] = []
    if unranked:
        reasons.append(f"{_named(unranked)} have no desired rank")
    if stray_ranks:
        reasons.append(f"{_named(stray_ranks)} are ranked but are not in the tree")
    if stray_edges:
        reasons.append(f"{_named(stray_edges)} are named by a dependency but not in the tree")
    stray_fixed = sorted(feature for feature in immovable if feature not in position)
    if stray_fixed:
        reasons.append(f"{_named(stray_fixed)} are called immovable but are not in the tree")
    if reasons:
        raise ValueError("; ".join(reasons))


def _named(features: Sequence[str]) -> str:
    return ", ".join(features)


# --- the rows the reorder never moves ---------------------------------------------


def _with_fixed_order(
    current: Sequence[str],
    dependencies: Mapping[str, Sequence[str]],
    fixed: frozenset[str],
) -> Mapping[str, Sequence[str]]:
    """`dependencies` plus one edge per consecutive pair of immovable rows.

    An immovable row keeps the tree position it has, so the order Kahn reaches must keep
    the immovable rows in the order the tree has them; the chain says exactly that and
    nothing more. It can only close a cycle on a tree that already contradicts its own
    `parent_ids` - an immovable row cannot both precede another and depend on something
    after it - and such a tree is refused as the cycle it is rather than reordered.
    """
    if len(fixed) < 2:
        return dependencies
    chain = [feature for feature in current if feature in fixed]
    extended = {feature: list(parents) for feature, parents in dependencies.items()}
    for parent, child in zip(chain, chain[1:], strict=False):
        extended.setdefault(child, []).append(parent)
    return extended


def _kept(
    order: Sequence[str], position: Mapping[str, int], fixed: frozenset[str]
) -> frozenset[str]:
    """The features that are not moved: every immovable row, plus the longest run of
    movable ones that can stay where they are around them.

    The immovable rows cut `order` into segments, and a movable feature can only stay put
    while its current position still falls between the positions of the immovable rows it
    now sits between - otherwise it has crossed one, which is a move. So the LIS is taken
    within each segment over the features the segment's bounds admit, which is the same
    argument as the unconstrained case applied to one span of the tree at a time.
    """
    if not fixed:
        return _longest_increasing_subsequence(order, position)

    kept = set(fixed)
    lower = -1
    segment: list[str] = []
    for feature in (*order, None):
        if feature is not None and feature not in fixed:
            segment.append(feature)
            continue
        upper = len(position) if feature is None else position[feature]
        kept |= _longest_increasing_subsequence(
            [one for one in segment if lower < position[one] < upper], position
        )
        segment = []
        if feature is not None:
            lower = position[feature]
    return frozenset(kept)


# --- Kahn with a priority queue ---------------------------------------------------


def _kahn(
    current: Sequence[str],
    position: Mapping[str, int],
    dependencies: Mapping[str, Sequence[str]],
    desired_rank: Mapping[str, int],
) -> tuple[list[str], tuple[str, ...] | None]:
    """The legal order closest to the desired one, or the cycle that makes none exist."""
    parents = {
        feature: tuple(dict.fromkeys(dependencies.get(feature, ()))) for feature in current
    }
    children: dict[str, list[str]] = {feature: [] for feature in current}
    for feature, feature_parents in parents.items():
        for parent in feature_parents:
            children[parent].append(feature)

    outstanding = {feature: len(feature_parents) for feature, feature_parents in parents.items()}
    ready: list[tuple[int, int, str]] = []
    for feature, count in outstanding.items():
        if count == 0:
            heappush(ready, _key(feature, position, desired_rank))

    order: list[str] = []
    while ready:
        _, _, feature = heappop(ready)
        order.append(feature)
        for child in children[feature]:
            outstanding[child] -= 1
            if outstanding[child] == 0:
                heappush(ready, _key(child, position, desired_rank))

    if len(order) == len(parents):
        return order, None
    return [], _find_cycle(parents, outstanding, position, desired_rank)


def _key(
    feature: str, position: Mapping[str, int], desired_rank: Mapping[str, int]
) -> tuple[int, int, str]:
    """The priority queue's key: the method's wish, then the tree's current order.

    The current position is the tie-break, so two features the method ranks equally keep
    the order they already have and the sort is total; the id is the last resort and makes
    the result reproducible whatever order the mappings were built in.
    """
    return desired_rank[feature], position[feature], feature


def _find_cycle(
    parents: Mapping[str, tuple[str, ...]],
    outstanding: Mapping[str, int],
    position: Mapping[str, int],
    desired_rank: Mapping[str, int],
) -> tuple[str, ...]:
    """One cycle among the features Kahn could not release, named as a chain.

    Every unreleased feature has at least one unreleased parent, so walking parents from
    any of them re-enters the walk within `len(parents)` steps and the cycle is the tail
    of that walk. The walk takes the lowest-keyed candidate at every step, so the same
    tree always names the same cycle. The result reads parent-to-child: each feature is a
    parent of the next and the last is a parent of the first.
    """
    stuck = {feature for feature, count in outstanding.items() if count > 0}
    walk: list[str] = [min(stuck, key=lambda feature: _key(feature, position, desired_rank))]
    seen = {walk[0]}
    while True:
        candidates = [parent for parent in parents[walk[-1]] if parent in stuck]
        step = min(candidates, key=lambda feature: _key(feature, position, desired_rank))
        if step in seen:
            cycle = walk[walk.index(step) :]
            return tuple(reversed(cycle))
        walk.append(step)
        seen.add(step)


# --- the minimal edit script ------------------------------------------------------


def _longest_increasing_subsequence(
    order: Sequence[str], position: Mapping[str, int]
) -> frozenset[str]:
    """The largest set of features that can stay where they are.

    Patience sorting over the current positions read along the achievable order: a
    strictly increasing run of current positions is a set of features already in the right
    relative order, so the longest one is the largest set no move has to touch, and
    `len(order) - len(this)` is therefore the minimum number of moves.
    """
    tails: list[int] = []  # tails[k]: the smallest achievable-index ending a run of k + 1
    previous: list[int | None] = [None] * len(order)
    for index, feature in enumerate(order):
        low, high = 0, len(tails)
        while low < high:  # the first run whose end is not below this feature
            middle = (low + high) // 2
            if position[order[tails[middle]]] < position[feature]:
                low = middle + 1
            else:
                high = middle
        previous[index] = tails[low - 1] if low > 0 else None
        if low == len(tails):
            tails.append(index)
        else:
            tails[low] = index

    kept: list[str] = []
    step = tails[-1] if tails else None
    while step is not None:
        kept.append(order[step])
        step = previous[step]
    return frozenset(kept)


def _edit_script(order: Sequence[str], kept: frozenset[str]) -> tuple[Move, ...]:
    """One move per feature that is not kept, each anchored to a feature already placed.

    The kept features never move, so they are the spine every other feature is positioned
    against, and a move is only correct when its anchor is already where the achievable
    order wants it. The script therefore grows outwards from the first kept feature: the
    features before it are moved `before` their successor, nearest first, and the features
    after it are moved `after` their predecessor, in order. Every anchor is a feature the
    script has already placed (or never moves), and inserting one feature never changes
    the relative order of the ones already placed, so the tree the script leaves behind is
    exactly `order`.

    Anchoring every move to its neighbour in the achievable order - rather than to the
    nearest kept feature - is what keeps the script to one move per unkept feature, which
    is `len(order) - len(kept)`, which is the minimum.
    """
    spine = next((index for index, feature in enumerate(order) if feature in kept), None)
    if spine is None:  # only an empty tree keeps nothing: the LIS of one feature is one
        return ()

    moves: list[Move] = []
    for index in range(spine - 1, -1, -1):
        moves.append(Move(order[index], order[index + 1], "before"))
    for index in range(spine + 1, len(order)):
        if order[index] not in kept:
            moves.append(Move(order[index], order[index - 1], "after"))
    return tuple(moves)
