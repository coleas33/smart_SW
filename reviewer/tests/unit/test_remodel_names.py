"""Unit tests for duplicate-name detection and the rename plan (feature 004 T012).

`IModelDocExtension.ReorderFeature` is **name-addressed** (`String FeatureToMove, String
TargetFeature`), SOLIDWORKS permits two features in different folders to share a name, and
a name-addressed reorder is then ambiguous with no error code to say so: the call returns
a bare `false`, or moves the wrong feature (research.md R3.7, FR-013). Name uniqueness is
therefore a **precondition** of this feature's whole reorder step, and this module is
where it is asserted.

What is pinned here:

- duplicates are found across the whole tree, folders included, in **one pass** over
  `features[]`;
- a repairable duplicate gets a unique, recorded, reversible new name: the previous name
  is carried so the inverse is a rename back, and the plan is complete - applying it
  leaves no two rows sharing a name;
- a feature that cannot be safely renamed goes on the rebuild list with reason
  `ambiguous_name` rather than being renamed anyway. Two conditions make a row unsafe, and
  both are the run's own rules rather than a guess: a row the grouping rules do not hold
  (a folder, an end-tag marker, a default plane, a tolerated system row) is not this
  step's to rename, and a name an equation references by text cannot be changed by a
  version that rewrites no equation (FR-029, FR-030).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from swreview.checks.rms_types import load_table
from swreview.ir.models import Equation, Feature
from swreview.remodel.names import (
    AMBIGUOUS_NAME,
    DUPLICATE_NAME,
    AmbiguousName,
    NamePlan,
    duplicate_names,
    plan_renames,
)
from tests.support.features import (
    EquationSpec,
    FeatureSpec,
    equation,
    feature,
    fillet_feature,
    folder,
    sketch_feature,
)
from tests.support.remodel import duplicate_name_features, remodel_package

TABLE = load_table()


def rows_of(
    specs: Sequence[FeatureSpec], equations: Sequence[EquationSpec] = ()
) -> tuple[list[Feature], list[Equation]]:
    package = remodel_package(list(specs), equations=list(equations))
    return list(package.features), list(package.equations)


def plan(
    specs: Sequence[FeatureSpec], equations: Sequence[EquationSpec] = ()
) -> NamePlan:
    rows, equation_rows = rows_of(specs, equations)
    return plan_renames(rows, equation_rows, TABLE)


def names_after(specs: Sequence[FeatureSpec], name_plan: NamePlan) -> list[str]:
    """Every row's name once the plan's renames have been applied."""
    rows, _ = rows_of(specs)
    renamed = {rename.feature_id: rename.after_name for rename in name_plan.renames}
    return [renamed.get(row.id, row.name) for row in rows]


# --- detection -----------------------------------------------------------------------


def test_duplicates_are_found_across_folder_boundaries() -> None:
    """The two `Fillet1` rows sit in different folders, which SOLIDWORKS permits and
    `ReorderFeature` cannot tell apart."""
    rows, _ = rows_of(duplicate_name_features())

    duplicates = duplicate_names(rows)

    assert set(duplicates) == {"Fillet1"}
    assert duplicates["Fillet1"] == tuple(
        row.id for row in rows if row.name == "Fillet1"
    )
    assert len(duplicates["Fillet1"]) == 2


def test_a_tree_with_unique_names_has_no_duplicates() -> None:
    rows, _ = rows_of(
        [feature("Boss-Extrude1", "Extrusion"), feature("Cut-Extrude1", "Cut")]
    )

    assert duplicate_names(rows) == {}


def test_folders_and_end_tag_markers_are_part_of_the_name_space() -> None:
    """A folder shares the tree's name space, so a feature that collides with one makes
    the reorder just as ambiguous as two features colliding."""
    rows, _ = rows_of(
        [
            folder("Fillet1", feature("Boss-Extrude1", "Extrusion")),
            fillet_feature("Fillet1"),
        ]
    )

    assert set(duplicate_names(rows)) == {"Fillet1"}


def test_detection_is_one_pass_over_the_features() -> None:
    """Handed an iterator, it still answers: nothing is read twice, which is what makes
    this affordable on a 200-row tree inside a planner that runs per part."""
    rows, _ = rows_of(duplicate_name_features())

    assert duplicate_names(iter(rows)) == duplicate_names(rows)


def test_the_ids_come_back_in_tree_order() -> None:
    """The first occurrence is the one that keeps the name, so the order is load-bearing."""
    rows, _ = rows_of(duplicate_name_features())

    first, second = duplicate_names(rows)["Fillet1"]

    assert [row.id for row in rows if row.name == "Fillet1"] == [first, second]
    assert first < second


# --- the rename plan -----------------------------------------------------------------


def test_the_first_occurrence_keeps_its_name_and_the_rest_are_renamed() -> None:
    specs = duplicate_name_features()

    name_plan = plan(specs)

    assert len(name_plan.renames) == 1
    rename = name_plan.renames[0]
    rows, _ = rows_of(specs)
    assert rename.feature_id == duplicate_names(rows)["Fillet1"][1]
    assert rename.before_name == "Fillet1"
    assert rename.reason == DUPLICATE_NAME == "duplicate_name"
    assert name_plan.blocked == ()


def test_the_rename_is_reversible_because_the_previous_name_is_recorded() -> None:
    """`derive_undo` inverts a rename by writing `before_name` back; a plan that did not
    carry it would have no inverse at all."""
    name_plan = plan(duplicate_name_features())

    rename = name_plan.renames[0]

    assert rename.before_name != rename.after_name
    assert rename.before_name == "Fillet1"


def test_the_plan_leaves_every_name_unique() -> None:
    specs = duplicate_name_features()

    applied = names_after(specs, plan(specs))

    assert len(set(applied)) == len(applied)


def test_a_new_name_never_collides_with_a_name_the_tree_already_has() -> None:
    """The obvious candidate is taken, so the plan keeps counting rather than proposing a
    name that would create the very ambiguity it is repairing."""
    specs = [
        fillet_feature("Fillet1"),
        fillet_feature("Fillet1_2"),
        folder("3-Core", fillet_feature("Fillet1")),
    ]

    name_plan = plan(specs)

    assert len(name_plan.renames) == 1
    assert name_plan.renames[0].after_name == "Fillet1_3"
    applied = names_after(specs, name_plan)
    assert len(set(applied)) == len(applied)


def test_three_rows_sharing_a_name_get_two_distinct_new_names() -> None:
    specs = [
        fillet_feature("Fillet1"),
        folder("3-Core", fillet_feature("Fillet1")),
        folder("4-Detail", fillet_feature("Fillet1")),
    ]

    name_plan = plan(specs)

    assert [rename.after_name for rename in name_plan.renames] == [
        "Fillet1_2",
        "Fillet1_3",
    ]
    applied = names_after(specs, name_plan)
    assert len(set(applied)) == len(applied)


def test_a_tree_with_unique_names_plans_nothing() -> None:
    name_plan = plan([feature("Boss-Extrude1", "Extrusion"), fillet_feature("Fillet1")])

    assert name_plan == NamePlan(renames=(), blocked=())


# --- what cannot be safely renamed ---------------------------------------------------


def test_a_row_the_grouping_rules_do_not_hold_is_never_renamed_by_this_step() -> None:
    """A folder is renamed by `folder.rename`, which the executor applies *after* every
    reorder (data-model.md section 1.11), so it cannot repair a reorder's ambiguity. The
    feature sharing its name is renamed instead and the tree comes out unique."""
    specs = [
        folder("Fillet1", feature("Boss-Extrude1", "Extrusion")),
        fillet_feature("Fillet1"),
    ]

    name_plan = plan(specs)

    assert [rename.before_name for rename in name_plan.renames] == ["Fillet1"]
    assert name_plan.renames[0].feature_id != duplicate_names(rows_of(specs)[0])[
        "Fillet1"
    ][0]
    assert name_plan.blocked == ()
    applied = names_after(specs, name_plan)
    assert len(set(applied)) == len(applied)


def test_two_rows_that_cannot_be_renamed_are_both_ambiguous_names() -> None:
    """Neither folder can be renamed here, so the ambiguity survives and both rows go on
    the rebuild list rather than one of them being renamed anyway (FR-013)."""
    specs = [
        folder("3-Core", folder("Ribs", feature("Rib1", "Extrusion"))),
        folder("4-Detail", folder("Ribs", feature("Rib2", "Extrusion"))),
    ]

    name_plan = plan(specs)

    assert name_plan.renames == ()
    assert [entry.name for entry in name_plan.blocked] == ["Ribs", "Ribs"]
    assert {entry.reason for entry in name_plan.blocked} == {AMBIGUOUS_NAME}
    assert AMBIGUOUS_NAME == "ambiguous_name"


def test_a_blocked_entry_names_the_rows_it_is_ambiguous_with_and_why() -> None:
    """`RebuildEntry.detail` is what the report prints, so an entry that did not name the
    other row would leave the engineer to find it."""
    specs = [
        folder("3-Core", folder("Ribs", feature("Rib1", "Extrusion"))),
        folder("4-Detail", folder("Ribs", feature("Rib2", "Extrusion"))),
    ]

    first, second = plan(specs).blocked

    assert isinstance(first, AmbiguousName)
    assert second.feature_id in first.detail
    assert first.feature_id in second.detail
    assert "rename" in first.detail


def test_a_name_an_equation_references_is_never_renamed() -> None:
    """`"D1@Sketch1"` addresses the sketch by name. Renaming it would break the equation,
    and this version rewrites no equation, so both rows are ambiguous instead."""
    specs = [
        sketch_feature("Sketch1", consumers=()),
        folder("3-Core", sketch_feature("Sketch1", consumers=())),
    ]

    name_plan = plan(specs, [equation('"D1@Sketch1" = 25')])

    assert name_plan.renames == ()
    assert [entry.name for entry in name_plan.blocked] == ["Sketch1", "Sketch1"]
    assert "D1@Sketch1" in name_plan.blocked[0].detail


def test_an_equation_naming_a_longer_name_does_not_block_the_shorter_one() -> None:
    """`@Sketch10` is not a reference to `Sketch1`; a substring match would strand a
    repairable duplicate on the rebuild list for a reference that does not exist."""
    specs = [
        sketch_feature("Sketch1", consumers=()),
        folder("3-Core", sketch_feature("Sketch1", consumers=())),
        sketch_feature("Sketch10", consumers=()),
    ]

    name_plan = plan(specs, [equation('"D1@Sketch10" = 25')])

    assert [rename.before_name for rename in name_plan.renames] == ["Sketch1"]
    assert name_plan.blocked == ()


def test_a_reference_carrying_a_document_suffix_still_blocks_the_rename() -> None:
    """`"D1@Sketch1@bracket.SLDPRT"` is the same reference with the document named."""
    specs = [
        sketch_feature("Sketch1", consumers=()),
        folder("3-Core", sketch_feature("Sketch1", consumers=())),
    ]

    name_plan = plan(specs, [equation('"D1@Sketch1@bracket.SLDPRT" = 25')])

    assert name_plan.renames == ()
    assert len(name_plan.blocked) == 2


def test_an_equation_that_names_no_duplicate_blocks_nothing() -> None:
    specs = duplicate_name_features()

    name_plan = plan(specs, [equation('"thickness" = 3', is_global=True)])

    assert len(name_plan.renames) == 1
    assert name_plan.blocked == ()


def test_a_blocked_row_is_never_also_renamed() -> None:
    """The two lists are disjoint: a row is repaired or it is reported, never both."""
    specs = [
        folder("3-Core", folder("Ribs", feature("Rib1", "Extrusion"))),
        folder("4-Detail", folder("Ribs", feature("Rib2", "Extrusion"))),
        fillet_feature("Fillet1"),
        folder("5-Modify", fillet_feature("Fillet1")),
    ]

    name_plan = plan(specs)

    renamed = {rename.feature_id for rename in name_plan.renames}
    blocked = {entry.feature_id for entry in name_plan.blocked}

    assert renamed & blocked == set()
    assert len(renamed) == 1
    assert len(blocked) == 2


def test_the_plan_is_frozen() -> None:
    name_plan = plan(duplicate_name_features())

    with pytest.raises(Exception):  # noqa: B017 - pydantic raises ValidationError on a frozen model
        name_plan.renames[0].after_name = "Fillet9"
