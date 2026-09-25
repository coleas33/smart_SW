"""Unit tests for the RMS type table (T007).

The table is the one place a `GetTypeName2` string becomes a class, a folder, an end-tag
marker, content, or a constrained-status name (`specs/003-resilient-modeling/data-model.md`
section 3 and `contracts/rules.md`, "Class vocabulary" and "Content features"). Everything
here is asserted against the shipped `checks/rms_types.yaml` read a second time in the
test, so the loader can never quietly disagree with the file an engineer edits.

The two answers the method must never guess are pinned hardest: a type name the table does
not carry classifies as `unknown` (and is still content, so it must be grouped and
described), and an absent constrained status is `unavailable`, never a defined sketch.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import yaml

from swreview.checks.rms_types import (
    CLASSIFICATIONS,
    DEFAULT_TYPES_PATH,
    FEATURE_CLASSES,
    NEEDS_JUDGEMENT,
    REQUIRED_KEYS,
    RmsTypeTable,
    class_of,
    load_table,
)
from swreview.ir.models import Feature
from tests.support.packages import persist_ref


def build_feature(**overrides: Any) -> Feature:
    """A minimal valid `Feature`; only `name` and `type_name` matter to the table."""
    fields: dict[str, Any] = {
        "id": "feat:0001",
        "persist_ref": persist_ref("feat:0001"),
        "persist_ref_scope": "doc:2",
        "document_id": "doc:2",
        "configuration": "Default",
        "name": "Boss-Extrude1",
        "type_name": "Extrusion",
        "description": None,
        "index": 0,
        "depth": 0,
        "folder_id": None,
        "suppressed": False,
        "error_code": 0,
        "child_ids": [],
        "parent_ids": [],
        "sketch": None,
        "fillet": None,
    }
    fields.update(overrides)
    return Feature(**fields)


@pytest.fixture(scope="module")
def table() -> RmsTypeTable:
    return load_table()


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    """The shipped YAML, read independently of the loader."""
    return yaml.safe_load(DEFAULT_TYPES_PATH.read_text(encoding="utf-8"))


# --- the shipped file -------------------------------------------------------------


def test_the_default_path_is_the_shipped_yaml() -> None:
    assert DEFAULT_TYPES_PATH.name == "rms_types.yaml"
    assert DEFAULT_TYPES_PATH.is_file()


def test_load_table_reads_the_shipped_file_by_default(
    table: RmsTypeTable, document: dict[str, Any]
) -> None:
    assert table.version == document["version"]
    assert table.folder_type == document["folder_type"] == "FtrFolder"
    assert table.end_tag_suffix == document["end_tag_suffix"] == "___EndTag___"
    assert list(table.groups) == document["groups"]
    assert len(table.groups) == 6


def test_the_required_keys_are_exactly_the_shipped_files_keys(
    document: dict[str, Any],
) -> None:
    assert set(document) == set(REQUIRED_KEYS)


@pytest.mark.parametrize(
    "field", ["classes", "constrained_status_map", "default_group_by_class"]
)
def test_the_cached_tables_mappings_cannot_be_mutated(
    table: RmsTypeTable, field: str
) -> None:
    """`load_table` is cached, so every rule in a review shares one object: a rule that
    edited one of its mappings would silently change what every later rule classifies."""
    mapping = getattr(table, field)

    assert isinstance(mapping, MappingProxyType)
    with pytest.raises(TypeError):
        mapping["nope"] = frozenset()  # type: ignore[index]


def test_load_table_is_cached_by_resolved_path(tmp_path: Path) -> None:
    unresolved = DEFAULT_TYPES_PATH.parent / ".." / "checks" / DEFAULT_TYPES_PATH.name

    assert load_table() is load_table(DEFAULT_TYPES_PATH)
    assert load_table() is load_table(str(DEFAULT_TYPES_PATH))
    assert load_table() is load_table(unresolved)

    copy = tmp_path / "rms_types.yaml"
    copy.write_text(DEFAULT_TYPES_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_table(copy) is not load_table()
    assert load_table(copy) is load_table(copy)


def test_calibrated_version_is_exposed(
    table: RmsTypeTable, document: dict[str, Any]
) -> None:
    assert table.calibrated_version == document["calibrated_version"] == "2026 SP1.1"


# --- classify ---------------------------------------------------------------------


def test_the_class_names_are_exactly_the_contract_vocabulary(table: RmsTypeTable) -> None:
    assert set(table.classes) == set(FEATURE_CLASSES)
    assert FEATURE_CLASSES == (
        "sketch",
        "solid",
        "cut",
        "hole",
        "fillet",
        "chamfer",
        "shell",
        "draft",
        "pattern",
        "reference",
        "construction",
    )


def test_the_class_sets_are_pairwise_disjoint(table: RmsTypeTable) -> None:
    seen: dict[str, str] = {}
    for name, members in table.classes.items():
        for type_name in members:
            assert type_name not in seen, (
                f"{type_name!r} is in both {seen.get(type_name)!r} and {name!r}"
            )
            seen[type_name] = name


def test_the_ambiguous_set_is_disjoint_from_every_class(table: RmsTypeTable) -> None:
    for members in table.classes.values():
        assert not (members & table.ambiguous)


def test_classify_returns_its_own_class_for_every_member(
    table: RmsTypeTable, document: dict[str, Any]
) -> None:
    for name, members in document["classes"].items():
        for type_name in members:
            assert table.classify(type_name) == name


def test_classify_spot_checks_one_member_of_each_class(table: RmsTypeTable) -> None:
    assert table.classify("ProfileFeature") == "sketch"
    assert table.classify("Extrusion") == "solid"
    assert table.classify("CutRevolve") == "cut"
    assert table.classify("HoleWzd") == "hole"
    assert table.classify("Fillet") == "fillet"
    assert table.classify("Chamfer") == "chamfer"
    assert table.classify("Shell") == "shell"
    assert table.classify("Draft") == "draft"
    assert table.classify("MirrorPattern") == "pattern"
    assert table.classify("RefPlane") == "reference"
    assert table.classify("SurfaceKnit") == "construction"


def test_classify_returns_ambiguous_for_ice(table: RmsTypeTable) -> None:
    assert table.ambiguous == frozenset({"ICE"})
    assert table.classify("ICE") == "ambiguous"


def test_classify_returns_unknown_for_a_name_the_table_does_not_carry(
    table: RmsTypeTable,
) -> None:
    assert table.classify("WeldmentStructuralMember") == "unknown"
    assert table.classify("") == "unknown"


def test_classify_is_case_sensitive_because_get_type_name2_is(
    table: RmsTypeTable,
) -> None:
    assert table.classify("extrusion") == "unknown"


def test_class_of_reads_the_features_type_name(table: RmsTypeTable) -> None:
    assert class_of(build_feature(type_name="Fillet"), table) == "fillet"
    assert class_of(build_feature(type_name="ICE"), table) == "ambiguous"
    assert class_of(build_feature(type_name="NoSuchFeature"), table) == "unknown"


def test_class_of_defaults_to_the_shipped_table() -> None:
    assert class_of(build_feature(type_name="Shell")) == "shell"


# --- folders and end-tag markers ---------------------------------------------------


def test_is_folder_is_true_for_a_folder_typed_feature(table: RmsTypeTable) -> None:
    assert table.is_folder(build_feature(name="Core", type_name="FtrFolder"))


def test_is_folder_is_false_for_any_other_type(table: RmsTypeTable) -> None:
    assert not table.is_folder(build_feature(name="Core", type_name="Extrusion"))


def test_an_end_tag_marker_is_folder_typed_with_the_suffix(table: RmsTypeTable) -> None:
    end_tag = build_feature(name="Bracket___EndTag___", type_name="FtrFolder")

    assert table.is_end_tag(end_tag)


def test_an_end_tag_marker_is_not_itself_a_folder(table: RmsTypeTable) -> None:
    end_tag = build_feature(name="Bracket___EndTag___", type_name="FtrFolder")

    assert not table.is_folder(end_tag)


def test_a_non_folder_named_like_an_end_tag_is_not_an_end_tag(
    table: RmsTypeTable,
) -> None:
    impostor = build_feature(name="X___EndTag___", type_name="Extrusion")

    assert not table.is_end_tag(impostor)
    assert not table.is_folder(impostor)
    assert table.is_content(impostor)


def test_a_folder_without_the_suffix_is_not_an_end_tag(table: RmsTypeTable) -> None:
    assert not table.is_end_tag(build_feature(name="Detail", type_name="FtrFolder"))


# --- content ----------------------------------------------------------------------


def test_an_ordinary_feature_is_content(table: RmsTypeTable) -> None:
    assert table.is_content(build_feature(name="Boss-Extrude1", type_name="Extrusion"))


def test_a_folder_is_not_content(table: RmsTypeTable) -> None:
    assert not table.is_content(build_feature(name="Core", type_name="FtrFolder"))


def test_an_end_tag_marker_is_not_content(table: RmsTypeTable) -> None:
    assert not table.is_content(
        build_feature(name="Bracket___EndTag___", type_name="FtrFolder")
    )


def test_no_tolerated_type_is_content(
    table: RmsTypeTable, document: dict[str, Any]
) -> None:
    for type_name in document["tolerated_loose"]:
        assert not table.is_content(build_feature(name="Whatever", type_name=type_name))


def test_no_excluded_default_name_is_content(
    table: RmsTypeTable, document: dict[str, Any]
) -> None:
    assert document["default_names_excluded"] == [
        "Front Plane",
        "Top Plane",
        "Right Plane",
        "Origin",
    ]
    for name in document["default_names_excluded"]:
        assert not table.is_content(build_feature(name=name, type_name="RefPlane"))


def test_the_excluded_names_are_excluded_by_name_not_by_type(
    table: RmsTypeTable,
) -> None:
    renamed = build_feature(name="Mounting Plane", type_name="ProfileFeature")

    assert table.is_content(renamed)


def test_a_feature_of_unknown_class_is_still_content(table: RmsTypeTable) -> None:
    unknown = build_feature(name="Structural Member1", type_name="WeldmentTrimExtendFeat")

    assert table.classify(unknown.type_name) == "unknown"
    assert table.is_content(unknown)


def test_an_ambiguous_feature_is_content(table: RmsTypeTable) -> None:
    assert table.is_content(build_feature(name="ICE1", type_name="ICE"))


def test_a_suppressed_content_feature_is_still_content(table: RmsTypeTable) -> None:
    assert table.is_content(build_feature(type_name="Extrusion", suppressed=True))


# --- the planner's target group per class (feature 004) ------------------------------


def test_default_group_by_class_is_loaded(
    table: RmsTypeTable, document: dict[str, Any]
) -> None:
    assert dict(table.default_group_by_class) == document["default_group_by_class"]


def test_the_table_answers_for_every_classification(table: RmsTypeTable) -> None:
    """`classify` returns one of these thirteen and nothing else, so `default_group` is
    total: no caller ever has to handle a missing key."""
    assert CLASSIFICATIONS == (*FEATURE_CLASSES, "unknown", "ambiguous")
    assert set(table.default_group_by_class) == set(CLASSIFICATIONS)
    for classification in CLASSIFICATIONS:
        assert table.default_group(classification) == table.default_group_by_class[
            classification
        ]


def test_every_feature_class_maps_to_a_group_or_to_needs_judgement(
    table: RmsTypeTable,
) -> None:
    allowed = {*table.groups, NEEDS_JUDGEMENT}
    for name in FEATURE_CLASSES:
        assert table.default_group(name) in allowed


def test_the_target_groups_are_exactly_the_six_the_checker_grades(
    table: RmsTypeTable,
) -> None:
    """The checker grades what is and this key says what should be; both read
    `groups`, so the two cannot disagree about what a group is called."""
    assert table.groups == (
        "1-Ref",
        "2-Construction",
        "3-Core",
        "4-Detail",
        "5-Modify",
        "6-Quarantine",
    )
    named = {
        value
        for value in table.default_group_by_class.values()
        if value != NEEDS_JUDGEMENT
    }
    assert named <= set(table.groups)
    assert NEEDS_JUDGEMENT not in table.groups


def test_unknown_and_ambiguous_need_judgement_and_never_name_a_group(
    table: RmsTypeTable,
) -> None:
    """Principle I: a type name nobody recognised, and `ICE`, are never guessed into a
    group. `needs_judgement` is the table saying it cannot decide, not a seventh group."""
    for classification in ("unknown", "ambiguous"):
        assert table.default_group(classification) == NEEDS_JUDGEMENT
        assert table.default_group(classification) not in table.groups


def test_default_group_spot_checks_every_class(table: RmsTypeTable) -> None:
    assert table.default_group("reference") == "1-Ref"
    assert table.default_group("construction") == "2-Construction"
    assert table.default_group("sketch") == "2-Construction"
    assert table.default_group("solid") == "3-Core"
    assert table.default_group("shell") == "3-Core"
    assert table.default_group("fillet") == "3-Core"
    assert table.default_group("chamfer") == "3-Core"
    assert table.default_group("cut") == "4-Detail"
    assert table.default_group("hole") == "4-Detail"
    assert table.default_group("draft") == "5-Modify"
    assert table.default_group("pattern") == "5-Modify"


def test_no_class_defaults_into_quarantine(table: RmsTypeTable) -> None:
    """Quarantine is where an engineer puts a feature, never where the planner sends one
    by default: a fillet is `3-Core` until a judgement moves it (research R6.1)."""
    assert "6-Quarantine" not in set(table.default_group_by_class.values())


def test_the_class_of_a_feature_is_what_default_group_is_asked(
    table: RmsTypeTable,
) -> None:
    """The one path the planner takes: type name -> class -> target group."""
    assert table.default_group(class_of(build_feature(type_name="Shell"), table)) == (
        "3-Core"
    )
    assert table.default_group(class_of(build_feature(type_name="ICE"), table)) == (
        NEEDS_JUDGEMENT
    )
    assert table.default_group(
        class_of(build_feature(type_name="NoSuchFeature"), table)
    ) == NEEDS_JUDGEMENT


# --- constrained status -------------------------------------------------------------


def test_constrained_status_maps_every_raw_value_the_table_lists(
    table: RmsTypeTable, document: dict[str, Any]
) -> None:
    assert set(document["constrained_status"]) == {1, 2, 3, 4, 5, 6, 7}
    for raw, name in document["constrained_status"].items():
        assert table.constrained_status(raw) == name


def test_constrained_status_maps_the_six_solved_states(table: RmsTypeTable) -> None:
    assert table.constrained_status(1) == "unknown"
    assert table.constrained_status(2) == "under_defined"
    assert table.constrained_status(3) == "fully_defined"
    assert table.constrained_status(4) == "over_defined"
    assert table.constrained_status(5) == "solver_error"
    assert table.constrained_status(6) == "solver_error"


def test_autosolve_off_is_unknown_not_an_error(table: RmsTypeTable) -> None:
    assert table.constrained_status(7) == "unknown"


def test_a_raw_value_the_table_does_not_list_is_unknown(table: RmsTypeTable) -> None:
    assert table.constrained_status(0) == "unknown"
    assert table.constrained_status(8) == "unknown"
    assert table.constrained_status(-1) == "unknown"


def test_a_null_raw_value_is_unavailable_not_unknown(table: RmsTypeTable) -> None:
    assert table.constrained_status(None) == "unavailable"


def test_unavailable_is_never_a_value_in_the_table(document: dict[str, Any]) -> None:
    assert "unavailable" not in set(document["constrained_status"].values())


# --- assembly ------------------------------------------------------------------------


def test_the_assembly_entity_kind_lists_are_exposed(
    table: RmsTypeTable, document: dict[str, Any]
) -> None:
    assembly = document["assembly"]

    assert list(table.assembly.reference_entity_kinds) == assembly[
        "reference_entity_kinds"
    ]
    assert list(table.assembly.geometry_entity_kinds) == assembly["geometry_entity_kinds"]
    assert "swSelDATUMPLANES" in table.assembly.reference_entity_kinds
    assert "swSelFACES" in table.assembly.geometry_entity_kinds


def test_the_entity_kind_lists_are_disjoint(table: RmsTypeTable) -> None:
    assert not set(table.assembly.reference_entity_kinds) & set(
        table.assembly.geometry_entity_kinds
    )


def test_an_unnamed_enum_value_is_in_neither_entity_kind_list(
    table: RmsTypeTable,
) -> None:
    for kind in ("unknown(7)", "unknown(0)", "swSelSKETCHSEGS"):
        assert kind not in table.assembly.reference_entity_kinds
        assert kind not in table.assembly.geometry_entity_kinds


def test_the_mate_chain_depth_limit_is_exposed(
    table: RmsTypeTable, document: dict[str, Any]
) -> None:
    assert (
        table.assembly.mate_chain_depth_limit
        == document["assembly"]["mate_chain_depth_limit"]
        == 3
    )


# --- a table that cannot be trusted ---------------------------------------------------


def _write(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "rms_types.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def test_a_table_whose_class_sets_overlap_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    document = dict(document, classes=dict(document["classes"]))
    document["classes"]["cut"] = [*document["classes"]["cut"], "Extrusion"]

    with pytest.raises(ValueError, match="Extrusion"):
        load_table(_write(tmp_path, document))


def test_a_table_with_an_unknown_class_name_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    document = dict(document, classes=dict(document["classes"]))
    document["classes"]["weldment"] = ["WeldmentStructuralMember"]

    with pytest.raises(ValueError, match="weldment"):
        load_table(_write(tmp_path, document))


def test_a_table_missing_a_class_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    document = dict(document, classes=dict(document["classes"]))
    del document["classes"]["shell"]

    with pytest.raises(ValueError, match="shell"):
        load_table(_write(tmp_path, document))


def test_a_table_claiming_a_raw_value_is_unavailable_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    document = dict(document, constrained_status=dict(document["constrained_status"]))
    document["constrained_status"][4] = "unavailable"

    with pytest.raises(ValueError, match="unavailable"):
        load_table(_write(tmp_path, document))


def test_a_table_whose_constrained_status_keys_are_not_ints_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    document = dict(document, constrained_status=dict(document["constrained_status"]))
    document["constrained_status"]["two"] = "under_defined"

    with pytest.raises(ValueError, match="two"):
        load_table(_write(tmp_path, document))


def test_a_table_whose_ambiguous_set_overlaps_a_class_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    """`classify` answers with the first class that matches, so an `ambiguous` name that
    is also a class member would never come back `ambiguous`: the file would be saying
    one thing and the loader doing another."""
    document = dict(document, ambiguous=[*document["ambiguous"], "Extrusion"])

    with pytest.raises(ValueError, match="Extrusion"):
        load_table(_write(tmp_path, document))


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_a_table_missing_a_required_key_is_refused(
    tmp_path: Path, document: dict[str, Any], key: str
) -> None:
    """A missing key names the file and the key, rather than surfacing a bare KeyError."""
    document = {name: value for name, value in document.items() if name != key}

    with pytest.raises(ValueError, match=key):
        load_table(_write(tmp_path, document))


def test_a_table_mapping_unknown_to_a_group_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    """The file may not overturn Principle I by naming a group for a type name the table
    does not classify."""
    document = dict(
        document, default_group_by_class=dict(document["default_group_by_class"])
    )
    document["default_group_by_class"]["unknown"] = "3-Core"

    with pytest.raises(ValueError, match="unknown"):
        load_table(_write(tmp_path, document))


def test_a_table_mapping_ambiguous_to_a_group_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    document = dict(
        document, default_group_by_class=dict(document["default_group_by_class"])
    )
    document["default_group_by_class"]["ambiguous"] = "6-Quarantine"

    with pytest.raises(ValueError, match="ambiguous"):
        load_table(_write(tmp_path, document))


def test_a_table_naming_a_group_that_is_not_one_of_the_six_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    document = dict(
        document, default_group_by_class=dict(document["default_group_by_class"])
    )
    document["default_group_by_class"]["hole"] = "7-Detail"

    with pytest.raises(ValueError, match="7-Detail"):
        load_table(_write(tmp_path, document))


def test_a_table_missing_a_classification_from_the_target_map_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    document = dict(
        document, default_group_by_class=dict(document["default_group_by_class"])
    )
    del document["default_group_by_class"]["draft"]

    with pytest.raises(ValueError, match="draft"):
        load_table(_write(tmp_path, document))


def test_a_target_map_carrying_a_name_that_is_not_a_classification_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    document = dict(
        document, default_group_by_class=dict(document["default_group_by_class"])
    )
    document["default_group_by_class"]["weldment"] = "3-Core"

    with pytest.raises(ValueError, match="weldment"):
        load_table(_write(tmp_path, document))


def test_a_table_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "rms_types.yaml"
    path.write_text("- not a mapping\n", encoding="utf-8")

    with pytest.raises(ValueError, match="mapping"):
        load_table(path)


# --- the census of the real packages (feature 004 T144, decision 17A) ---------------------

CENSUS_2026_09_25: tuple[str, ...] = (
    "AmbientLight",
    "AnnotationViewFeat",
    "Chamfer",
    "CommentsFolder",
    "CosmeticThread",
    "DetailCabinet",
    "DirectionLight",
    "DocsFolder",
    "EnvFolder",
    "EqnFolder",
    "Extrusion",
    "FavoriteFolder",
    "FeatSolidBodyFolder",
    "FeatSurfaceBodyFolder",
    "Fillet",
    "FtrFolder",
    "HistoryFolder",
    "HoleWzd",
    "ICE",
    "InkMarkupFolder",
    "MaterialFolder",
    "MirrorStock",
    "NotesAreaFtrFolder",
    "OriginProfileFeature",
    "ProfileFeature",
    "ProfileFtrFolder",
    "RefAxis",
    "RefAxisFtrFolder",
    "RefPlane",
    "RefPlaneFtrFolder",
    "RefPointFtrFolder",
    "SelectionSetFolder",
    "SensorFolder",
    "SolidBodyFolder",
    "SurfaceBodyFolder",
)
"""Every `GetTypeName2` value the three real single-part ModelCheck packages carry (2024 SP5,
counted 2026-09-25). SOLIDWORKS type names only: API vocabulary, not anything of the parts."""

SYSTEM_TYPES_ADDED_2026_09_25: tuple[str, ...] = (
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
)
"""The census names the table did not carry and the planner filed `unclassified`: the
annotation folder and view under the annotations container, the scene's lights, a derived
part's body and reference folders, and the cosmetic thread annotation. They are the planner's
`remodel_not_content`; feature 003's rules still count them until decision 20A lands (003 T090
to T092, waiting on the owner's question 20A-Q1)."""


def test_the_census_is_thirty_five_distinct_names() -> None:
    assert len(set(CENSUS_2026_09_25)) == len(CENSUS_2026_09_25) == 35


@pytest.mark.parametrize("type_name", CENSUS_2026_09_25)
def test_no_type_the_real_packages_carry_is_left_unplaced(
    table: RmsTypeTable, type_name: str
) -> None:
    """Each census name is in a class, the ambiguous set, `tolerated_loose`, the folder type
    or the derived-base set; none is a content type nobody recognised."""
    placed = (
        table.classify(type_name) != "unknown"
        or type_name in table.tolerated_loose
        or type_name in table.remodel_not_content
        or type_name == table.folder_type
        or type_name in table.derived_base
    )

    assert placed, f"{type_name} is on a real package and nowhere in the table"


@pytest.mark.parametrize("type_name", SYSTEM_TYPES_ADDED_2026_09_25)
def test_the_system_types_the_real_packages_carry_are_not_content_to_the_planner(
    table: RmsTypeTable, type_name: str
) -> None:
    row = build_feature(type_name=type_name, name=f"{type_name}1")

    assert type_name in table.remodel_not_content
    assert not table.planner_view().is_content(row)
    assert table.classify(type_name) == "unknown"


@pytest.mark.parametrize("type_name", SYSTEM_TYPES_ADDED_2026_09_25)
def test_feature_003s_rules_still_count_them_until_decision_20a_lands(
    table: RmsTypeTable, type_name: str
) -> None:
    """`tolerated_loose` is feature 003's key too, and the recorded runs feature 008 replays
    grade these rows as content. The owner decided the checker stops counting them (decision
    20A), and that lands with 003 T090 to T092, which wait on the owner's question 20A-Q1;
    until then the checker's reading is pinned unchanged here and the planner's alone moves."""
    row = build_feature(type_name=type_name, name=f"{type_name}1")

    assert type_name not in table.tolerated_loose
    assert table.is_content(row)


FEATURE_003 = Path(__file__).resolve().parents[3] / "specs" / "003-resilient-modeling"
"""Feature 003's package, whose normative texts record decision 20A."""

DECISION_20A_PENDING = {
    FEATURE_003 / "contracts" / "rules.md": (
        "*Status 2026-09-25 (review of decision 20A): not yet in effect.*"
    ),
    FEATURE_003 / "research.md": (
        "*Status 2026-09-25 (review of decision 20A): decided, not yet in effect.*"
    ),
    FEATURE_003 / "spec.md": "*Not yet in effect (review of 2026-09-25):*",
}
"""Each text that records decision 20A as it will read, and the sentence saying it is pending."""


@pytest.mark.parametrize("path", sorted(DECISION_20A_PENDING), ids=lambda path: path.name)
def test_the_texts_say_decision_20a_is_pending_exactly_while_the_planner_only_key_stands(
    path: Path,
) -> None:
    """Decision 20A is written into feature 003's normative texts as the table will read once
    T090 to T092 land. While the shipped file still has decision 17A's `remodel_not_content`,
    each of them says the decision is not yet in effect, and the day the key goes the sentence
    goes with it, so no text describes a table that is not the one shipped (the review of
    2026-09-25 found the contract written as if the key had already gone)."""
    shipped = yaml.safe_load(DEFAULT_TYPES_PATH.read_text(encoding="utf-8"))
    key_stands = "remodel_not_content" in shipped

    assert (DECISION_20A_PENDING[path] in path.read_text(encoding="utf-8")) is key_stands


def test_the_planner_view_tolerates_the_planners_system_types_and_changes_nothing_else(
    table: RmsTypeTable,
) -> None:
    view = table.planner_view()

    assert view.tolerated_loose == table.tolerated_loose | table.remodel_not_content
    assert view.remodel_not_content == frozenset()
    assert view.planner_view() == view
    for name in ("version", "calibrated_version", "groups", "classes", "ambiguous",
                 "default_group_by_class", "derived_base", "default_names_excluded",
                 "constrained_status_map", "assembly"):
        assert getattr(view, name) == getattr(table, name), name


def test_the_planners_system_types_are_disjoint_from_every_other_answer(
    table: RmsTypeTable,
) -> None:
    classified = table.ambiguous.union(*table.classes.values())

    assert not table.remodel_not_content & table.tolerated_loose
    assert not table.remodel_not_content & table.derived_base
    assert not table.remodel_not_content & classified


@pytest.mark.parametrize(
    ("key", "name"),
    [("tolerated_loose", "AmbientLight"), ("derived_base", "AmbientLight")],
)
def test_a_table_that_answers_for_a_planner_system_type_twice_is_refused(
    tmp_path: Path, document: dict[str, Any], key: str, name: str
) -> None:
    document = dict(document, **{key: [*document[key], name]})

    with pytest.raises(ValueError, match="remodel_not_content|derived_base"):
        load_table(_write(tmp_path, document))


def test_the_census_adds_no_type_the_real_packages_do_not_carry() -> None:
    """The table grows from readings, not from a list of names someone expects."""
    assert set(SYSTEM_TYPES_ADDED_2026_09_25) <= set(CENSUS_2026_09_25)


# --- the derived base (feature 004 T146, decision 17A) ------------------------------------


def test_the_derived_base_set_is_loaded(table: RmsTypeTable, document: dict[str, Any]) -> None:
    """`MirrorStock` is the mirrored part's base feature the real packages carry; `Stock` is
    Insert Part's, from the API's type-name list and not yet seen in a package."""
    assert table.derived_base == frozenset(document["derived_base"])
    assert frozenset({"MirrorStock", "Stock"}) == table.derived_base


def test_is_derived_base_reads_the_type_name_exactly(table: RmsTypeTable) -> None:
    assert table.is_derived_base(build_feature(type_name="MirrorStock"))
    assert table.is_derived_base(build_feature(type_name="Stock"))
    assert not table.is_derived_base(build_feature(type_name="Extrusion"))
    assert not table.is_derived_base(build_feature(type_name="mirrorstock"))
    assert not table.is_derived_base(build_feature(type_name="StockFolder"))


def test_no_derived_base_is_tolerated_or_classified(table: RmsTypeTable) -> None:
    """A derived base refuses the part; a tolerated row is one the method ignores, and a
    classified one is one the planner would place. It can be neither."""
    assert not table.derived_base & table.tolerated_loose
    assert {table.classify(name) for name in table.derived_base} == {"unknown"}


def test_a_table_that_tolerates_a_derived_base_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    document = dict(document, tolerated_loose=[*document["tolerated_loose"], "MirrorStock"])

    with pytest.raises(ValueError, match="derived_base"):
        load_table(_write(tmp_path, document))


def test_a_table_that_classifies_a_derived_base_is_refused(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    document = dict(document, classes=dict(document["classes"]))
    document["classes"]["solid"] = [*document["classes"]["solid"], "Stock"]

    with pytest.raises(ValueError, match="derived_base"):
        load_table(_write(tmp_path, document))
