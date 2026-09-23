"""The drawing-context fixtures: the builders, the generator, and the cases they carry
(feature 011 T011, `specs/011-drawing-context/contracts/fixtures.md`).

No recorded package carries a drawing, so every acceptance test of feature 011 reads three
synthetic packages built by code (`tests/support/drawings.py`,
`tests/fixtures/drawings/generate_fixtures.py`). This module pins three things:

1. **the builders** make IR 1.6.0 packages that validate, with drawing ids continuing one
   sequence across drawings, a drawing document shaped as the extractor writes one, and an
   attached face tied to a real face of the package;
2. **the generator reproduces every committed byte**, so a drifted fixture is a red test and
   never a silent rewrite;
3. **every case row of `contracts/fixtures.md` section 2** is present with its numbers,
   counted here straight off the package - never through `drawings/`, which these fixtures
   exist to test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.ir.loader import load_package
from swreview.ir.models import (
    DisplayDimensionRecord,
    DrawingRecord,
    DrawingView,
    EvidencePackage,
)
from tests.support import drawings
from tests.support.drawings import (
    DRAWING_FIXTURE_SCHEMA_VERSION,
    Attach,
    DrawingBuilder,
)
from tests.support.mechanical import FICTIONAL_ROOT, PackageBuilder, load_generator

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"
MECHANICAL = Path(__file__).resolve().parents[1] / "fixtures" / "mechanical"


def generator():
    return load_generator(FIXTURES / "generate_fixtures.py")


@pytest.fixture(scope="module")
def plate() -> EvidencePackage:
    return load_package(FIXTURES / "plate-drawing").package


@pytest.fixture(scope="module")
def root() -> EvidencePackage:
    return load_package(FIXTURES / "drawing-root").package


@pytest.fixture(scope="module")
def assembly() -> EvidencePackage:
    return load_package(FIXTURES / "assembly-drawings").package


def record_of(package: EvidencePackage, file_name: str) -> DrawingRecord:
    document = next(item for item in package.documents if item.file_name == file_name)
    return next(
        item for item in package.drawing_records if item.document_id == document.document_id
    )


def views(record: DrawingRecord) -> list[DrawingView]:
    return [view for sheet in record.sheets for view in sheet.views]


def dimension(record: DrawingRecord, name: str) -> DisplayDimensionRecord:
    return next(
        item for view in views(record) for item in view.display_dimensions if item.name == name
    )


# --- 1. the builders ----------------------------------------------------------------------


def base_package() -> EvidencePackage:
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    plate = builder.document("FICT-KALO-0001", "part", material="Alloy Steel")
    component = builder.component(plate, name="FICT-KALO-0001-1")
    builder.cylinder_face(
        component,
        origin_mm=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0),
        diameter_mm=3.0,
        lo_mm=0.0,
        hi_mm=6.0,
    )
    return builder.build().package


def test_the_builders_write_schema_1_6_0_whatever_the_models_default_to() -> None:
    """Pinned to the string, not `SCHEMA_VERSION`: a later IR minor must not rewrite these
    fixtures under the regeneration test (FR-048)."""
    builder = DrawingBuilder(base_package())
    builder.drawing(builder.drawing_document("FICT-KALO-0001"))

    package = builder.build()

    assert package.schema_version == DRAWING_FIXTURE_SCHEMA_VERSION == "1.6.0"
    assert EvidencePackage.model_validate_json(package.model_dump_json()) == package


def test_a_drawing_document_is_shaped_as_the_extractor_writes_one() -> None:
    builder = DrawingBuilder(base_package())
    document_id = builder.drawing_document("FICT-KALO-0001")
    builder.drawing(document_id)

    package = builder.build()

    document = next(item for item in package.documents if item.document_id == document_id)
    assert document.kind == "drawing"
    assert document.file_name == "FICT-KALO-0001.SLDDRW"
    assert document.path == f"{FICTIONAL_ROOT}Vault\\FICT-KALO-0001.SLDDRW"
    assert document.configurations == [] and document.active_configuration == ""
    entry = next(item for item in package.manifest.entries if item.document_id == document_id)
    assert entry.configuration == ""
    assert package.design.drawing_document_ids == [document_id]


def test_two_drawings_continue_every_id_sequence() -> None:
    builder = DrawingBuilder(base_package())
    part = "doc:0002"
    for stem in ("FICT-KALO-0001", "FICT-KALO-0001-B"):
        record = builder.drawing(builder.drawing_document(stem))
        sheet = builder.sheet(record, "Sheet1")
        view = builder.view(sheet, "Drawing View1", references=part)
        builder.dimension(view, "KALOMIR1@FICT-HOLE-0001", value_mm=3.0)
        builder.annotation(view, type_raw=2, name="DatumTag1", datum_label="A")
        builder.note(view, "FICTIONAL NOTE 1")
        builder.table(sheet, view, type_raw=0, title="FICTIONAL TABLE", rows=[["1"]])
        builder.revision_table(sheet, rows=[["REV"], ["A"]], current_revision="A")

    first, second = builder.build().drawing_records

    def ids(record: DrawingRecord) -> list[str]:
        sheet = record.sheets[0]
        view = sheet.views[0]
        return [
            sheet.id,
            view.id,
            view.display_dimensions[0].id,
            view.annotations[0].id,
            view.notes[0].id,
            sheet.revision_tables[0].id,
            sheet.tables[0].id,
        ]

    assert ids(first) == [
        "dsh:0001",
        "dvw:0001",
        "ddm:0001",
        "dan:0001",
        "dnt:0001",
        "drv:0001",
        "dtb:0001",
    ]
    assert ids(second) == [
        "dsh:0002",
        "dvw:0002",
        "ddm:0002",
        "dan:0002",
        "dnt:0002",
        "drv:0002",
        "dtb:0002",
    ]


def test_an_attached_face_carries_the_faces_reference_and_its_part_document() -> None:
    base = base_package()
    builder = DrawingBuilder(base)
    record = builder.drawing(builder.drawing_document("FICT-KALO-0001"))
    view = builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references="doc:0002")

    added = builder.dimension(
        view, "KALOMIR1@FICT-HOLE-0001", value_mm=3.0, attached=[Attach("fac:0001", via="edge")]
    )

    face = base.faces[0]
    assert [(item.persist_ref, item.scope, item.via) for item in added.attached_faces] == [
        (face.persist_ref, "doc:0002", "edge")
    ]


def test_a_face_that_is_not_in_the_package_is_refused() -> None:
    builder = DrawingBuilder(base_package())
    view = builder.view(
        builder.sheet(builder.drawing(builder.drawing_document("FICT-KALO-0001")), "Sheet1"),
        "Drawing View1",
        references="doc:0002",
    )

    with pytest.raises(ValueError, match="fac:0099"):
        builder.dimension(
            view, "KALOMIR1@FICT-HOLE-0001", value_mm=3.0, attached=[Attach("fac:0099")]
        )


def test_a_view_of_a_document_that_is_not_in_the_package_is_refused() -> None:
    builder = DrawingBuilder(base_package())
    sheet = builder.sheet(builder.drawing(builder.drawing_document("FICT-KALO-0001")), "Sheet1")

    with pytest.raises(ValueError, match="doc:0099"):
        builder.view(sheet, "Drawing View1", references="doc:0099")


def test_a_dimension_with_no_unit_records_no_value_and_the_gap_that_says_so() -> None:
    builder = DrawingBuilder(base_package())
    view = builder.view(
        builder.sheet(builder.drawing(builder.drawing_document("FICT-KALO-0001")), "Sheet1"),
        "Drawing View1",
        references="doc:0002",
    )

    added = builder.dimension(view, "KALOMIR9@FICT-HOLE-0001", value_mm=2.0, type_raw=13)

    package = builder.build()
    assert added.value is None
    assert [
        (gap.entity_kind, gap.entity_id)
        for gap in package.gaps
        if gap.entity_kind == "dimension_unit"
    ] == [("dimension_unit", added.id)]


def test_a_candidate_is_the_same_stem_beside_its_document() -> None:
    builder = DrawingBuilder(base_package())
    builder.candidate("doc:0002")

    candidate = builder.build().drawing_candidates[0]

    assert (candidate.document_id, candidate.path, candidate.reason) == (
        "doc:0002",
        f"{FICTIONAL_ROOT}Vault\\FICT-KALO-0001.SLDDRW",
        "same_name_beside_model",
    )


def test_the_drawing_vocabulary_refuses_a_word_it_does_not_know() -> None:
    assert drawings.drawing_fictional_offences("FICTIONAL-FORMAT-A") == []
    assert drawings.drawing_fictional_offences("Drawing View1") == []
    assert drawings.drawing_fictional_offences("FICTIONAL-HOUSING") == ["HOUSING"]


# --- 2. the generator reproduces every committed byte ------------------------------------


def as_committed(path: Path) -> bytes:
    """A fixture file's bytes as git stores them: JSON is text (LF in the blob), a GLB is not."""
    content = path.read_bytes()
    return content if path.suffix == ".glb" else content.replace(b"\r\n", b"\n")


def test_re_running_the_generator_reproduces_every_committed_fixture_byte_for_byte() -> None:
    rendered = generator().render_all()

    committed = {
        path.relative_to(FIXTURES).as_posix(): as_committed(path)
        for path in sorted(FIXTURES.rglob("*"))
        if path.is_file() and path.parent != FIXTURES and "__pycache__" not in path.parts
    }
    assert sorted(rendered) == sorted(committed), "the generator and the tree name different files"
    drifted = [name for name, content in rendered.items() if committed[name] != content]
    assert drifted == [], "regenerate with generate_fixtures.py; never edit a fixture by hand"


@pytest.mark.parametrize("name", ["plate-drawing", "drawing-root", "assembly-drawings"])
def test_every_fixture_is_an_ir_1_6_0_package(name: str) -> None:
    assert load_package(FIXTURES / name).package.schema_version == "1.6.0"


# --- 3. plate-drawing: feature 010's tolerances assembly with two drawings of the plate ---


def test_the_plate_fixture_is_feature_010s_tolerances_assembly_unchanged(
    plate: EvidencePackage,
) -> None:
    tolerances = load_package(MECHANICAL / "tolerances").package

    assert [item for item in plate.documents if item.kind != "drawing"] == tolerances.documents
    for array in (
        "components",
        "holes",
        "faces",
        "bodies",
        "model_dimensions",
        "model_annotations",
    ):
        assert getattr(plate, array) == getattr(tolerances, array), array


def test_the_plate_has_two_attached_drawings_and_the_block_a_candidate(
    plate: EvidencePackage,
) -> None:
    drawing_a = next(
        item for item in plate.documents if item.file_name == "FICT-TULMKALO-3001.SLDDRW"
    )
    drawing_b = next(
        item for item in plate.documents if item.file_name == "FICT-TULMKALO-3001-B.SLDDRW"
    )

    assert plate.design.drawing_document_ids == [drawing_a.document_id, drawing_b.document_id]
    assert [(item.document_id, item.path) for item in plate.drawing_candidates] == [
        ("doc:0003", f"{FICTIONAL_ROOT}Vault\\FICT-TULMSORN-3002.SLDDRW")
    ]


def test_drawing_a_states_its_settings_and_one_third_angle_sheet(plate: EvidencePackage) -> None:
    record = record_of(plate, "FICT-TULMKALO-3001.SLDDRW")

    assert (record.is_detailing_mode, record.length_unit_raw, record.dimension_precision_raw) == (
        False,
        0,
        2,
    )
    assert record.drafting_standard_name == "FICTIONAL-STANDARD"
    sheet = record.sheets[0]
    assert len(record.sheets) == 1 and sheet.sheet_format_name == "FICTIONAL-FORMAT-A"
    assert sheet.first_angle is False
    model_views = [view for view in sheet.views if view.referenced_document_id == "doc:0002"]
    assert model_views and all(
        (view.referenced_configuration, view.is_model_out_of_date, view.is_model_loaded)
        == ("Default", False, True)
        for view in model_views
    )


def test_drawing_a_carries_every_dimension_case(plate: EvidencePackage) -> None:
    record = record_of(plate, "FICT-TULMKALO-3001.SLDDRW")
    faces = {face.id: face.persist_ref for face in plate.faces}

    bilateral = dimension(record, "KALOMIR11@FICT-TULMKALO-3001")
    assert bilateral.tolerance is not None and bilateral.tolerance.kind == "bilateral"
    assert [item.persist_ref for item in bilateral.attached_faces] == [faces["fac:0001"]]

    model_item = dimension(record, "KALOMIR1@FICT-HOLE-0001@fict-tulmkalo-3001.sldprt")
    assert model_item.name.split("@fict-")[0] == plate.model_dimensions[0].name
    assert (model_item.tolerance_type_raw, model_item.fit_hole_class) == (8, "H7")

    two_decimal = dimension(record, "KALOMIR13@FICT-TULMKALO-3001")
    assert (two_decimal.tolerance_type_raw, two_decimal.uses_document_precision) == (0, True)
    assert [item.persist_ref for item in two_decimal.attached_faces] == [faces["fac:0002"]]

    assert dimension(record, "KALOMIR14@FICT-TULMKALO-3001").tolerance_type_raw == 10
    assert dimension(record, "KALOMIR15@FICT-TULMKALO-3001").tolerance_type_raw == 11

    callout = dimension(record, "KALOMIR16@FICT-TULMKALO-3001")
    assert callout.is_hole_callout is True and len(callout.hole_callout_variables_raw) == 3

    edge = dimension(record, "KALOMIR17@FICT-TULMKALO-3001")
    assert edge.is_reference is True
    assert [item.via for item in edge.attached_faces] == ["edge", "edge"]

    unitless = dimension(record, "KALOMIR18@FICT-TULMKALO-3001")
    assert unitless.value is None
    assert any(
        gap.entity_kind == "dimension_unit" and gap.entity_id == unitless.id for gap in plate.gaps
    )

    overridden = dimension(record, "KALOMIR19@FICT-TULMKALO-3001")
    assert overridden.is_overridden is True
    assert [item.persist_ref for item in overridden.attached_faces] == [faces["fac:0001"]]


def test_drawing_a_carries_every_callout_note_and_table(plate: EvidencePackage) -> None:
    record = record_of(plate, "FICT-TULMKALO-3001.SLDDRW")
    annotations = [item for view in views(record) for item in view.annotations]

    gtol = next(item for item in annotations if item.type_raw == 5)
    assert gtol.gtol_frames[0].values_raw[0] == "0.05" and gtol.attached_faces
    assert sorted(item.datum_label for item in annotations if item.type_raw == 2) == ["A", "B"]
    finish = next(item for item in annotations if item.type_raw == 7)
    assert finish.surface_finish_symbol_raw is not None and finish.surface_finish_texts_raw

    notes = [note.text for view in views(record) for note in view.notes]
    assert len(notes) == 3 and any("GENERAL TOLERANCE" in (text or "") for text in notes)
    assert sorted(table.table_type_raw for table in record.sheets[0].tables) == [1, 5, 9]
    assert len(record.sheets[0].revision_tables) == 1


def test_drawing_b_shows_another_configuration_and_an_out_of_date_view(
    plate: EvidencePackage,
) -> None:
    record = record_of(plate, "FICT-TULMKALO-3001-B.SLDDRW")
    other, stale = views(record)

    assert other.referenced_configuration != "Default" and other.is_model_out_of_date is False
    assert stale.referenced_configuration == "Default" and stale.is_model_out_of_date is True
    [different] = other.display_dimensions
    assert different.tolerance is not None and different.tolerance.kind == "bilateral"
    [three] = stale.display_dimensions
    assert (three.precision_raw, three.uses_document_precision, three.tolerance_type_raw) == (
        3,
        False,
        0,
    )


# --- 4. drawing-root ------------------------------------------------------------------------

NEW_RECORD_FIELDS = {
    "DrawingRecord": (
        "is_detailing_mode",
        "length_unit_raw",
        "dimension_precision_raw",
        "units_decimal_places_raw",
        "tolerance_precision_raw",
        "drafting_standard_name",
    ),
    "DrawingSheetRecord": (
        "sheet_format_path",
        "scale_numerator",
        "scale_denominator",
        "first_angle",
        "tables",
    ),
    "DrawingView": (
        "referenced_configuration",
        "is_model_out_of_date",
        "is_model_loaded",
        "scale_decimal",
        "orientation_name",
    ),
    "DisplayDimensionRecord": (
        "text_prefix",
        "text_suffix",
        "text_above",
        "text_below",
        "precision_raw",
        "tolerance_precision_raw",
        "uses_document_precision",
        "units_raw",
        "uses_document_units",
        "tolerance",
        "tolerance_type_raw",
        "fit_hole_class",
        "fit_shaft_class",
        "is_reference",
        "driven_state_raw",
        "is_hole_callout",
        "hole_callout_variables_raw",
        "attached_faces",
    ),
    "DrawingAnnotation": (
        "gtol_frames",
        "datum_identifier_raw",
        "datum_label",
        "surface_finish_symbol_raw",
        "surface_finish_texts_raw",
        "attached_faces",
    ),
}
"""Every 1.6.0 member of the drawing records but `opened_by_review`, which only the confirmed
read-only open writes and which a drawing root - open already - never carries."""


def test_the_drawing_root_is_a_drawing_with_three_sheets_and_two_referenced_models(
    root: EvidencePackage,
) -> None:
    [record] = root.drawing_records
    assert record.document_id == root.design.root_assembly_document_id
    assert [(sheet.index, sheet.was_active, bool(sheet.views)) for sheet in record.sheets] == [
        (0, True, True),
        (1, False, True),
        (2, False, False),
    ]
    assert any(
        gap.entity_kind == "drawing_sheet_views" and gap.entity_id == record.sheets[2].id
        for gap in root.gaps
    )
    referenced = {view.referenced_document_id for view in views(record)} - {None}
    assert len(referenced) == 2
    assert record.opened_by_review is None and root.drawing_candidates == []


def test_the_drawing_root_binds_no_configuration(root: EvidencePackage) -> None:
    """`contracts/attach.md` section 2: a drawing session has no configuration, so the design,
    the drawing's document row and manifest entry, and the forest's root node all carry the
    empty string; each referenced model keeps its own (feature 011 T017, corrected on T012)."""
    root_id = root.design.root_assembly_document_id
    document = next(item for item in root.documents if item.document_id == root_id)
    entry = next(item for item in root.manifest.entries if item.document_id == root_id)
    [node] = [item for item in root.components if item.parent_id is None]

    assert root.design.active_configuration == ""
    assert document.configurations == [] and document.active_configuration == ""
    assert entry.configuration == ""
    assert node.document_id == root_id and node.referenced_configuration == ""
    models = [item for item in root.documents if item.kind != "drawing"]
    assert models and all(item.active_configuration == "Default" for item in models)


def test_every_new_record_field_is_present_on_at_least_one_record(root: EvidencePackage) -> None:
    [record] = root.drawing_records
    instances = {
        "DrawingRecord": [record],
        "DrawingSheetRecord": record.sheets,
        "DrawingView": views(record),
        "DisplayDimensionRecord": [
            item for view in views(record) for item in view.display_dimensions
        ],
        "DrawingAnnotation": [item for view in views(record) for item in view.annotations],
    }
    missing = [
        f"{model}.{name}"
        for model, names in NEW_RECORD_FIELDS.items()
        for name in names
        if not any(getattr(item, name) not in (None, []) for item in instances[model])
    ]
    assert missing == []
    tables = [table for sheet in record.sheets for table in sheet.tables]
    assert any(table.bom_rows for table in tables)


# --- 5. assembly-drawings ----------------------------------------------------------------


def test_the_assembly_drawing_carries_a_bill_of_materials(assembly: EvidencePackage) -> None:
    record = record_of(assembly, "FICT-OKTAVEN-5000.SLDDRW")
    [bom] = [
        table for sheet in record.sheets for table in sheet.tables if table.table_type_raw == 2
    ]

    documents = {item.document_id for item in assembly.documents}
    resolved = [document for row in bom.bom_rows for document in row.document_ids]
    unresolved = [path for row in bom.bom_rows for path in row.unresolved_paths]
    assert len(resolved) == 3 and set(resolved) <= documents
    assert len(unresolved) == 1 and unresolved[0].startswith(FICTIONAL_ROOT)


def test_one_part_is_shown_by_three_attached_drawings(assembly: EvidencePackage) -> None:
    part = next(
        item for item in assembly.documents if item.file_name == "FICT-OKTAKALO-5001.SLDPRT"
    )
    showing = [
        record.document_id
        for record in assembly.drawing_records
        if any(view.referenced_document_id == part.document_id for view in views(record))
    ]
    assert len(showing) == 3
    assert assembly.drawing_candidates == []


def test_a_view_of_a_document_outside_the_design_is_kept_with_its_gap(
    assembly: EvidencePackage,
) -> None:
    record = record_of(assembly, "FICT-OKTAVEN-5000.SLDDRW")
    [outside] = [
        view
        for view in views(record)
        if view.referenced_document_id is None and view.referenced_model_path
    ]

    assert outside.referenced_model_path.startswith(FICTIONAL_ROOT)
    assert any(
        gap.entity_kind == "drawing_referenced_document" and gap.entity_id == outside.id
        for gap in assembly.gaps
    )
