"""Unit tests for the RMS feature-tree builders (T003).

`tests/support/features.py` is test data, not product code, so what is pinned here is
exactly what the rule tests, the group tests and the golden fixtures will rely on:

- the two traversal shapes of `specs/003-resilient-modeling/contracts/rules.md` ("Group
  assignment"): nested (folder contents at depth 1 with `folder_id` set) and flat (every
  row at depth 0 with `folder_id` null, the contents following the folder and an end-tag
  marker closing it);
- names resolved to `feat:NNNN` ids for `child_ids`, `parent_ids` and
  `sketch.consumer_ids`, with `None` reserved for the gap case (absence is null, never a
  default);
- packages that validate and round-trip through `EvidencePackage`, so no later task
  builds a fixture the IR would reject.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import swreview.checks
from swreview.ir.models import SCHEMA_VERSION, EvidencePackage, Feature, Gap, Quantity
from tests.support.contracts import contract_validator
from tests.support.features import (
    END_TAG_SUFFIX,
    FOLDER_TYPE,
    AssemblySpec,
    InstanceSpec,
    MateSpec,
    PartSpec,
    SubassemblySpec,
    build_features,
    end_tag,
    equation,
    feature,
    fillet_feature,
    folder,
    rms_package,
    sketch_feature,
    suppress_row,
    suppress_run,
)

IR_CONTRACT = contract_validator("ir.schema.json")
"""The committed `ir.schema.json`; every built package is validated against it."""

TYPE_TABLE = yaml.safe_load(
    (Path(swreview.checks.__file__).with_name("rms_types.yaml")).read_text(encoding="utf-8")
)


def core_specs() -> list:
    """One reference feature, a group folder holding a sketch and its consumer, one loose."""
    return [
        feature("Front Plane", "RefPlane"),
        folder(
            "3-Core",
            sketch_feature("Sketch1", consumers=("Boss-Extrude1",)),
            feature("Boss-Extrude1", "Extrusion", parent_names=("Sketch1",)),
        ),
        feature("Shell1", "Shell"),
    ]


def assert_round_trips(package: EvidencePackage) -> None:
    """The package survives both dump modes *and* the committed JSON Schema.

    Pydantic and the contract are kept in step by `test_schema_sync.py`, but only the
    models run when a fixture is built: validating here is what stops a fixture the
    extractor's own contract would reject from reaching a golden baseline.
    """
    assert EvidencePackage.model_validate(package.model_dump()) == package
    assert EvidencePackage.model_validate(package.model_dump(mode="json")) == package
    IR_CONTRACT.validate(package.model_dump(mode="json"))


# --- the shared vocabulary comes from the shipped table ---------------------------


def test_folder_type_and_end_tag_suffix_match_the_shipped_table() -> None:
    assert FOLDER_TYPE == TYPE_TABLE["folder_type"]
    assert END_TAG_SUFFIX == TYPE_TABLE["end_tag_suffix"]


# --- traversal shapes -------------------------------------------------------------


def test_nested_shape_puts_folder_contents_at_depth_one() -> None:
    rows = build_features(core_specs(), document_id="doc:2", shape="nested")

    assert [row.id for row in rows] == [
        "feat:0001",
        "feat:0002",
        "feat:0003",
        "feat:0004",
        "feat:0005",
    ]
    assert [row.name for row in rows] == [
        "Front Plane",
        "3-Core",
        "Sketch1",
        "Boss-Extrude1",
        "Shell1",
    ]
    assert [row.index for row in rows] == [0, 1, 2, 3, 4]
    assert [row.depth for row in rows] == [0, 0, 1, 1, 0]
    assert [row.folder_id for row in rows] == [None, None, "feat:0002", "feat:0002", None]
    assert [row.type_name for row in rows] == [
        "RefPlane",
        FOLDER_TYPE,
        "ProfileFeature",
        "Extrusion",
        "Shell",
    ]
    assert all(row.document_id == "doc:2" for row in rows)
    assert all(row.persist_ref_scope == "doc:2" for row in rows)
    assert all(row.configuration == "Default" for row in rows)


def test_nested_shape_emits_no_end_tag_of_its_own() -> None:
    rows = build_features(core_specs(), document_id="doc:2", shape="nested")

    assert not [row for row in rows if row.name.endswith(END_TAG_SUFFIX)]


def test_flat_shape_keeps_every_row_at_depth_zero_and_closes_folders() -> None:
    rows = build_features(core_specs(), document_id="doc:2", shape="flat")

    assert [row.name for row in rows] == [
        "Front Plane",
        "3-Core",
        "Sketch1",
        "Boss-Extrude1",
        f"3-Core{END_TAG_SUFFIX}",
        "Shell1",
    ]
    assert [row.index for row in rows] == [0, 1, 2, 3, 4, 5]
    assert all(row.depth == 0 for row in rows)
    assert all(row.folder_id is None for row in rows)
    assert rows[4].type_name == FOLDER_TYPE


def test_flat_shape_can_leave_a_folder_unclosed() -> None:
    rows = build_features(
        [folder("3-Core", feature("Boss-Extrude1", "Extrusion"), end_tag=False)],
        document_id="doc:2",
        shape="flat",
    )

    assert [row.name for row in rows] == ["3-Core", "Boss-Extrude1"]


def test_end_tag_builder_emits_a_marker_in_both_shapes() -> None:
    specs = [folder("4-Detail", end_tag=False), end_tag("4-Detail")]

    for shape in ("nested", "flat"):
        rows = build_features(specs, document_id="doc:2", shape=shape)
        assert [row.name for row in rows] == ["4-Detail", f"4-Detail{END_TAG_SUFFIX}"]
        assert [row.type_name for row in rows] == [FOLDER_TYPE, FOLDER_TYPE]


def test_nested_subfolder_inherits_its_folder_id() -> None:
    specs = [
        folder(
            "4-Detail",
            folder("Boss pair", feature("Boss-Extrude2", "Extrusion")),
        )
    ]

    nested = build_features(specs, document_id="doc:2", shape="nested")
    assert [row.depth for row in nested] == [0, 1, 2]
    assert [row.folder_id for row in nested] == [None, "feat:0001", "feat:0002"]

    flat = build_features(specs, document_id="doc:2", shape="flat")
    assert [row.name for row in flat] == [
        "4-Detail",
        "Boss pair",
        "Boss-Extrude2",
        f"Boss pair{END_TAG_SUFFIX}",
        f"4-Detail{END_TAG_SUFFIX}",
    ]
    assert all(row.depth == 0 for row in flat)


def test_start_continues_the_id_sequence() -> None:
    rows = build_features([feature("Boss-Extrude1", "Extrusion")], document_id="doc:3", start=7)

    assert [row.id for row in rows] == ["feat:0007"]
    assert rows[0].index == 0


# --- per-feature data -------------------------------------------------------------


def test_names_resolve_to_ids_for_children_parents_and_consumers() -> None:
    rows = build_features(core_specs(), document_id="doc:2", shape="nested")
    by_name = {row.name: row for row in rows}

    assert by_name["Sketch1"].child_ids == [by_name["Boss-Extrude1"].id]
    assert by_name["Sketch1"].sketch is not None
    assert by_name["Sketch1"].sketch.consumer_ids == [by_name["Boss-Extrude1"].id]
    assert by_name["Sketch1"].sketch.raw_status == 3
    assert by_name["Boss-Extrude1"].parent_ids == [by_name["Sketch1"].id]
    assert by_name["Boss-Extrude1"].child_ids == []
    assert by_name["Boss-Extrude1"].sketch is None
    assert by_name["Boss-Extrude1"].fillet is None


def test_unknown_name_in_a_reference_is_refused() -> None:
    with pytest.raises(ValueError, match="Nope"):
        build_features(
            [feature("Boss-Extrude1", "Extrusion", child_names=("Nope",))],
            document_id="doc:2",
        )


@pytest.mark.parametrize("shape", ["nested", "flat"])
def test_a_duplicate_group_folder_builds_two_rows_of_its_own(shape: str) -> None:
    """`rules.md` ("Group assignment"): a group name appearing a second time re-opens it.

    Duplicate names are legal evidence, so the builder emits them; each occurrence keeps
    its own id and its own `persist_ref`, the way SOLIDWORKS reports two distinct folders.
    """
    rows = build_features(
        [
            folder("3-Core", feature("Boss-Extrude1", "Extrusion")),
            folder("4-Detail", feature("Hole1", "HoleWzd")),
            folder("3-Core", fillet_feature("Fillet1")),
        ],
        document_id="doc:2",
        shape=shape,
    )

    cores = [row for row in rows if row.name == "3-Core"]
    assert len(cores) == 2
    assert len({row.id for row in cores}) == 2
    assert len({row.persist_ref for row in cores}) == 2
    if shape == "flat":
        markers = [row for row in rows if row.name == f"3-Core{END_TAG_SUFFIX}"]
        assert len(markers) == 2
        assert len({row.persist_ref for row in markers}) == 2


def test_a_reference_to_a_duplicated_name_is_refused() -> None:
    with pytest.raises(ValueError, match=r"names '3-Core', which is the name of 2 features"):
        build_features(
            [
                folder("3-Core", feature("Boss-Extrude1", "Extrusion", parent_names=("3-Core",))),
                folder("3-Core", fillet_feature("Fillet1")),
            ],
            document_id="doc:2",
        )


def test_null_children_parents_and_description_stay_null() -> None:
    rows = build_features(
        [
            feature(
                "Boss-Extrude1",
                "Extrusion",
                description=None,
                child_names=None,
                parent_names=None,
                error_code=None,
                suppressed=None,
            )
        ],
        document_id="doc:2",
    )

    row = rows[0]
    assert row.description is None
    assert row.child_ids is None
    assert row.parent_ids is None
    assert row.error_code is None
    assert row.suppressed is None


def test_suppressed_and_blank_description_are_expressible() -> None:
    rows = build_features(
        [feature("Cut-Extrude1", "Cut", description="", suppressed=True)],
        document_id="doc:2",
    )

    assert rows[0].description == ""
    assert rows[0].suppressed is True


def test_sketch_feature_carries_unknown_status_and_null_consumers() -> None:
    rows = build_features(
        [sketch_feature("Sketch1", raw_status=None, consumers=None)],
        document_id="doc:2",
    )

    assert rows[0].sketch is not None
    assert rows[0].sketch.raw_status is None
    assert rows[0].sketch.consumer_ids is None
    assert rows[0].child_ids is None


def test_fillet_feature_carries_a_radius_in_meters_or_null() -> None:
    rows = build_features(
        [fillet_feature("Fillet1", radius_m=0.006), fillet_feature("Fillet2", radius_m=None)],
        document_id="doc:2",
    )

    assert rows[0].fillet is not None
    assert rows[0].fillet.default_radius == Quantity(value=0.006, unit="m")
    assert rows[1].fillet is not None
    assert rows[1].fillet.default_radius is None


# --- packages ---------------------------------------------------------------------


def test_part_only_package_validates_and_round_trips() -> None:
    package = rms_package(
        parts=[PartSpec(document_id="doc:2", name="housing", features=core_specs())]
    )

    assert package.schema_version == SCHEMA_VERSION
    assert [doc.document_id for doc in package.documents] == ["doc:2"]
    assert package.documents[0].kind == "part"
    assert [entry.document_id for entry in package.manifest.entries] == ["doc:2"]
    assert package.design.root_assembly_document_id == "doc:2"
    assert [cmp.id for cmp in package.components] == ["cmp:0001"]
    assert package.components[0].parent_id is None
    assert package.components[0].document_id == "doc:2"
    assert package.gaps == []
    assert package.holes == []
    assert package.fasteners == []
    assert [row.document_id for row in package.features] == ["doc:2"] * 5
    assert_round_trips(package)


def test_two_parts_share_one_feature_id_sequence() -> None:
    package = rms_package(
        parts=[
            PartSpec(document_id="doc:2", name="housing", features=[feature("Boss1", "Extrusion")]),
            PartSpec(document_id="doc:3", name="cover", features=[feature("Boss2", "Extrusion")]),
        ]
    )

    assert [(row.id, row.document_id) for row in package.features] == [
        ("feat:0001", "doc:2"),
        ("feat:0002", "doc:3"),
    ]
    assert [doc.document_id for doc in package.documents] == ["doc:2", "doc:3"]
    assert [cmp.id for cmp in package.components] == ["cmp:0001", "cmp:0002"]
    assert_round_trips(package)


def test_part_instances_are_explicit_and_carry_the_rms_fields() -> None:
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                features=[feature("Boss1", "Extrusion")],
                instances=[
                    InstanceSpec("housing-1", is_fixed=True, constrained_status_raw=3),
                    InstanceSpec("housing-2", constrained_status_raw=2, is_toolbox=True),
                ],
            )
        ]
    )

    first, second = package.components
    assert (first.name, first.is_fixed, first.constrained_status_raw) == ("housing-1", True, 3)
    assert (second.name, second.is_fixed, second.constrained_status_raw) == ("housing-2", False, 2)
    assert second.is_toolbox is True
    assert first.suppression == "resolved"
    assert second.suppression == "resolved"
    assert_round_trips(package)


@pytest.mark.parametrize("state", ["lightweight", "suppressed", "unloaded"])
def test_non_resolved_instances_carry_a_feature_tree_unavailable_gap(state: str) -> None:
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                features=[],
                instances=[InstanceSpec("housing-1", suppression=state)],
            )
        ]
    )

    assert package.components[0].suppression == state
    gap = next(gap for gap in package.gaps if gap.entity_kind == "feature_tree_unavailable")
    assert gap.entity_id == "cmp:0001"
    assert gap.kind == "not_extracted"
    assert state in gap.reason
    assert "housing-1" in gap.reason
    assert_round_trips(package)


def test_resolved_instances_carry_no_gap() -> None:
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                features=[],
                instances=[
                    InstanceSpec("housing-1"),
                    InstanceSpec("housing-2", suppression="lightweight"),
                ],
            )
        ]
    )

    assert [gap.entity_id for gap in package.gaps] == ["cmp:0002"]


def test_assembly_package_roots_at_cmp_0001_with_mates_and_a_subassembly() -> None:
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                features=[feature("Boss1", "Extrusion")],
                instances=[InstanceSpec("housing-1", is_fixed=True)],
            ),
            PartSpec(
                document_id="doc:3",
                name="cover",
                features=[feature("Boss2", "Extrusion")],
                instances=[InstanceSpec("cover-1", constrained_status_raw=2)],
            ),
        ],
        assembly=AssemblySpec(
            document_id="doc:1",
            name="cover-assy",
            mates=[
                MateSpec(
                    entities=[("housing-1", "swSelDATUMPLANES"), ("cover-1", "swSelDATUMPLANES")]
                ),
                MateSpec(
                    entities=[("housing-1", "swSelFACES"), ("cover-1", "swSelFACES")],
                    type="DISTANCE",
                    suppressed=True,
                ),
            ],
            subassembly=SubassemblySpec(document_id="doc:4", name="gearbox"),
        ),
    )

    root = package.components[0]
    assert (root.id, root.document_id, root.parent_id) == ("cmp:0001", "doc:1", None)
    assert [cmp.id for cmp in package.components] == [
        "cmp:0001",
        "cmp:0002",
        "cmp:0003",
        "cmp:0004",
    ]
    assert [cmp.name for cmp in package.components] == [
        "cover-assy",
        "housing-1",
        "cover-1",
        "gearbox-1",
    ]
    assert all(cmp.parent_id == "cmp:0001" for cmp in package.components[1:])
    assert [doc.document_id for doc in package.documents] == ["doc:1", "doc:4", "doc:2", "doc:3"]
    assert [doc.kind for doc in package.documents] == ["assembly", "assembly", "part", "part"]
    assert package.design.root_assembly_document_id == "doc:1"
    assert [entry.document_id for entry in package.manifest.entries] == [
        "doc:1",
        "doc:4",
        "doc:2",
        "doc:3",
    ]

    first, second = package.mates
    assert [(ent.component_id, ent.entity_kind) for ent in first.entities] == [
        ("cmp:0002", "swSelDATUMPLANES"),
        ("cmp:0003", "swSelDATUMPLANES"),
    ]
    assert first.suppressed is False
    assert first.persist_ref_scope == "doc:1"
    assert second.type == "DISTANCE"
    assert second.suppressed is True
    assert [ent.entity_kind for ent in second.entities] == ["swSelFACES", "swSelFACES"]
    assert_round_trips(package)


def test_component_under_a_subassembly_names_its_parent() -> None:
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                features=[],
                instances=[InstanceSpec("housing-1", parent_name="gearbox-1")],
            )
        ],
        assembly=AssemblySpec(subassembly=SubassemblySpec(document_id="doc:4", name="gearbox")),
    )

    by_name = {cmp.name: cmp for cmp in package.components}
    assert by_name["housing-1"].parent_id == by_name["gearbox-1"].id
    assert by_name["housing-1"].full_path == "gearbox-1/housing-1"
    assert by_name["gearbox-1"].document_id == "doc:4"


def test_unknown_mate_or_parent_name_is_refused() -> None:
    with pytest.raises(ValueError, match="nope-1"):
        rms_package(
            parts=[PartSpec(document_id="doc:2", name="housing")],
            assembly=AssemblySpec(mates=[MateSpec(entities=[("nope-1", "swSelFACES")])]),
        )

    with pytest.raises(ValueError, match="nope-1"):
        rms_package(
            parts=[
                PartSpec(
                    document_id="doc:2",
                    name="housing",
                    instances=[InstanceSpec("housing-1", parent_name="nope-1")],
                )
            ],
            assembly=AssemblySpec(),
        )


def test_mate_suppression_gap_is_expressible() -> None:
    package = rms_package(
        parts=[PartSpec(document_id="doc:2", name="housing")],
        assembly=AssemblySpec(
            mates=[MateSpec(entities=[("housing-1", "swSelFACES")], suppression_gap=True)]
        ),
    )

    gap = next(gap for gap in package.gaps if gap.entity_kind == "mate_suppression")
    assert gap.entity_id == package.mates[0].id
    assert_round_trips(package)


def test_extra_gaps_are_carried_through() -> None:
    extra = Gap(
        kind="not_extracted",
        entity_kind="feature_tree_configuration",
        entity_id="doc:2",
        reason="other configurations not read: Machined",
        error=None,
    )
    package = rms_package(parts=[PartSpec(document_id="doc:2", name="housing")], gaps=[extra])

    assert extra in package.gaps


def test_flat_shape_is_selected_per_part() -> None:
    package = rms_package(
        parts=[
            PartSpec(document_id="doc:2", name="housing", features=core_specs(), shape="flat"),
            PartSpec(document_id="doc:3", name="cover", features=core_specs(), shape="nested"),
        ]
    )

    flat = [row for row in package.features if row.document_id == "doc:2"]
    nested = [row for row in package.features if row.document_id == "doc:3"]
    assert [row.name for row in flat][-2:] == [f"3-Core{END_TAG_SUFFIX}", "Shell1"]
    assert all(row.depth == 0 for row in flat)
    assert max(row.depth for row in nested) == 1
    assert_round_trips(package)


def test_configuration_flows_into_features_and_instances() -> None:
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                features=[feature("Boss1", "Extrusion")],
                configuration="Machined",
                configurations=["Default", "Machined"],
            )
        ]
    )

    assert package.features[0].configuration == "Machined"
    assert package.documents[0].active_configuration == "Machined"
    assert package.documents[0].configurations == ["Default", "Machined"]
    assert package.components[0].referenced_configuration == "Machined"


# --- equations and the suppress-test run ------------------------------------------


def test_equations_are_numbered_per_document_with_a_parsed_lhs() -> None:
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                equations=[
                    equation('"width" = 40', is_global=True, value=40.0),
                    equation('"D1@Sketch1" = "width" * 2'),
                ],
            )
        ]
    )

    first, second = package.equations
    assert (first.document_id, first.index, first.lhs) == ("doc:2", 0, "width")
    assert (first.is_global, first.value) == (True, 40.0)
    assert (second.index, second.lhs) == (1, "D1@Sketch1")
    assert (second.is_global, second.value) == (False, None)
    assert_round_trips(package)


def test_equation_is_global_can_be_unreadable() -> None:
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                equations=[equation('"width" = 40', is_global=None)],
            )
        ]
    )

    assert package.equations[0].is_global is None


def test_suppress_run_rows_are_built_from_features_and_round_trip() -> None:
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                features=[folder("4-Detail", feature("Hole1", "HoleWzd"), feature("Cut1", "Cut"))],
            )
        ]
    )
    by_name: dict[str, Feature] = {row.name: row for row in package.features}

    run = suppress_run(
        document_id="doc:2",
        rows=[
            suppress_row(by_name["Hole1"], "ok", whats_wrong_count=0),
            suppress_row(
                by_name["Cut1"],
                "rebuild_errors",
                whats_wrong_count=2,
                messages=["Boss-Extrude2 is in error"],
                messages_truncated=1,
            ),
        ],
    )
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                features=[folder("4-Detail", feature("Hole1", "HoleWzd"), feature("Cut1", "Cut"))],
            )
        ],
        suppress_test=run,
    )

    assert package.rms_suppress_test is not None
    assert package.rms_suppress_test.document_id == "doc:2"
    assert package.rms_suppress_test.group == "4-Detail"
    assert package.rms_suppress_test.configuration == "Default"
    assert package.rms_suppress_test.acknowledged is True
    assert package.rms_suppress_test.baseline_whats_wrong_count == 0
    assert package.rms_suppress_test.restore_verified is True
    assert package.rms_suppress_test.features_present == 2
    first, second = package.rms_suppress_test.rows
    assert (first.feature_id, first.name, first.outcome) == (
        by_name["Hole1"].id,
        "Hole1",
        "ok",
    )
    assert first.persist_ref == by_name["Hole1"].persist_ref
    assert first.persist_ref_scope == "doc:2"
    assert (second.outcome, second.whats_wrong_count) == ("rebuild_errors", 2)
    assert second.messages == ["Boss-Extrude2 is in error"]
    assert second.messages_truncated == 1
    assert_round_trips(package)


def test_suppress_run_records_an_unverified_restore() -> None:
    run = suppress_run(
        document_id="doc:2",
        rows=[],
        restore_verified=False,
        unrestored_feature_ids=["feat:0004"],
        run_at=datetime(2026, 9, 15, 8, 0, tzinfo=UTC),
    )

    assert run.restore_verified is False
    assert run.unrestored_feature_ids == ["feat:0004"]
    assert run.features_present == 0


def test_an_unknown_traversal_shape_is_refused() -> None:
    with pytest.raises(ValueError, match="sideways"):
        build_features([feature("Boss1", "Extrusion")], document_id="doc:2", shape="sideways")


def test_a_package_the_ir_would_reject_fails_loudly() -> None:
    with pytest.raises(ValidationError):
        rms_package(
            parts=[
                PartSpec(
                    document_id="doc:2",
                    name="housing",
                    instances=[InstanceSpec("housing-1", suppression="half-loaded")],
                )
            ]
        )
