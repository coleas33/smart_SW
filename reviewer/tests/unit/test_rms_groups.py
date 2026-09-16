"""Unit tests for the RMS group assigner (T009).

`specs/003-resilient-modeling/contracts/rules.md` ("Group assignment") is normative and
says the same tree must come out the same way in both traversal shapes, so nearly every
test here runs over `nested` and `flat` and asserts by feature *name*: the shapes differ in
ids, depth, `folder_id` and end-tag rows, and the point of the assigner is that none of
that changes which group a feature is in.

What is pinned hardest is the half a rule must never guess: sticky semantics (a group
folder opens a group and everything after it stays in that group until the next group
folder, end tags included), no group at all before the first group folder, and derived
subfolders that close where the shape says they close - by `folder_id` in the nested shape,
at the folder's own end-tag marker in the flat one.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from swreview.checks.rms.groups import GroupAssignment, assign_groups
from swreview.checks.rms_types import load_table
from swreview.ir.models import Feature
from tests.support.features import (
    END_TAG_SUFFIX,
    FOLDER_TYPE,
    FeatureSpec,
    build_features,
    end_tag,
    feature,
    fillet_feature,
    folder,
    sketch_feature,
)

TABLE = load_table()
SHAPES = ("nested", "flat")


def assign(specs: Sequence[FeatureSpec], shape: str) -> tuple[list[Feature], GroupAssignment]:
    rows = build_features(specs, document_id="doc:2", shape=shape)
    return rows, assign_groups(rows, TABLE)


def groups_of(rows: Sequence[Feature], assignment: GroupAssignment) -> dict[str, str | None]:
    """The group of every row, keyed by name (names are unique within a document)."""
    return {row.name: assignment.by_feature_id[row.id] for row in rows}


def subfolders_of(rows: Sequence[Feature], assignment: GroupAssignment) -> dict[str, str | None]:
    """The derived subfolder of every row, with the subfolder id read back as its name."""
    name_by_id = {row.id: row.name for row in rows}
    subfolders: dict[str, str | None] = {}
    for row in rows:
        subfolder_id = assignment.subfolder_by_feature_id[row.id]
        subfolders[row.name] = None if subfolder_id is None else name_by_id[subfolder_id]
    return subfolders


def rename_folder(rows: Sequence[Feature], old: str, new: str) -> list[Feature]:
    """Rename a folder and its end-tag marker.

    `build_features` forbids two rows with the same name, and a duplicate group folder is
    exactly two rows with the same name, so the fixture is built with a distinct name and
    renamed here.
    """
    swap = {old: new, f"{old}{END_TAG_SUFFIX}": f"{new}{END_TAG_SUFFIX}"}
    return [
        row.model_copy(update={"name": swap[row.name]}) if row.name in swap else row
        for row in rows
    ]


def consumed_by(rows: Sequence[Feature], sub_feature: str, owner: str) -> list[Feature]:
    """Nest `sub_feature` under `owner`, whatever traversal shape the folders are in.

    `GetFirstSubFeature` lists the sketch an extrusion consumed whether or not *folders*
    report their contents that way (research.md open question 1 is about folder contents
    only), so a real dump mixes the two: flat folders with end-tag markers, and ordinary
    features that own sub-features. `build_features` emits one shape throughout, so the
    mixed tree is made here.
    """
    owner_id = next(row.id for row in rows if row.name == owner)
    return [
        row.model_copy(update={"depth": row.depth + 1, "folder_id": owner_id})
        if row.name == sub_feature
        else row
        for row in rows
    ]


def core_specs() -> list[FeatureSpec]:
    """A plane, two group folders, and a feature trailing the second folder's contents."""
    return [
        feature("Front Plane", "RefPlane"),
        folder("1-Ref", feature("Plane1", "RefPlane")),
        folder(
            "3-Core",
            sketch_feature("Sketch1", consumers=("Boss-Extrude1",)),
            feature("Boss-Extrude1", "Extrusion", parent_names=("Sketch1",)),
        ),
        feature("Shell1", "Shell"),
    ]


# --- sticky semantics -------------------------------------------------------------


@pytest.mark.parametrize("shape", SHAPES)
def test_a_group_folder_opens_a_group_that_sticks_past_its_contents(shape: str) -> None:
    rows, assignment = assign(core_specs(), shape)

    groups = groups_of(rows, assignment)
    assert groups["Front Plane"] is None
    assert groups["1-Ref"] == "1-Ref"
    assert groups["Plane1"] == "1-Ref"
    assert groups["3-Core"] == "3-Core"
    assert groups["Sketch1"] == "3-Core"
    assert groups["Boss-Extrude1"] == "3-Core"
    assert groups["Shell1"] == "3-Core"


@pytest.mark.parametrize("shape", SHAPES)
def test_features_before_the_first_group_folder_have_no_group(shape: str) -> None:
    specs = [
        feature("Front Plane", "RefPlane"),
        folder("Misc", feature("Boss-Extrude1", "Extrusion")),
        folder("3-Core", feature("Boss-Extrude2", "Extrusion")),
    ]

    rows, assignment = assign(specs, shape)

    groups = groups_of(rows, assignment)
    assert groups["Front Plane"] is None
    assert groups["Misc"] is None
    assert groups["Boss-Extrude1"] is None
    assert groups["Boss-Extrude2"] == "3-Core"
    core = next(row for row in rows if row.name == "3-Core")
    assert assignment.groups_seen == [("3-Core", core.id)]


@pytest.mark.parametrize("shape", SHAPES)
def test_a_document_with_no_group_folder_has_no_group_anywhere(shape: str) -> None:
    rows, assignment = assign([folder("Misc", feature("Boss-Extrude1", "Extrusion"))], shape)

    assert set(groups_of(rows, assignment).values()) == {None}
    assert assignment.groups_seen == []
    assert assignment.duplicates == []
    assert assignment.order_ok is True


@pytest.mark.parametrize("group", TABLE.groups)
def test_every_group_name_in_the_table_opens_a_group(group: str) -> None:
    rows, assignment = assign([folder(group, feature("Boss-Extrude1", "Extrusion"))], "nested")

    assert groups_of(rows, assignment)["Boss-Extrude1"] == group
    assert assignment.groups_seen == [(group, rows[0].id)]


@pytest.mark.parametrize("shape", SHAPES)
def test_a_group_folder_nested_inside_another_folder_opens_the_group(shape: str) -> None:
    specs = [
        folder(
            "Misc",
            folder("3-Core", feature("Boss-Extrude1", "Extrusion")),
            feature("Trailing-Fillet", "Fillet"),
        )
    ]

    rows, assignment = assign(specs, shape)

    groups = groups_of(rows, assignment)
    assert groups["Misc"] is None
    assert groups["3-Core"] == "3-Core"
    assert groups["Boss-Extrude1"] == "3-Core"
    assert groups["Trailing-Fillet"] == "3-Core"


def test_the_assignment_follows_index_order_not_list_order() -> None:
    rows, assignment = assign(core_specs(), "nested")

    shuffled = assign_groups(list(reversed(rows)), TABLE)

    assert shuffled == assignment
    assert groups_of(rows, shuffled)["Shell1"] == "3-Core"


# --- end-tag markers --------------------------------------------------------------


def test_an_end_tag_never_changes_the_group_and_content_after_it_stays_in_the_group() -> None:
    rows, assignment = assign(core_specs(), "flat")

    groups = groups_of(rows, assignment)
    assert groups[f"1-Ref{END_TAG_SUFFIX}"] == "1-Ref"
    assert groups[f"3-Core{END_TAG_SUFFIX}"] == "3-Core"
    assert groups["Shell1"] == "3-Core"


@pytest.mark.parametrize("shape", SHAPES)
def test_an_end_tag_named_for_a_group_never_opens_that_group(shape: str) -> None:
    specs = [end_tag("3-Core"), feature("Boss-Extrude1", "Extrusion")]

    rows, assignment = assign(specs, shape)

    assert groups_of(rows, assignment) == {f"3-Core{END_TAG_SUFFIX}": None, "Boss-Extrude1": None}
    assert assignment.groups_seen == []
    assert assignment.duplicates == []


def test_end_tags_are_never_recorded_as_group_folders() -> None:
    rows, assignment = assign(core_specs(), "flat")

    recorded = {feature_id for _, feature_id in assignment.groups_seen}
    end_tags = {row.id for row in rows if row.name.endswith(END_TAG_SUFFIX)}
    assert end_tags
    assert recorded & end_tags == set()


# --- derived subfolders -----------------------------------------------------------


def subfolder_specs() -> list[FeatureSpec]:
    """A group folder holding a loose hole, a subfolder of two, and a trailing fillet."""
    return [
        folder(
            "4-Detail",
            feature("Hole1", "HoleWzd"),
            folder(
                "Boss pair",
                sketch_feature("Sketch2", consumers=("Boss-Extrude2",)),
                feature("Boss-Extrude2", "Extrusion", parent_names=("Sketch2",)),
            ),
            fillet_feature("Fillet1"),
        ),
        fillet_feature("Fillet2"),
    ]


@pytest.mark.parametrize("shape", SHAPES)
def test_a_non_group_folder_yields_a_derived_subfolder_for_its_members(shape: str) -> None:
    rows, assignment = assign(subfolder_specs(), shape)

    subfolders = subfolders_of(rows, assignment)
    assert subfolders["Sketch2"] == "Boss pair"
    assert subfolders["Boss-Extrude2"] == "Boss pair"
    assert subfolders["Boss pair"] is None
    assert groups_of(rows, assignment)["Boss-Extrude2"] == "4-Detail"


@pytest.mark.parametrize("shape", SHAPES)
def test_a_group_folder_is_not_a_derived_subfolder(shape: str) -> None:
    rows, assignment = assign(subfolder_specs(), shape)

    subfolders = subfolders_of(rows, assignment)
    assert subfolders["4-Detail"] is None
    assert subfolders["Hole1"] is None


@pytest.mark.parametrize("shape", SHAPES)
def test_a_derived_subfolder_closes_where_the_shape_says_it_closes(shape: str) -> None:
    rows, assignment = assign(subfolder_specs(), shape)

    subfolders = subfolders_of(rows, assignment)
    assert subfolders["Fillet1"] is None
    assert subfolders["Fillet2"] is None


@pytest.mark.parametrize("shape", SHAPES)
def test_a_derived_subfolder_survives_a_group_folder_nested_inside_it(shape: str) -> None:
    specs = [
        folder(
            "Misc",
            folder("3-Core", feature("Boss-Extrude1", "Extrusion")),
            feature("Trailing-Fillet", "Fillet"),
        )
    ]

    rows, assignment = assign(specs, shape)

    subfolders = subfolders_of(rows, assignment)
    assert subfolders["Misc"] is None
    assert subfolders["3-Core"] == "Misc"
    assert subfolders["Boss-Extrude1"] is None
    assert subfolders["Trailing-Fillet"] == "Misc"


def test_a_flat_subfolder_closes_at_its_own_end_tag_not_the_groups() -> None:
    rows, assignment = assign(subfolder_specs(), "flat")

    subfolders = subfolders_of(rows, assignment)
    assert subfolders[f"Boss pair{END_TAG_SUFFIX}"] is None
    assert subfolders[f"4-Detail{END_TAG_SUFFIX}"] is None


def test_a_flat_folder_left_unclosed_keeps_its_members_to_the_end() -> None:
    """With nothing enclosing it, an unclosed folder runs on, as "until its own end-tag
    marker" says it does."""
    specs = [
        folder("Misc", feature("Boss-Extrude1", "Extrusion"), end_tag=False),
        fillet_feature("Fillet2"),
    ]

    rows, assignment = assign(specs, "flat")

    subfolders = subfolders_of(rows, assignment)
    assert subfolders["Boss-Extrude1"] == "Misc"
    assert subfolders["Fillet2"] == "Misc"


def test_a_flat_folder_left_unclosed_still_ends_with_the_folder_around_it() -> None:
    """A folder that closes takes any folder left open inside it with it.

    The contract closes a subfolder at its own end-tag marker and says nothing about a
    marker that never comes. Ending it with its enclosing folder keeps it inside that
    folder, as the nested shape does, and stops one malformed row making a coupled pair out
    of two features in different groups - a fail rule must not be excused by a missing tag.
    """
    specs = [
        folder(
            "4-Detail",
            folder("Boss pair", feature("Boss-Extrude2", "Extrusion"), end_tag=False),
        ),
        fillet_feature("Fillet2"),
    ]

    rows, assignment = assign(specs, "flat")

    subfolders = subfolders_of(rows, assignment)
    assert subfolders["Boss-Extrude2"] == "Boss pair"
    assert subfolders[f"4-Detail{END_TAG_SUFFIX}"] is None
    assert subfolders["Fillet2"] is None


def pattern_specs(*, subfolder: bool) -> list[FeatureSpec]:
    """A pattern - an ordinary feature that owns sub-features - in the Detail group.

    `subfolder=True` puts it inside a non-group folder, which is the only thing that may
    open a derived subfolder for its members.
    """
    pattern = FeatureSpec(
        name="LPattern1",
        type_name="LPattern",
        contents=(
            feature("Boss-Extrude2", "Extrusion"),
            sketch_feature("Sketch9", consumers=()),
        ),
    )
    return [folder("4-Detail", folder("Boss pair", pattern) if subfolder else pattern)]


@pytest.mark.parametrize("shape", SHAPES)
def test_a_feature_that_owns_sub_features_opens_no_derived_subfolder(shape: str) -> None:
    """Only a folder opens a subfolder, so a pattern's seeds are not a coupled pair.

    `Feature.folder_id` is the nearest enclosing *feature* (data-model section 1) and the
    indexer nests whatever `GetFirstSubFeature` listed, so reading it as the subfolder
    would pair up the two seeds of this pattern and excuse a Detail-to-Detail reference.
    """
    rows, assignment = assign(pattern_specs(subfolder=False), shape)

    subfolders = subfolders_of(rows, assignment)
    assert subfolders["LPattern1"] is None
    assert subfolders["Boss-Extrude2"] is None
    assert subfolders["Sketch9"] is None


@pytest.mark.parametrize("shape", SHAPES)
def test_sub_features_take_the_folder_around_the_feature_that_owns_them(shape: str) -> None:
    """One level down inside a real subfolder is still inside that subfolder."""
    rows, assignment = assign(pattern_specs(subfolder=True), shape)

    subfolders = subfolders_of(rows, assignment)
    assert subfolders["LPattern1"] == "Boss pair"
    assert subfolders["Boss-Extrude2"] == "Boss pair"
    assert subfolders["Sketch9"] == "Boss pair"


def test_flat_folders_survive_a_feature_that_owns_sub_features() -> None:
    """The mixed tree a real dump produces: flat folders, and one consumed sketch nested.

    The traversal shape is a statement about folders, so one nested sub-feature must not
    put the whole document into the nested shape and lose every flat folder's membership.
    """
    specs = [
        folder(
            "4-Detail",
            folder(
                "Boss pair",
                feature(
                    "Boss-Extrude2",
                    "Extrusion",
                    contents=(sketch_feature("Sketch2", consumers=()),),
                ),
                fillet_feature("Fillet1"),
            ),
        ),
        fillet_feature("Fillet2"),
    ]
    rows = consumed_by(
        build_features(specs, document_id="doc:2", shape="flat"), "Sketch2", "Boss-Extrude2"
    )

    assignment = assign_groups(rows, TABLE)

    subfolders = subfolders_of(rows, assignment)
    assert subfolders["Boss-Extrude2"] == "Boss pair"
    assert subfolders["Sketch2"] == "Boss pair"
    assert subfolders["Fillet1"] == "Boss pair"
    assert subfolders["Fillet2"] is None
    assert groups_of(rows, assignment)["Fillet2"] == "4-Detail"


# --- duplicates and order ---------------------------------------------------------


@pytest.mark.parametrize("shape", SHAPES)
def test_a_duplicate_group_name_re_opens_the_group_and_is_recorded(shape: str) -> None:
    specs = [
        folder("3-Core", feature("Boss-Extrude1", "Extrusion")),
        folder("4-Detail", feature("Hole1", "HoleWzd")),
        folder("3-Core again", fillet_feature("Fillet1")),
    ]
    built = build_features(specs, document_id="doc:2", shape=shape)
    rows = rename_folder(built, "3-Core again", "3-Core")

    assignment = assign_groups(rows, TABLE)

    first, second = [row.id for row in rows if row.name == "3-Core"]
    detail = next(row for row in rows if row.name == "4-Detail")
    assert assignment.groups_seen == [
        ("3-Core", first),
        ("4-Detail", detail.id),
        ("3-Core", second),
    ]
    assert assignment.duplicates == [("3-Core", second)]
    assert assignment.order_ok is False
    assert groups_of(rows, assignment)["Fillet1"] == "3-Core"


@pytest.mark.parametrize("shape", SHAPES)
def test_order_ok_is_true_when_the_groups_follow_the_table_order(shape: str) -> None:
    specs = [
        folder(group, feature(f"Boss-Extrude{index}", "Extrusion"))
        for index, group in enumerate(TABLE.groups)
    ]

    _, assignment = assign(specs, shape)

    assert assignment.order_ok is True
    assert [group for group, _ in assignment.groups_seen] == list(TABLE.groups)
    assert assignment.duplicates == []


@pytest.mark.parametrize("shape", SHAPES)
def test_order_ok_is_false_when_two_groups_are_out_of_order(shape: str) -> None:
    specs = [
        folder("4-Detail", feature("Hole1", "HoleWzd")),
        folder("3-Core", feature("Boss-Extrude1", "Extrusion")),
    ]

    _, assignment = assign(specs, shape)

    assert assignment.order_ok is False
    assert assignment.duplicates == []


@pytest.mark.parametrize("count", [0, 1])
def test_order_ok_is_true_with_fewer_than_two_groups(count: int) -> None:
    specs = [
        folder(group, feature(f"Boss-Extrude{index}", "Extrusion"))
        for index, group in enumerate(TABLE.groups[:count])
    ]

    _, assignment = assign(specs or [feature("Front Plane", "RefPlane")], "nested")

    assert assignment.order_ok is True


# --- completeness -----------------------------------------------------------------


@pytest.mark.parametrize("shape", SHAPES)
def test_every_feature_has_an_entry_in_both_maps(shape: str) -> None:
    rows, assignment = assign([*core_specs(), *subfolder_specs()], shape)

    ids = [row.id for row in rows]
    assert list(assignment.by_feature_id) == ids
    assert list(assignment.subfolder_by_feature_id) == ids


def test_an_empty_tree_assigns_nothing() -> None:
    assignment = assign_groups([], TABLE)

    assert assignment == GroupAssignment(
        by_feature_id={},
        subfolder_by_feature_id={},
        groups_seen=[],
        duplicates=[],
        order_ok=True,
    )


def test_the_folder_type_decides_what_a_folder_is() -> None:
    """A folder-named feature of another type opens nothing (`is_folder` is the table's)."""
    specs = [feature("3-Core", "Extrusion"), feature("Boss-Extrude1", "Extrusion")]

    rows, assignment = assign(specs, "nested")

    assert rows[0].type_name != FOLDER_TYPE
    assert groups_of(rows, assignment) == {"3-Core": None, "Boss-Extrude1": None}
    assert assignment.groups_seen == []
