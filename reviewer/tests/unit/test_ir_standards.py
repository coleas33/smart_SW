"""Unit tests for the IR 1.4.0 additions: the standards-check evidence (006 T012).

`specs/006-standards-check/contracts/ir-additions.md` is the normative list: ten new
fields on existing models, one new field on the PDF ingest's `DrawingSheet`, one widened
enum on `ExtractorInfo`, one new `CutListItem` model and eight new drawing models.

Every one of them obeys the same additivity rule, and this file is where that rule is
measured rather than asserted by inspection:

- optional, with a default, and absent from `required`;
- **omitted when null** (a list, when it carries no rows), so a package that carries none
  of this feature's evidence serializes to the bytes the 1.3.0 build wrote and the feature
  001, 002 and 003 goldens stay byte-identical (SC-004);
- 1.3.0 still loads, and 2.0.0 still raises - the major gate of feature 001 is untouched.

**Where the new drawing records live.** `contracts/ir-additions.md` section 3 heads its
table `EvidencePackage.drawings[]`, but `drawings` has held the PDF ingest's
`DrawingSheet` rows since feature 001 and five shipped golden fixtures carry rows there.
`research.md` R9 rejects one array with a discriminator, and section 4 requires those five
fixtures to keep loading unchanged, so the two cannot share a member: the native records
land in a **new** `drawing_records[]` beside the untouched `drawings[]`, exactly as the
cut-list items land in a new `cut_list_items[]`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from swreview.ir.models import (
    SCHEMA_VERSION,
    Angle,
    ComponentInstance,
    CutListItem,
    DisplayDimensionRecord,
    Document,
    DrawingAnnotation,
    DrawingNote,
    DrawingRecord,
    DrawingSheet,
    DrawingSheetRecord,
    DrawingView,
    EvidencePackage,
    ExtractorInfo,
    Gap,
    MateEntity,
    Quantity,
    RevisionTable,
    RevisionTableRow,
    SketchInfo,
    UnsupportedSchemaVersionError,
)
from swreview.ir.schema import export_schema
from tests.golden.test_golden import PRE_1_4_0_FIXTURE_DIRS
from tests.support.contracts import load_contract
from tests.support.packages import build_package, persist_ref

GOLDEN_FIXTURE_DIRS = PRE_1_4_0_FIXTURE_DIRS
"""Every golden written before 1.4.0. Feature 006's own `standards-*` goldens are written
*at* 1.4.0 and carry its evidence by design, so they are not packages the two gates below
can ask "does this predate the bump?" of (`tests/golden/test_golden.py`)."""

# `contracts/ir-additions.md` section 1, verbatim: the ten fields on existing models plus
# the one on the PDF ingest's sheet. The count is stated in the contract and read here.
NEW_FIELDS_ON_EXISTING_MODELS: dict[str, tuple[str, ...]] = {
    "Document": (
        "is_exploded",
        "rebuild_error_count",
        "mass_overridden",
        "material_configuration",
    ),
    "ComponentInstance": (
        "transparency_raw",
        "has_appearance_override",
        "visibility_raw",
        "is_pattern_instance",
    ),
    "MateEntity": ("resolution_status",),
    "SketchInfo": ("text_segment_count",),
    "DrawingSheet": ("source",),
}

# The nine new `$defs` of `contracts/README.md`: one cut-list model, eight drawing models.
NEW_MODELS: tuple[str, ...] = (
    "CutListItem",
    "DrawingRecord",
    "DrawingSheetRecord",
    "DrawingView",
    "DisplayDimensionRecord",
    "DrawingAnnotation",
    "DrawingNote",
    "RevisionTable",
    "RevisionTableRow",
)

# The seven records of section 4 that carry a package id AND a persistent-reference pair.
IDENTIFIED_RECORDS: dict[str, str] = {
    "CutListItem": "cut",
    "DrawingSheetRecord": "dsh",
    "DrawingView": "dvw",
    "DisplayDimensionRecord": "ddm",
    "DrawingAnnotation": "dan",
    "DrawingNote": "dnt",
    "RevisionTable": "drv",
}

# Section 5: the twenty-one new gap entity kinds, each with a producing condition in a row
# of the contract.
NEW_GAP_ENTITY_KINDS: tuple[str, ...] = (
    "assembly_exploded",
    "rebuild_error_count",
    "mass_override",
    "component_transparency",
    "component_visibility",
    "component_pattern",
    "mate_entity_reference",
    "sketch_text",
    "cut_list_folder",
    "cut_list_body_count",
    "cut_list_exclusion",
    "drawing_sheet",
    "drawing_sheet_views",
    "drawing_view",
    "drawing_referenced_document",
    "dimension_override",
    "dimension_unit",
    "annotation_identity",
    "annotation_dangling",
    "note_text",
    "revision_table_read",
)

NEW_PACKAGE_ARRAYS: tuple[str, ...] = ("cut_list_items", "drawing_records")


# --- builders ------------------------------------------------------------------------


def build_document(**overrides: Any) -> Document:
    fields: dict[str, Any] = {
        "document_id": "doc:1",
        "kind": "assembly",
        "file_name": "cover-assy.SLDASM",
        "path": "native/cover-assy.SLDASM",
        "configurations": ["Default"],
        "active_configuration": "Default",
        "custom_properties": {},
        "config_properties": {},
        "material": None,
        "mass": None,
    }
    fields.update(overrides)
    return Document(**fields)


def build_component(**overrides: Any) -> ComponentInstance:
    fields: dict[str, Any] = {
        "id": "cmp:0001",
        "persist_ref": persist_ref("cmp:0001"),
        "persist_ref_scope": "doc:1",
        "name": "housing-1",
        "document_id": "doc:2",
        "parent_id": None,
        "referenced_configuration": "Default",
        "transform": [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        "suppression": "resolved",
        "is_fixed": True,
        "pattern_id": None,
        "is_toolbox": False,
        "full_path": "housing-1",
    }
    fields.update(overrides)
    return ComponentInstance(**fields)


def build_sketch(**overrides: Any) -> SketchInfo:
    fields: dict[str, Any] = {"raw_status": 1, "consumer_ids": []}
    fields.update(overrides)
    return SketchInfo(**fields)


def build_drawing_sheet(**overrides: Any) -> DrawingSheet:
    fields: dict[str, Any] = {
        "document_id": "doc:3",
        "sheet_name": "Sheet1",
        "page": 1,
        "scale": "1:1",
        "units": "mm",
        "general_notes": [],
        "dimensions": [],
        "views": [],
        "parse_status": "text",
        "parser": "pymupdf",
    }
    fields.update(overrides)
    return DrawingSheet(**fields)


def build_cut_list_item(**overrides: Any) -> CutListItem:
    fields: dict[str, Any] = {
        "id": "cut:0001",
        "document_id": "doc:2",
        "configuration": "Default",
        "folder_name": "Cut-List-Item1",
        "folder_type_name": "CutListFolder",
        "name": "Tube 40 x 40 x 3",
    }
    fields.update(overrides)
    return CutListItem(**fields)


def build_note(**overrides: Any) -> DrawingNote:
    fields: dict[str, Any] = {"id": "dnt:0001", "owner_id": "dvw:0001", "text": "SEE SHEET 2"}
    fields.update(overrides)
    return DrawingNote(**fields)


def build_annotation(**overrides: Any) -> DrawingAnnotation:
    fields: dict[str, Any] = {
        "id": "dan:0001",
        "owner_id": "dvw:0001",
        "name": "Note1",
        "type_raw": 6,
        "is_dangling": False,
    }
    fields.update(overrides)
    return DrawingAnnotation(**fields)


def build_dimension(**overrides: Any) -> DisplayDimensionRecord:
    fields: dict[str, Any] = {
        "id": "ddm:0001",
        "view_id": "dvw:0001",
        "name": "D1@Sketch1",
        "dimension_type_raw": 2,
        "is_overridden": False,
        "override_value": None,
        "value": Quantity(value=40.0, unit="mm"),
    }
    fields.update(overrides)
    return DisplayDimensionRecord(**fields)


def build_revision_table(**overrides: Any) -> RevisionTable:
    fields: dict[str, Any] = {
        "id": "drv:0001",
        "sheet_id": "dsh:0001",
        "current_revision_raw": "B",
        "row_count": 2,
        "column_count": 3,
        "rows": [
            RevisionTableRow(index=0, cells=["ZONE", "REV", "DESCRIPTION"], is_header=True),
            RevisionTableRow(index=1, cells=["A1", "B", "Released"], is_header=False),
        ],
    }
    fields.update(overrides)
    return RevisionTable(**fields)


def build_view(**overrides: Any) -> DrawingView:
    fields: dict[str, Any] = {
        "id": "dvw:0001",
        "sheet_id": "dsh:0001",
        "name": "Drawing View1",
        "view_type_raw": 1,
        "referenced_document_id": "doc:2",
        "referenced_model_path": "native/housing.SLDPRT",
        "display_dimensions": [build_dimension()],
        "annotations": [build_annotation()],
        "notes": [build_note()],
    }
    fields.update(overrides)
    return DrawingView(**fields)


def build_sheet_record(**overrides: Any) -> DrawingSheetRecord:
    fields: dict[str, Any] = {
        "id": "dsh:0001",
        "name": "Sheet1",
        "index": 0,
        "sheet_format_name": "A3 - Landscape",
        "was_active": True,
        "views": [build_view()],
        "revision_tables": [build_revision_table()],
    }
    fields.update(overrides)
    return DrawingSheetRecord(**fields)


def build_drawing_record(**overrides: Any) -> DrawingRecord:
    fields: dict[str, Any] = {
        "document_id": "doc:3",
        "active_sheet_name": "Sheet1",
        "sheets": [build_sheet_record()],
    }
    fields.update(overrides)
    return DrawingRecord(**fields)


def build_extractor(**overrides: Any) -> ExtractorInfo:
    fields: dict[str, Any] = {
        "name": "SwReview.Extractor",
        "version": "0.1.0",
        "sw_version": None,
        "machine": "test",
    }
    fields.update(overrides)
    return ExtractorInfo(**fields)


def standards_package() -> EvidencePackage:
    """A package carrying every kind of evidence this feature adds."""
    return build_package(
        extractor=build_extractor(profile="standards"),
        cut_list_items=[build_cut_list_item()],
        drawing_records=[build_drawing_record()],
    )


def contract_validator() -> Draft202012Validator:
    return Draft202012Validator(
        load_contract("ir.schema.json"),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def defs() -> dict[str, Any]:
    return export_schema()["$defs"]


# --- 1. the version bump --------------------------------------------------------------


def test_the_bump_is_a_minor_one() -> None:
    """Every addition in this feature is optional, so the major does not move."""
    assert SCHEMA_VERSION == "1.4.0"
    assert build_package().schema_version == "1.4.0"


def test_a_one_three_zero_package_still_loads_with_the_new_fields_defaulted() -> None:
    payload = json.loads(build_package().model_dump_json())
    payload["schema_version"] = "1.3.0"

    package = EvidencePackage.model_validate_json(json.dumps(payload))

    assert package.schema_version == "1.3.0"
    assert package.cut_list_items == []
    assert package.drawing_records == []
    assert package.documents[0].is_exploded is None
    assert package.components[0].visibility_raw is None


def test_the_schema_major_gate_is_unchanged() -> None:
    payload = json.loads(build_package().model_dump_json())
    payload["schema_version"] = "2.0.0"

    with pytest.raises(UnsupportedSchemaVersionError):
        EvidencePackage.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("fixture", GOLDEN_FIXTURE_DIRS, ids=lambda path: path.name)
def test_every_shipped_golden_fixture_still_loads_and_carries_none_of_it(
    fixture: Path,
) -> None:
    """Every fixture in the tree predates 1.4.0. One that no longer loaded would be a
    major bump wearing a minor's number (SC-004)."""
    text = (fixture / "package.json").read_text(encoding="utf-8")

    package = EvidencePackage.model_validate_json(text)

    assert package.cut_list_items == []
    assert package.drawing_records == []
    assert all(sheet.source is None for sheet in package.drawings)


# --- 2. fields on existing models: type and null rule ---------------------------------


def test_document_carries_the_four_new_reads() -> None:
    document = build_document(
        is_exploded=True,
        rebuild_error_count=3,
        mass_overridden=False,
        material_configuration="Default",
    )

    assert document.is_exploded is True
    assert document.rebuild_error_count == 3
    assert document.mass_overridden is False
    assert document.material_configuration == "Default"


def test_the_four_document_reads_default_to_unknown() -> None:
    """A part or a drawing is never exploded and has no material configuration, and that
    absence is null - not `False` and not the empty string."""
    document = build_document(kind="part")

    assert document.is_exploded is None
    assert document.rebuild_error_count is None
    assert document.mass_overridden is None
    assert document.material_configuration is None


def test_a_material_configuration_survives_a_null_material() -> None:
    """"No material in configuration X" and "no material, configuration unknown" are
    different facts, so the configuration is present whenever the read was attempted."""
    document = build_document(kind="part", material=None, material_configuration="Heavy")

    assert document.material is None
    assert document.material_configuration == "Heavy"


def test_a_negative_rebuild_error_count_is_rejected() -> None:
    """Unknown is null; a count is a count."""
    with pytest.raises(ValidationError):
        build_document(rebuild_error_count=-1)


def test_component_carries_the_four_new_reads() -> None:
    component = build_component(
        transparency_raw=0.75,
        has_appearance_override=True,
        visibility_raw=0,
        is_pattern_instance=True,
    )

    assert component.transparency_raw == pytest.approx(0.75)
    assert component.has_appearance_override is True
    assert component.visibility_raw == 0
    assert component.is_pattern_instance is True


def test_the_four_component_reads_default_to_unknown() -> None:
    component = build_component()

    assert component.transparency_raw is None
    assert component.has_appearance_override is None
    assert component.visibility_raw is None
    assert component.is_pattern_instance is None


@pytest.mark.parametrize("raw", [-1, 0, 1])
def test_visibility_is_recorded_verbatim_and_classified_nowhere_here(raw: int) -> None:
    """`swComponentVisibilityState_e` hidden/visible/unknown is 0/1/-1; the extractor
    records the number and Python names it, so no value is refused here."""
    assert build_component(visibility_raw=raw).visibility_raw == raw


@pytest.mark.parametrize("status", ["resolved", "unresolved", "unknown"])
def test_a_mate_entity_records_its_resolution(status: str) -> None:
    resolved = MateEntity(
        component_id="cmp:0001",
        persist_ref=None,
        entity_kind="face",
        resolution_status=status,
    )

    assert resolved.resolution_status == status


def test_a_mate_entity_written_before_one_four_zero_has_no_resolution() -> None:
    entity = MateEntity(component_id="cmp:0001", persist_ref=None, entity_kind="face")

    assert entity.resolution_status is None


def test_an_unknown_mate_entity_resolution_is_refused() -> None:
    """Three outcomes plus "written before 1.4.0"; a fourth word is a status no reader has
    a rule for."""
    with pytest.raises(ValidationError):
        MateEntity(
            component_id="cmp:0001",
            persist_ref=None,
            entity_kind="face",
            resolution_status="dangling",
        )


def test_a_sketch_records_its_text_segment_count() -> None:
    assert build_sketch().text_segment_count is None
    assert build_sketch(text_segment_count=0).text_segment_count == 0
    assert build_sketch(text_segment_count=4).text_segment_count == 4


def test_a_negative_text_segment_count_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_sketch(text_segment_count=-1)


@pytest.mark.parametrize("source", ["native", "pdf_ingest", None])
def test_the_pdf_ingest_sheet_records_its_source(source: str | None) -> None:
    assert build_drawing_sheet(source=source).source == source


def test_a_sheet_written_before_the_stamp_records_no_source() -> None:
    """Null is "source not recorded", which the four drawing checks read exactly as they
    read `pdf_ingest`."""
    assert build_drawing_sheet().source is None


def test_an_unknown_sheet_source_is_refused() -> None:
    with pytest.raises(ValidationError):
        build_drawing_sheet(source="scanned")


# --- 3. the widened profile enum ------------------------------------------------------


def test_the_profile_enum_admits_standards() -> None:
    assert build_extractor(profile="standards").profile == "standards"


@pytest.mark.parametrize("value", ["standards_check", "STANDARDS", "release", "", None])
def test_the_profile_enum_stays_closed(value: object) -> None:
    """A free string would let a package name a profile no reader has a rule for; a
    pre-1.4.0 reader refuses a `standards` package outright, which is the point."""
    with pytest.raises(ValidationError):
        build_extractor(profile=value)


def test_the_generated_schema_lists_the_three_profiles() -> None:
    profile = defs()["ExtractorInfo"]["properties"]["profile"]

    assert sorted(profile["enum"]) == ["full", "model_check", "standards"]


# --- 4. the new models validate -------------------------------------------------------


def test_a_cut_list_item_validates() -> None:
    item = build_cut_list_item(body_count=2, excluded_from_cut_list=False)

    assert item.document_id == "doc:2"
    assert item.configuration == "Default"
    assert item.folder_type_name == "CutListFolder"
    assert item.body_count == 2
    assert item.excluded_from_cut_list is False


def test_a_cut_list_item_leaves_the_unreadable_reads_unknown() -> None:
    """`body_count` and `excluded_from_cut_list` are null plus a gap when unreadable; a
    zero body count is a measurement, and means a folder SOLIDWORKS does not display."""
    item = build_cut_list_item()

    assert item.body_count is None
    assert item.excluded_from_cut_list is None
    assert build_cut_list_item(body_count=0).body_count == 0


def test_the_whole_drawing_record_tree_validates() -> None:
    record = build_drawing_record()
    sheet = record.sheets[0]
    view = sheet.views[0]

    assert record.source == "native"
    assert record.active_sheet_name == "Sheet1"
    assert sheet.source == "native"
    assert sheet.was_active is True
    assert sheet.index == 0
    assert sheet.sheet_format_name == "A3 - Landscape"
    assert view.view_type_raw == 1
    assert view.referenced_document_id == "doc:2"
    assert view.referenced_model_path == "native/housing.SLDPRT"
    assert [dimension.name for dimension in view.display_dimensions] == ["D1@Sketch1"]
    assert [annotation.type_raw for annotation in view.annotations] == [6]
    assert [note.text for note in view.notes] == ["SEE SHEET 2"]
    assert sheet.revision_tables[0].current_revision_raw == "B"


def test_a_referenced_model_path_survives_an_unloaded_reference() -> None:
    """It is what lets the `drawing_referenced_document` gap name the model that was not
    loaded (FR-025)."""
    view = build_view(referenced_document_id=None, referenced_model_path="V:/lib/bracket.SLDPRT")

    assert view.referenced_document_id is None
    assert view.referenced_model_path == "V:/lib/bracket.SLDPRT"


def test_a_sheet_whose_views_failed_to_enumerate_carries_no_views() -> None:
    sheet = build_sheet_record(views=[], revision_tables=[])

    assert sheet.views == []
    assert sheet.revision_tables == []


def test_an_active_sheet_name_may_be_unknown() -> None:
    assert build_drawing_record(active_sheet_name=None).active_sheet_name is None


def test_the_whole_package_round_trips_through_json() -> None:
    package = standards_package()

    restored = EvidencePackage.model_validate_json(package.model_dump_json())

    assert restored == package


def test_the_package_validates_against_the_committed_contract() -> None:
    """The committed contract is what the C# extractor validates against."""
    sample = standards_package().model_dump(mode="json")

    errors = sorted(
        contract_validator().iter_errors(sample), key=lambda error: list(error.absolute_path)
    )

    assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]


def test_the_nine_new_defs_are_in_the_generated_schema() -> None:
    generated = defs()

    assert [name for name in NEW_MODELS if name not in generated] == []


def test_an_unknown_member_on_a_new_record_is_forbidden() -> None:
    payload = json.loads(standards_package().model_dump_json())
    payload["cut_list_items"][0]["weight_kg"] = 4.2

    with pytest.raises(ValidationError):
        EvidencePackage.model_validate_json(json.dumps(payload))


# --- 5. identity: the id prefixes and the persistent-reference pair --------------------


@pytest.mark.parametrize(
    ("builder", "prefix"),
    [
        (build_cut_list_item, "cut"),
        (build_sheet_record, "dsh"),
        (build_view, "dvw"),
        (build_dimension, "ddm"),
        (build_annotation, "dan"),
        (build_note, "dnt"),
        (build_revision_table, "drv"),
    ],
    ids=list(IDENTIFIED_RECORDS),
)
def test_each_identified_record_carries_its_own_id_prefix(builder: Any, prefix: str) -> None:
    assert builder().id.startswith(f"{prefix}:")

    with pytest.raises(ValidationError):
        builder(id="xyz:0001")

    with pytest.raises(ValidationError):
        builder(id=f"{prefix}:1")


@pytest.mark.parametrize(
    "builder",
    [
        build_cut_list_item,
        build_sheet_record,
        build_view,
        build_dimension,
        build_annotation,
        build_note,
        build_revision_table,
    ],
    ids=list(IDENTIFIED_RECORDS),
)
def test_each_identified_record_carries_a_persistent_reference_pair(builder: Any) -> None:
    record = builder(persist_ref=persist_ref("seed"), persist_ref_scope="doc:3")

    assert record.persist_ref == persist_ref("seed")
    assert record.persist_ref_scope == "doc:3"


@pytest.mark.parametrize(
    "builder",
    [
        build_cut_list_item,
        build_sheet_record,
        build_view,
        build_dimension,
        build_annotation,
        build_note,
        build_revision_table,
    ],
    ids=list(IDENTIFIED_RECORDS),
)
def test_a_null_persistent_reference_is_legal_and_leaves_the_id_as_the_identity(
    builder: Any,
) -> None:
    """Section 4: a null `persist_ref` is the statement FR-026 requires - the `id` is a
    within-dump identity, so the page renders no Show control for that subject and a
    waiver fingerprints the record's content rather than its number."""
    record = builder()

    assert record.persist_ref is None
    assert record.persist_ref_scope is None


@pytest.mark.parametrize("model", [DrawingRecord, RevisionTableRow])
def test_the_two_keyed_records_carry_neither_an_id_nor_a_persistent_reference(
    model: Any,
) -> None:
    """A `DrawingRecord` is keyed by its `document_id` and a `RevisionTableRow` by its
    `index` inside its table, so neither needs a package id of its own (section 4)."""
    assert "id" not in model.model_fields
    assert "persist_ref" not in model.model_fields
    assert "persist_ref_scope" not in model.model_fields


def test_a_drawing_record_is_keyed_by_its_document() -> None:
    assert build_drawing_record().document_id == "doc:3"


def test_a_revision_table_row_is_keyed_by_its_index() -> None:
    assert build_revision_table().rows[1].index == 1


# --- 6. the dimension value union -----------------------------------------------------


def test_a_length_dimension_carries_a_quantity() -> None:
    record = build_dimension(
        is_overridden=True,
        override_value=Quantity(value=40.0, unit="mm"),
        value=Quantity(value=38.5, unit="mm"),
    )

    assert isinstance(record.override_value, Quantity)
    assert isinstance(record.value, Quantity)


def test_an_angular_dimension_carries_an_angle() -> None:
    record = build_dimension(
        dimension_type_raw=3,
        is_overridden=True,
        override_value=Angle(value=45.0, unit="deg"),
        value=Angle(value=44.5, unit="deg"),
    )

    assert isinstance(record.override_value, Angle)
    assert isinstance(record.value, Angle)


@pytest.mark.parametrize("unit", ["deg", "rad"])
def test_a_quantity_cannot_carry_an_angular_dimension(unit: str) -> None:
    """`Quantity` carries a `LengthUnit` only, which is why the two value fields are a
    union and not a `Quantity`: an angular value inside a `Quantity` fails validation on
    both sides rather than being rendered as a length - the macro's own bug (difference
    p)."""
    with pytest.raises(ValidationError):
        Quantity(value=45.0, unit=unit)


@pytest.mark.parametrize("unit", ["deg", "rad"])
def test_an_angular_value_parses_as_an_angle_and_never_as_a_quantity(unit: str) -> None:
    payload = json.loads(build_dimension().model_dump_json())
    payload["dimension_type_raw"] = 3
    payload["value"] = {"value": 45.0, "unit": unit}

    record = DisplayDimensionRecord.model_validate_json(json.dumps(payload))

    assert record.value == Angle(value=45.0, unit=unit)


def test_a_dimension_whose_unit_could_not_be_determined_reports_no_value() -> None:
    """A number with a guessed unit is worse than no number: both value fields are null
    plus a `dimension_unit` gap, and the check reports that dimension unresolved."""
    record = build_dimension(is_overridden=True, override_value=None, value=None)

    assert record.override_value is None
    assert record.value is None


def test_a_dimension_whose_override_could_not_be_read_is_unknown() -> None:
    assert build_dimension(is_overridden=None).is_overridden is None


# --- 7. an empty revision cell is not an unread one -----------------------------------


def test_an_empty_revision_cell_is_the_empty_string_and_an_unread_one_is_null() -> None:
    """An empty revision cell is a real mismatch; a cell that could not be read is not."""
    row = RevisionTableRow(index=2, cells=["A1", "", None], is_header=False)

    assert row.cells == ["A1", "", None]
    assert row.cells[1] == ""
    assert row.cells[2] is None


def test_a_revision_table_that_could_not_be_cast_carries_no_rows() -> None:
    table = build_revision_table(row_count=None, column_count=None, rows=[])

    assert table.row_count is None
    assert table.column_count is None
    assert table.rows == []


def test_a_current_revision_is_recorded_verbatim_including_the_empty_string() -> None:
    """The macro's author found this empty under the vault and parsed the table instead;
    both readings are kept and the check names both with their source (RK-4)."""
    assert build_revision_table(current_revision_raw="").current_revision_raw == ""
    assert build_revision_table(current_revision_raw=None).current_revision_raw is None


def test_a_header_row_is_the_extractors_reading_and_may_be_unknown() -> None:
    assert RevisionTableRow(index=0, cells=[]).is_header is None


# --- 8. the additivity rule, measured -------------------------------------------------


@pytest.mark.parametrize(
    ("model_name", "field_name"),
    [
        (model_name, field_name)
        for model_name, field_names in NEW_FIELDS_ON_EXISTING_MODELS.items()
        for field_name in field_names
    ],
    ids=[
        f"{model_name}.{field_name}"
        for model_name, field_names in NEW_FIELDS_ON_EXISTING_MODELS.items()
        for field_name in field_names
    ],
)
def test_every_new_field_on_an_existing_model_is_optional(
    model_name: str, field_name: str
) -> None:
    schema = defs()[model_name]

    assert field_name in schema["properties"]
    assert "default" in schema["properties"][field_name]
    assert field_name not in schema.get("required", [])


@pytest.mark.parametrize("array", NEW_PACKAGE_ARRAYS)
def test_every_new_package_array_is_optional(array: str) -> None:
    schema = export_schema()

    assert array in schema["properties"]
    assert array not in schema.get("required", [])


def test_a_package_carrying_none_of_this_evidence_writes_none_of_it() -> None:
    """The additivity rule's whole point: a 1.3.0-shaped package serializes to the bytes
    the 1.3.0 build wrote apart from its version string, so the shipped goldens stay
    byte-identical (SC-004)."""
    written = json.loads(build_package().model_dump_json())

    assert "cut_list_items" not in written
    assert "drawing_records" not in written
    for key in NEW_FIELDS_ON_EXISTING_MODELS["Document"]:
        assert key not in written["documents"][0]
    for key in NEW_FIELDS_ON_EXISTING_MODELS["ComponentInstance"]:
        assert key not in written["components"][0]


def test_a_pdf_sheet_without_a_source_writes_no_source() -> None:
    assert "source" not in json.loads(build_drawing_sheet().model_dump_json())


def test_an_unset_mate_entity_resolution_is_left_out() -> None:
    entity = MateEntity(component_id="cmp:0001", persist_ref=None, entity_kind="face")

    assert "resolution_status" not in json.loads(entity.model_dump_json())


def test_an_unset_sketch_text_count_is_left_out() -> None:
    assert "text_segment_count" not in json.loads(build_sketch().model_dump_json())


def test_an_existing_null_is_still_written() -> None:
    """Only this feature's own additions are omitted. Every field a 1.3.0 package already
    carried keeps its null, because dropping those would change the shape feature 001's
    readers were written against."""
    written = json.loads(build_package().model_dump_json())

    assert written["documents"][0]["material"] is None
    assert written["components"][0]["pattern_id"] is None
    assert written["components"][0]["constrained_status_raw"] is None


def test_the_new_records_omit_their_own_unknowns() -> None:
    item = json.loads(build_cut_list_item().model_dump_json())

    assert item == {
        "id": "cut:0001",
        "document_id": "doc:2",
        "configuration": "Default",
        "folder_name": "Cut-List-Item1",
        "folder_type_name": "CutListFolder",
        "name": "Tube 40 x 40 x 3",
    }


def test_an_empty_list_on_a_new_record_is_left_out() -> None:
    sheet = json.loads(build_sheet_record(views=[], revision_tables=[]).model_dump_json())

    assert "views" not in sheet
    assert "revision_tables" not in sheet


def test_the_omitted_members_round_trip_to_the_same_package() -> None:
    package = standards_package()

    assert EvidencePackage.model_validate_json(package.model_dump_json()) == package


# --- 9. the new gap entity kinds ------------------------------------------------------


@pytest.mark.parametrize("entity_kind", NEW_GAP_ENTITY_KINDS)
def test_every_new_gap_entity_kind_validates(entity_kind: str) -> None:
    gap = Gap(
        kind="not_extracted",
        entity_kind=entity_kind,
        entity_id="doc:1",
        reason=f"{entity_kind} could not be read",
        error=None,
    )
    package = build_package(gaps=[gap])

    errors = sorted(
        contract_validator().iter_errors(package.model_dump(mode="json")),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == []


def test_the_twenty_one_new_kinds_are_distinct() -> None:
    """Section 5 names twenty-one; a duplicate would mean two producing conditions wearing
    one name."""
    assert len(set(NEW_GAP_ENTITY_KINDS)) == len(NEW_GAP_ENTITY_KINDS) == 21
