"""Where every feature of a part sits: its group and its derived subfolder (T010).

`specs/003-resilient-modeling/contracts/rules.md` ("Group assignment") is normative, and
this module is the one place it is implemented: the rules ask `GroupAssignment` which group
a feature is in and never re-derive it from `name`, `depth`, or `folder_id`. The extractor
classifies nothing (`data-model.md` section 1), so folders, end-tag markers and the six
group names all come from `RmsTypeTable`.

Two things the contract insists on and this module therefore does:

- **groups are sticky, not structural.** A group folder opens a group and everything after
  it in `index` order belongs to that group until the next group folder - nested under it,
  following it at depth 0, or after its end-tag marker. So the group is a single running
  value over the traversal, which is what makes both shapes of `IFeatureManager` (folder
  contents reported as sub-features, or reported flat with `<name>___EndTag___` markers)
  come out the same;
- **derived subfolders are structural,** and are the one thing the two shapes disagree
  about: nested, a folder's members are the rows whose `folder_id` chain reaches it; flat,
  they are the rows until its own end-tag marker. The shape is decided once for the whole
  document - does any *folder* own sub-features - rather than guessed per row, because
  ordinary features own sub-features in both shapes (`GetFirstSubFeature` lists the sketch
  an extrusion consumed however folders report their contents, research.md open question 1)
  and one of those must not make a flat document look nested.

`Feature.folder_id` is the nearest enclosing *feature*, not the nearest enclosing folder
(`data-model.md` section 1: the indexer nests whatever the walk listed and classifies
nothing), so the nested shape walks that chain up to the first row the table calls a folder.
A pattern is not a folder, and its seed features are not a coupled pair.

A feature's derived subfolder is the id of the nearest enclosing folder, or null when that
folder is a group folder or there is none: a group folder is a group, never a subfolder,
so the coupled-pair exception in `rms.detail.no_internal_references` can compare subfolder
ids without accidentally pairing everything in Detail.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from swreview.checks.rms_types import RmsTypeTable
from swreview.ir.models import Feature

__all__ = ["GroupAssignment", "assign_groups"]


@dataclass(frozen=True)
class GroupAssignment:
    """Where the features of one document sit (`data-model.md` section 2).

    Both maps carry an entry for every feature - folders and end-tag markers included, so a
    rule may look any feature up - and `None` means "no group" / "no subfolder", which is
    an answer, not a gap: a feature before the first group folder genuinely has no group.
    """

    by_feature_id: dict[str, str | None]
    """Feature id to group name; `None` before the first group folder."""

    subfolder_by_feature_id: dict[str, str | None]
    """Feature id to the id of the non-group folder holding it; `None` when there is none."""

    groups_seen: list[tuple[str, str]]
    """Every group folder in traversal order, as `(group name, folder feature id)`."""

    duplicates: list[tuple[str, str]]
    """The second and later occurrence of a group name, in the same form; the first
    occurrence is in `groups_seen`, which is how `rms.folders.ordered` names both."""

    order_ok: bool
    """Whether `groups_seen` is strictly increasing in the table's group order, which a
    duplicate also breaks. True for a document with fewer than two group folders."""


def assign_groups(features: Sequence[Feature], table: RmsTypeTable) -> GroupAssignment:
    """Assign the features of one document to groups and derived subfolders.

    `features` is one part document's `EvidencePackage.features[]` rows; they are walked in
    `index` order, whatever order they arrive in.
    """
    rows = sorted(features, key=lambda row: row.index)
    rows_by_id = {row.id: row for row in rows}
    nested = _folders_report_sub_features(rows, rows_by_id, table)
    group_names = set(table.groups)

    by_feature_id: dict[str, str | None] = {}
    subfolder_by_feature_id: dict[str, str | None] = {}
    groups_seen: list[tuple[str, str]] = []
    duplicates: list[tuple[str, str]] = []
    open_folders: list[Feature] = []  # flat shape only; the nested shape reads folder_id
    current_group: str | None = None
    opened: set[str] = set()

    for row in rows:
        if not nested and table.is_end_tag(row):
            _close_folder(open_folders, row.name.removesuffix(table.end_tag_suffix))

        if nested:
            enclosing = _enclosing_folder(row, rows_by_id, table)
        else:
            enclosing = open_folders[-1] if open_folders else None
        subfolder_by_feature_id[row.id] = (
            None
            if enclosing is None or enclosing.name in group_names
            else enclosing.id
        )

        if table.is_folder(row):
            if row.name in group_names:
                current_group = row.name
                groups_seen.append((row.name, row.id))
                if row.name in opened:
                    duplicates.append((row.name, row.id))
                opened.add(row.name)
            if not nested:
                open_folders.append(row)
        by_feature_id[row.id] = current_group

    order = [table.groups.index(name) for name, _ in groups_seen]
    return GroupAssignment(
        by_feature_id=by_feature_id,
        subfolder_by_feature_id=subfolder_by_feature_id,
        groups_seen=groups_seen,
        duplicates=duplicates,
        order_ok=all(before < after for before, after in pairwise(order)),
    )


def _folders_report_sub_features(
    rows: Sequence[Feature], rows_by_id: dict[str, Feature], table: RmsTypeTable
) -> bool:
    """Whether any *folder* owns sub-features, which is the nested traversal shape.

    Deliberately not "does anything own sub-features": an extrusion owns the sketch it
    consumed in both shapes, and reading that as the nested shape would throw away every
    flat folder's end-tag marker and lose its members.
    """
    for row in rows:
        if row.folder_id is None:
            continue
        enclosing = rows_by_id.get(row.folder_id)
        if enclosing is not None and table.is_folder(enclosing):
            return True
    return False


def _enclosing_folder(
    row: Feature, rows_by_id: dict[str, Feature], table: RmsTypeTable
) -> Feature | None:
    """The nearest enclosing folder of `row` in the nested shape, or `None`.

    Walks the `folder_id` chain past the ordinary features that own sub-features, so a
    sketch nested under the extrusion that consumed it, one level inside a folder, is still
    in that folder. `seen` stops a self-reference or a cycle in malformed rows; a
    `folder_id` naming a row this document does not carry ends the walk with no folder,
    because inventing one would be a guess about a tree we did not receive.
    """
    seen = {row.id}
    current = row.folder_id
    while current is not None and current not in seen:
        seen.add(current)
        enclosing = rows_by_id.get(current)
        if enclosing is None:
            return None
        if table.is_folder(enclosing):
            return enclosing
        current = enclosing.folder_id
    return None


def _close_folder(open_folders: list[Feature], name: str) -> None:
    """Close the innermost open folder called `name`, and any folder left open inside it.

    An end-tag marker naming a folder that is not open closes nothing: it is a marker for a
    folder this document never opened, and dropping it is better than closing the wrong one.
    """
    for position in range(len(open_folders) - 1, -1, -1):
        if open_folders[position].name == name:
            del open_folders[position:]
            return
