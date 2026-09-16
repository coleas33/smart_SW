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
    DEFAULT_TYPES_PATH,
    FEATURE_CLASSES,
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


@pytest.mark.parametrize("field", ["classes", "constrained_status_map"])
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


def test_a_table_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "rms_types.yaml"
    path.write_text("- not a mapping\n", encoding="utf-8")

    with pytest.raises(ValueError, match="mapping"):
        load_table(path)
