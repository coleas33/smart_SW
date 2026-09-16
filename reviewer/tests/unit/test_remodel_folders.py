"""Unit tests for the folder half of the plan (T018).

`data-model.md` section 1.6, FR-015 and `research.md` R6.6 give the whole specification,
and it is five claims:

- **each of the six folders is created once, over a run proven contiguous first.** Every
  emitted `FolderAction` carries `contiguous=True`, because contiguity is a precondition of
  the creation and not a property discovered afterwards; a group whose members are split by
  an interloper is simply not wrapped, and `feasibility.py` is what reports the interloper;
- **an existing folder with exactly the right members is a no-op**, and membership equality
  is decided on **ids**. SOLIDWORKS permits two features to share a name, so a folder
  holding a feature that merely shares a name with an expected member holds the wrong
  feature;
- **an existing folder with a subset or a superset is `rms_named_folder_wrong_members`**,
  the one token of the closed `Refusal` code set of `data-model.md` section 4.2, taken from
  `remodel/scope.py` rather than spelled at this call site. In v1 that refuses the part:
  dissolving a folder needs `IModelDoc2.EditDelete`, which the owner deliberately left off
  the stage-1 allowlist, so there is no repair path;
- **a derived subfolder is preserved and never dissolved.** It travels into its group as one
  member, which is also how `Select2` would reach it, so the plan names the subfolder and
  never its contents;
- **no plan ever contains a move-into-an-existing-folder step.** There is no such operation
  in v1 at all - it would need three UNVERIFIED calls on the critical path (R3.3) - so an
  existing folder is either already right (a no-op) or a refusal, and never a destination.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import get_args

import pytest

from swreview.checks.rms_types import load_table
from swreview.ir.models import EvidencePackage, Feature
from swreview.remodel.folders import (
    FolderAction,
    FolderPlan,
    existing_folders,
    plan_folders,
)
from swreview.remodel.scope import REFUSAL_CODES, RMS_NAMED_FOLDER_WRONG_MEMBERS
from tests.support.features import Shape, feature, fillet_feature, folder, sketch_feature
from tests.support.remodel import (
    derived_subfolder_features,
    linked,
    mis_membered_group_folder_features,
    remodel_package,
)

TABLE = load_table()
GROUPS = TABLE.groups
SHAPES: tuple[Shape, ...] = ("nested", "flat")
"""Both traversal shapes of `IFeatureManager`. A folder's members are its sub-features in
one and the rows up to its end-tag marker in the other, and every reading of "who is in
this folder" has to give the same answer in both or a correct part is refused in one."""


def ids_by_name(package: EvidencePackage) -> dict[str, str]:
    """Feature ids keyed by name; only for fixtures whose names are unique."""
    names = [row.name for row in package.features]
    assert len(names) == len(set(names)), "this helper is for fixtures with unique names"
    return {row.name: row.id for row in package.features}


def content_order(package: EvidencePackage) -> tuple[str, ...]:
    """The tree order of the content features, which is what the achievable order is over."""
    return tuple(row.id for row in package.features if TABLE.is_content(row))


def plan(
    package: EvidencePackage,
    targets: Mapping[str, str],
    *,
    order: Sequence[str] | None = None,
) -> FolderPlan:
    return plan_folders(
        package.features,
        TABLE,
        order=content_order(package) if order is None else order,
        target_group_by_id=targets,
    )


def named(actions: Sequence[FolderAction]) -> list[str]:
    return [action.name for action in actions]


# --- the six folders --------------------------------------------------------------


def six_group_package() -> tuple[EvidencePackage, dict[str, str], dict[str, str]]:
    """One feature per group, already in the method's order and with no existing folder."""
    rows = [
        feature("Axis1", "RefAxis"),
        sketch_feature("Sketch1"),
        feature("Boss-Extrude1", "Extrusion"),
        feature("Hole1", "HoleWzd"),
        feature("Mirror1", "MirrorPattern"),
        fillet_feature("Fillet1"),
    ]
    package = remodel_package(rows)
    ids = ids_by_name(package)
    targets = {
        ids["Axis1"]: "1-Ref",
        ids["Sketch1"]: "2-Construction",
        ids["Boss-Extrude1"]: "3-Core",
        ids["Hole1"]: "4-Detail",
        ids["Mirror1"]: "5-Modify",
        ids["Fillet1"]: "6-Quarantine",
    }
    return package, ids, targets


def test_each_of_the_six_folders_is_planned_exactly_once() -> None:
    package, _, targets = six_group_package()

    result = plan(package, targets)

    assert named(result.actions) == list(GROUPS)
    assert len(set(named(result.actions))) == len(GROUPS) == 6
    assert result.refusals == ()
    assert result.refused is False


def test_every_emitted_action_was_proven_contiguous_before_creation() -> None:
    package, _, targets = six_group_package()

    result = plan(package, targets)

    assert all(action.contiguous for action in result.actions)
    assert all(action.status == "planned" for action in result.actions)
    assert all(action.existing_folder_id is None for action in result.actions)


def test_a_group_with_no_members_is_not_created() -> None:
    package, ids, _ = six_group_package()
    targets = {ids["Boss-Extrude1"]: "3-Core", ids["Hole1"]: "4-Detail"}

    result = plan(package, targets)

    assert named(result.actions) == ["3-Core", "4-Detail"]


def test_a_group_split_by_an_interloper_is_not_wrapped() -> None:
    """Contiguity is proven first, so a non-contiguous group produces no action at all;
    the interloper is `feasibility.py`'s `splits_group` entry, not a folder action."""
    package, ids, _ = six_group_package()
    targets = {
        ids["Boss-Extrude1"]: "3-Core",
        ids["Hole1"]: "4-Detail",
        ids["Mirror1"]: "3-Core",
    }

    result = plan(package, targets)

    assert named(result.actions) == ["4-Detail"]
    assert all(action.contiguous for action in result.actions)


def test_the_members_are_recorded_in_tree_order() -> None:
    package, ids, _ = six_group_package()
    targets = {
        ids["Boss-Extrude1"]: "3-Core",
        ids["Hole1"]: "3-Core",
        ids["Mirror1"]: "3-Core",
    }

    result = plan(package, targets)

    assert result.actions[0].member_feature_ids == (
        ids["Boss-Extrude1"],
        ids["Hole1"],
        ids["Mirror1"],
    )


def test_the_achievable_order_and_not_the_tree_order_decides_contiguity() -> None:
    """The folders are created after the reorder (C4), so the run that must be contiguous
    is the one the reorder achieves."""
    package, ids, _ = six_group_package()
    targets = {
        ids["Boss-Extrude1"]: "3-Core",
        ids["Hole1"]: "4-Detail",
        ids["Mirror1"]: "3-Core",
    }
    reordered = (ids["Boss-Extrude1"], ids["Mirror1"], ids["Hole1"])

    result = plan(package, targets, order=reordered)

    assert named(result.actions) == ["3-Core", "4-Detail"]
    assert result.actions[0].member_feature_ids == (ids["Boss-Extrude1"], ids["Mirror1"])


# --- an existing folder -----------------------------------------------------------


def existing_core_package(
    *, holds: Sequence[str] = ("Boss-Extrude1", "Fillet1"), shape: Shape = "nested"
) -> EvidencePackage:
    """A tree whose `3-Core` folder already holds `holds`, with `Hole1` outside it."""
    inside = {
        "Boss-Extrude1": feature("Boss-Extrude1", "Extrusion"),
        "Fillet1": fillet_feature("Fillet1"),
        "Hole1": feature("Hole1", "HoleWzd"),
    }
    rows = [
        sketch_feature("Sketch1"),
        folder("3-Core", *(inside[name] for name in holds)),
        *(row for name, row in inside.items() if name not in holds),
    ]
    return remodel_package(rows, shape=shape)


@pytest.mark.parametrize("shape", SHAPES)
def test_an_existing_folder_with_exactly_the_right_members_is_a_no_op(shape: Shape) -> None:
    package = existing_core_package(shape=shape)
    ids = ids_by_name(package)
    targets = {
        ids["Sketch1"]: "2-Construction",
        ids["Boss-Extrude1"]: "3-Core",
        ids["Fillet1"]: "3-Core",
        ids["Hole1"]: "4-Detail",
    }

    result = plan(package, targets)

    core = next(action for action in result.actions if action.name == "3-Core")
    assert core.status == "no_op"
    assert core.existing_folder_id == ids["3-Core"]
    assert core.member_feature_ids == (ids["Boss-Extrude1"], ids["Fillet1"])
    assert result.refusals == ()


def test_an_existing_folder_the_achievable_order_splits_is_not_a_no_op() -> None:
    """A correct folder is a no-op only while the order the reorder achieves keeps its
    members together; contiguity is proven for the folder that exists as well."""
    package = existing_core_package()
    ids = ids_by_name(package)
    targets = {
        ids["Sketch1"]: "2-Construction",
        ids["Boss-Extrude1"]: "3-Core",
        ids["Fillet1"]: "3-Core",
        ids["Hole1"]: "4-Detail",
    }
    split = (ids["Sketch1"], ids["Boss-Extrude1"], ids["Hole1"], ids["Fillet1"])

    result = plan(package, targets, order=split)

    assert "3-Core" not in named(result.actions)
    assert result.refusals == ()


def test_an_existing_folder_holding_a_superset_is_refused() -> None:
    package = existing_core_package(holds=("Boss-Extrude1", "Fillet1", "Hole1"))
    ids = ids_by_name(package)
    targets = {
        ids["Sketch1"]: "2-Construction",
        ids["Boss-Extrude1"]: "3-Core",
        ids["Fillet1"]: "3-Core",
        ids["Hole1"]: "4-Detail",
    }

    result = plan(package, targets)

    assert len(result.refusals) == 1
    refusal = result.refusals[0]
    assert refusal.name == "3-Core"
    assert refusal.existing_folder_id == ids["3-Core"]
    assert set(refusal.expected_member_ids) == {ids["Boss-Extrude1"], ids["Fillet1"]}
    assert ids["Hole1"] in refusal.actual_member_ids
    assert "3-Core" not in named(result.actions)
    assert result.refused is True


def test_an_existing_folder_holding_a_subset_is_refused() -> None:
    package = existing_core_package(holds=("Boss-Extrude1",))
    ids = ids_by_name(package)
    targets = {
        ids["Sketch1"]: "2-Construction",
        ids["Boss-Extrude1"]: "3-Core",
        ids["Fillet1"]: "3-Core",
        ids["Hole1"]: "4-Detail",
    }

    result = plan(package, targets)

    assert [refusal.name for refusal in result.refusals] == ["3-Core"]
    assert set(result.refusals[0].expected_member_ids) == {
        ids["Boss-Extrude1"],
        ids["Fillet1"],
    }
    assert result.refusals[0].actual_member_ids == (ids["Boss-Extrude1"],)


@pytest.mark.parametrize("shape", SHAPES)
def test_the_mis_membered_group_folder_fixture_refuses_the_part(shape: Shape) -> None:
    """The support fixture: `3-Core` is both a superset and a subset at once."""
    package = remodel_package(mis_membered_group_folder_features(), shape=shape)
    ids = ids_by_name(package)
    targets = {
        ids["Sketch1"]: "2-Construction",
        ids["Boss-Extrude1"]: "3-Core",
        ids["Cut-Extrude1"]: "4-Detail",
        ids["Hole1"]: "4-Detail",
        ids["Fillet1"]: "3-Core",
    }

    result = plan(package, targets)

    assert result.refused is True
    assert [refusal.reason for refusal in result.refusals] == [RMS_NAMED_FOLDER_WRONG_MEMBERS]


def test_the_refusal_reason_is_the_one_token_of_the_closed_scope_code_set() -> None:
    package = existing_core_package(holds=("Boss-Extrude1",))
    ids = ids_by_name(package)
    targets = {ids["Boss-Extrude1"]: "3-Core", ids["Fillet1"]: "3-Core"}

    result = plan(package, targets)

    assert result.refusals[0].reason == RMS_NAMED_FOLDER_WRONG_MEMBERS
    assert RMS_NAMED_FOLDER_WRONG_MEMBERS in REFUSAL_CODES


def test_an_rms_named_folder_the_plan_has_no_members_for_is_refused() -> None:
    package = existing_core_package(holds=("Boss-Extrude1",))
    ids = ids_by_name(package)
    targets = {ids["Boss-Extrude1"]: "4-Detail", ids["Fillet1"]: "4-Detail"}

    result = plan(package, targets)

    assert [refusal.name for refusal in result.refusals] == ["3-Core"]
    assert result.refusals[0].expected_member_ids == ()


def test_two_folders_carrying_the_same_group_name_are_both_refused() -> None:
    package = remodel_package(
        [
            folder("3-Core", feature("Boss-Extrude1", "Extrusion")),
            folder("3-Core", feature("Boss-Extrude2", "Extrusion")),
        ]
    )
    core_ids = [row.id for row in package.features if row.name == "3-Core"]
    targets = {
        row.id: "3-Core" for row in package.features if row.name.startswith("Boss-Extrude")
    }

    result = plan(package, targets)

    assert [refusal.existing_folder_id for refusal in result.refusals] == core_ids
    assert "3-Core" not in named(result.actions)


# --- membership equality is on ids ------------------------------------------------


@pytest.mark.parametrize("shape", SHAPES)
def test_membership_equality_is_decided_on_ids_and_never_on_names(shape: Shape) -> None:
    """Two features may share a name; a folder holding the other one holds the wrong one."""
    package = remodel_package(
        [
            folder("3-Core", fillet_feature("Fillet1")),
            fillet_feature("Fillet1"),
        ],
        shape=shape,
    )
    inside, outside = (row.id for row in package.features if row.name == "Fillet1")
    result = plan(package, {outside: "3-Core"})

    assert [refusal.name for refusal in result.refusals] == ["3-Core"]
    assert result.refusals[0].expected_member_ids == (outside,)
    assert result.refusals[0].actual_member_ids == (inside,)


# --- a derived subfolder ----------------------------------------------------------


def test_a_derived_subfolder_is_preserved_and_travels_as_one_member() -> None:
    package = remodel_package(derived_subfolder_features())
    ids = ids_by_name(package)
    targets = {
        ids["Sketch1"]: "2-Construction",
        ids["Boss-Extrude1"]: "3-Core",
        ids["Rib1"]: "3-Core",
        ids["Rib2"]: "3-Core",
    }

    result = plan(package, targets)

    core = next(action for action in result.actions if action.name == "3-Core")
    assert core.status == "no_op"
    assert core.member_feature_ids == (ids["Boss-Extrude1"], ids["Ribs"])
    assert ids["Rib1"] not in core.member_feature_ids
    assert result.refusals == ()


def test_a_derived_subfolder_is_never_named_by_an_action_or_a_refusal() -> None:
    package = remodel_package(derived_subfolder_features())
    ids = ids_by_name(package)
    targets = {
        ids["Sketch1"]: "2-Construction",
        ids["Boss-Extrude1"]: "3-Core",
        ids["Rib1"]: "3-Core",
        ids["Rib2"]: "3-Core",
    }

    result = plan(package, targets)

    assert "Ribs" not in named(result.actions)
    assert ids["Ribs"] not in [action.existing_folder_id for action in result.actions]
    assert "Ribs" not in [refusal.name for refusal in result.refusals]


def test_a_subfolder_whose_members_span_two_groups_wraps_neither_of_them() -> None:
    """A subfolder is preserved whole, so it cannot be half of one group and half of
    another; both groups are left unwrapped rather than the folder being split."""
    package = remodel_package(derived_subfolder_features())
    ids = ids_by_name(package)
    targets = {
        ids["Boss-Extrude1"]: "3-Core",
        ids["Rib1"]: "3-Core",
        ids["Rib2"]: "4-Detail",
    }

    result = plan(package, targets)

    assert "4-Detail" not in named(result.actions)
    assert all(ids["Ribs"] not in action.member_feature_ids for action in result.actions)


# --- no move into an existing folder ----------------------------------------------


def test_the_operation_set_is_closed_and_holds_no_move_or_dissolve() -> None:
    operations = set(get_args(FolderAction.model_fields["op"].annotation))

    assert operations == {"create", "rename"}
    assert not operations & {"move", "move_into", "dissolve", "delete"}


def test_no_plan_contains_a_move_into_an_existing_folder_step() -> None:
    package = existing_core_package()
    ids = ids_by_name(package)
    targets = {
        ids["Sketch1"]: "2-Construction",
        ids["Boss-Extrude1"]: "3-Core",
        ids["Fillet1"]: "3-Core",
        ids["Hole1"]: "4-Detail",
    }

    result = plan(package, targets)

    assert {action.op for action in result.actions} == {"create"}
    for action in result.actions:
        if action.existing_folder_id is not None:
            assert action.status == "no_op"


# --- the existing-folder reading --------------------------------------------------


@pytest.mark.parametrize("shape", SHAPES)
def test_existing_folders_reads_direct_members_and_names_the_group_folders(
    shape: Shape,
) -> None:
    package = remodel_package(derived_subfolder_features(), shape=shape)
    ids = ids_by_name(package)

    found = {found.name: found for found in existing_folders(package.features, TABLE)}

    assert set(found) == {"3-Core", "Ribs"}
    assert found["3-Core"].is_group_folder is True
    assert found["3-Core"].member_ids == (ids["Boss-Extrude1"], ids["Ribs"])
    assert found["Ribs"].is_group_folder is False
    assert found["Ribs"].member_ids == (ids["Rib1"], ids["Rib2"])


def test_an_end_tag_marker_is_never_read_as_a_member_of_any_folder() -> None:
    """The flat shape's `<name>___EndTag___` row is a marker that closes a folder, not a
    feature sitting in the one outside it."""
    package = remodel_package(derived_subfolder_features(), shape="flat")
    markers = {row.id for row in package.features if TABLE.is_end_tag(row)}

    found = existing_folders(package.features, TABLE)

    assert markers, "the flat shape marks the end of every folder"
    for one in found:
        assert not markers & set(one.member_ids), f"{one.name} holds an end-tag marker"


def test_a_target_outside_the_achievable_order_is_refused_rather_than_guessed() -> None:
    package, ids, targets = six_group_package()

    with pytest.raises(ValueError, match="not in the achievable order"):
        plan(package, targets, order=(ids["Boss-Extrude1"],))


def test_a_target_naming_a_group_the_table_does_not_carry_is_refused() -> None:
    package, ids, _ = six_group_package()

    with pytest.raises(ValueError, match="7-Invented"):
        plan(package, {ids["Boss-Extrude1"]: "7-Invented"})


def test_the_fixture_tree_is_the_shape_the_planner_receives() -> None:
    """A guard on the fixtures above: the builders stamp the Model check profile, and the
    dependency edges the support module declares are the ones the planner reads."""
    package = remodel_package(linked([feature("Boss-Extrude1", "Extrusion")]))

    assert package.extractor.profile == "model_check"
    assert all(isinstance(row, Feature) for row in package.features)
