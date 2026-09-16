"""Feature-tree query tools: the part tree as the Resilient Modeling rules read it.

One function per row of the query table in `specs/003-resilient-modeling/contracts/tools.md`.
Like `swreview.tools.query` they are pure with respect to the package - nothing here writes
to the session, loads a mesh, or talks to SOLIDWORKS - and they return JSON-serializable
dicts and lists that `swreview.tools.registry` serializes and records.

The reason they exist rather than the model reading `package.json` itself is the derived
half of every answer. The extractor classifies nothing (`data-model.md` section 1): it
carries `type_name` and `name` verbatim, and what the method makes of them - the class, the
group, whether a row is a folder or an end-tag marker - is decided by `checks/rms_types.py`
and `checks/rms/groups.py`. These tools call those two and nothing else, so what the model
is shown and what `check_rms_part` evaluated cannot disagree, and the two traversal shapes
`IFeatureManager` reports (folder contents as sub-features, or flat with `___EndTag___`
markers) come out the same either way.

The two rules of `swreview.tools.query` hold here too (constitution Principle I):

- a value the extractor could not obtain stays `null` and is labelled, never estimated; so
  `include_suppressed=false` drops the rows that *are* suppressed and keeps the row whose
  suppression state nobody could read, and an id that resolves to no feature resolves to a
  `null` name rather than to an invented one;
- an argument that names nothing in the package comes back as an error result, so the model
  sees the mistake as a tool result instead of as an empty list it reads as "nothing there".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from swreview.checks.rms.groups import GroupAssignment, assign_groups
from swreview.checks.rms_types import RmsTypeTable, class_of, load_table
from swreview.ir.models import EvidencePackage, Feature
from swreview.tools.context import current_context, error_result, unknown_id
from swreview.tools.query import ToolResult, as_json


def list_features(
    document_id: str,
    folder: str | None = None,
    include_suppressed: bool = True,
) -> list[dict[str, Any]] | ToolResult:
    """The feature tree of one document, in traversal order, with its derived columns.

    `class` and `group` are the method's own answers, not the extractor's: `class` is
    `unknown` for a type name the RMS type table does not carry and `ambiguous` for one
    that spans classes, and `group` is `null` for a feature before the first group folder.
    Folders and end-tag markers are listed like any other row. `folder_id` is the nearest
    enclosing *feature* as the extractor reported it, which is `null` in the traversal
    shape that reports no sub-features; `folder` filters on the enclosing folder, which is
    the same answer in both shapes.

    A document whose tree was not extracted - an assembly, a suppressed component's part -
    has no rows here; `list_gaps` says why.

    Args:
        document_id: Document id whose feature tree to list.
        folder: One of the six group names, a group folder's feature id (which selects
            that whole group), or a subfolder's feature id (which selects that folder's
            members); null for the whole tree.
        include_suppressed: Keep the features that are suppressed in this configuration.
            A feature whose suppression state was not readable is kept either way.
    """
    context = current_context()
    if context.document(document_id) is None:
        return unknown_id("document", document_id)
    table = load_table()
    rows = _rows_of(context.ir, document_id)
    assignment = assign_groups(rows, table)
    if folder is not None:
        selected = _in_folder(folder, rows, assignment, table)
        if selected is None:
            return error_result(
                f"folder {folder!r} names neither one of the groups {list(table.groups)} "
                f"nor a folder feature of document {document_id!r}"
            )
        rows = selected
    if not include_suppressed:
        rows = [row for row in rows if row.suppressed is not True]
    return [
        {
            "id": row.id,
            "name": row.name,
            "type_name": row.type_name,
            "class": class_of(row, table),
            "group": assignment.by_feature_id[row.id],
            "folder_id": row.folder_id,
            "depth": row.depth,
            "suppressed": row.suppressed,
            "description": row.description,
        }
        for row in rows
    ]


def get_feature(feature_id: str) -> ToolResult:
    """Everything the package holds about one feature, plus what the method makes of it.

    The whole `Feature` as it was extracted, then `class`, `group`, `is_folder` and
    `is_end_tag` derived from the RMS type table and the group assignment, and then
    `child_names`, `parent_names` and `consumer_names` - the dependency, dependent and
    sketch-consumer id lists resolved to feature names, position by position.

    A null id list stays null: it means `GetChildren` or `GetParents` failed for this
    feature, which is not the same as having none. A name is null where the id names a
    feature this package does not carry. `consumer_names` is null for a feature that has
    no sketch at all; `sketch` itself says which of the two it is.

    Args:
        feature_id: Feature id, for example `feat:0004`.
    """
    context = current_context()
    package = context.ir
    found = next((row for row in package.features if row.id == feature_id), None)
    if found is None:
        return unknown_id("feature", feature_id)
    table = load_table()
    assignment = assign_groups(_rows_of(package, found.document_id), table)
    names = {row.id: row.name for row in package.features}
    result = as_json(found)
    result["class"] = class_of(found, table)
    result["group"] = assignment.by_feature_id[found.id]
    result["is_folder"] = table.is_folder(found)
    result["is_end_tag"] = table.is_end_tag(found)
    result["child_names"] = _resolved(found.child_ids, names)
    result["parent_names"] = _resolved(found.parent_ids, names)
    result["consumer_names"] = (
        None if found.sketch is None else _resolved(found.sketch.consumer_ids, names)
    )
    return result


def _rows_of(package: EvidencePackage, document_id: str) -> list[Feature]:
    """One document's feature rows in `index` order, whatever order they arrive in."""
    return sorted(
        (row for row in package.features if row.document_id == document_id),
        key=lambda row: row.index,
    )


def _in_folder(
    folder: str,
    rows: Sequence[Feature],
    assignment: GroupAssignment,
    table: RmsTypeTable,
) -> list[Feature] | None:
    """The rows `folder` selects, or `None` when it names no group and no folder here.

    A group name and a group folder's id select the same thing - the group - because a
    group is sticky over the traversal and a re-opened group folder re-opens the one
    group (`checks/rms/groups.py`). A folder that is not a group folder selects the rows
    whose derived subfolder is that folder.
    """
    group = folder if folder in table.groups else None
    if group is None:
        named = next((row for row in rows if row.id == folder), None)
        if named is None or not table.is_folder(named):
            return None
        if named.name not in table.groups:
            return [
                row for row in rows if assignment.subfolder_by_feature_id[row.id] == folder
            ]
        group = named.name
    return [row for row in rows if assignment.by_feature_id[row.id] == group]


def _resolved(ids: list[str] | None, names: Mapping[str, str]) -> list[str | None] | None:
    """`ids` as feature names, position by position; `None` for an id nobody carries."""
    if ids is None:
        return None
    return [names.get(entity_id) for entity_id in ids]
