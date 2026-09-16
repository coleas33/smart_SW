"""Unit tests for the re-modeler's fixture builders (feature 004 T005).

`tests/support/remodel.py` is test data, not product code, so what is pinned here is what
the planner tasks (T008 to T030) will rely on:

- every tree builds a package that validates against IR **1.2.0** and round-trips, so no
  planner fixture is one the extractor's own contract would reject;
- every package is stamped `extractor.profile: "model_check"`, because that is the shape
  feature 003 US6 produces and the shape `package-before.json` will carry. A fixture built
  at 1.1.0 is not a package the planner will ever receive - both serializers forbid unknown
  members, so a 1.1.0 package has no `profile` field at all and a 1.2.0 reader would be
  guessing which profile wrote it;
- the dependency graph is declared once and stamped in **both** directions, because the
  planner's ordering reads `parent_ids` and its feasibility check reads `child_ids`, and a
  fixture that disagreed with itself would grade the planner against a part SOLIDWORKS
  cannot produce;
- the scope signals carry the rows of `specs/004-resilient-remodeler/data-model.md`
  section 4.1 by name, with a readable value each, so an unreadable signal in a test is
  one the test asked for rather than one the builder forgot.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
import yaml

import swreview.checks
from swreview.ir.models import SCHEMA_VERSION, EvidencePackage, Feature
from tests.support import remodel
from tests.support.contracts import contract_validator
from tests.support.features import (
    FOLDER_TYPE,
    equation,
    feature,
    fillet_feature,
    sketch_feature,
)
from tests.support.remodel import (
    SCOPE_SIGNAL_FIELDS,
    dependency_chain_features,
    derived_subfolder_features,
    duplicate_name_features,
    linked,
    mis_membered_group_folder_features,
    remodel_package,
    scope_signals,
    shared_sketch_features,
    unknown_type_features,
    variable_radius_fillet_features,
)

IR_CONTRACT = contract_validator("ir.schema.json")
"""The committed `ir.schema.json`; every built package is validated against it."""

TYPE_TABLE = yaml.safe_load(
    (Path(swreview.checks.__file__).with_name("rms_types.yaml")).read_text(encoding="utf-8")
)

TREE_BUILDERS = {
    "dependency_chain_features": dependency_chain_features,
    "derived_subfolder_features": derived_subfolder_features,
    "duplicate_name_features": duplicate_name_features,
    "mis_membered_group_folder_features": mis_membered_group_folder_features,
    "shared_sketch_features": shared_sketch_features,
    "unknown_type_features": unknown_type_features,
    "variable_radius_fillet_features": variable_radius_fillet_features,
}
"""Every part tree the module builds, by name. Listed by hand and checked against the
module below, so a builder added later is untested only until this test runs."""


def rows_by_name(package: EvidencePackage) -> dict[str, Feature]:
    """The package's features keyed by name; only for trees whose names are unique."""
    rows: dict[str, Feature] = {}
    for row in package.features:
        assert row.name not in rows, f"{row.name!r} is not unique in this tree"
        rows[row.name] = row
    return rows


def assert_round_trips(package: EvidencePackage) -> None:
    """The package survives both dump modes *and* the committed JSON Schema."""
    assert EvidencePackage.model_validate(package.model_dump()) == package
    assert EvidencePackage.model_validate(package.model_dump(mode="json")) == package
    IR_CONTRACT.validate(package.model_dump(mode="json"))


# --- every tree ---------------------------------------------------------------------


def test_the_listed_builders_are_every_builder_the_module_has() -> None:
    """`_features` is the module's naming convention for a part tree; a new one that is
    not listed above would otherwise never be round-tripped."""
    found = {
        name
        for name, value in inspect.getmembers(remodel, inspect.isfunction)
        if name.endswith("_features") and value.__module__ == remodel.__name__
    }

    assert found == set(TREE_BUILDERS)


@pytest.mark.parametrize("name", sorted(TREE_BUILDERS))
def test_every_tree_builds_a_package_that_validates_and_round_trips(name: str) -> None:
    assert_round_trips(remodel_package(TREE_BUILDERS[name]()))


@pytest.mark.parametrize("name", sorted(TREE_BUILDERS))
def test_every_package_is_stamped_with_the_model_check_profile(name: str) -> None:
    package = remodel_package(TREE_BUILDERS[name]())

    assert package.extractor.profile == "model_check"


@pytest.mark.parametrize("name", sorted(TREE_BUILDERS))
def test_every_package_is_at_the_schema_version_the_planner_receives(name: str) -> None:
    """1.2.0 is the version that carries `extractor.profile`; a 1.1.0 package has no such
    field, and both serializers forbid unknown members, so it can never be one."""
    package = remodel_package(TREE_BUILDERS[name]())

    assert package.schema_version == SCHEMA_VERSION == "1.2.0"


@pytest.mark.parametrize("name", sorted(TREE_BUILDERS))
def test_every_tree_is_one_part_opened_alone(name: str) -> None:
    """The re-modeler's only subject is a part opened alone (the copy it just made), so a
    fixture with an assembly document would be testing a shape it never sees."""
    package = remodel_package(TREE_BUILDERS[name]())

    assert [document.kind for document in package.documents] == ["part"]
    assert package.design.root_assembly_document_id == package.documents[0].document_id
    assert package.features
    assert {row.document_id for row in package.features} == {package.documents[0].document_id}


@pytest.mark.parametrize("name", sorted(TREE_BUILDERS))
def test_every_tree_builds_in_both_traversal_shapes(name: str) -> None:
    nested = remodel_package(TREE_BUILDERS[name](), shape="nested")
    flat = remodel_package(TREE_BUILDERS[name](), shape="flat")

    assert_round_trips(flat)
    assert {row.depth for row in flat.features} == {0}
    assert {row.folder_id for row in flat.features} == {None}
    assert len(flat.features) >= len(nested.features)


def test_remodel_package_carries_equations_and_configurations() -> None:
    package = remodel_package(
        dependency_chain_features(),
        equations=(equation('"width" = 120', is_global=True, value=120.0),),
        configurations=("Default", "Machined"),
    )

    assert_round_trips(package)
    assert [row.text for row in package.equations] == ['"width" = 120']
    assert package.equations[0].is_global is True
    assert package.documents[0].configurations == ["Default", "Machined"]


# --- the declared dependency graph ---------------------------------------------------


def test_the_dependency_chain_declares_both_directions() -> None:
    rows = rows_by_name(remodel_package(dependency_chain_features()))
    sketch, boss = rows["Sketch1"], rows["Boss-Extrude1"]

    assert sketch.child_ids == [boss.id]
    assert boss.parent_ids == [sketch.id]
    assert rows["Fillet1"].parent_ids == [boss.id]
    assert boss.child_ids == [rows["Fillet1"].id]


def test_every_edge_of_every_tree_is_declared_in_both_directions() -> None:
    """The invariant `linked` exists to keep: a child that names a parent is named back."""
    for name, build in sorted(TREE_BUILDERS.items()):
        package = remodel_package(build())
        children: dict[str, set[str]] = {}
        parents: dict[str, set[str]] = {}
        for row in package.features:
            children[row.id] = set(row.child_ids or ())
            parents[row.id] = set(row.parent_ids or ())
        for row in package.features:
            for child in children[row.id]:
                assert row.id in parents[child], f"{name}: {row.name} -> {child}"
            for parent in parents[row.id]:
                assert row.id in children[parent], f"{name}: {parent} -> {row.name}"


def test_linked_stamps_an_edge_on_both_ends() -> None:
    specs = linked(
        [feature("A", "Extrusion"), feature("B", "Fillet")],
        ("A", "B"),
    )

    assert [spec.name for spec in specs] == ["A", "B"]
    assert specs[0].child_names == ("B",)
    assert specs[1].parent_names == ("A",)


def test_linked_keeps_what_a_spec_already_declared_and_adds_no_duplicate() -> None:
    specs = linked(
        [
            feature("A", "Extrusion", child_names=("B",)),
            feature("B", "Fillet", parent_names=("A",)),
            feature("C", "Chamfer"),
        ],
        ("A", "B"),
        ("A", "C"),
    )

    assert specs[0].child_names == ("B", "C")
    assert specs[1].parent_names == ("A",)
    assert specs[2].parent_names == ("A",)


def test_linked_keeps_a_sketchs_consumers_in_step_with_its_children() -> None:
    """A sketch's consumers *are* its dependents (`GetChildren` reads them as one call),
    so a fixture whose two lists disagreed would be one no dump can produce."""
    specs = linked(
        [sketch_feature("Sketch1"), feature("Boss-Extrude1", "Extrusion")],
        ("Sketch1", "Boss-Extrude1"),
    )

    assert specs[0].child_names == ("Boss-Extrude1",)
    assert specs[0].sketch is not None
    assert specs[0].sketch.consumer_names == ("Boss-Extrude1",)


def test_linked_leaves_an_unreadable_direction_unreadable() -> None:
    """`child_names=None` is `GetChildren` having failed (the `graph_unreadable` case);
    stamping an edge onto it would invent a reading the dump never got."""
    specs = linked(
        [feature("A", "Extrusion", child_names=None), feature("B", "Fillet")],
        ("A", "B"),
    )

    assert specs[0].child_names is None
    assert specs[1].parent_names == ("A",)


def test_linked_refuses_an_edge_naming_a_feature_that_is_not_there() -> None:
    with pytest.raises(ValueError, match="Nope"):
        linked([feature("A", "Extrusion")], ("A", "Nope"))


def test_linked_refuses_an_edge_naming_a_duplicated_name() -> None:
    """`build_features` resolves references by name, so an edge onto a duplicated name is
    exactly the ambiguity the rename plan exists to remove: it may not be built."""
    with pytest.raises(ValueError, match="Fillet1"):
        linked(
            [
                feature("A", "Extrusion"),
                feature("Fillet1", "Fillet"),
                feature("Fillet1", "Fillet"),
            ],
            ("A", "Fillet1"),
        )


def test_linked_refuses_an_edge_from_a_feature_to_itself() -> None:
    with pytest.raises(ValueError, match="A"):
        linked([feature("A", "Extrusion")], ("A", "A"))


# --- the cases the planner has to handle ---------------------------------------------


def test_the_duplicate_name_tree_carries_the_same_name_twice() -> None:
    package = remodel_package(duplicate_name_features())
    names = [row.name for row in package.features]

    assert names.count("Fillet1") == 2
    duplicates = [row for row in package.features if row.name == "Fillet1"]
    assert duplicates[0].id != duplicates[1].id
    assert duplicates[0].persist_ref != duplicates[1].persist_ref
    assert duplicates[0].folder_id != duplicates[1].folder_id


def test_the_shared_sketch_has_two_consumers_that_both_name_it() -> None:
    package = remodel_package(shared_sketch_features())
    rows = rows_by_name(package)
    sketch = rows["Sketch1"]

    assert sketch.sketch is not None
    assert sketch.sketch.consumer_ids == [rows["Boss-Extrude1"].id, rows["Cut-Extrude1"].id]
    assert sketch.child_ids == sketch.sketch.consumer_ids
    for consumer in ("Boss-Extrude1", "Cut-Extrude1"):
        assert rows[consumer].parent_ids == [sketch.id]


def test_the_variable_radius_fillet_has_no_default_radius() -> None:
    rows = rows_by_name(remodel_package(variable_radius_fillet_features()))
    variable, readable = rows["Fillet-Variable1"], rows["Fillet1"]

    assert variable.fillet is not None
    assert variable.fillet.default_radius is None
    assert readable.fillet is not None
    assert readable.fillet.default_radius is not None


def test_the_unknown_type_is_a_name_the_table_does_not_carry() -> None:
    """Asserted against the shipped table read here, not through the loader: a fixture
    that stopped being unknown because the table was calibrated must fail loudly."""
    package = remodel_package(unknown_type_features())
    unknown = [row for row in package.features if row.type_name == remodel.UNKNOWN_TYPE_NAME]

    assert len(unknown) == 1
    members = {name for members in TYPE_TABLE["classes"].values() for name in members}
    assert remodel.UNKNOWN_TYPE_NAME not in members
    assert remodel.UNKNOWN_TYPE_NAME not in TYPE_TABLE["ambiguous"]
    assert remodel.UNKNOWN_TYPE_NAME not in TYPE_TABLE["tolerated_loose"]


def test_the_mis_membered_group_folder_carries_an_rms_name_and_the_wrong_members() -> None:
    package = remodel_package(mis_membered_group_folder_features())
    folder_row = next(row for row in package.features if row.type_name == FOLDER_TYPE)
    members = [row for row in package.features if row.folder_id == folder_row.id]

    assert folder_row.name in TYPE_TABLE["groups"]
    assert folder_row.name == "3-Core"
    assert [row.type_name for row in members] == ["Extrusion", "Cut", "HoleWzd"]


def test_the_derived_subfolder_sits_inside_a_group_folder() -> None:
    package = remodel_package(derived_subfolder_features())
    rows = rows_by_name(package)
    group, subfolder = rows["3-Core"], rows["Ribs"]

    assert group.type_name == FOLDER_TYPE
    assert subfolder.type_name == FOLDER_TYPE
    assert subfolder.folder_id == group.id
    assert group.folder_id is None
    assert [row.name for row in package.features if row.folder_id == subfolder.id] == [
        "Rib1",
        "Rib2",
    ]


def test_the_derived_subfolder_is_closed_by_its_own_end_tag_in_the_flat_shape() -> None:
    package = remodel_package(derived_subfolder_features(), shape="flat")
    names = [row.name for row in package.features]

    assert names.index("Ribs") < names.index("Ribs___EndTag___")
    assert names.index("Ribs___EndTag___") < names.index("3-Core___EndTag___")


# --- scope signals --------------------------------------------------------------------


def test_the_scope_signal_fields_are_the_rows_of_the_data_model() -> None:
    """data-model.md section 4.1, in its order. A row renamed there and not here is a
    test that passes against a signal the gate never receives."""
    assert SCOPE_SIGNAL_FIELDS == (
        "document_type",
        "solid_body_count",
        "sheet_body_count",
        "is_weldment",
        "sheet_metal_folder_present",
        "mesh_body_present",
        "graphics_body_present",
        "is_3d_interconnect",
        "imported_file_names",
        "configuration_names",
        "rms_named_folders",
        "external_reference_count",
        "save_flag_dirty",
        "read_only",
        "rebuild_error_count",
        "vault",
    )
    assert set(scope_signals()) == set(SCOPE_SIGNAL_FIELDS)


def test_the_default_signals_are_a_part_the_gate_admits() -> None:
    signals = scope_signals()

    assert signals["document_type"] == 1
    assert signals["solid_body_count"] == 1
    assert signals["sheet_body_count"] == 0
    assert signals["is_weldment"] is False
    assert signals["sheet_metal_folder_present"] is False
    assert signals["mesh_body_present"] is False
    assert signals["graphics_body_present"] is False
    assert signals["is_3d_interconnect"] is False
    assert signals["imported_file_names"] == []
    assert signals["configuration_names"] == ["Default"]
    assert signals["rms_named_folders"] == []
    assert signals["external_reference_count"] == 0
    assert signals["rebuild_error_count"] == 0
    assert signals["vault"] is None


def test_no_default_signal_is_null_except_the_vault() -> None:
    """A null signal is an unreadable one, never a pass (data-model section 4.1). A test
    that wants unreadable asks for it; it never gets it by default."""
    nulls = {name for name, value in scope_signals().items() if value is None}

    assert nulls == {"vault"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("solid_body_count", 2),
        ("is_weldment", True),
        ("sheet_metal_folder_present", True),
        ("mesh_body_present", True),
        ("graphics_body_present", True),
        ("is_3d_interconnect", True),
        ("imported_file_names", ["bracket.step"]),
        ("sheet_body_count", 3),
        ("configuration_names", ["Default", "Machined", "Plated"]),
        ("is_weldment", None),
    ],
)
def test_one_signal_at_a_time_and_the_rest_stay_in_scope(field: str, value: Any) -> None:
    signals = scope_signals(**{field: value})
    default = scope_signals()

    assert signals[field] == value
    assert {name: signals[name] for name in signals if name != field} == {
        name: default[name] for name in default if name != field
    }


def test_two_signals_at_once() -> None:
    signals = scope_signals(is_weldment=True, solid_body_count=4)

    assert signals["is_weldment"] is True
    assert signals["solid_body_count"] == 4


def test_scope_signals_refuses_a_field_the_data_model_does_not_carry() -> None:
    with pytest.raises(ValueError, match="is_sheetmetal"):
        scope_signals(is_sheetmetal=True)


def test_each_call_gets_its_own_lists() -> None:
    """Every signal row is a fresh object, so a test that mutates one cannot reach the
    next test through a shared default."""
    first, second = scope_signals(), scope_signals()

    first["configuration_names"].append("Machined")
    first["imported_file_names"].append("bracket.step")

    assert second["configuration_names"] == ["Default"]
    assert second["imported_file_names"] == []


def test_the_configuration_count_is_the_length_of_the_names() -> None:
    """`which_configs` on every equation add is driven by this count, so the fixture
    carries the names rather than a number nobody can trace back to a configuration."""
    signals = scope_signals(configuration_names=["Default", "Machined"])

    assert len(signals["configuration_names"]) == 2


def test_the_rms_named_folder_rows_carry_a_name_and_its_members() -> None:
    package = remodel_package(mis_membered_group_folder_features())
    members = [row.persist_ref for row in package.features if row.folder_id is not None]
    signals = scope_signals(
        rms_named_folders=[{"name": "3-Core", "member_persist_refs": members}]
    )

    assert signals["rms_named_folders"] == [
        {"name": "3-Core", "member_persist_refs": members}
    ]
    assert len(members) == 3


def test_a_fillet_spec_still_builds_outside_a_tree_builder() -> None:
    """The module adds to `tests/support/features.py`; it does not replace it."""
    package = remodel_package([fillet_feature("Fillet1", radius_m=0.003)])

    assert_round_trips(package)
    assert package.features[0].fillet is not None
