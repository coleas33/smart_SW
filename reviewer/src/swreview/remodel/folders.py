"""The folder half of the plan: which of the six folders this run creates, and which it refuses.

`data-model.md` section 1.6, FR-015 and `research.md` R6.6. A folder is created by selecting
a **contiguous** run of features and calling `InsertFeatureTreeFolder2(Containing = 2)` then
`set_Name`, so contiguity is a precondition of the action and never something discovered
afterwards: `FolderAction.contiguous` is `True` on every action this module emits, and a
group whose members are split is simply not wrapped. Naming the interloper is
`feasibility.py`'s `splits_group` entry, not a folder action.

Four rules, and the fourth is the one that costs a part its run:

1. **an existing folder with exactly the right members is a no-op.** The action is still
   emitted, carrying the folder's id and `status="no_op"`, so the report can say "already
   correct" rather than saying nothing;
2. **a derived subfolder is preserved, never dissolved.** It enters its group as one member,
   which is also how `Select2` reaches it, so the plan names the subfolder and never its
   contents. A subfolder whose members would land in two different groups is not split: both
   groups go unwrapped, because splitting it would dissolve it in all but name;
3. **membership equality is decided on ids.** SOLIDWORKS permits two features to share a
   name, so a folder holding a feature that merely shares a name with an expected member
   holds the wrong feature. Names are compared nowhere in this module except against the six
   group names, which are folder names and not feature names;
4. **an existing folder carrying one of the six names but holding anything else is
   `rms_named_folder_wrong_members`**, and in v1 that refuses the part. Repairing it would
   mean dissolving it, which needs `IModelDoc2.EditDelete`, which the owner deliberately
   left off the stage-1 allowlist (`research.md` R12 OQ-3). The token comes from
   `remodel/scope.py`, which owns the closed `Refusal` code set, rather than being spelled
   here: a token that differed by an underscore would be a refusal that maps to nothing.

**There is no move-into-an-existing-folder operation in v1 at all.** It would put three
UNVERIFIED calls on the critical path (R3.3), and it is not needed: an existing folder is
either already right or a refusal, so it is never a destination. `FolderAction.op` keeps the
bridge command's name space (`create`, `rename`), and stage 2's `dissolve` is an allowlist
entry away rather than a protocol change.

The existing folders and the derived-subfolder membership are read through feature 003's
`assign_groups`, which is the one implementation of "where does this feature sit"; this
module re-derives neither.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms_types import RmsTypeTable
from swreview.ir.models import Feature
from swreview.remodel.scope import RMS_NAMED_FOLDER_WRONG_MEMBERS

__all__ = [
    "ExistingFolder",
    "FolderAction",
    "FolderPlan",
    "FolderRefusal",
    "existing_folders",
    "plan_folders",
]


@dataclass(frozen=True)
class ExistingFolder:
    """A folder the part already carries, with its **direct** members in tree order.

    Direct, not flattened: a subfolder counts once, as itself, which is the same unit the
    plan wraps and the same unit `Select2` reaches. Comparing a flattened listing against a
    planned one would report a correct nested folder as wrong members.
    """

    folder_id: str
    name: str
    member_ids: tuple[str, ...]
    is_group_folder: bool
    """Whether `name` is one of the six group names; everything else is a derived subfolder."""


class FolderAction(BaseModel):
    """One folder the plan creates, or one it found already correct (section 1.6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["create", "rename"]
    name: str
    member_feature_ids: tuple[str, ...]
    contiguous: bool
    existing_folder_id: str | None
    status: Literal["planned", "no_op"]


class FolderRefusal(BaseModel):
    """An existing folder carrying a group name that this version cannot repair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    existing_folder_id: str
    name: str
    expected_member_ids: tuple[str, ...]
    actual_member_ids: tuple[str, ...]
    reason: Literal["rms_named_folder_wrong_members"]


class FolderPlan(BaseModel):
    """The whole folder plan. A non-empty `refusals` makes the run a refusal in v1."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actions: tuple[FolderAction, ...]
    refusals: tuple[FolderRefusal, ...]

    @property
    def refused(self) -> bool:
        return bool(self.refusals)


def existing_folders(
    features: Sequence[Feature], table: RmsTypeTable
) -> tuple[ExistingFolder, ...]:
    """Every folder in the tree, in tree order, with its direct members.

    A folder's direct members are the rows whose nearest enclosing folder is it, which is
    `assign_groups().enclosing_folder_by_feature_id` and nothing else: that walk is the one
    place the two traversal shapes are reconciled - `folder_id` in the nested shape, the
    end-tag markers in the flat one - and a second walk here over `folder_id` alone would
    report every group folder of a flat document as holding nothing, which refuses a part
    that is completely correct on evidence that was never read.

    An end-tag marker is not a member of anything: it closes a folder, and `assign_groups`
    closes that folder before it places the marker, so the marker reads as enclosed by the
    folder *outside* the one it ends. Dropping it here is the one row this function filters.
    """
    rows = sorted(features, key=lambda row: row.index)
    group_names = set(table.groups)
    enclosing_by_id = assign_groups(features, table).enclosing_folder_by_feature_id
    members: dict[str, list[str]] = {row.id: [] for row in rows if table.is_folder(row)}
    for row in rows:
        enclosing = enclosing_by_id[row.id]
        if enclosing is not None and not table.is_end_tag(row):
            members[enclosing].append(row.id)
    return tuple(
        ExistingFolder(
            folder_id=row.id,
            name=row.name,
            member_ids=tuple(members[row.id]),
            is_group_folder=row.name in group_names,
        )
        for row in rows
        if table.is_folder(row)
    )


def plan_folders(
    features: Sequence[Feature],
    table: RmsTypeTable,
    *,
    order: Sequence[str],
    target_group_by_id: Mapping[str, str],
) -> FolderPlan:
    """Plan one folder per group whose members come out contiguous in `order`.

    `order` is the **achievable** order of the content features - what the reorder (C3)
    leaves behind - because folder creation (C4) runs after it and contiguity is only true
    once the order is achieved. `target_group_by_id` is the resolved target of each content
    feature; a feature with no resolved target is in no group and therefore in no folder.

    Contiguity is checked before the action is emitted, for the folder that already exists
    as much as for the one that does not: a correct folder is only a no-op while the order
    the reorder achieves keeps its members together, and claiming `contiguous=True` without
    having looked would be the one field of the action nobody proved.

    Raises `ValueError` for a target naming a feature that is not in `order`, and for a
    target naming a group the table does not carry: a plan that silently dropped either
    would wrap the wrong run.
    """
    groups = table.groups
    unknown = sorted(set(target_group_by_id.values()) - set(groups))
    if unknown:
        raise ValueError(
            f"{unknown} is not one of the six groups {list(groups)}; the planner and the "
            "checker read one table and cannot disagree about what a group is"
        )
    missing = sorted(set(target_group_by_id) - set(order))
    if missing:
        raise ValueError(
            f"{missing} carry a target group but are not in the achievable order, so the "
            "run to wrap them in is unknown"
        )

    folders = existing_folders(features, table)
    subfolder_by_id = assign_groups(features, table).subfolder_by_feature_id
    slots = _slots(order, subfolder_by_id)
    group_of_slot = _group_of_slot(order, slots, subfolder_by_id, target_group_by_id)
    existing_by_name: dict[str, list[ExistingFolder]] = {}
    for found in folders:
        if found.is_group_folder:
            existing_by_name.setdefault(found.name, []).append(found)

    actions: list[FolderAction] = []
    refusals: list[FolderRefusal] = []
    for group in groups:
        members = tuple(slot for slot in slots if group_of_slot[slot] == group)
        found = existing_by_name.get(group, [])
        if len(found) > 1 or (found and set(found[0].member_ids) != set(members)):
            refusals.extend(
                FolderRefusal(
                    existing_folder_id=one.folder_id,
                    name=group,
                    expected_member_ids=members,
                    actual_member_ids=one.member_ids,
                    reason=RMS_NAMED_FOLDER_WRONG_MEMBERS,
                )
                for one in found
            )
            continue
        if not members or not _contiguous(slots, members):
            continue
        actions.append(
            FolderAction(
                op="create",
                name=group,
                member_feature_ids=members,
                contiguous=True,
                existing_folder_id=found[0].folder_id if found else None,
                status="no_op" if found else "planned",
            )
        )

    return FolderPlan(actions=tuple(actions), refusals=tuple(refusals))


def _slot_of(feature_id: str, subfolder_by_id: Mapping[str, str | None]) -> str:
    """The unit of the run this feature travels in: the **outermost** derived subfolder
    holding it, or the feature itself when no subfolder does.

    Outermost, not nearest: a subfolder nested two deep is reached by selecting the one
    that is directly in the group, and selecting the inner one would leave the outer one
    half in and half out of the folder being created. `subfolder_by_feature_id` answers
    "the nearest derived folder", and it answers it for a folder row too, so walking it to
    a fixed point walks outwards until the next folder out is a group folder (`None`).
    """
    slot = feature_id
    while (outer := subfolder_by_id.get(slot)) is not None:
        slot = outer
    return slot


def _slots(order: Sequence[str], subfolder_by_id: Mapping[str, str | None]) -> tuple[str, ...]:
    """`order` with every derived subfolder's members collapsed onto the subfolder itself.

    A subfolder is preserved, so it is one unit of the run: the plan wraps it, never its
    contents. Consecutive members of one subfolder therefore contribute one slot.
    """
    slots: list[str] = []
    for feature_id in order:
        slot = _slot_of(feature_id, subfolder_by_id)
        if not slots or slots[-1] != slot:
            slots.append(slot)
    return tuple(slots)


def _group_of_slot(
    order: Sequence[str],
    slots: Sequence[str],
    subfolder_by_id: Mapping[str, str | None],
    target_group_by_id: Mapping[str, str],
) -> dict[str, str | None]:
    """The group each slot belongs to, or `None` when it has none or its members disagree.

    A derived subfolder's group is the one group every member of it targets. A member with
    no target contributes `None` and so leaves the subfolder groupless: preserving a
    subfolder and splitting it are the same thing stated twice, so neither group is wrapped
    and the disagreement is reported by `feasibility.py` instead. The members are the rows
    of `order` and only those, so a row the order does not carry - a folder, a tolerated
    type, an excluded default name - travels with its subfolder and casts no vote.
    """
    groups_by_slot: dict[str, set[str | None]] = {slot: set() for slot in slots}
    for feature_id in order:
        slot = _slot_of(feature_id, subfolder_by_id)
        groups_by_slot[slot].add(target_group_by_id.get(feature_id))
    return {
        slot: next(iter(groups)) if len(groups) == 1 and None not in groups else None
        for slot, groups in groups_by_slot.items()
    }


def _contiguous(slots: Sequence[str], members: Sequence[str]) -> bool:
    """Whether `members` occupy one unbroken run of `slots`."""
    positions = [index for index, slot in enumerate(slots) if slot in set(members)]
    return bool(positions) and positions[-1] - positions[0] + 1 == len(positions)
