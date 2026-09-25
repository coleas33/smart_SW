"""Unit tests for one node per feature (T142, decision 17A).

A real package lists every absorbed sketch twice: at depth 0, in traversal order just
before the feature that consumes it, and again at depth 1 under that feature, with the same
`persist_ref`. The planner planned both - two targets, a duplicate-name rename of one
feature against itself, and a reorder naming a persist ref another reorder already named.

`contracts/run-artifacts.md` ("How the planner reads the tree") states the rule; this file
pins it from both ends:

- `tree_nodes` over hand-built rows, one case per edge of the rule: what is merged, what is
  kept and why, and every edge that named the dropped row naming the kept one afterwards;
- `plan_reorganize` over a fictional, code-built package laid out in the real shape
  (`tests/support/remodel.py::absorbed_twice`): the second listing changes nothing in the
  plan but the coverage line that says it was read.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swreview.checks.rms_types import load_table
from swreview.ir.models import EvidencePackage, Feature, SketchInfo
from swreview.remodel.nodes import MergedRow, tree_nodes
from swreview.remodel.plan import RemodelPlan, plan_reorganize
from tests.support.features import feature, folder, sketch_feature
from tests.support.remodel import (
    absorbed_sketch_features,
    absorbed_twice,
    linked,
    remodel_package,
)

TABLE = load_table()
AT = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)
ABSORBED = ("Sketch1", "Sketch2", "Sketch3")
SECOND_LISTINGS = "second listings"


def base_package() -> EvidencePackage:
    return remodel_package(absorbed_sketch_features())


def real_shape_package() -> EvidencePackage:
    return absorbed_twice(base_package(), *ABSORBED)


def by_name(rows: tuple[Feature, ...] | list[Feature], name: str) -> list[Feature]:
    return [row for row in rows if row.name == name]


def retyped(row: Feature, **update: object) -> Feature:
    return row.model_copy(update=update)


# --- tree_nodes: what is one node --------------------------------------------------


def test_a_second_listing_under_its_consumer_is_merged_into_the_top_level_row() -> None:
    rows = real_shape_package().features
    nodes = tree_nodes(rows, TABLE)

    for name in ABSORBED:
        top, second = by_name(rows, name)
        assert by_name(nodes.rows, name) == [
            row for row in nodes.rows if row.id == top.id
        ]
        assert MergedRow(dropped_id=second.id, kept_id=top.id) in nodes.merged
    assert len(nodes.rows) == len(rows) - len(ABSORBED)
    assert len(nodes.merged) == len(ABSORBED)


def test_the_kept_row_is_the_top_level_row_with_its_own_readings() -> None:
    """The depth-0 row is where the flat walk - and `ReorderFeature` - meets the feature,
    so its index, depth and readings stand; only its edges are rewritten."""
    rows = real_shape_package().features
    nodes = tree_nodes(rows, TABLE)

    for name in ABSORBED:
        top, _ = by_name(rows, name)
        (kept,) = by_name(nodes.rows, name)
        assert kept.id == top.id
        assert (kept.index, kept.depth, kept.folder_id) == (top.index, 0, None)
        assert kept.persist_ref == top.persist_ref
        assert kept.description == top.description


def test_every_edge_that_named_the_second_listing_names_the_kept_row() -> None:
    rows = real_shape_package().features
    nodes = tree_nodes(rows, TABLE)
    dropped = {merge.dropped_id for merge in nodes.merged}

    for row in nodes.rows:
        named = (
            *(row.parent_ids or ()),
            *(row.child_ids or ()),
            *((row.sketch.consumer_ids or ()) if row.sketch else ()),
        )
        assert not dropped & set(named), row.name
        assert row.folder_id not in dropped
    kept = {row.id for row in nodes.rows}
    for row in nodes.rows:
        assert set(row.parent_ids or ()) <= kept
        assert set(row.child_ids or ()) <= kept

    (boss,) = by_name(nodes.rows, "Boss-Extrude1")
    (sketch,) = by_name(nodes.rows, "Sketch1")
    assert sketch.id in (boss.parent_ids or ())


def test_the_merge_reproduces_the_tree_the_flat_walk_lists() -> None:
    """Merging the second listings of the real shape gives back the base tree, edge for
    edge, once both sides are keyed by name - which is the whole claim of the rule."""
    base = base_package().features
    nodes = tree_nodes(real_shape_package().features, TABLE)

    def edges(rows: tuple[Feature, ...] | list[Feature]) -> dict[str, tuple[set[str], set[str]]]:
        names = {row.id: row.name for row in rows}
        return {
            row.name: (
                {names[one] for one in row.parent_ids or ()},
                {names[one] for one in row.child_ids or ()},
            )
            for row in rows
        }

    assert [row.name for row in nodes.rows] == [row.name for row in base]
    assert edges(nodes.rows) == edges(base)


def test_a_tree_with_no_second_listing_is_returned_unchanged() -> None:
    rows = base_package().features
    nodes = tree_nodes(rows, TABLE)

    assert list(nodes.rows) == list(rows)
    assert nodes.merged == ()


def test_a_row_the_walk_found_only_under_its_owner_is_kept() -> None:
    """A sub-feature with no depth-0 twin - the Hole Wizard's own profile sketch is one on
    the real packages - is not a second listing of anything."""
    rows = list(base_package().features)
    hole = by_name(rows, "Hole1")[0]
    inner = retyped(
        by_name(rows, "Sketch3")[0],
        id="feat:0099",
        name="Sketch9",
        persist_ref="aW5uZXI=",
        index=len(rows),
        depth=1,
        folder_id=hole.id,
        parent_ids=[],
    )
    nodes = tree_nodes([*rows, inner], TABLE)

    assert inner in nodes.rows
    assert nodes.merged == ()


def test_a_row_under_a_folder_is_not_merged() -> None:
    """The rule is about a feature's own sub-feature listing. A depth-1 row under a
    **folder** is folder membership in the nested shape, which the group assigner reads
    from `folder_id`; nothing on the real packages shows a folder member listed twice, so
    none is merged on a guess."""
    package = remodel_package(
        linked(
            [
                sketch_feature("Sketch1"),
                folder("Ribs", feature("Rib1", "Extrusion")),
            ],
            ("Sketch1", "Rib1"),
        )
    )
    rows = list(package.features)
    ribs, rib = by_name(rows, "Ribs")[0], by_name(rows, "Rib1")[0]
    twin = retyped(rib, id="feat:0099", index=len(rows), depth=0, folder_id=None)
    nodes = tree_nodes([*rows, twin], TABLE)

    assert rib.folder_id == ribs.id
    assert nodes.merged == ()
    assert len(nodes.rows) == len(rows) + 1


def test_a_second_listing_of_another_type_is_not_merged() -> None:
    rows = list(real_shape_package().features)
    _, second = by_name(rows, "Sketch1")
    rows[second.index] = retyped(second, type_name="3DProfileFeature")
    nodes = tree_nodes(rows, TABLE)

    assert MergedRow(dropped_id=second.id, kept_id=by_name(rows, "Sketch1")[0].id) not in (
        nodes.merged
    )
    assert len(nodes.merged) == len(ABSORBED) - 1


def test_a_persist_ref_two_top_level_rows_share_merges_nothing() -> None:
    """The real packages carry seven system folders at depth 0 that share one persist ref.
    A second listing whose persist ref names two top-level rows cannot say which one it is,
    so it is kept as the dump gave it rather than merged on a guess."""
    rows = list(real_shape_package().features)
    top, second = by_name(rows, "Sketch2")
    impostor = retyped(top, id="feat:0098", name="Sketch2b", index=len(rows))
    nodes = tree_nodes([*rows, impostor], TABLE)

    assert second in nodes.rows
    assert all(merge.dropped_id != second.id for merge in nodes.merged)
    assert len(nodes.merged) == len(ABSORBED) - 1


def test_the_system_folders_that_share_one_persist_ref_are_left_alone() -> None:
    rows = list(base_package().features)
    shared = "c2hhcmVk"
    folders = [
        feature_row(f"feat:09{number:02d}", type_name, shared, len(rows) + number)
        for number, type_name in enumerate(
            ("FavoriteFolder", "HistoryFolder", "SensorFolder", "MaterialFolder")
        )
    ]
    nodes = tree_nodes([*rows, *folders], TABLE)

    assert nodes.merged == ()
    assert all(row in nodes.rows for row in folders)


def feature_row(feature_id: str, type_name: str, persist_ref: str, index: int) -> Feature:
    template = base_package().features[0]
    return template.model_copy(
        update={
            "id": feature_id,
            "name": type_name,
            "type_name": type_name,
            "persist_ref": persist_ref,
            "index": index,
            "depth": 0,
            "folder_id": None,
            "parent_ids": [],
            "child_ids": [],
            "sketch": None,
        }
    )


def test_a_sketch_listed_under_each_of_two_consumers_is_one_node() -> None:
    """SOLIDWORKS shows a shared sketch under every feature that uses it, so it can be
    listed three times; all three are one feature."""
    rows = list(real_shape_package().features)
    top, second = by_name(rows, "Sketch1")
    cut = by_name(rows, "Cut-Extrude1")[0]
    third = retyped(second, id="feat:0097", index=len(rows), folder_id=cut.id)
    nodes = tree_nodes([*rows, third], TABLE)

    assert by_name(nodes.rows, "Sketch1") == [row for row in nodes.rows if row.id == top.id]
    assert MergedRow(dropped_id=third.id, kept_id=top.id) in nodes.merged


def test_an_edge_list_naming_both_listings_names_the_kept_row_once() -> None:
    rows = list(real_shape_package().features)
    top, second = by_name(rows, "Sketch1")
    boss = by_name(rows, "Boss-Extrude1")[0]
    rows[boss.index] = retyped(boss, parent_ids=[second.id, top.id, *(boss.parent_ids or ())])
    nodes = tree_nodes(rows, TABLE)

    (merged_boss,) = by_name(nodes.rows, "Boss-Extrude1")
    assert (merged_boss.parent_ids or []).count(top.id) == 1


def test_an_unreadable_edge_list_stays_unreadable() -> None:
    """`None` is `GetParents` failing; the rewrite never turns it into a read."""
    rows = list(real_shape_package().features)
    boss = by_name(rows, "Boss-Extrude1")[0]
    rows[boss.index] = retyped(boss, parent_ids=None)
    nodes = tree_nodes(rows, TABLE)

    (merged_boss,) = by_name(nodes.rows, "Boss-Extrude1")
    assert merged_boss.parent_ids is None


def test_a_sketch_readings_consumers_are_rewritten_too() -> None:
    rows = list(real_shape_package().features)
    top, second = by_name(rows, "Sketch2")
    fillet = by_name(rows, "Fillet1")[0]
    rows[fillet.index] = retyped(
        fillet, sketch=SketchInfo(raw_status=3, consumer_ids=[second.id])
    )
    nodes = tree_nodes(rows, TABLE)

    (merged_fillet,) = by_name(nodes.rows, "Fillet1")
    assert merged_fillet.sketch is not None
    assert merged_fillet.sketch.consumer_ids == [top.id]


def test_rows_of_two_documents_are_refused() -> None:
    rows = list(base_package().features)
    stray = retyped(rows[0], id="feat:0099", document_id="doc:2")

    with pytest.raises(ValueError, match="one document"):
        tree_nodes([*rows, stray], TABLE)


# --- plan_reorganize over the real shape --------------------------------------------


def plan(package: EvidencePackage) -> RemodelPlan:
    return plan_reorganize(package, now=AT)


def names_of(result: RemodelPlan) -> dict[str, str]:
    return {item.feature_id: item.name for item in result.targets}


def test_the_plan_has_one_target_per_feature_not_per_row() -> None:
    package = real_shape_package()
    result = plan(package)
    targeted = [item.name for item in result.targets]

    assert len(result.targets) == len(package.features) - len(ABSORBED)
    for name in ABSORBED:
        assert targeted.count(name) == 1


def test_no_feature_is_renamed_against_its_own_second_listing() -> None:
    result = plan(real_shape_package())

    assert result.renames == ()
    assert [change for change in result.changes if change.kind == "rename"] == []


def test_no_persist_ref_is_moved_twice() -> None:
    result = plan(real_shape_package())
    moved = [change.subject.persist_ref for change in result.changes if change.kind == "reorder"]

    assert len(moved) == len(set(moved))


def test_the_second_listing_changes_nothing_in_the_plan_but_its_coverage_line() -> None:
    """The strongest form of the rule: the same tree, with and without the dump's second
    listings, plans the same targets, moves, pins, rebuild list and folders, keyed by name."""
    with_twins, without = plan(real_shape_package()), plan(base_package())

    def projection(result: RemodelPlan) -> dict[str, object]:
        names = names_of(result)
        return {
            "targets": [
                (item.name, item.state, item.target_group, item.basis) for item in result.targets
            ],
            "moves": [
                (names[move.feature_id], names[move.anchor_feature_id], move.location)
                for move in result.order.edit_script
            ],
            "pins": [
                (names[pin.feature_id], names[pin.blocking_edge.parent_id]) for pin in result.pins
            ],
            "rebuild": [(names[entry.feature_id], entry.reason) for entry in result.rebuild],
            "folders": [
                (action.op, action.name, [names[one] for one in action.member_feature_ids])
                for action in result.folders.actions
            ],
            "changes": [change.kind for change in result.changes],
            "state": result.state,
        }

    assert projection(with_twins) == projection(without)
    assert with_twins.order.move_count == 1


def test_the_coverage_names_every_second_listing_it_merged() -> None:
    package = real_shape_package()
    result = plan(package)
    (item,) = [item for item in result.coverage if item.item == SECOND_LISTINGS]
    second = {by_name(package.features, name)[1].id for name in ABSORBED}

    assert set(item.feature_ids) == second
    assert str(len(ABSORBED)) in item.reason


def test_the_coverage_says_so_when_no_row_was_listed_twice() -> None:
    """Every coverage item is written on every run: "nothing was listed twice" is an answer,
    and a plan that left the item out could not be told apart from one that never looked."""
    (item,) = [item for item in plan(base_package()).coverage if item.item == SECOND_LISTINGS]

    assert item.feature_ids == ()
    assert item.reason
