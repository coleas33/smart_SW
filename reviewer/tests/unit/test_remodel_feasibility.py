"""Unit tests for pins, non-contiguous groups and the rebuild list (T016).

The rebuild list is the product of stage 1 (`research.md` R6.7): a part the re-modeler
cannot reorganize is not a failure to report as a number, it is a partition with a reason
per entry, and the reasons are what an engineer acts on. So this file is built around one
fixture per reason of the closed taxonomy (`research.md` R6.5, FR-014), each asserting
three things - the reason, the subject it is about, and the blocking edge, interloper,
span or cycle that produced it - because a reason with no evidence beside it is a label.

The taxonomy is **exactly eight**: `backward_reference`, `shared_sketch`, `splits_group`,
`cycle`, `radius_unreadable`, `ambiguous_name`, `unclassified`, `graph_unreadable`. A
ninth is not reachable: `RebuildEntry` refuses a reason outside the set at construction,
so "the planner never invents a reason at runtime" is a property of the type.

Two boundaries are asserted here rather than assumed:

- **an RMS-named folder holding the wrong members is not a ninth rebuild reason.** It is
  the scope refusal `rms_named_folder_wrong_members` (`data-model.md` sections 1.6 and
  4.2), raised from `ScopeSignals` alone and therefore **before anything is copied**,
  because `IModelDoc2.EditDelete` is not in the stage-1 allowlist and there is no dissolve
  path in v1. `scope.py` (T023) and `folders.py` (T019) own that token; what is asserted
  here is that feasibility never spells it and never files the folder on the rebuild list;
- **exactly one reason per feature.** A feature can match several detections at once - an
  unclassified feature whose graph is also unreadable, a pinned feature that also splits a
  group - so the module resolves them in a stated precedence, evidence-absence first, and
  the precedence is asserted rather than left to whichever detection happened to run last.

What feasibility is **not** given is anything it could get wrong twice. Duplicate names
come from `names.py` as the ids it could not safely rename, because most duplicates are
renamed before any reorder and are not rebuild entries at all; the achievable order comes
from `order.py`; the target groups come from `target.py`. This module reads the package
for the facts only it needs (a fillet's unreadable radius, a sketch's consumers, a
feature's parents, a type the table does not carry) and re-derives no decision another
module already made.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import get_args

import pytest

from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.part import PartTree, part_tree
from swreview.checks.rms_types import load_table
from swreview.remodel.feasibility import (
    REBUILD_REASONS,
    RESOLUTION_ORDER,
    Edge,
    FeasibilityReport,
    RebuildEntry,
    RebuildReason,
    assess,
)
from swreview.remodel.names import AMBIGUOUS_NAME, AmbiguousName, plan_renames
from swreview.remodel.order import OrderResult, plan_order
from tests.support.features import (
    FeatureSpec,
    equation,
    feature,
    fillet_feature,
    sketch_feature,
)
from tests.support.remodel import (
    UNKNOWN_TYPE_NAME,
    duplicate_name_features,
    linked,
    mis_membered_group_folder_features,
    remodel_package,
    shared_sketch_features,
    unknown_type_features,
    variable_radius_fillet_features,
)

TABLE = load_table()
DOCUMENT = "doc:1"
REF, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = TABLE.groups

TAXONOMY = (
    "backward_reference",
    "shared_sketch",
    "splits_group",
    "cycle",
    "radius_unreadable",
    "ambiguous_name",
    "unclassified",
    "graph_unreadable",
)
"""FR-014's list, written out here so the product's tuple is compared against the
requirement rather than against itself."""

RMS_NAMED_FOLDER_WRONG_MEMBERS = "rms_named_folder_wrong_members"
"""The scope refusal of `data-model.md` section 4.2, owned by `scope.py` (T023) and
`folders.py` (T019). It appears in this file only to assert that feasibility never
produces it: it is a refusal that precedes the copy, not a rebuild-list reason."""


# --- helpers ----------------------------------------------------------------------


def build(specs: Sequence[FeatureSpec]) -> PartTree:
    """One part document as the planner receives it, indexed as every 003 rule reads it."""
    package = remodel_package(specs)
    rows = [row for row in package.features if row.document_id == DOCUMENT]
    return part_tree(DOCUMENT, rows, TABLE, assign_groups(rows, TABLE), package)


def ids(tree: PartTree, *names: str) -> tuple[str, ...]:
    """The ids of the named features, refusing a name the tree does not carry once."""
    found: list[str] = []
    for name in names:
        matches = [row.id for row in tree.rows if row.name == name]
        assert len(matches) == 1, f"{name} names {len(matches)} features in this tree"
        found.append(matches[0])
    return tuple(found)


def content_ids(tree: PartTree) -> tuple[str, ...]:
    return tuple(row.id for row in tree.content)


def groups_of(tree: PartTree, by_name: Mapping[str, str]) -> dict[str, str | None]:
    """Target groups keyed by feature id, `None` for every feature not named."""
    targets: dict[str, str | None] = {row.id: None for row in tree.rows}
    for name, group in by_name.items():
        (feature_id,) = ids(tree, name)
        targets[feature_id] = group
    return targets


def entries(report: FeasibilityReport) -> Mapping[str, RebuildEntry]:
    """The rebuild list keyed by feature id, refusing a feature listed twice."""
    keyed: dict[str, RebuildEntry] = {}
    for entry in report.rebuild:
        assert entry.feature_id not in keyed, (
            f"{entry.feature_id} carries two reasons: {keyed.get(entry.feature_id)} and {entry}"
        )
        keyed[entry.feature_id] = entry
    return keyed


def in_tree_order(tree: PartTree, order: Sequence[str]) -> list[str]:
    return [row.id for row in tree.content if row.id in set(order)]


# --- the fixture every group-shaped case is built from ----------------------------


def backward_reference_tree() -> PartTree:
    """A `4-Detail` cut sketched on a face a `6-Quarantine` fillet created.

    `research.md` R6.5's own example, and the one tree that produces three of the eight
    reasons at once: the cut is held by the edge (`backward_reference`), the fillet lands
    inside the Detail span (`splits_group` on the interloper), and the Detail features it
    splits cannot be folded (`splits_group` on the members, spec.md US1 scenario 5).
    """
    return build(
        linked(
            [
                sketch_feature("Sketch1"),
                feature("Boss-Extrude1", "Extrusion"),
                fillet_feature("Fillet1"),
                sketch_feature("Sketch2"),
                feature("Cut-Extrude1", "Cut"),
            ],
            ("Sketch1", "Boss-Extrude1"),
            ("Boss-Extrude1", "Fillet1"),
            ("Fillet1", "Cut-Extrude1"),
            ("Sketch2", "Cut-Extrude1"),
        )
    )


def backward_reference_targets(tree: PartTree) -> dict[str, str | None]:
    """The fillet is reviewed as cosmetic and sent to Quarantine; everything else follows
    the table."""
    sketch1, boss, fillet, sketch2, cut = ids(
        tree, "Sketch1", "Boss-Extrude1", "Fillet1", "Sketch2", "Cut-Extrude1"
    )
    return {
        sketch1: CORE,
        boss: CORE,
        fillet: QUARANTINE,
        sketch2: DETAIL,
        cut: DETAIL,
    }


def ordered(
    tree: PartTree, targets: Mapping[str, str | None]
) -> tuple[list[str], OrderResult]:
    """The desired order (group, then tree order) and the achievable order `order.py`
    reaches from it."""
    rank_of = {group: index for index, group in enumerate(TABLE.groups)}
    desired = sorted(
        content_ids(tree),
        key=lambda feature_id: (
            rank_of.get(targets[feature_id] or "", len(TABLE.groups)),
            tree.by_id[feature_id].index,
        ),
    )
    content = set(content_ids(tree))
    result = plan_order(
        content_ids(tree),
        {
            row.id: [parent_id for parent_id in (row.parent_ids or ()) if parent_id in content]
            for row in tree.content
        },
        {feature_id: index for index, feature_id in enumerate(desired)},
    )
    return desired, result


# --- the taxonomy is closed -------------------------------------------------------


def test_the_taxonomy_is_exactly_the_eight_reasons_of_fr_014() -> None:
    assert REBUILD_REASONS == TAXONOMY
    assert get_args(RebuildReason) == TAXONOMY
    assert sorted(RESOLUTION_ORDER) == sorted(TAXONOMY), (
        "the precedence order must resolve every reason and invent none"
    )


def test_no_ninth_reason_is_reachable() -> None:
    with pytest.raises(ValueError, match="rms_named_folder_wrong_members"):
        RebuildEntry(
            feature_id="feat:0001",
            name="Boss-Extrude1",
            reason=RMS_NAMED_FOLDER_WRONG_MEMBERS,  # type: ignore[arg-type]
            detail="a folder named 3-Core holds the wrong members",
            blocking_edge=None,
        )


def test_every_entry_carries_a_reason_from_the_taxonomy_and_its_evidence() -> None:
    tree = backward_reference_tree()
    targets = backward_reference_targets(tree)
    desired, result = ordered(tree, targets)
    report = assess(
        tree, target_groups=targets, desired=desired, achievable=result.achievable
    )

    assert report.rebuild, "this fixture is supposed to produce a rebuild list"
    for entry in report.rebuild:
        assert entry.reason in REBUILD_REASONS
        assert entry.detail, f"{entry.feature_id} carries {entry.reason} with no evidence"


# --- one fixture per reason -------------------------------------------------------


def test_backward_reference_names_the_edge_that_holds_the_feature() -> None:
    tree = backward_reference_tree()
    targets = backward_reference_targets(tree)
    desired, result = ordered(tree, targets)
    fillet, cut = ids(tree, "Fillet1", "Cut-Extrude1")

    report = assess(
        tree, target_groups=targets, desired=desired, achievable=result.achievable
    )

    entry = entries(report)[cut]
    assert entry.reason == "backward_reference"
    assert entry.blocking_edge == Edge(parent_id=fillet, child_id=cut)
    assert "Fillet1" in entry.detail and QUARANTINE in entry.detail


def test_a_backward_reference_pins_the_feature_and_names_the_same_edge() -> None:
    tree = backward_reference_tree()
    targets = backward_reference_targets(tree)
    desired, result = ordered(tree, targets)
    fillet, cut = ids(tree, "Fillet1", "Cut-Extrude1")

    report = assess(
        tree, target_groups=targets, desired=desired, achievable=result.achievable
    )

    (pin,) = [entry for entry in report.pins if entry.feature_id == cut]
    assert pin.blocking_edge == Edge(parent_id=fillet, child_id=cut)
    assert pin.desired_index == desired.index(cut)
    assert pin.achievable_index == list(result.achievable).index(cut)
    assert pin.desired_index < pin.achievable_index
    assert pin.reason, "a pin with no reason is a bug, not a pin"


def test_splits_group_names_the_interloper_and_the_span() -> None:
    """The Quarantine fillet lands between the two Detail features, so Detail cannot be
    folded: the interloper is listed with the span it splits, and every member of the
    group is listed with the interloper named (spec.md US1 scenario 5)."""
    tree = backward_reference_tree()
    targets = backward_reference_targets(tree)
    desired, result = ordered(tree, targets)
    fillet, sketch2, cut = ids(tree, "Fillet1", "Sketch2", "Cut-Extrude1")

    report = assess(
        tree, target_groups=targets, desired=desired, achievable=result.achievable
    )

    (split,) = report.non_contiguous
    assert split.group == DETAIL
    assert split.member_ids == (sketch2, cut)
    assert split.interloper_ids == (fillet,)

    by_id = entries(report)
    assert by_id[fillet].reason == "splits_group"
    assert DETAIL in by_id[fillet].detail
    assert by_id[fillet].blocking_edge == Edge(parent_id=fillet, child_id=cut)

    assert by_id[sketch2].reason == "splits_group"
    assert "Fillet1" in by_id[sketch2].detail
    assert by_id[cut].reason == "backward_reference", (
        "the edge that holds a feature is more actionable than the span it lands in"
    )


def test_shared_sketch_names_both_consumers() -> None:
    tree = build(shared_sketch_features())
    sketch, boss, cut = ids(tree, "Sketch1", "Boss-Extrude1", "Cut-Extrude1")
    targets = {sketch: CORE, boss: CORE, cut: DETAIL}
    desired, result = ordered(tree, targets)

    report = assess(
        tree, target_groups=targets, desired=desired, achievable=result.achievable
    )

    entry = entries(report)[sketch]
    assert entry.reason == "shared_sketch"
    assert "Boss-Extrude1" in entry.detail and "Cut-Extrude1" in entry.detail
    assert entry.blocking_edge is None


def test_cycle_names_the_cycle_and_reports_no_order() -> None:
    """A cycle is `order.py`'s refusal, and every feature it names is on the rebuild list:
    there is no legal order for them, so there is nothing to pin them against."""
    tree = build(
        linked(
            [
                sketch_feature("Sketch1"),
                feature("Boss-Extrude1", "Extrusion"),
                feature("Cut-Extrude1", "Cut"),
            ],
            ("Sketch1", "Boss-Extrude1"),
        )
    )
    boss, cut = ids(tree, "Boss-Extrude1", "Cut-Extrude1")
    targets = groups_of(
        tree, {"Sketch1": CORE, "Boss-Extrude1": CORE, "Cut-Extrude1": DETAIL}
    )

    report = assess(
        tree,
        target_groups=targets,
        desired=list(content_ids(tree)),
        achievable=(),
        cycle=(boss, cut),
    )

    by_id = entries(report)
    assert by_id[boss].reason == "cycle"
    assert by_id[cut].reason == "cycle"
    assert "Boss-Extrude1" in by_id[boss].detail and "Cut-Extrude1" in by_id[boss].detail
    assert by_id[boss].blocking_edge is None
    assert report.pins == ()
    assert report.non_contiguous == ()


def test_radius_unreadable_blocks_the_fillet_that_cannot_be_ranked() -> None:
    tree = build(variable_radius_fillet_features())
    sketch, boss, fillet, variable = ids(
        tree, "Sketch1", "Boss-Extrude1", "Fillet1", "Fillet-Variable1"
    )
    targets = {sketch: CORE, boss: CORE, fillet: CORE, variable: CORE}
    desired, result = ordered(tree, targets)

    report = assess(
        tree, target_groups=targets, desired=desired, achievable=result.achievable
    )

    by_id = entries(report)
    assert by_id[variable].reason == "radius_unreadable"
    assert by_id[variable].blocking_edge is None
    assert "radius" in by_id[variable].detail.lower()
    assert fillet not in by_id, "a fillet whose radius reads is rankable and not rebuilt"


def test_ambiguous_name_is_carried_across_from_the_rename_plan() -> None:
    """Most duplicates are renamed before any reorder (T012), so only the ones `names.py`
    blocked are rebuild entries - and their sentence is the one it wrote, because it names
    the rows that share the name and why neither could be renamed first.

    Both fillets here are referenced by an equation, which is `names.py`'s refusal to
    rename, so the pair reaches feasibility blocked rather than repaired.
    """
    package = remodel_package(
        [
            feature("Boss-Extrude1", "Extrusion"),
            fillet_feature("Fillet1"),
            fillet_feature("Fillet1"),
        ],
        equations=[equation('"D1@Fillet1" = 5')],
    )
    rows = [row for row in package.features if row.document_id == DOCUMENT]
    tree = part_tree(DOCUMENT, rows, TABLE, assign_groups(rows, TABLE), package)
    name_plan = plan_renames(tree.rows, package.equations, TABLE)
    assert name_plan.renames == (), "a referenced duplicate is not renamed by this version"
    blocked = {entry.feature_id: entry for entry in name_plan.blocked}
    assert len(blocked) == 2, "both rows carrying the name are reported"

    targets = {row.id: CORE for row in tree.rows}
    desired = list(content_ids(tree))

    report = assess(
        tree,
        target_groups=targets,
        desired=desired,
        achievable=desired,
        ambiguous_names=name_plan.blocked,
    )

    by_id = entries(report)
    for feature_id, blocked_entry in blocked.items():
        assert by_id[feature_id].reason == "ambiguous_name"
        assert by_id[feature_id].detail == blocked_entry.detail
        assert by_id[feature_id].blocking_edge is None
    assert AMBIGUOUS_NAME in REBUILD_REASONS


def test_a_repairable_duplicate_is_renamed_and_is_not_a_rebuild_entry() -> None:
    tree = build(duplicate_name_features())
    duplicates = [row.id for row in tree.content if row.name == "Fillet1"]
    assert len(duplicates) == 2, "the fixture is two features sharing one name"
    name_plan = plan_renames(tree.rows, tree.package.equations, TABLE)
    assert {rename.feature_id for rename in name_plan.renames} == {duplicates[1]}
    assert name_plan.blocked == ()

    desired = list(content_ids(tree))
    report = assess(
        tree,
        target_groups={row.id: CORE for row in tree.rows},
        desired=desired,
        achievable=desired,
        ambiguous_names=name_plan.blocked,
    )

    assert entries(report) == {}


def test_a_blocked_name_naming_a_feature_outside_the_tree_is_refused() -> None:
    tree = build([feature("Boss-Extrude1", "Extrusion")])
    (boss,) = ids(tree, "Boss-Extrude1")

    with pytest.raises(ValueError, match="feat:9999"):
        assess(
            tree,
            target_groups={boss: CORE},
            desired=[boss],
            achievable=[boss],
            ambiguous_names=[
                AmbiguousName(
                    feature_id="feat:9999", name="Fillet1", detail="shared with feat:0001"
                )
            ],
        )


def test_unclassified_names_the_type_the_table_does_not_carry() -> None:
    tree = build(unknown_type_features())
    sketch, boss, deform = ids(tree, "Sketch1", "Boss-Extrude1", "Deform1")
    targets: dict[str, str | None] = {sketch: CORE, boss: CORE, deform: None}
    desired, result = ordered(tree, targets)

    report = assess(
        tree, target_groups=targets, desired=desired, achievable=result.achievable
    )

    entry = entries(report)[deform]
    assert entry.reason == "unclassified"
    assert UNKNOWN_TYPE_NAME in entry.detail
    assert entry.blocking_edge is None


def test_an_ambiguous_type_is_not_unclassified() -> None:
    """`ICE` is in the table as `ambiguous`; it goes to the model (R6.1), and reporting it
    as a type the table does not carry would be a different and untrue statement."""
    tree = build([feature("Boss-Extrude1", "Extrusion"), feature("ICE1", "ICE")])
    boss, ice = ids(tree, "Boss-Extrude1", "ICE1")
    targets: dict[str, str | None] = {boss: CORE, ice: None}

    report = assess(
        tree,
        target_groups=targets,
        desired=[boss, ice],
        achievable=[boss, ice],
    )

    assert ice not in entries(report)


def test_graph_unreadable_never_moves_a_feature_on_an_unknown_graph() -> None:
    tree = build(
        [
            sketch_feature("Sketch1", consumers=["Boss-Extrude1"]),
            feature("Boss-Extrude1", "Extrusion", parent_names=["Sketch1"]),
            feature("Rib1", "Extrusion", child_names=None, parent_names=None),
        ]
    )
    sketch, boss, rib = ids(tree, "Sketch1", "Boss-Extrude1", "Rib1")
    targets = {sketch: CORE, boss: CORE, rib: CORE}

    report = assess(
        tree,
        target_groups=targets,
        desired=[sketch, boss, rib],
        achievable=[sketch, boss, rib],
    )

    entry = entries(report)[rib]
    assert entry.reason == "graph_unreadable"
    assert "GetChildren" in entry.detail or "children" in entry.detail
    assert entry.blocking_edge is None


# --- the boundaries ---------------------------------------------------------------


def test_an_rms_named_folder_with_the_wrong_members_is_not_a_rebuild_reason() -> None:
    """`data-model.md` sections 1.6 and 4.2: one scope refusal token, raised from
    `ScopeSignals` before anything is copied, because there is no dissolve path in v1.
    Feasibility neither spells it nor files the folder on the rebuild list."""
    assert RMS_NAMED_FOLDER_WRONG_MEMBERS not in REBUILD_REASONS

    tree = build(mis_membered_group_folder_features())
    (folder_id,) = ids(tree, CORE)
    targets = groups_of(
        tree,
        {
            "Sketch1": CORE,
            "Boss-Extrude1": CORE,
            "Cut-Extrude1": DETAIL,
            "Hole1": DETAIL,
            "Fillet1": CORE,
        },
    )
    desired, result = ordered(tree, targets)

    report = assess(
        tree, target_groups=targets, desired=desired, achievable=result.achievable
    )

    assert all(entry.reason != RMS_NAMED_FOLDER_WRONG_MEMBERS for entry in report.rebuild)
    assert RMS_NAMED_FOLDER_WRONG_MEMBERS not in str(report.rebuild)
    assert folder_id not in entries(report), "a folder is not a feature the plan moves"


def test_a_sketch_whose_consumers_were_unreadable_is_not_a_shared_sketch() -> None:
    """Unreadable is not "two consumers" and not "graph unreadable" either: the parents
    read, so the taxonomy has no entry for it and the plan's coverage list (`data-model.md`
    section 1.10) is where the gap is reported. Asserted so the silence stays deliberate."""
    tree = build(
        [
            sketch_feature("Sketch1", consumers=None),
            feature("Boss-Extrude1", "Extrusion", parent_names=["Sketch1"]),
        ]
    )
    sketch, boss = ids(tree, "Sketch1", "Boss-Extrude1")
    assert tree.by_id[sketch].sketch is not None
    assert tree.by_id[sketch].sketch.consumer_ids is None
    assert tree.by_id[sketch].parent_ids == []

    report = assess(
        tree,
        target_groups={sketch: CONSTRUCTION, boss: CORE},
        desired=[sketch, boss],
        achievable=[sketch, boss],
    )

    assert sketch not in entries(report)


def test_a_feature_that_matches_two_detections_carries_the_higher_precedence_reason() -> None:
    """An unclassified feature whose graph is also unreadable is `graph_unreadable`:
    evidence that was never read comes before evidence that was read and did not fit."""
    tree = build(
        [
            feature("Boss-Extrude1", "Extrusion"),
            feature("Deform1", UNKNOWN_TYPE_NAME, child_names=None, parent_names=None),
        ]
    )
    boss, deform = ids(tree, "Boss-Extrude1", "Deform1")

    report = assess(
        tree,
        target_groups={boss: CORE, deform: None},
        desired=[boss, deform],
        achievable=[boss, deform],
    )

    assert entries(report)[deform].reason == "graph_unreadable"
    assert RESOLUTION_ORDER.index("graph_unreadable") < RESOLUTION_ORDER.index("unclassified")


def test_a_compliant_part_has_no_pins_no_splits_and_an_empty_rebuild_list() -> None:
    tree = build(
        linked(
            [
                sketch_feature("Sketch1"),
                feature("Boss-Extrude1", "Extrusion"),
                sketch_feature("Sketch2"),
                feature("Cut-Extrude1", "Cut"),
            ],
            ("Sketch1", "Boss-Extrude1"),
            ("Sketch2", "Cut-Extrude1"),
        )
    )
    sketch1, boss, sketch2, cut = ids(
        tree, "Sketch1", "Boss-Extrude1", "Sketch2", "Cut-Extrude1"
    )
    targets = {sketch1: CORE, boss: CORE, sketch2: DETAIL, cut: DETAIL}
    desired, result = ordered(tree, targets)

    report = assess(
        tree, target_groups=targets, desired=desired, achievable=result.achievable
    )

    assert result.move_count == 0
    assert report.pins == ()
    assert report.non_contiguous == ()
    assert report.rebuild == ()


def test_the_rebuild_list_is_in_tree_order_and_names_each_feature_once() -> None:
    tree = backward_reference_tree()
    targets = backward_reference_targets(tree)
    desired, result = ordered(tree, targets)

    report = assess(
        tree, target_groups=targets, desired=desired, achievable=result.achievable
    )

    listed = [entry.feature_id for entry in report.rebuild]
    assert listed == in_tree_order(tree, listed)
    assert len(listed) == len(set(listed))
    for entry in report.rebuild:
        assert entry.name == tree.by_id[entry.feature_id].name


# --- refusals ---------------------------------------------------------------------


def test_a_feature_with_no_target_group_entry_is_refused_by_name() -> None:
    tree = build([feature("Boss-Extrude1", "Extrusion")])
    (boss,) = ids(tree, "Boss-Extrude1")

    with pytest.raises(ValueError, match=boss):
        assess(tree, target_groups={}, desired=[boss], achievable=[boss])


def test_an_order_that_omits_a_content_feature_is_refused_by_name() -> None:
    tree = build([feature("Boss-Extrude1", "Extrusion"), feature("Cut-Extrude1", "Cut")])
    boss, cut = ids(tree, "Boss-Extrude1", "Cut-Extrude1")

    with pytest.raises(ValueError, match=cut):
        assess(
            tree,
            target_groups={boss: CORE, cut: DETAIL},
            desired=[boss, cut],
            achievable=[boss],
        )


def test_a_cycle_that_names_no_feature_is_refused() -> None:
    tree = build([feature("Boss-Extrude1", "Extrusion")])
    (boss,) = ids(tree, "Boss-Extrude1")

    with pytest.raises(ValueError, match="names none"):
        assess(
            tree, target_groups={boss: CORE}, desired=[boss], achievable=(), cycle=()
        )


def test_a_refused_order_may_not_also_carry_an_achievable_order() -> None:
    tree = build([feature("Boss-Extrude1", "Extrusion")])
    (boss,) = ids(tree, "Boss-Extrude1")

    with pytest.raises(ValueError, match="cycle"):
        assess(
            tree,
            target_groups={boss: CORE},
            desired=[boss],
            achievable=[boss],
            cycle=(boss,),
        )
