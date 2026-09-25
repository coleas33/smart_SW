"""Unit tests for the planner's target group (feature 004 T008).

`remodel/target.py` answers one question per feature - *which of the six groups should
this feature be in* - and it is the only place feature 004 turns a class into a group.
What is pinned here:

- every class resolves to the group `default_group_by_class` names, so the planner and
  feature 003's checker read one file and cannot disagree about what "should" means;
- the two rules that are code rather than table: a consumed sketch follows its **single**
  consumer into that consumer's group, and an unconsumed sketch takes the table's sketch
  default;
- nothing is ever guessed. A sketch with two consumers, a type name the table does not
  carry, `ICE`, and a graph that could not be read are all `NeedsJudgement`, never a group
  (constitution Principle I);
- folders, end-tag markers, the excluded default names and the tolerated system rows are
  `NotContent`: they are not the grouping rules' subjects, which is a different answer
  from "content whose group is undecided".
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from swreview.checks.rms_types import FEATURE_CLASSES, FeatureClass, load_table
from swreview.ir.models import Feature
from swreview.remodel.target import (
    BASES,
    JUDGEMENT_REASONS,
    NeedsJudgement,
    NotContent,
    Resolved,
    TargetDecision,
    target_group,
)
from tests.support.features import (
    FeatureSpec,
    end_tag,
    feature,
    fillet_feature,
    folder,
    sketch_feature,
)
from tests.support.remodel import (
    UNKNOWN_TYPE_NAME,
    linked,
    remodel_package,
    shared_sketch_features,
    unknown_type_features,
)

TABLE = load_table()

REPRESENTATIVE_TYPE: dict[FeatureClass, str] = {
    "sketch": "ProfileFeature",
    "solid": "Extrusion",
    "cut": "Cut",
    "hole": "HoleWzd",
    "fillet": "Fillet",
    "chamfer": "Chamfer",
    "shell": "Shell",
    "draft": "Draft",
    "pattern": "LPattern",
    "reference": "RefAxis",
    "construction": "SurfaceExtrude",
}
"""One `GetTypeName2` value per class, named here rather than taken from the table's own
sets, so a case reads as the part it stands for. Every one is checked against the table
below: a type moved to another class fails that test rather than silently re-labelling a
case here. `RefAxis` is the reference-class representative because `RefPlane`,
`RefPoint` and `CoordSys` are tolerated system rows and therefore not content."""


def decide(specs: Sequence[FeatureSpec], name: str) -> TargetDecision:
    """The decision for the row called `name` in a package built from `specs`."""
    package = remodel_package(list(specs))
    rows = list(package.features)
    return target_group(row_named(rows, name), rows, TABLE)


def row_named(rows: Sequence[Feature], name: str) -> Feature:
    matches = [row for row in rows if row.name == name]
    assert len(matches) == 1, f"{name!r} names {len(matches)} rows, not one"
    return matches[0]


# --- one case per class -------------------------------------------------------------


def test_the_representative_types_are_the_classes_the_table_carries() -> None:
    """The cases below stand for the eleven classes; a type re-classified in
    `rms_types.yaml` must fail here rather than quietly test another class."""
    assert set(REPRESENTATIVE_TYPE) == set(FEATURE_CLASSES)
    for name, type_name in REPRESENTATIVE_TYPE.items():
        assert TABLE.classify(type_name) == name


@pytest.mark.parametrize(
    "feature_class", [name for name in FEATURE_CLASSES if name != "sketch"]
)
def test_every_non_sketch_class_takes_the_group_the_table_names(
    feature_class: FeatureClass,
) -> None:
    decision = decide([feature("Feature1", REPRESENTATIVE_TYPE[feature_class])], "Feature1")

    assert decision == Resolved(
        group=TABLE.default_group(feature_class), basis="type_table"
    )


def test_a_fillet_defaults_to_core_rather_than_quarantine() -> None:
    """The owner's safe default (research.md R6.1): Core never violates
    `rms.refs.quarantine_has_no_children`, and only the judgement phase may move a
    cosmetic fillet to Quarantine."""
    decision = decide([fillet_feature("Fillet1")], "Fillet1")

    assert decision == Resolved(group="3-Core", basis="type_table")


# --- sketches: the two rules that are code, not table --------------------------------


def test_a_sketch_follows_its_single_consumer() -> None:
    specs = linked(
        [sketch_feature("Sketch1"), feature("Cut-Extrude1", "Cut")],
        ("Sketch1", "Cut-Extrude1"),
    )

    decision = decide(specs, "Sketch1")

    assert decision == Resolved(
        group=TABLE.default_group("cut"), basis="sketch_follows_consumer"
    )
    assert decision != decide(specs, "Cut-Extrude1")  # the consumer keeps its own basis


def test_a_sketch_follows_a_chain_of_consumers_to_the_feature_that_ends_it() -> None:
    """A sketch consumed by a sketch consumed by a boss belongs where the boss belongs;
    stopping at the intermediate sketch would put it in Construction on a technicality."""
    specs = linked(
        [
            sketch_feature("Sketch1"),
            sketch_feature("Sketch2", type_name="3DProfileFeature"),
            feature("Boss-Extrude1", "Extrusion"),
        ],
        ("Sketch1", "Sketch2"),
        ("Sketch2", "Boss-Extrude1"),
    )

    assert decide(specs, "Sketch1") == Resolved(
        group=TABLE.default_group("solid"), basis="sketch_follows_consumer"
    )


def test_an_unconsumed_sketch_takes_the_tables_sketch_default() -> None:
    decision = decide([sketch_feature("Sketch1", consumers=())], "Sketch1")

    assert decision == Resolved(
        group=TABLE.default_group("sketch"), basis="unconsumed_sketch"
    )
    assert decision.group == "2-Construction"


def test_a_sketch_with_two_consumers_needs_judgement() -> None:
    """`shared_sketch`: it can be contiguous with one consumer and not the other, so the
    planner names the problem instead of picking a consumer."""
    decision = decide(shared_sketch_features(), "Sketch1")

    assert decision == NeedsJudgement(reason="shared_sketch", candidates=())


def test_a_sketch_whose_consumers_were_not_read_is_never_placed() -> None:
    """`GetChildren` failed, so the sketch has no consumer to follow. Absence is not
    emptiness: this is not the unconsumed case and does not take its default."""
    decision = decide([sketch_feature("Sketch1", consumers=None)], "Sketch1")

    assert decision == NeedsJudgement(reason="graph_unreadable", candidates=())


def test_a_sketch_consumed_only_by_a_tolerated_row_has_no_group_to_follow() -> None:
    """A tolerated system row is not held to the grouping rules, so it carries no group
    for a sketch to follow and the sketch takes the unconsumed default."""
    specs = linked(
        [sketch_feature("Sketch1"), feature("Plane1", "RefPlane")],
        ("Sketch1", "Plane1"),
    )

    assert decide(specs, "Sketch1") == Resolved(
        group=TABLE.default_group("sketch"), basis="unconsumed_sketch"
    )


def test_a_sketch_whose_single_consumer_is_undecided_is_undecided_for_the_same_reason() -> (
    None
):
    """Following an unclassified consumer into a group would be guessing twice."""
    specs = linked(
        [sketch_feature("Sketch1"), feature("Deform1", UNKNOWN_TYPE_NAME)],
        ("Sketch1", "Deform1"),
    )

    assert decide(specs, "Sketch1") == decide(specs, "Deform1")
    assert decide(specs, "Sketch1").reason == "unclassified"


def test_a_consumer_chain_that_loops_is_refused_rather_than_followed_forever() -> None:
    """Two sketches consuming each other is not a tree SOLIDWORKS builds, and the answer
    is the taxonomy's `cycle`, not a recursion error."""
    specs = linked(
        [
            sketch_feature("Sketch1"),
            sketch_feature("Sketch2", type_name="3DProfileFeature"),
        ],
        ("Sketch1", "Sketch2"),
        ("Sketch2", "Sketch1"),
    )

    assert decide(specs, "Sketch1") == NeedsJudgement(reason="cycle", candidates=())


# --- the two the table refuses to place ----------------------------------------------


def test_an_unclassified_type_is_offered_to_judgement_and_never_guessed() -> None:
    decision = decide(unknown_type_features(), "Deform1")

    assert decision == NeedsJudgement(reason="unclassified", candidates=TABLE.groups)
    assert not hasattr(decision, "group")


def test_ice_is_ambiguous_and_never_guessed() -> None:
    """`ICE` is in the table as ambiguous: the name is known and the class is not, which
    is a different reason from a name nobody recognised."""
    decision = decide([feature("ICE1", "ICE")], "ICE1")

    assert decision == NeedsJudgement(reason="ambiguous_type", candidates=TABLE.groups)


def test_the_candidates_offered_are_exactly_the_six_groups() -> None:
    """`classify_unknown` accepts one of the six (contracts/tools.md), so those are what
    the model may be offered and `needs_judgement` is never among them."""
    decision = decide([feature("ICE1", "ICE")], "ICE1")

    assert decision.candidates == TABLE.groups
    assert len(decision.candidates) == 6
    assert "needs_judgement" not in decision.candidates


# --- what is not content -------------------------------------------------------------


@pytest.mark.parametrize(
    ("specs", "name"),
    [
        pytest.param(
            [folder("3-Core", feature("Boss-Extrude1", "Extrusion"))], "3-Core", id="folder"
        ),
        pytest.param([end_tag("3-Core")], "3-Core___EndTag___", id="end_tag"),
        pytest.param([feature("Front Plane", "RefPlane")], "Front Plane", id="default_name"),
        pytest.param([feature("Plane1", "RefPlane")], "Plane1", id="tolerated_type"),
    ],
)
def test_rows_the_grouping_rules_do_not_hold_are_not_content(
    specs: Sequence[FeatureSpec], name: str
) -> None:
    assert decide(specs, name) == NotContent()


@pytest.mark.parametrize(
    "type_name",
    [
        "NotesAreaFtrFolder",
        "AnnotationViewFeat",
        "AmbientLight",
        "DirectionLight",
        "FeatSolidBodyFolder",
        "FeatSurfaceBodyFolder",
        "RefAxisFtrFolder",
        "RefPlaneFtrFolder",
        "ProfileFtrFolder",
        "RefPointFtrFolder",
        "CosmeticThread",
    ],
)
def test_the_system_types_of_the_real_packages_are_not_content(type_name: str) -> None:
    """T144 (decision 17A): the planner counted these as content of unknown class and put
    them on the rebuild list as `unclassified`, although no one of them is a feature the six
    groups organize. Listed top-level here, where the carried-row rule of `nodes.py` does
    not already take them out of the plan. They are `tolerated_loose` in the shipped table
    itself (decision 20A), the table `plan_reorganize` hands `target_group` as it is."""
    rows = list(remodel_package([feature(f"{type_name}1", type_name)]).features)

    assert target_group(rows[0], rows, TABLE) == NotContent()


def test_not_content_is_not_the_same_answer_as_undecided() -> None:
    """A folder has no target because it is not a subject; an unclassified feature has no
    target because nobody could decide. The report says different things about them."""
    folder_decision = decide([folder("3-Core", feature("Boss1", "Extrusion"))], "3-Core")
    unknown_decision = decide(unknown_type_features(), "Deform1")

    assert isinstance(folder_decision, NotContent)
    assert isinstance(unknown_decision, NeedsJudgement)
    assert folder_decision != unknown_decision


# --- the closed vocabularies ---------------------------------------------------------


def test_every_resolved_group_is_one_of_the_six_and_every_basis_is_in_the_closed_set() -> (
    None
):
    """One sweep over a tree carrying every shape: no decision may invent a group name or
    a basis, whatever path produced it."""
    specs = linked(
        [
            feature("Plane1", "RefPlane"),
            sketch_feature("Sketch1"),
            feature("Boss-Extrude1", "Extrusion"),
            fillet_feature("Fillet1"),
            feature("Hole1", "HoleWzd"),
            feature("Draft1", "Draft"),
            feature("LPattern1", "LPattern"),
            feature("Shell1", "Shell"),
            feature("Deform1", UNKNOWN_TYPE_NAME),
            folder("3-Core"),
        ],
        ("Plane1", "Sketch1"),
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Fillet1"),
        ("Boss-Extrude1", "Hole1"),
        ("Boss-Extrude1", "Draft1"),
        ("Draft1", "LPattern1"),
        ("Fillet1", "Shell1"),
    )
    package = remodel_package(specs)
    rows = list(package.features)

    decisions = [target_group(row, rows, TABLE) for row in rows]

    assert any(isinstance(decision, Resolved) for decision in decisions)
    assert any(isinstance(decision, NeedsJudgement) for decision in decisions)
    assert any(isinstance(decision, NotContent) for decision in decisions)
    for decision in decisions:
        if isinstance(decision, Resolved):
            assert decision.group in TABLE.groups
            assert decision.basis in BASES
        elif isinstance(decision, NeedsJudgement):
            assert decision.reason in JUDGEMENT_REASONS
            assert all(group in TABLE.groups for group in decision.candidates)


def test_the_judgement_reasons_are_the_five_the_planner_can_reach() -> None:
    """Closed, and every one of them is produced by a test above; a sixth would be a
    reason the rebuild-list taxonomy has no home for."""
    assert JUDGEMENT_REASONS == (
        "unclassified",
        "ambiguous_type",
        "shared_sketch",
        "graph_unreadable",
        "cycle",
    )


def test_the_bases_are_the_five_the_data_model_names() -> None:
    """The last two belong to the judgement phase; the pure planner emits the first
    three, and `plan.py` writes them into `PlanTarget.basis` from this one vocabulary."""
    assert BASES == (
        "type_table",
        "sketch_follows_consumer",
        "unconsumed_sketch",
        "model_judgement",
        "quarantine_has_children",
    )


def test_a_decision_is_frozen() -> None:
    """A plan is rewritten on every state transition; a decision another step could edit
    in place would make the written plan and the decision disagree."""
    decision = decide([feature("Boss1", "Extrusion")], "Boss1")

    with pytest.raises(Exception):  # noqa: B017 - pydantic raises ValidationError on a frozen model
        decision.group = "6-Quarantine"
