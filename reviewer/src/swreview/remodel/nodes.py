"""One node per feature: the dump's second listing of an absorbed sketch (T143, decision 17A).

The extractor walks a part's tree twice over: with `FirstFeature`/`GetNextFeature` for the
flat order, and under every feature with `GetFirstSubFeature`/`GetNextSubFeature`
(`FeatureTreeIndexer`). SOLIDWORKS lists an absorbed sketch in both walks - at depth 0, in
traversal order just before the feature that consumes it, and again at depth 1 under that
feature - and the two rows carry one persistent reference, because they are one feature.
The real packages of 2026-09-25 show it for every absorbed sketch, and a planner that read
the two rows as two features planned the same feature twice: two targets, a duplicate-name
rename of a feature against itself, and a second reorder naming a persist ref the first had
already moved.

**The rule** (`contracts/run-artifacts.md`, "How the planner reads the tree"):

    A row at depth 1 or deeper whose enclosing row (`folder_id`) is a feature and not a
    folder, and whose `persist_ref` and `type_name` equal those of exactly one depth-0 row
    of the same document, is that depth-0 row listed a second time. The planner keeps the
    depth-0 row, drops the second listing, and rewrites every `parent_ids`, `child_ids`,
    `sketch.consumer_ids` and `folder_id` naming the dropped id to name the kept one.

Why each clause is there:

- **the depth-0 row is kept** because its position is the feature's place in the flat
  order `IModelDocExtension.ReorderFeature` works on, and its readings stand: the second
  listing adds nothing the planner reads except its id, which is the id the other rows'
  edges name (the dumper's handle index keeps the last id it gave a feature);
- **a feature, not a folder, encloses it**: a depth-1 row under a folder is folder
  membership in the nested traversal shape, which `assign_groups` reads from `folder_id`,
  and no real package shows a folder member listed twice, so none is merged on a guess;
- **persist ref and type, against exactly one depth-0 row**: the real packages also carry
  seven system folders of seven types at depth 0 that share one persist ref, and a second
  listing whose reference names two top-level rows cannot say which one it is.

Nothing else is merged, and a row the walk found only under its owner - the Hole Wizard's
own profile sketch on the real packages - is kept as the dump gave it: it is not a second
listing of anything. What is merged is returned beside the rows, so the plan can say so
(`plan.py`'s "second listings" coverage item) rather than showing fewer targets than the
package has rows with no word why.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from swreview.checks.rms_types import RmsTypeTable
from swreview.ir.models import Feature

__all__ = ["MergedRow", "TreeNodes", "tree_nodes"]


@dataclass(frozen=True)
class MergedRow:
    """One second listing, and the depth-0 row it is."""

    dropped_id: str
    kept_id: str


@dataclass(frozen=True)
class TreeNodes:
    """One document's rows, one per feature, and the second listings merged into them."""

    rows: tuple[Feature, ...]
    """In the order the rows arrived; the kept rows are the depth-0 rows, unchanged but for
    their edges."""

    merged: tuple[MergedRow, ...]
    """In the order the second listings arrived."""


def tree_nodes(rows: Sequence[Feature], table: RmsTypeTable) -> TreeNodes:
    """Merge every second listing of one document's tree into the row it repeats.

    Pure and total over what it is given: a tree with no second listing comes back as it
    went in, with nothing merged.

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
    top_level: dict[tuple[str, str], list[Feature]] = {}
    for row in rows:
        if row.depth == 0:
            top_level.setdefault((row.persist_ref, row.type_name), []).append(row)

    kept_for: dict[str, str] = {}
    merged: list[MergedRow] = []
    for row in rows:
        twin = _twin(row, by_id, top_level, table)
        if twin is not None:
            kept_for[row.id] = twin.id
            merged.append(MergedRow(dropped_id=row.id, kept_id=twin.id))

    if not merged:
        return TreeNodes(rows=tuple(rows), merged=())
    return TreeNodes(
        rows=tuple(_rewired(row, kept_for) for row in rows if row.id not in kept_for),
        merged=tuple(merged),
    )


def _twin(
    row: Feature,
    by_id: dict[str, Feature],
    top_level: dict[tuple[str, str], list[Feature]],
    table: RmsTypeTable,
) -> Feature | None:
    """The depth-0 row `row` is a second listing of, or `None` when it is its own feature."""
    if row.depth < 1 or row.folder_id is None:
        return None
    enclosing = by_id.get(row.folder_id)
    if enclosing is None or table.is_folder(enclosing) or table.is_end_tag(enclosing):
        return None
    candidates = top_level.get((row.persist_ref, row.type_name), [])
    return candidates[0] if len(candidates) == 1 else None


def _rewired(row: Feature, kept_for: dict[str, str]) -> Feature:
    """`row` with every id it names that was a second listing naming the kept row, once.

    A row that names no second listing comes back equal to itself: the rule rewrites edges
    to dropped rows and touches no other reading.
    """
    sketch = row.sketch
    if sketch is not None and sketch.consumer_ids is not None:
        sketch = sketch.model_copy(
            update={"consumer_ids": _renamed(sketch.consumer_ids, kept_for)}
        )
    folder_id = row.folder_id
    return row.model_copy(
        update={
            "parent_ids": _renamed(row.parent_ids, kept_for),
            "child_ids": _renamed(row.child_ids, kept_for),
            "sketch": sketch,
            "folder_id": None if folder_id is None else kept_for.get(folder_id, folder_id),
        }
    )


def _renamed(ids: Sequence[str] | None, kept_for: dict[str, str]) -> list[str] | None:
    """`ids` with each second listing replaced by its kept row, in order, without repeats.

    `None` is an edge list that was never read and stays unread. A list naming no second
    listing is returned as it is; one that named both listings of a feature named one
    feature twice, and names it once afterwards.
    """
    if ids is None:
        return None
    if not any(one in kept_for for one in ids):
        return list(ids)
    return list(dict.fromkeys(kept_for.get(one, one) for one in ids))
