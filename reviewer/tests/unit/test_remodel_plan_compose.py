"""Unit tests for `plan_reorganize` (T026).

The eight pure modules each answer one question; this is the one function that asks them,
in the order `data-model.md` gives - target, rank, names, order, feasibility, folders,
intent, scope - and turns the answers into the executor's input. What is asserted here is
the **composition**, not the modules: each of the eight is already tested on its own, and
a second set of assertions about what `target.py` decides would be a copy that drifts.

Three properties carry the file:

- **the change list is in the fixed order of `data-model.md` section 1.11**: C1 rename the
  duplicates, C2 describe, C3 reorder, C4 create the folders, C5 repair an existing global
  in place, C6 add the new ones. It is asserted as an invariant of the emitted list and,
  through `RemodelPlan`, as a property of the type - not as a comment beside the builder;
- **v1 addresses no dimension at all.** FR-030 removes the dimension rename and the
  dimension equation the brief carried, because the IR carries no dimensions: the planner
  can neither name one nor prove what an equation on one would drive. So no change, no
  subject kind and no piece of global evidence can name one;
- **an empty change list is a plan, not a failure.** A part already in the method's order
  whose six folders already hold exactly their members has nothing to change, and the plan
  says so in a coverage item rather than leaving a reader to infer it from an empty list.

The trees are built with `tests/support/remodel.py`, which is the shape feature 003 US6
actually produces, so the planner is exercised over the package it will really receive.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from swreview.checks.rms_types import load_table
from swreview.ir.models import EvidencePackage
from swreview.remodel.plan import (
    CHANGE_ORDER,
    PLAN_SCHEMA,
    RemodelPlan,
    part_document_ids,
    plan_reorganize,
)
from swreview.remodel.scope import ScopeSignals
from tests.support.features import (
    FeatureSpec,
    equation,
    feature,
    fillet_feature,
    folder,
    sketch_feature,
)
from tests.support.remodel import (
    UNKNOWN_TYPE_NAME,
    dependency_chain_features,
    linked,
    mis_membered_group_folder_features,
    remodel_package,
    scope_signals,
    variable_radius_fillet_features,
)

TABLE = load_table()
REF, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = TABLE.groups
DOCUMENT = "doc:1"
AT = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)


# --- helpers ----------------------------------------------------------------------


def planned(specs: Sequence[FeatureSpec], **kwargs: Any) -> RemodelPlan:
    """The plan for one part built from `specs`, at a fixed instant so it is comparable."""
    package = remodel_package(list(specs), **{"equations": (), **kwargs})
    return plan_reorganize(package, now=AT)


def ids(plan: RemodelPlan, *names: str) -> tuple[str, ...]:
    """The ids of the named features, refusing a name the plan does not carry once."""
    found: list[str] = []
    for name in names:
        matches = [item.feature_id for item in plan.targets if item.name == name]
        assert len(matches) == 1, f"{name} names {len(matches)} features in this plan"
        found.append(matches[0])
    return tuple(found)


def kinds(plan: RemodelPlan) -> list[str]:
    return [change.kind for change in plan.changes]


def coverage_items(plan: RemodelPlan) -> dict[str, str]:
    return {item.item: item.reason for item in plan.coverage}


def already_organized() -> list[FeatureSpec]:
    """A part already in the method's order, in folders that already hold its features.

    Every sketch is consumed once and therefore follows its consumer into that consumer's
    group, which is why the sketches sit in `3-Core` and `4-Detail` rather than in
    `2-Construction`: an unconsumed sketch takes the construction default, and a consumed
    one does not (`target.py`).
    """
    return linked(
        [
            folder(
                CORE,
                sketch_feature("Sketch1"),
                feature("Boss-Extrude1", "Extrusion"),
                feature("Shell1", "Shell"),
            ),
            folder(
                DETAIL,
                sketch_feature("Sketch2"),
                feature("Cut-Extrude1", "Cut"),
                feature("Hole1", "HoleWzd"),
            ),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Shell1"),
        ("Boss-Extrude1", "Sketch2"),
        ("Sketch2", "Cut-Extrude1"),
        ("Cut-Extrude1", "Hole1"),
    )


def duplicate_names_in_subfolders() -> list[FeatureSpec]:
    """Two features sharing a name in two derived subfolders, which SOLIDWORKS permits,
    with a Detail cut ahead of the Core features it belongs behind.

    Derived subfolders and not group folders, so the tree exercises the rename without also
    tripping the v1 refusal an existing group-named folder raises; and out of order, so one
    tree produces a change of all three kinds revision 1 can emit - C1, C3 and C4 - and the
    fixed order can be asserted on a list that actually holds them.
    """
    return [
        feature("Cut-Extrude1", "Cut"),
        folder("Ribs", feature("Rib1", "Extrusion"), fillet_feature("Fillet1")),
        folder("Slots", feature("Rib2", "Extrusion"), fillet_feature("Fillet1")),
    ]


def out_of_order() -> list[FeatureSpec]:
    """A Detail cut and a Detail hole ahead of the Core boss they belong behind."""
    return linked(
        [
            sketch_feature("Sketch1"),
            feature("Boss-Extrude1", "Extrusion"),
            feature("Cut-Extrude1", "Cut"),
            feature("Hole1", "HoleWzd"),
            feature("Shell1", "Shell"),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Cut-Extrude1"),
        ("Boss-Extrude1", "Hole1"),
        ("Boss-Extrude1", "Shell1"),
    )


# --- the plan is composed from all eight modules ------------------------------------


def test_the_plan_is_revision_1_pure_and_names_the_document_it_read() -> None:
    plan = planned(dependency_chain_features())

    assert plan.plan_schema == PLAN_SCHEMA
    assert plan.plan_revision == 1
    assert plan.document_id == DOCUMENT
    assert plan.configuration == "Default"
    assert plan.configuration_names == ("Default",)
    assert (plan.created_at, plan.updated_at) == (AT, AT)


def test_the_plan_records_the_type_table_it_was_graded_against() -> None:
    plan = planned(dependency_chain_features())

    assert plan.type_table_version == str(TABLE.version)
    assert plan.type_table_calibrated_version == TABLE.calibrated_version


def test_a_pure_plan_names_no_copy_and_no_attestation() -> None:
    plan = planned(dependency_chain_features())

    assert (plan.run_id, plan.copy_path, plan.source) == (None, None, None)


def test_every_row_of_the_tree_gets_a_target_so_the_plan_is_a_partition() -> None:
    specs = already_organized()
    plan = planned(specs)

    package = remodel_package(specs)
    assert len(plan.targets) == len([row for row in package.features])
    assert {item.state for item in plan.targets} <= {
        "resolved",
        "needs_judgement",
        "not_content",
        "unresolved",
    }
    folders = [item for item in plan.targets if item.name in (CORE, DETAIL)]
    assert [item.state for item in folders] == ["not_content", "not_content"]


def test_a_sketch_follows_its_consumer_and_the_basis_says_so() -> None:
    plan = planned(already_organized())

    sketch = next(item for item in plan.targets if item.name == "Sketch1")
    assert (sketch.target_group, sketch.basis) == (CORE, "sketch_follows_consumer")
    assert sketch.decided_by == "planner"
    assert (sketch.provider, sketch.model) == (None, None)


def test_every_content_feature_with_a_resolved_target_is_ranked() -> None:
    plan = planned(already_organized())

    resolved = {item.feature_id for item in plan.targets if item.state == "resolved"}
    assert {rank.feature_id for rank in plan.ranks} == resolved
    shell = ids(plan, "Shell1")[0]
    ranked = next(rank for rank in plan.ranks if rank.feature_id == shell)
    assert ranked.intra_rule_id == "rms.core.shell_last"


def test_an_unrankable_fillet_is_on_the_rebuild_list_and_never_positioned() -> None:
    plan = planned(variable_radius_fillet_features())

    blocked = next(
        rank for rank in plan.ranks if rank.feature_id == ids(plan, "Fillet-Variable1")[0]
    )
    assert blocked.rankable is False
    assert blocked.intra_rank is None
    assert [entry.reason for entry in plan.rebuild if entry.feature_id == blocked.feature_id] == [
        "radius_unreadable"
    ]


def test_an_unclassified_type_is_unresolved_terminal_and_never_moved() -> None:
    plan = planned(
        linked(
            [
                sketch_feature("Sketch1"),
                feature("Boss-Extrude1", "Extrusion"),
                feature("Deform1", UNKNOWN_TYPE_NAME),
            ],
            ("Sketch1", "Boss-Extrude1"),
            ("Boss-Extrude1", "Deform1"),
        )
    )

    deform = next(item for item in plan.targets if item.name == "Deform1")
    assert deform.state == "needs_judgement"
    assert deform.target_group is None
    assert deform.candidates == TABLE.groups
    assert [entry.reason for entry in plan.rebuild if entry.name == "Deform1"] == [
        "unclassified"
    ]


def test_the_system_rows_of_the_real_packages_are_not_content_and_never_rebuilt() -> None:
    """T144 (decision 17A): a light, an annotation folder and a cosmetic thread listed at the
    top of the tree - where no owner carries them - are not content to the planner and are
    never filed `unclassified`, while a type nobody knows still is."""
    plan = planned(
        [
            sketch_feature("Sketch1"),
            feature("Ambient", "AmbientLight"),
            feature("Notes", "NotesAreaFtrFolder"),
            feature("Thread1", "CosmeticThread"),
            feature("Deform1", UNKNOWN_TYPE_NAME),
        ]
    )
    states = {item.name: item.state for item in plan.targets}
    rebuilt = {entry.name for entry in plan.rebuild}

    assert states["Ambient"] == states["Notes"] == states["Thread1"] == "not_content"
    assert rebuilt == {"Deform1"}


def test_the_achievable_order_holds_every_content_feature_and_counts_its_moves() -> None:
    plan = planned(out_of_order())

    content = {item.feature_id for item in plan.targets if item.state != "not_content"}
    assert set(plan.order.achievable) == content
    assert plan.order.move_count == len(plan.order.edit_script)
    assert plan.order.cycle is None
    assert {move.location for move in plan.order.edit_script} <= {"before", "after"}


def test_an_already_organized_tree_yields_no_move_at_all() -> None:
    plan = planned(already_organized())

    assert plan.order.move_count == 0
    assert plan.order.edit_script == ()
    assert plan.rebuild == ()


def test_the_folder_plan_wraps_a_run_the_order_proved_contiguous() -> None:
    plan = planned(out_of_order())

    for action in plan.folders.actions:
        assert action.contiguous is True
        assert action.name in TABLE.groups
    assert plan.folders.refusals == ()


def test_an_existing_group_folder_holding_the_wrong_members_refuses_the_part() -> None:
    plan = planned(mis_membered_group_folder_features())

    assert [refusal.reason for refusal in plan.folders.refusals] == [
        "rms_named_folder_wrong_members"
    ]
    assert plan.state == "failed"
    assert plan.changes == ()
    assert "folders" in coverage_items(plan)


def test_the_scope_of_a_dry_run_is_unresolved_because_no_signal_was_read() -> None:
    plan = planned(dependency_chain_features())

    assert plan.scope.verdict == "unresolved"
    assert {refusal.code for refusal in plan.scope.refusals} == {"signal_unresolved"}
    assert plan.scope.signals is None
    assert plan.scope.probe_id is None


def test_scope_signals_the_host_did_read_are_carried_and_can_refuse_the_part() -> None:
    package = remodel_package(dependency_chain_features())
    plan = plan_reorganize(
        package,
        signals=ScopeSignals(**scope_signals(solid_body_count=3, is_weldment=True)),
        probe_id="probe:1",
        now=AT,
    )

    assert plan.scope.verdict == "refused"
    assert [refusal.code for refusal in plan.scope.refusals] == ["multibody", "weldment"]
    assert plan.scope.probe_id == "probe:1"
    assert plan.state == "failed"
    assert plan.changes == ()


def test_the_intent_gaps_are_reported_as_coverage_rather_than_as_proposals() -> None:
    plan = planned(dependency_chain_features())

    items = coverage_items(plan)
    assert "feature descriptions" in items
    assert "global variables" in items
    assert "sketch dimensions" in items
    assert plan.descriptions == ()
    assert plan.globals == ()


def test_a_broken_equation_is_reported_and_never_repaired_by_the_pure_planner() -> None:
    plan = planned(
        dependency_chain_features(),
        equations=(equation('"width" = "missing" * 2', lhs="width", is_global=True),),
    )

    assert "equations" in coverage_items(plan)
    assert kinds(plan).count("equation.edit") == 0
    assert kinds(plan).count("equation.add") == 0


def test_a_fillet_defaulted_to_the_structural_group_is_a_reported_deviation() -> None:
    plan = planned(dependency_chain_features())

    deviation = next(item for item in plan.deviations if item.kind == "fillet_default_core")
    assert deviation.chosen == CORE
    assert deviation.report_line == (
        "reviewed as structural; move to Quarantine if cosmetic"
    )


# --- the change list -----------------------------------------------------------------


def test_a_duplicate_name_is_renamed_before_anything_is_reordered() -> None:
    plan = planned(duplicate_names_in_subfolders())

    assert [rename.reason for rename in plan.renames] == ["duplicate_name"]
    assert kinds(plan)[0] == "rename"
    rename = plan.changes[0]
    assert rename.subject is not None
    assert rename.params["new_name"] == plan.renames[0].after_name
    assert rename.params["persist_ref"] == rename.subject.persist_ref


def test_the_change_list_is_in_the_fixed_order_of_section_1_11() -> None:
    plan = planned(duplicate_names_in_subfolders())

    steps = [CHANGE_ORDER.index(kind) for kind in kinds(plan)]
    assert steps == sorted(steps)
    assert set(kinds(plan)) <= {"rename", "reorder", "folder.create"}


def test_the_reorder_changes_are_the_edit_script_in_application_order() -> None:
    plan = planned(out_of_order())

    reorders = [change for change in plan.changes if change.kind == "reorder"]
    assert len(reorders) == plan.order.move_count
    for change, move in zip(reorders, plan.order.edit_script, strict=True):
        assert change.subject is not None
        assert change.subject.feature_id == move.feature_id
        assert change.params["location"] == move.location
        assert change.params["feature_persist_ref"] == change.subject.persist_ref
        assert change.params["anchor_persist_ref"] != change.params["feature_persist_ref"]


def test_every_folder_creation_comes_after_every_reorder() -> None:
    plan = planned(out_of_order())

    last_reorder = max(
        (index for index, kind in enumerate(kinds(plan)) if kind == "reorder"), default=-1
    )
    first_folder = min(
        (index for index, kind in enumerate(kinds(plan)) if kind == "folder.create"),
        default=len(plan.changes),
    )
    assert last_reorder < first_folder


def test_a_folder_creation_carries_its_members_persistent_references() -> None:
    plan = planned(out_of_order())

    created = next(change for change in plan.changes if change.kind == "folder.create")
    assert created.subject is None
    assert created.params["op"] == "create"
    assert created.params["folder_persist_ref"] is None
    assert created.params["member_persist_refs"]
    assert created.expect["folder_location"] == created.params["name"]


def test_a_folder_that_is_already_correct_is_a_no_op_and_not_a_change() -> None:
    plan = planned(already_organized())

    assert {action.status for action in plan.folders.actions} == {"no_op"}
    assert kinds(plan).count("folder.create") == 0


def test_the_sequence_numbers_are_one_to_n_in_application_order() -> None:
    plan = planned(duplicate_names_in_subfolders())

    assert [change.seq for change in plan.changes] == list(range(1, len(plan.changes) + 1))


def test_an_empty_change_list_is_a_plan_that_says_why_it_is_empty() -> None:
    plan = planned(already_organized())

    assert plan.changes == ()
    assert plan.state == "planned"
    assert "changes" in coverage_items(plan)
    assert coverage_items(plan)["changes"]


# --- FR-030: v1 addresses no dimension ------------------------------------------------


def test_no_change_kind_and_no_subject_kind_names_a_dimension() -> None:
    assert not any("dimension" in kind for kind in CHANGE_ORDER)

    plan = planned(duplicate_names_in_subfolders())
    assert {change.subject_kind for change in plan.changes} <= {"feature", "folder"}


def test_no_plan_over_a_part_with_equations_renames_or_drives_a_dimension() -> None:
    plan = planned(
        variable_radius_fillet_features(),
        equations=(
            equation('"width" = 120', lhs="width", is_global=True, value=120.0),
            equation('"D1@Sketch1" = "width" / 2', lhs="D1@Sketch1", is_global=False),
        ),
    )

    for change in plan.changes:
        assert "@" not in repr(change.params)
    assert plan.globals == ()
    assert all("@" not in item.item for item in plan.coverage if item.item == "dimension")


# --- document selection ---------------------------------------------------------------


def test_the_part_documents_of_a_package_are_named_in_package_order() -> None:
    package = remodel_package(dependency_chain_features())

    assert part_document_ids(package) == (DOCUMENT,)
    assert part_document_ids(package, [DOCUMENT]) == (DOCUMENT,)


def test_a_document_the_package_does_not_carry_is_refused_by_name() -> None:
    package = remodel_package(dependency_chain_features())

    with pytest.raises(ValueError, match="doc:404"):
        part_document_ids(package, ["doc:404"])


def test_a_document_whose_tree_was_never_dumped_is_refused_rather_than_planned() -> None:
    package: EvidencePackage = remodel_package(dependency_chain_features())
    empty = package.model_copy(update={"features": []})

    with pytest.raises(ValueError, match="features"):
        plan_reorganize(empty, now=AT)


def test_a_package_with_more_than_one_part_must_be_told_which_one_to_plan() -> None:
    from tests.support.features import PartSpec, rms_package

    package = rms_package(
        parts=[
            PartSpec(document_id="doc:1", name="a", features=dependency_chain_features()),
            PartSpec(document_id="doc:2", name="b", features=dependency_chain_features()),
        ]
    )

    with pytest.raises(ValueError, match="doc:1"):
        plan_reorganize(package, now=AT)

    assert plan_reorganize(package, document_id="doc:2", now=AT).document_id == "doc:2"


# --- a parent the method does not grade ---------------------------------------------


def mid_tree_plane() -> EvidencePackage:
    """A user-created reference plane sitting mid-tree, with a sketch built on it.

    `RefPlane` is `tolerated_loose`, so the plane is not a content feature and is never
    moved - but it is a real `GetParents` parent occupying a real tree position, and no
    reorder may lift `Sketch9` above it.
    """
    return remodel_package(
        linked(
            [
                feature("Boss-Extrude1", "Extrusion"),
                feature("Cut-Extrude1", "Cut"),
                feature("Cut-Extrude2", "Cut"),
                feature("Cut-Extrude3", "Cut"),
                feature("Plane1", "RefPlane"),
                sketch_feature("Sketch9"),
                feature("Boss-Extrude2", "Extrusion"),
            ],
            ("Plane1", "Sketch9"),
            ("Sketch9", "Boss-Extrude2"),
        )
    )


def reordered_tree(package: EvidencePackage, plan: RemodelPlan) -> list[str]:
    """Every row of the tree after the plan's edit script, exactly as the reorder leaves it."""
    tree = [row.id for row in package.features]
    for move in plan.order.edit_script:
        tree.remove(move.feature_id)
        anchor = tree.index(move.anchor_feature_id)
        tree.insert(anchor if move.location == "before" else anchor + 1, move.feature_id)
    return tree


def test_no_move_lifts_a_feature_above_a_parent_the_method_does_not_grade() -> None:
    package = mid_tree_plane()
    plan = plan_reorganize(package, now=AT)
    by_name = {row.name: row.id for row in package.features}

    tree = reordered_tree(package, plan)

    assert tree.index(by_name["Sketch9"]) > tree.index(by_name["Plane1"])
    assert tree.index(by_name["Boss-Extrude2"]) > tree.index(by_name["Sketch9"])


def test_a_non_content_parent_that_holds_a_feature_back_is_reported_as_a_pin() -> None:
    package = mid_tree_plane()
    plan = plan_reorganize(package, now=AT)
    by_name = {row.name: row.id for row in package.features}

    held = [pin for pin in plan.pins if pin.feature_id == by_name["Sketch9"]]

    assert len(held) == 1
    assert held[0].blocking_edge.parent_id == by_name["Plane1"]
    assert "Plane1" in held[0].reason


def test_a_cycle_refused_plan_never_says_nothing_refused_this_part() -> None:
    plan = planned(
        linked(
            [
                sketch_feature("Sketch1"),
                feature("Boss-Extrude1", "Extrusion"),
                feature("Cut-Extrude1", "Cut"),
            ],
            ("Sketch1", "Boss-Extrude1"),
            ("Boss-Extrude1", "Cut-Extrude1"),
            ("Cut-Extrude1", "Boss-Extrude1"),
        )
    )

    changes = coverage_items(plan)["changes"]

    assert plan.state == "failed"
    assert plan.order.cycle is not None
    assert "nothing refused this part" not in changes
    assert "cycle" in changes
    assert "Boss-Extrude1" in changes and "Cut-Extrude1" in changes


def random_tree(rng: random.Random) -> EvidencePackage:
    """One tree of random types and random backward-only edges.

    Backward-only because a real feature tree is one: a feature can only be built on
    something already in it, so every edge runs from a lower index to a higher one and the
    graph the planner receives is acyclic however the rows are drawn.
    """
    types = (
        "Extrusion",
        "Cut",
        "HoleWzd",
        "Chamfer",
        "Shell",
        "MirrorPattern",
        "RefPlane",
        "CoordSys",
        "OriginPoint",
        "ProfileFeature",
    )
    names = []
    specs: list[FeatureSpec] = []
    for index in range(rng.randint(3, 11)):
        type_name = rng.choice(types)
        name = f"F{index}_{type_name}"
        names.append(name)
        specs.append(
            sketch_feature(name)
            if type_name == "ProfileFeature"
            else feature(name, type_name)
        )
    edges: list[tuple[str, str]] = []
    for child in range(1, len(names)):
        for _ in range(rng.randint(0, 2)):
            edge = (names[rng.randrange(child)], names[child])
            if edge not in edges:
                edges.append(edge)
    return remodel_package(linked(specs, *edges))


def test_no_plan_ever_emits_a_reorder_the_feature_graph_forbids() -> None:
    """The property the planner exists to hold: the tree its edit script leaves behind
    satisfies every edge the dump reported, including the edges into the rows the method
    does not grade. `ReorderFeature` cannot move a feature past its own parent, so a plan
    that broke one would be a plan SOLIDWORKS refuses halfway through.

    Seeded, so the trees are the same on every run and a failure is reproducible.
    """
    rng = random.Random(20260916)
    planned_trees = 0

    for _ in range(120):
        package = random_tree(rng)
        plan = plan_reorganize(package, now=AT)
        if plan.state != "planned":
            continue
        planned_trees += 1
        tree = reordered_tree(package, plan)
        at = {feature_id: index for index, feature_id in enumerate(tree)}
        by_id = {row.id: row for row in package.features}
        for row in package.features:
            for parent_id in row.parent_ids or ():
                assert at[parent_id] < at[row.id], (
                    f"{by_id[parent_id].name} is a parent of {row.name} and the plan "
                    f"leaves it below: {[by_id[one].name for one in tree]}"
                )

    assert planned_trees > 50, "the trees drawn here are almost all refusals; draw others"
