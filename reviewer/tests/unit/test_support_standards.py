"""The standards fixture builder: one builder, every standards fixture and golden (T007).

`tests/support/standards.py` is to this feature what `tests/support/features.py` is to feature
003: the single place a fixture package is described, so a golden and a unit test cannot
disagree about what "the same package" means. It is built on `tests/support/packages.py` (the
schema version, the package id, the creation time and the extractor block stay in one place)
and it reuses feature 003's `build_features` for the feature tree rather than laying out a
second one.

The last test is the one that makes a golden trustworthy: **re-running the builder reproduces
a written fixture byte for byte**, so a fixture that has drifted from its builder is a failure
and not an invitation to rewrite the file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swreview.checks.standards.library import PrefixMatcher
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.ir.loader import load_package, save_package
from swreview.ir.models import EvidencePackage
from tests.support.features import feature, sketch_feature
from tests.support.standards import (
    PHASE_ORDER,
    AnnotationSpec,
    AssemblySpec,
    ComponentSpec,
    CutListSpec,
    DimensionSpec,
    DrawingSpec,
    MateEntitySpec,
    MateSpec,
    NoteSpec,
    PartSpec,
    RevisionTableSpec,
    SheetSpec,
    ViewSpec,
    standards_package,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE_A = FIXTURE_DIR / "profile-a.yaml"
PROFILE_B = FIXTURE_DIR / "profile-b.yaml"


def a_part(**overrides: object) -> PartSpec:
    fields: dict[str, object] = {"name": "housing", "features": (sketch_feature("Sketch1"),)}
    fields.update(overrides)
    return PartSpec(**fields)  # type: ignore[arg-type]


def an_assembly(**overrides: object) -> AssemblySpec:
    fields: dict[str, object] = {
        "name": "cover-assy",
        "components": (ComponentSpec(name="housing-1", document="housing"),),
    }
    fields.update(overrides)
    return AssemblySpec(**fields)  # type: ignore[arg-type]


# --- the package validates and round-trips ------------------------------------------------


def test_a_minimal_package_validates_and_round_trips() -> None:
    package = standards_package(documents=[a_part()])

    reloaded = EvidencePackage.model_validate_json(package.model_dump_json())

    assert reloaded == package


def test_a_written_package_loads_back_unchanged(tmp_path: Path) -> None:
    package = standards_package(documents=[an_assembly(), a_part()])

    save_package(package, tmp_path / "run")

    assert load_package(tmp_path / "run").package == package


# --- one row per document, with its kind and its path -------------------------------------


def test_each_document_becomes_one_row_with_its_kind_and_path() -> None:
    package = standards_package(
        documents=[
            an_assembly(folder="projects/"),
            a_part(folder="projects/parts/"),
            DrawingSpec(name="cover", folder="projects/", sheets=()),
        ],
        vault_root="D:/Vault",
    )

    assert [(row.document_id, row.kind, row.path) for row in package.documents] == [
        ("doc:1", "assembly", "D:/Vault/projects/cover-assy.SLDASM"),
        ("doc:2", "part", "D:/Vault/projects/parts/housing.SLDPRT"),
        ("doc:3", "drawing", "D:/Vault/projects/cover.SLDDRW"),
    ]
    assert [row.file_name for row in package.documents] == [
        "cover-assy.SLDASM",
        "housing.SLDPRT",
        "cover.SLDDRW",
    ]


def test_a_document_carries_its_configuration_independent_properties() -> None:
    package = standards_package(documents=[a_part(properties={"Any Name": "value"})])

    assert package.documents[0].custom_properties == {"Any Name": "value"}


def test_the_design_names_the_first_document_as_the_root() -> None:
    package = standards_package(
        documents=[an_assembly(), a_part(), DrawingSpec(name="cover", sheets=())]
    )

    assert package.design.root_assembly_document_id == "doc:1"
    assert package.design.drawing_document_ids == ["doc:3"]
    assert [entry.document_id for entry in package.manifest.entries] == ["doc:1", "doc:2", "doc:3"]


@pytest.mark.parametrize("fixture", [PROFILE_A, PROFILE_B], ids=lambda path: path.stem)
def test_a_package_can_be_built_for_either_fixture_profile(fixture: Path) -> None:
    """The paths a package carries are written for the profile it will be graded against."""
    profile: StandardsProfile = load_profile(fixture)
    skip_prefix = profile.library.skip_prefixes[0]

    package = standards_package(documents=[a_part(folder=skip_prefix)], profile=profile)

    path = package.documents[0].path
    assert path.startswith(profile.vault_root)
    assert PrefixMatcher.from_profile(profile).match(path).skip == skip_prefix


# --- the component instances that reach a document ----------------------------------------


def test_every_component_instance_names_the_document_it_reaches() -> None:
    package = standards_package(
        documents=[
            an_assembly(
                components=(
                    ComponentSpec(name="housing-1", document="housing", is_fixed=True),
                    ComponentSpec(name="housing-2", document="housing"),
                )
            ),
            a_part(),
        ]
    )

    instances = [row for row in package.components if row.document_id == "doc:2"]

    assert [row.id for row in instances] == ["cmp:0002", "cmp:0003"]
    assert [row.name for row in instances] == ["housing-1", "housing-2"]
    assert [row.is_fixed for row in instances] == [True, False]
    assert package.components[0].id == "cmp:0001"
    assert package.components[0].document_id == "doc:1"


def test_a_nested_instance_names_its_parent_and_its_full_path() -> None:
    package = standards_package(
        documents=[
            an_assembly(components=(ComponentSpec(name="sub-1", document="sub-assy"),)),
            AssemblySpec(
                name="sub-assy",
                components=(
                    ComponentSpec(name="housing-1", document="housing", parent="sub-1"),
                ),
            ),
            a_part(),
        ]
    )

    housing = next(row for row in package.components if row.name == "housing-1")

    assert housing.parent_id == "cmp:0002"
    assert housing.full_path == "sub-1/housing-1"
    assert housing.document_id == "doc:3"


def test_a_non_resolved_instance_keeps_its_state() -> None:
    """Suppressed, lightweight and unloaded are one rule in the checks and three states here."""
    package = standards_package(
        documents=[
            an_assembly(
                components=(
                    ComponentSpec(name="a-1", document="housing", suppression="suppressed"),
                    ComponentSpec(name="a-2", document="housing", suppression="lightweight"),
                    ComponentSpec(name="a-3", document="housing", suppression="unloaded"),
                )
            ),
            a_part(),
        ]
    )

    assert [row.suppression for row in package.components[1:]] == [
        "suppressed",
        "lightweight",
        "unloaded",
    ]


def test_an_instance_carries_the_appearance_visibility_and_pattern_readings() -> None:
    package = standards_package(
        documents=[
            an_assembly(
                components=(
                    ComponentSpec(
                        name="housing-1",
                        document="housing",
                        transparency_raw=0.75,
                        has_appearance_override=True,
                        visibility_raw=0,
                        is_pattern_instance=True,
                        constrained_status_raw=2,
                    ),
                )
            ),
            a_part(),
        ]
    )

    instance = package.components[1]

    assert instance.transparency_raw == 0.75
    assert instance.has_appearance_override is True
    assert instance.visibility_raw == 0
    assert instance.is_pattern_instance is True
    assert instance.constrained_status_raw == 2


def test_an_instance_of_an_unknown_document_is_refused() -> None:
    with pytest.raises(ValueError, match="nowhere"):
        standards_package(
            documents=[an_assembly(components=(ComponentSpec(name="x-1", document="nowhere"),))]
        )


# --- mates --------------------------------------------------------------------------------


def test_mates_carry_their_entities_resolution_status() -> None:
    package = standards_package(
        documents=[
            an_assembly(
                mates=(
                    MateSpec(
                        entities=(
                            MateEntitySpec(component="housing-1"),
                            MateEntitySpec(component="housing-1", resolution_status="unresolved"),
                        )
                    ),
                    MateSpec(
                        entities=(MateEntitySpec(component="housing-1", resolution_status=None),),
                        suppressed=True,
                    ),
                )
            ),
            a_part(),
        ]
    )

    assert [row.id for row in package.mates] == ["mate:0001", "mate:0002"]
    assert [entity.resolution_status for entity in package.mates[0].entities] == [
        "resolved",
        "unresolved",
    ]
    assert package.mates[0].entities[0].component_id == "cmp:0002"
    assert package.mates[1].entities[0].resolution_status is None
    assert package.mates[1].suppressed is True


# --- features, sketches and cut-list items -------------------------------------------------


def test_features_carry_their_sketch_status_and_text_segment_count() -> None:
    package = standards_package(
        documents=[
            a_part(
                features=(
                    sketch_feature("Sketch1", raw_status=2, text_segments=3),
                    sketch_feature("Sketch2", raw_status=None),
                    feature("Boss-Extrude1", "Extrusion", error_code=7),
                )
            )
        ]
    )

    sketches = [row for row in package.features if row.sketch is not None]

    assert [row.name for row in package.features] == ["Sketch1", "Sketch2", "Boss-Extrude1"]
    assert [row.sketch.raw_status for row in sketches] == [2, None]  # type: ignore[union-attr]
    assert [row.sketch.text_segment_count for row in sketches] == [3, None]  # type: ignore[union-attr]
    assert package.features[2].error_code == 7
    assert {row.document_id for row in package.features} == {"doc:1"}


def test_cut_list_items_are_emitted_for_the_part_that_owns_them() -> None:
    package = standards_package(
        documents=[
            a_part(
                cut_list=(
                    CutListSpec(name="Tube 1", folder_name="Cut-List-Item1"),
                    CutListSpec(
                        name="Tube 2",
                        folder_name="Cut-List-Item2",
                        excluded_from_cut_list=False,
                        body_count=0,
                    ),
                    CutListSpec(name="Tube 3", body_count=None, excluded_from_cut_list=None),
                )
            )
        ]
    )

    items = package.cut_list_items

    assert [item.id for item in items] == ["cut:0001", "cut:0002", "cut:0003"]
    assert {item.document_id for item in items} == {"doc:1"}
    assert [item.name for item in items] == ["Tube 1", "Tube 2", "Tube 3"]
    assert [item.excluded_from_cut_list for item in items] == [True, False, None]
    assert [item.body_count for item in items] == [1, 0, None]
    assert items[0].folder_name == "Cut-List-Item1"
    assert items[0].configuration == "Default"


# --- the drawing record --------------------------------------------------------------------


def drawing_fixture() -> DrawingSpec:
    return DrawingSpec(
        name="cover",
        properties={"Rev": "A"},
        active_sheet="Sheet1",
        sheets=(
            SheetSpec(
                name="Sheet1",
                was_active=True,
                views=(
                    ViewSpec(name="Sheet Format1", view_type_raw=1, notes=(NoteSpec("a note"),)),
                    ViewSpec(
                        name="Drawing View1",
                        references="cover-assy",
                        dimensions=(
                            DimensionSpec(name="D1@Sketch1"),
                            DimensionSpec(name="D2@Sketch1", is_overridden=True, override_mm=12.5),
                        ),
                        annotations=(
                            AnnotationSpec(name="RevSymbol1"),
                            AnnotationSpec(name="Note2", is_dangling=True),
                        ),
                        notes=(NoteSpec("another note"), NoteSpec(None)),
                    ),
                ),
                revision_tables=(
                    RevisionTableSpec(
                        rows=(("REVISION", "DESCRIPTION", "DATE"), ("B", "update", "2026-01-01")),
                        current_revision_raw="B",
                    ),
                ),
            ),
            SheetSpec(name="Sheet2"),
        ),
    )


def test_a_drawing_record_carries_its_sheets_views_and_contents() -> None:
    package = standards_package(documents=[an_assembly(), a_part(), drawing_fixture()])

    record = package.drawing_records[0]
    sheet = record.sheets[0]
    views = sheet.views

    assert [row.document_id for row in package.drawing_records] == ["doc:3"]
    assert record.active_sheet_name == "Sheet1"
    assert [row.name for row in record.sheets] == ["Sheet1", "Sheet2"]
    assert [row.index for row in record.sheets] == [0, 1]
    assert [row.was_active for row in record.sheets] == [True, False]
    assert [row.id for row in record.sheets] == ["dsh:0001", "dsh:0002"]
    assert [row.id for row in views] == ["dvw:0001", "dvw:0002"]
    assert [row.sheet_id for row in views] == ["dsh:0001", "dsh:0001"]
    assert views[0].view_type_raw == 1
    assert [row.id for row in views[1].display_dimensions] == ["ddm:0001", "ddm:0002"]
    assert [row.is_overridden for row in views[1].display_dimensions] == [False, True]
    assert views[1].display_dimensions[1].override_value is not None
    assert [row.id for row in views[1].annotations] == ["dan:0001", "dan:0002"]
    assert [row.is_dangling for row in views[1].annotations] == [False, True]
    assert [row.id for row in views[0].notes] == ["dnt:0001"]
    assert [row.text for row in views[1].notes] == ["another note", None]
    assert [row.owner_id for row in views[1].notes] == ["dvw:0002", "dvw:0002"]


def test_a_revision_table_carries_its_rows_cells_and_counts() -> None:
    package = standards_package(documents=[an_assembly(), a_part(), drawing_fixture()])

    table = package.drawing_records[0].sheets[0].revision_tables[0]

    assert table.id == "drv:0001"
    assert table.sheet_id == "dsh:0001"
    assert table.current_revision_raw == "B"
    assert table.row_count == 2
    assert table.column_count == 3
    assert [row.index for row in table.rows] == [0, 1]
    assert [row.is_header for row in table.rows] == [True, False]
    assert table.rows[1].cells == ["B", "update", "2026-01-01"]


def test_a_view_resolves_the_document_it_references() -> None:
    package = standards_package(documents=[an_assembly(), a_part(), drawing_fixture()])

    view = package.drawing_records[0].sheets[0].views[1]

    assert view.referenced_document_id == "doc:1"
    assert view.referenced_model_path == package.documents[0].path


def test_a_view_referencing_an_unknown_document_is_refused() -> None:
    drawing = DrawingSpec(
        name="cover",
        sheets=(SheetSpec(name="Sheet1", views=(ViewSpec(name="V1", references="nowhere"),)),),
    )

    with pytest.raises(ValueError, match="nowhere"):
        standards_package(documents=[a_part(), drawing])


# --- a drawing root ------------------------------------------------------------------------

# A drawing is never instantiated as a component, so the dump synthesizes a forest root
# carrying the drawing's own document id and hangs one subtree per referenced model under it
# (`contracts/ir-additions.md` section 7, `research.md` R9). The builder must produce that
# shape, because a traversal test that writes that shape by hand is testing its own helper.


def a_drawing_root(*references: str) -> DrawingSpec:
    """A drawing whose one sheet carries a sheet-format view and one view per reference."""
    return DrawingSpec(
        name="cover",
        sheets=(
            SheetSpec(
                name="Sheet1",
                views=(
                    ViewSpec(name="Sheet Format1", view_type_raw=1),
                    *(
                        ViewSpec(name=f"View{number}", references=name)
                        for number, name in enumerate(references, start=1)
                    ),
                ),
            ),
        ),
    )


def parents(package: EvidencePackage) -> list[tuple[str, str | None]]:
    return [(row.id, row.parent_id) for row in package.components]


def test_a_drawing_root_carries_a_synthesized_forest_root_of_its_own() -> None:
    package = standards_package(documents=[a_drawing_root("cover-assy"), an_assembly(), a_part()])

    forest_root = package.components[0]

    assert forest_root.id == "cmp:0001"
    assert forest_root.document_id == "doc:1"
    assert forest_root.parent_id is None
    assert forest_root.name == "cover"
    assert forest_root.suppression == "resolved"


def test_each_referenced_assembly_gets_one_instance_under_the_forest_root() -> None:
    package = standards_package(
        documents=[
            a_drawing_root("cover-assy", "sub-assy"),
            an_assembly(),
            AssemblySpec(
                name="sub-assy", components=(ComponentSpec(name="bracket-1", document="bracket"),)
            ),
            a_part(),
            PartSpec(name="bracket"),
        ]
    )

    assert parents(package) == [
        ("cmp:0001", None),
        ("cmp:0002", "cmp:0001"),
        ("cmp:0003", "cmp:0001"),
        ("cmp:0004", "cmp:0002"),
        ("cmp:0005", "cmp:0003"),
    ]
    assert [row.document_id for row in package.components] == [
        "doc:1",
        "doc:2",
        "doc:3",
        "doc:4",
        "doc:5",
    ]
    assert [row.name for row in package.components[1:3]] == ["cover-assy", "sub-assy"]
    assert [row.full_path for row in package.components[1:3]] == [
        "cover/cover-assy",
        "cover/sub-assy",
    ]


def test_a_referenced_assembly_drawn_in_two_views_gets_one_instance() -> None:
    package = standards_package(
        documents=[a_drawing_root("cover-assy", "cover-assy"), an_assembly(), a_part()]
    )

    assert [row.document_id for row in package.components] == ["doc:1", "doc:2", "doc:3"]


def test_a_referenced_part_gets_no_instance_of_its_own() -> None:
    """A part has no component tree, so there is no subtree to hang under the forest root."""
    package = standards_package(documents=[a_drawing_root("housing"), a_part()])

    assert [row.document_id for row in package.components] == ["doc:1"]


def test_no_instance_of_a_drawing_rooted_package_is_its_own_parent() -> None:
    """The defect this shape replaces: with no root-assembly instance to fall back on, the
    first component of a referenced model became its own parent and the referenced assembly
    got no instance row at all."""
    package = standards_package(documents=[a_drawing_root("cover-assy"), an_assembly(), a_part()])

    assert all(row.parent_id != row.id for row in package.components)
    assert {row.document_id for row in package.components} == {"doc:1", "doc:2", "doc:3"}


def test_a_drawing_that_references_nothing_still_carries_its_forest_root() -> None:
    package = standards_package(documents=[a_drawing_root(), a_part()])

    assert [(row.id, row.document_id) for row in package.components] == [("cmp:0001", "doc:1")]


def test_an_assembly_root_is_unchanged_by_the_drawing_branch() -> None:
    """The root assembly's own instance is still `cmp:0001`, and nothing hangs above it."""
    package = standards_package(documents=[an_assembly(), a_part()])

    assert parents(package) == [("cmp:0001", None), ("cmp:0002", "cmp:0001")]


# --- what a standards package says about itself --------------------------------------------


def test_the_extractor_block_says_standards_and_lists_every_phase() -> None:
    package = standards_package(documents=[a_part()])

    phases = package.extractor.phases

    assert package.extractor.profile == "standards"
    assert [row.name for row in phases] == list(PHASE_ORDER)
    assert {row.name: row.status for row in phases}["cutlist"] == "ok"
    assert {row.name: row.status for row in phases}["drawing"] == "skipped"
    assert [row.name for row in phases if row.status == "skipped"] == [
        "drawing",
        "hole",
        "fastener",
        "face",
        "body",
    ]
    assert all(row.elapsed_ms is None for row in phases if row.status == "skipped")
    assert all(row.elapsed_ms is not None for row in phases if row.status == "ok")


def test_the_drawing_phase_ran_when_the_package_carries_a_drawing() -> None:
    package = standards_package(documents=[an_assembly(), a_part(), drawing_fixture()])

    assert {row.name: row.status for row in package.extractor.phases}["drawing"] == "ok"


def test_a_package_with_neither_new_array_serializes_as_a_1_3_0_package_did() -> None:
    """The additivity rule: the two 1.4.0 arrays are omitted when empty (SC-004)."""
    written = json.loads(standards_package(documents=[a_part()]).model_dump_json())

    assert "cut_list_items" not in written
    assert "drawing_records" not in written


def test_gaps_are_passed_through_verbatim() -> None:
    package = standards_package(documents=[a_part()], gaps=[])

    assert package.gaps == []


# --- a fixture that has drifted from its builder is a failure ------------------------------


def test_rebuilding_reproduces_a_written_fixture_byte_for_byte(tmp_path: Path) -> None:
    specs = [an_assembly(), a_part(), drawing_fixture()]

    first = save_package(standards_package(documents=specs), tmp_path / "first")
    second = save_package(standards_package(documents=specs), tmp_path / "second")

    assert first.read_bytes() == second.read_bytes()
