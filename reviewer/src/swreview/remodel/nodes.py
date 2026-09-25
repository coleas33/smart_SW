"""One node per feature position: how the planner reads a dumped tree (T143, T163; decision 17A).

The extractor walks a part's tree twice over: with `FirstFeature`/`GetNextFeature` for the
flat order, and under every feature with `GetFirstSubFeature`/`GetNextSubFeature`
(`FeatureTreeIndexer`). The flat walk is the order `IModelDocExtension.ReorderFeature` works
on; the sub-feature walk adds rows that hold no place in it. The real packages of 2026-09-25
carry two such shapes, and a planner that read every row as a feature with a position of its
own mis-planned both:

1. **a second listing.** SOLIDWORKS lists an absorbed sketch in both walks - at depth 0 just
   before the feature that consumes it, and again at depth 1 under that feature - with one
   persistent reference, because they are one feature. Read as two, it got two targets, a
   duplicate-name rename against itself, and a second reorder of one persist ref;
2. **a carried sub-feature.** The Hole Wizard's own profile sketch is listed only under its
   hole, after it, and is that hole's parent. Read as a feature with a position, it was moved
   on its own and moves were anchored to it, and a folder could have tried to select it.

**The rules** (`contracts/run-artifacts.md`, "How the planner reads the tree"), for a row at
depth 1 or deeper whose enclosing row (`folder_id`) is a feature and not a folder:

    If its `persist_ref` and `type_name` equal those of exactly one depth-0 row, it is that
    row listed a second time: the depth-0 row is kept with its readings, and every
    `parent_ids`, `child_ids`, `sketch.consumer_ids` and `folder_id` naming the second listing
    names the kept row instead, once.

    If no depth-0 row carries its `persist_ref` at all, it is carried by the nearest kept
    feature above it: it is not a node, every edge naming it names that owner instead (an
    edge from the owner to itself is dropped), and its own parents and children become the
    owner's - an unreadable list on either side leaving the owner's list unread.

    Otherwise - a persist ref two depth-0 rows share, or a depth-0 twin of another type - the
    row is kept as the dump gave it: it names a top-level row nobody can pick, so neither rule
    applies, and `RemodelPlan` refuses a second move of one persist ref if it comes to that.

Why the clauses are there:

- **the depth-0 row is kept** because its position is the feature's place in the flat order;
  the second listing adds nothing the planner reads except its id, which is the id the other
  rows' edges name (the dumper's handle index keeps the last id it gave a feature);
- **a feature, not a folder, encloses it**: a depth-1 row under a folder is folder membership
  in the nested traversal shape, which `assign_groups` reads from `folder_id` and which is a
  real position `ReorderFeature` can move; nothing on the real packages shows a folder member
  listed twice, so none is merged or carried on a guess;
- **a carried row's edges become its owner's**: it travels with its owner, so whatever it
  depends on the owner depends on, and whatever depends on it depends on the owner; the owner
  naming it as a parent - the hole naming its own sketch - is the edge that disappears;
- **exactly one depth-0 row, or none**: the real packages carry seven system folders of seven
  types at depth 0 that share one persist ref, and a reference that names two top-level rows
  cannot say which one a listing is.

What is merged and what is carried are returned beside the rows, so the plan says so
(`plan.py`'s "second listings" and "carried sub-features" coverage items) rather than showing
fewer targets than the package has rows with no word why.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from swreview.checks.rms_types import RmsTypeTable
from swreview.ir.models import Feature

__all__ = ["CarriedRow", "MergedRow", "TreeNodes", "tree_nodes"]


@dataclass(frozen=True)
class MergedRow:
    """One second listing, and the depth-0 row it is."""

    dropped_id: str
    kept_id: str


@dataclass(frozen=True)
class CarriedRow:
    """One row found only under the feature that owns it, and that owner."""

    dropped_id: str
    owner_id: str


@dataclass(frozen=True)
class TreeNodes:
    """One document's rows, one per feature position, and the rows folded into them."""

    rows: tuple[Feature, ...]
    """In the order the rows arrived; a kept row is unchanged but for its edges."""

    merged: tuple[MergedRow, ...]
    """The second listings, in the order they arrived."""

    carried: tuple[CarriedRow, ...]
    """The carried sub-features, in the order they arrived."""


def tree_nodes(rows: Sequence[Feature], table: RmsTypeTable) -> TreeNodes:
    """Fold every second listing and every carried sub-feature of one document's tree into
    the row that holds its position.

    Pure and total over what it is given: a tree with neither shape comes back as it went in.

    Raises:
        ValueError: `rows` span more than one document. A persist ref is scoped to the
            document that owns it, so a twin in another document is not a twin.
    """
    documents = sorted({row.document_id for row in rows})
    if len(documents) > 1:
        raise ValueError(
            f"a tree is one document's rows; these carry {documents}, and a persist ref "
            "only names a feature inside the document that owns it"
        )

    by_id = {row.id: row for row in rows}
    top_level: dict[str, list[Feature]] = {}
    for row in rows:
        if row.depth == 0:
            top_level.setdefault(row.persist_ref, []).append(row)

    merged: list[MergedRow] = []
    carried_rows: list[Feature] = []
    for row in rows:
        if not _under_a_feature(row, by_id, table):
            continue
        twins = top_level.get(row.persist_ref, [])
        if len(twins) == 1 and twins[0].type_name == row.type_name:
            merged.append(MergedRow(dropped_id=row.id, kept_id=twins[0].id))
        elif not twins:
            carried_rows.append(row)

    into = {merge.dropped_id: merge.kept_id for merge in merged}
    carried = tuple(
        CarriedRow(dropped_id=row.id, owner_id=_owner(row, by_id, into, carried_rows))
        for row in carried_rows
    )
    into.update({carry.dropped_id: carry.owner_id for carry in carried})
    if not into:
        return TreeNodes(rows=tuple(rows), merged=(), carried=())

    owned: dict[str, list[Feature]] = {}
    for carry in carried:
        owned.setdefault(carry.owner_id, []).append(by_id[carry.dropped_id])
    return TreeNodes(
        rows=tuple(
            _rewired(row, into, owned.get(row.id, ())) for row in rows if row.id not in into
        ),
        merged=tuple(merged),
        carried=carried,
    )


def _under_a_feature(row: Feature, by_id: dict[str, Feature], table: RmsTypeTable) -> bool:
    """Whether the sub-feature walk found `row` under a feature rather than a folder.

    A `folder_id` naming a row this document does not carry answers no: inventing an owner
    would be a guess about a tree nobody received.
    """
    if row.depth < 1 or row.folder_id is None:
        return False
    enclosing = by_id.get(row.folder_id)
    return (
        enclosing is not None
        and not table.is_folder(enclosing)
        and not table.is_end_tag(enclosing)
    )


def _owner(
    row: Feature,
    by_id: dict[str, Feature],
    merged_into: dict[str, str],
    carried_rows: Sequence[Feature],
) -> str:
    """The nearest kept feature above a carried row: its enclosing row, or - when that is
    itself carried or a second listing - the row that one folds into, walked upwards.

    The walk is bounded by the rows it has seen, so a `folder_id` chain that loops ends at
    the last row before the loop rather than going round it.
    """
    carried_ids = {one.id for one in carried_rows}
    seen = {row.id}
    current = row.folder_id or row.id
    while current not in seen:
        seen.add(current)
        if current in merged_into:
            return merged_into[current]
        enclosing = by_id.get(current)
        if current not in carried_ids or enclosing is None or enclosing.folder_id is None:
            return current
        current = enclosing.folder_id
    return current


def _rewired(row: Feature, into: dict[str, str], carried: Sequence[Feature]) -> Feature:
    """`row` with every id it names that was folded naming the row it folded into, once,
    and - for an owner - the edges of the rows it carries.

    A row that names no folded row and carries none comes back equal to itself: the rules
    rewrite edges and touch no other reading.
    """
    parents = _renamed(row.parent_ids, into, row.id)
    children = _renamed(row.child_ids, into, row.id)
    for sub in carried:
        parents = _joined(parents, _renamed(sub.parent_ids, into, row.id), row.id)
        children = _joined(children, _renamed(sub.child_ids, into, row.id), row.id)
    sketch = row.sketch
    if sketch is not None and sketch.consumer_ids is not None:
        sketch = sketch.model_copy(
            update={"consumer_ids": _renamed(sketch.consumer_ids, into, row.id)}
        )
    folder_id = row.folder_id
    return row.model_copy(
        update={
            "parent_ids": parents,
            "child_ids": children,
            "sketch": sketch,
            "folder_id": None if folder_id is None else into.get(folder_id, folder_id),
        }
    )


def _renamed(ids: Sequence[str] | None, into: dict[str, str], own_id: str) -> list[str] | None:
    """`ids` with each folded row replaced by the row it folded into, in order, once each.

    `None` is an edge list nobody read and stays unread. A list naming no folded row is
    returned as it is; in one that did, a row folded into `own_id` - the owner naming its own
    carried sketch - is dropped rather than made an edge from a feature to itself.
    """
    if ids is None:
        return None
    if not any(one in into for one in ids):
        return list(ids)
    renamed = (into.get(one, one) for one in ids)
    return list(dict.fromkeys(one for one in renamed if one != own_id))


def _joined(
    owner: list[str] | None, carried: list[str] | None, own_id: str
) -> list[str] | None:
    """An owner's edges with a carried row's added after them; unread if either is unread.

    The carried row's edge to its own owner - the sketch naming the hole it belongs to - is
    the one edge that does not cross over: the owner is not its own child or parent.
    """
    if owner is None or carried is None:
        return None
    return list(dict.fromkeys((*owner, *(one for one in carried if one != own_id))))
