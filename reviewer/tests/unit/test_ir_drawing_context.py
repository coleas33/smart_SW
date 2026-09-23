"""Unit tests for the IR 1.6.0 additions: the drawing context (feature 011 T005).

`specs/011-drawing-context/data-model.md` sections 1 and 2 are the normative list: new optional
members on five of feature 006's drawing models (`DrawingRecord`, `DrawingSheetRecord`,
`DrawingView`, `DisplayDimensionRecord`, `DrawingAnnotation`), four new models (`AttachedFace`,
`DrawingTable`, `BomRow`, `DrawingCandidate`) and one new package array
(`EvidencePackage.drawing_candidates`).

Every one of them obeys feature 006's additivity rule, and this file measures it:

- optional, with a default, and absent from `required` in both schemas;
- **omitted when null** (a list, when it carries no rows), so every package written before
  1.6.0 - every golden, every fixture - re-serializes without gaining a member;
- 1.5.0 still loads, and 2.0.0 still raises.

Three fields carry a rule of their own, stated where the data model states it: a table is
never a revision table (type 3 has its own list since feature 006), a sheet's scale is both
numbers or neither, and `opened_by_review` is written only as `true` - the product opened the
drawing at the engineer's confirmation (owner, 2026-09-23, research R5 Q2) - and never as
`false`, because an absent member already says "the review did not open it".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from swreview.ir.models import (
    SCHEMA_VERSION,
    AttachedFace,
    BomRow,
    DisplayDimensionRecord,
    DrawingAnnotation,
    DrawingCandidate,
    DrawingRecord,
    DrawingSheetRecord,
    DrawingTable,
    DrawingView,
    EvidencePackage,
    GtolFrame,
    Quantity,
    RevisionTableRow,
    SourceRef,
    Tolerance,
    UnsupportedSchemaVersionError,
)
from swreview.ir.schema import export_schema
from tests.support.contracts import load_contract
from tests.support.packages import build_package, persist_ref

TESTS_DIR = Path(__file__).resolve().parents[1]

COMMITTED_PACKAGES: list[Path] = sorted(TESTS_DIR.rglob("package.json"))
"""Every package committed under `reviewer/tests/`. None carries a 1.6.0 member: each was
written before the bump, whatever version it declares."""

NEW_MODELS: tuple[str, ...] = ("AttachedFace", "DrawingTable", "BomRow", "DrawingCandidate")

NEW_FIELDS: dict[type[BaseModel], dict[str, Any]] = {
    DrawingRecord: {
        "is_detailing_mode": False,
        "length_unit_raw": 0,
        "dimension_precision_raw": 2,
        "units_decimal_places_raw": 2,
        "tolerance_precision_raw": 3,
        "drafting_standard_name": "FICTIONAL-STANDARD",
        "opened_by_review": True,
    },
    DrawingSheetRecord: {
        "sheet_format_path": "C:\\Fictional\\formats\\fictional-format-a.slddrt",
        "first_angle": False,
    },
    DrawingView: {
        "referenced_configuration": "Default",
        "is_model_out_of_date": False,
        "is_model_loaded": True,
        "scale_decimal": 0.5,
        "orientation_name": "*Front",
    },
    DisplayDimensionRecord: {
        "text_prefix": "<MOD-DIAM>",
        "text_suffix": "",
        "text_above": "",
        "text_below": "THRU",
        "precision_raw": 2,
        "tolerance_precision_raw": 3,
        "uses_document_precision": False,
        "units_raw": 0,
        "uses_document_units": True,
        "tolerance_type_raw": 2,
        "fit_hole_class": "H7",
        "fit_shaft_class": "g6",
        "is_reference": False,
        "driven_state_raw": 1,
        "is_hole_callout": True,
    },
    DrawingAnnotation: {
        "datum_identifier_raw": "A",
        "datum_label": "B",
        "surface_finish_symbol_raw": 1,
    },
}
"""The scalar additions, each with a value that is not its default."""

NEW_LISTS: dict[type[BaseModel], tuple[str, ...]] = {
    DrawingSheetRecord: ("tables",),
    DisplayDimensionRecord: ("hole_callout_variables_raw", "attached_faces"),
    DrawingAnnotation: ("gtol_frames", "surface_finish_texts_raw", "attached_faces"),
}

NEW_MEMBER_NAMES: frozenset[str] = frozenset(
    {name for fields in NEW_FIELDS.values() for name in fields}
    | {name for names in NEW_LISTS.values() for name in names}
    | {"drawing_candidates", "tolerance", "scale_numerator", "scale_denominator"}
)


# --- builders ---------------------------------------------------------------------------


def build_attached_face(**overrides: Any) -> AttachedFace:
    fields: dict[str, Any] = {
        "persist_ref": persist_ref("fac:0001"),
        "scope": "doc:2",
        "via": "face",
    }
    fields.update(overrides)
    return AttachedFace(**fields)


def build_bom_row(**overrides: Any) -> BomRow:
    fields: dict[str, Any] = {
        "index": 1,
        "document_ids": ["doc:2"],
        "unresolved_paths": ["C:\\Fictional\\library\\fictional-washer.SLDPRT"],
    }
    fields.update(overrides)
    return BomRow(**fields)


def build_table(**overrides: Any) -> DrawingTable:
    fields: dict[str, Any] = {
        "id": "dtb:0001",
        "sheet_id": "dsh:0001",
        "owner_view_id": "dvw:0001",
        "table_type_raw": 2,
        "title": "FICTIONAL PARTS LIST",
        "row_count": 2,
        "column_count": 2,
        "rows": [
            RevisionTableRow(index=0, cells=["ITEM", "QTY"]),
            RevisionTableRow(index=1, cells=["1", None]),
        ],
        "bom_rows": [build_bom_row()],
        "persist_ref": persist_ref("dtb:0001"),
        "persist_ref_scope": "doc:3",
    }
    fields.update(overrides)
    return DrawingTable(**fields)


def build_candidate(**overrides: Any) -> DrawingCandidate:
    fields: dict[str, Any] = {
        "document_id": "doc:2",
        "path": "C:\\Fictional\\designs\\fictional-block.SLDDRW",
        "reason": "same_name_beside_model",
    }
    fields.update(overrides)
    return DrawingCandidate(**fields)


def build_tolerance() -> Tolerance:
    return Tolerance(
        kind="bilateral",
        upper=Quantity(value=0.05, unit="mm"),
        lower=Quantity(value=0.0, unit="mm"),
        source=SourceRef(document_id="doc:3", sheet="Sheet1", annotation="ddm:0001"),
    )


def build_dimension(**overrides: Any) -> DisplayDimensionRecord:
    fields: dict[str, Any] = {
        "id": "ddm:0001",
        "view_id": "dvw:0001",
        "name": "D1@Sketch1@fictional-plate.SLDPRT",
        "dimension_type_raw": 6,
        "is_overridden": False,
        "value": Quantity(value=3.1, unit="mm"),
        **NEW_FIELDS[DisplayDimensionRecord],
        "tolerance": build_tolerance(),
        "hole_callout_variables_raw": ["<hw-diameter>=3.10", ""],
        "attached_faces": [build_attached_face(), build_attached_face(
            persist_ref=persist_ref("fac:0002"), via="edge")],
    }
    fields.update(overrides)
    return DisplayDimensionRecord(**fields)


def build_annotation(**overrides: Any) -> DrawingAnnotation:
    fields: dict[str, Any] = {
        "id": "dan:0001",
        "owner_id": "dvw:0001",
        "name": "GTol1",
        "type_raw": 5,
        "is_dangling": False,
        **NEW_FIELDS[DrawingAnnotation],
        "gtol_frames": [GtolFrame(number=1, symbols_raw=["<GTOL-POSI>"], values_raw=["0.05"])],
        "surface_finish_texts_raw": ["1.6", ""],
        "attached_faces": [build_attached_face()],
    }
    fields.update(overrides)
    return DrawingAnnotation(**fields)


def build_view(**overrides: Any) -> DrawingView:
    fields: dict[str, Any] = {
        "id": "dvw:0001",
        "sheet_id": "dsh:0001",
        "name": "Drawing View1",
        "view_type_raw": 7,
        "referenced_document_id": "doc:2",
        "referenced_model_path": "C:\\Fictional\\designs\\fictional-plate.SLDPRT",
        **NEW_FIELDS[DrawingView],
        "display_dimensions": [build_dimension()],
        "annotations": [build_annotation()],
    }
    fields.update(overrides)
    return DrawingView(**fields)


def build_sheet(**overrides: Any) -> DrawingSheetRecord:
    fields: dict[str, Any] = {
        "id": "dsh:0001",
        "name": "Sheet1",
        "index": 0,
        "sheet_format_name": "FICTIONAL-FORMAT-A",
        "was_active": True,
        **NEW_FIELDS[DrawingSheetRecord],
        "scale_numerator": 1.0,
        "scale_denominator": 2.0,
        "views": [build_view()],
        "tables": [build_table()],
    }
    fields.update(overrides)
    return DrawingSheetRecord(**fields)


def build_drawing(**overrides: Any) -> DrawingRecord:
    fields: dict[str, Any] = {
        "document_id": "doc:3",
        "active_sheet_name": "Sheet1",
        **NEW_FIELDS[DrawingRecord],
        "sheets": [build_sheet()],
    }
    fields.update(overrides)
    return DrawingRecord(**fields)


def drawing_package() -> EvidencePackage:
    """A 1.6.0 package carrying every member this feature adds."""
    return build_package(drawing_records=[build_drawing()], drawing_candidates=[build_candidate()])


def json_paths(node: Any, prefix: str = "") -> set[str]:
    """Every key in `node` as a dotted path, list indices elided."""
    paths: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}"
            paths.add(path)
            paths |= json_paths(value, path)
    elif isinstance(node, list):
        for item in node:
            paths |= json_paths(item, f"{prefix}[]")
    return paths


def schemas() -> list[dict[str, Any]]:
    return [export_schema(), load_contract("ir.schema.json")]


# --- 1. the version bump ------------------------------------------------------------------


def test_the_bump_is_a_minor_one() -> None:
    """Every addition is optional, so the major does not move (FR-048)."""
    assert SCHEMA_VERSION == "1.6.0"
    assert build_package().schema_version == "1.6.0"


def test_a_one_five_zero_package_still_loads_with_the_new_members_absent() -> None:
    legacy = build_package(
        schema_version="1.5.0",
        drawing_records=[DrawingRecord(document_id="doc:3", sheets=[])],
    )
    package = EvidencePackage.model_validate_json(legacy.model_dump_json())

    assert package.schema_version == "1.5.0"
    assert package.drawing_candidates == []
    record = package.drawing_records[0]
    assert record.is_detailing_mode is None
    assert record.opened_by_review is None
    assert record.length_unit_raw is None


def test_the_schema_major_gate_is_unchanged() -> None:
    payload = json.loads(build_package().model_dump_json())
    payload["schema_version"] = "2.0.0"

    with pytest.raises(UnsupportedSchemaVersionError):
        EvidencePackage.model_validate_json(json.dumps(payload))


# --- 2. every committed package re-serializes without gaining or losing a member --------


def test_the_committed_packages_are_found() -> None:
    assert len(COMMITTED_PACKAGES) >= 40, COMMITTED_PACKAGES


@pytest.mark.parametrize(
    "package_file",
    COMMITTED_PACKAGES,
    ids=[path.parent.relative_to(TESTS_DIR).as_posix() for path in COMMITTED_PACKAGES],
)
def test_a_committed_package_round_trips_without_gaining_or_losing_a_member(
    package_file: Path,
) -> None:
    """Additivity measured on the files themselves: a 1.6.0 member that appeared here would be
    a field serialized when it says nothing, which would move every package on disk at once."""
    on_disk = json.loads(package_file.read_bytes())
    package = EvidencePackage.model_validate_json(package_file.read_bytes())
    written = json.loads(package.model_dump_json())

    added = json_paths(written) - json_paths(on_disk)
    dropped = json_paths(on_disk) - json_paths(written)

    assert not dropped, f"{package_file} lost {sorted(dropped)}"
    leaked = {path for path in added if path.rsplit(".", 1)[-1] in NEW_MEMBER_NAMES}
    assert not leaked, f"{package_file} gained 1.6.0 members {sorted(leaked)}"


def test_a_package_carrying_none_of_this_evidence_writes_none_of_it() -> None:
    record = DrawingRecord(
        document_id="doc:3",
        sheets=[
            DrawingSheetRecord(
                id="dsh:0001",
                name="Sheet1",
                index=0,
                was_active=True,
                views=[
                    DrawingView(
                        id="dvw:0001",
                        sheet_id="dsh:0001",
                        display_dimensions=[
                            DisplayDimensionRecord(id="ddm:0001", view_id="dvw:0001")
                        ],
                        annotations=[DrawingAnnotation(id="dan:0001", owner_id="dvw:0001")],
                    )
                ],
            )
        ],
    )
    written = json.loads(build_package(drawing_records=[record]).model_dump_json())

    assert "drawing_candidates" not in written
    paths = json_paths(written["drawing_records"], ".drawing_records")
    leaked = {path for path in paths if path.rsplit(".", 1)[-1] in NEW_MEMBER_NAMES}
    assert leaked == set()


# --- 3. the scalar additions on feature 006's models ---------------------------------------

SCALAR_CASES = [(model, name) for model, fields in NEW_FIELDS.items() for name in fields]


def minimal(model: type[BaseModel]) -> BaseModel:
    """The smallest valid instance of one of the five extended models."""
    required: dict[type[BaseModel], dict[str, Any]] = {
        DrawingRecord: {"document_id": "doc:3"},
        DrawingSheetRecord: {"id": "dsh:0001", "name": "Sheet1", "index": 0, "was_active": True},
        DrawingView: {"id": "dvw:0001", "sheet_id": "dsh:0001"},
        DisplayDimensionRecord: {"id": "ddm:0001", "view_id": "dvw:0001"},
        DrawingAnnotation: {"id": "dan:0001", "owner_id": "dvw:0001"},
    }
    return model(**required[model])


@pytest.mark.parametrize(
    ("model", "name"), SCALAR_CASES, ids=[f"{m.__name__}.{n}" for m, n in SCALAR_CASES]
)
def test_each_scalar_is_optional_and_omitted_when_null(model: type[BaseModel], name: str) -> None:
    instance = minimal(model)

    assert getattr(instance, name) is None
    assert name not in json.loads(instance.model_dump_json())


@pytest.mark.parametrize(
    ("model", "name"), SCALAR_CASES, ids=[f"{m.__name__}.{n}" for m, n in SCALAR_CASES]
)
def test_each_scalar_is_written_when_read(model: type[BaseModel], name: str) -> None:
    value = NEW_FIELDS[model][name]
    instance = model.model_validate({**minimal(model).model_dump(), name: value})

    assert json.loads(instance.model_dump_json())[name] == value


@pytest.mark.parametrize(
    ("model", "name"), SCALAR_CASES, ids=[f"{m.__name__}.{n}" for m, n in SCALAR_CASES]
)
def test_each_scalar_is_absent_from_required(model: type[BaseModel], name: str) -> None:
    for schema in schemas():
        definition = schema["$defs"][model.__name__]
        assert name in definition["properties"]
        assert name not in definition.get("required", [])


LIST_CASES = [(model, name) for model, names in NEW_LISTS.items() for name in names]


@pytest.mark.parametrize(
    ("model", "name"), LIST_CASES, ids=[f"{m.__name__}.{n}" for m, n in LIST_CASES]
)
def test_each_list_defaults_empty_and_is_omitted_when_empty(
    model: type[BaseModel], name: str
) -> None:
    instance = minimal(model)

    assert getattr(instance, name) == []
    assert name not in json.loads(instance.model_dump_json())
    for schema in schemas():
        assert name not in schema["$defs"][model.__name__].get("required", [])


def test_the_text_parts_keep_an_empty_string() -> None:
    """Verbatim, empty string kept: an empty suffix is what the drawing says, a null one is
    a part that could not be read (data-model.md section 1)."""
    written = json.loads(build_dimension(text_suffix="", text_prefix=None).model_dump_json())

    assert written["text_suffix"] == ""
    assert "text_prefix" not in written


def test_the_verbatim_lists_keep_an_empty_slot() -> None:
    dimension = json.loads(build_dimension().model_dump_json())
    annotation = json.loads(build_annotation().model_dump_json())

    assert dimension["hole_callout_variables_raw"] == ["<hw-diameter>=3.10", ""]
    assert annotation["surface_finish_texts_raw"] == ["1.6", ""]


def test_a_dimension_tolerance_is_the_ir_tolerance() -> None:
    written = json.loads(build_dimension().model_dump_json())

    assert written["tolerance"]["kind"] == "bilateral"
    assert written["tolerance"]["upper"] == {"value": 0.05, "unit": "mm"}


def test_a_drawing_gtol_reuses_feature_010s_frame() -> None:
    annotation = build_annotation()

    assert isinstance(annotation.gtol_frames[0], GtolFrame)
    assert annotation.gtol_frames[0].values_raw == ["0.05"]


# --- 4. the rules of their own ------------------------------------------------------------


def test_opened_by_review_is_written_only_as_true() -> None:
    assert json.loads(build_drawing().model_dump_json())["opened_by_review"] is True
    unset = json.loads(build_drawing(opened_by_review=None).model_dump_json())
    assert "opened_by_review" not in unset
    with pytest.raises(ValidationError, match="opened_by_review"):
        build_drawing(opened_by_review=False)


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    [(1.0, None), (None, 2.0)],
    ids=["numerator-only", "denominator-only"],
)
def test_a_sheet_scale_is_both_numbers_or_neither(
    numerator: float | None, denominator: float | None
) -> None:
    with pytest.raises(ValidationError, match="scale"):
        build_sheet(scale_numerator=numerator, scale_denominator=denominator)


def test_a_sheet_with_no_scale_writes_neither_number() -> None:
    sheet = build_sheet(scale_numerator=None, scale_denominator=None)
    written = json.loads(sheet.model_dump_json())

    assert "scale_numerator" not in written
    assert "scale_denominator" not in written


def test_a_revision_table_is_never_a_drawing_table() -> None:
    """Type 3 goes to `revision_tables`, exactly as feature 006 records it."""
    with pytest.raises(ValidationError, match="revision"):
        build_table(table_type_raw=3)


def test_an_unread_table_type_is_allowed() -> None:
    assert build_table(table_type_raw=None).table_type_raw is None


@pytest.mark.parametrize("bad_id", ["dtb:1", "dtb:12a4", "tab:0001", "drv:0001"])
def test_a_table_id_follows_its_pattern(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        build_table(id=bad_id)


@pytest.mark.parametrize("field", ["row_count", "column_count"])
def test_a_table_count_is_never_negative(field: str) -> None:
    with pytest.raises(ValidationError):
        build_table(**{field: -1})


def test_a_table_omits_what_it_does_not_have() -> None:
    written = json.loads(
        build_table(
            title=None, row_count=None, column_count=None, rows=[], bom_rows=[],
            persist_ref=None, persist_ref_scope=None,
        ).model_dump_json()
    )

    assert set(written) == {"id", "sheet_id", "owner_view_id", "table_type_raw"}


def test_a_null_cell_is_unread_and_an_empty_one_is_empty() -> None:
    written = json.loads(build_table().model_dump_json())

    assert written["rows"][1]["cells"] == ["1", None]


def test_an_attached_face_needs_its_reference_scope_and_route() -> None:
    for missing in ("persist_ref", "scope", "via"):
        payload = json.loads(build_attached_face().model_dump_json())
        del payload[missing]
        with pytest.raises(ValidationError):
            AttachedFace.model_validate(payload)


def test_an_attached_face_reference_is_base64() -> None:
    with pytest.raises(ValidationError):
        build_attached_face(persist_ref="not base64!")


def test_an_attached_face_route_is_face_or_edge() -> None:
    assert build_attached_face(via="edge").via == "edge"
    with pytest.raises(ValidationError):
        build_attached_face(via="vertex")


def test_a_bom_row_keeps_an_unresolved_path_verbatim() -> None:
    written = json.loads(build_bom_row().model_dump_json())

    assert written == {
        "index": 1,
        "document_ids": ["doc:2"],
        "unresolved_paths": ["C:\\Fictional\\library\\fictional-washer.SLDPRT"],
    }


def test_a_bom_row_omits_its_empty_lists() -> None:
    assert json.loads(build_bom_row(document_ids=[], unresolved_paths=[]).model_dump_json()) == {
        "index": 1
    }


def test_a_bom_row_index_is_never_negative() -> None:
    with pytest.raises(ValidationError):
        build_bom_row(index=-1)


def test_a_candidate_reason_is_the_only_rule() -> None:
    with pytest.raises(ValidationError):
        build_candidate(reason="found_in_folder")


def test_a_candidate_needs_its_document_and_path() -> None:
    for missing in ("document_id", "path"):
        payload = json.loads(build_candidate().model_dump_json())
        del payload[missing]
        with pytest.raises(ValidationError):
            DrawingCandidate.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (AttachedFace, lambda: build_attached_face().model_dump(mode="json")),
        (DrawingTable, lambda: build_table().model_dump(mode="json")),
        (BomRow, lambda: build_bom_row().model_dump(mode="json")),
        (DrawingCandidate, lambda: build_candidate().model_dump(mode="json")),
    ],
    ids=list(NEW_MODELS),
)
def test_each_new_model_refuses_an_unknown_field(model: type[BaseModel], payload: Any) -> None:
    data = payload()
    data["fictional_extra"] = 1

    with pytest.raises(ValidationError):
        model.model_validate(data)


# --- 5. the package -----------------------------------------------------------------------


def test_the_package_carries_the_candidates_when_it_has_some() -> None:
    written = json.loads(drawing_package().model_dump_json())

    assert written["drawing_candidates"] == [
        {
            "document_id": "doc:2",
            "path": "C:\\Fictional\\designs\\fictional-block.SLDDRW",
            "reason": "same_name_beside_model",
        }
    ]


def test_a_one_six_zero_package_round_trips() -> None:
    package = drawing_package()

    assert EvidencePackage.model_validate_json(package.model_dump_json()) == package


def test_a_one_six_zero_package_writes_every_member() -> None:
    paths = json_paths(json.loads(drawing_package().model_dump_json()))
    leaves = {path.rsplit(".", 1)[-1] for path in paths}

    assert NEW_MEMBER_NAMES <= leaves, sorted(NEW_MEMBER_NAMES - leaves)


def test_the_package_validates_against_the_committed_contract() -> None:
    schema = load_contract("ir.schema.json")
    instance = json.loads(drawing_package().model_dump_json())

    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=str)

    assert errors == []


def test_the_committed_contract_refuses_a_bad_table_id() -> None:
    schema = load_contract("ir.schema.json")
    instance = json.loads(drawing_package().model_dump_json())
    instance["drawing_records"][0]["sheets"][0]["tables"][0]["id"] = "tab:1"

    assert list(Draft202012Validator(schema).iter_errors(instance))


def test_the_committed_contract_refuses_opened_by_review_false() -> None:
    schema = load_contract("ir.schema.json")
    instance = json.loads(drawing_package().model_dump_json())
    instance["drawing_records"][0]["opened_by_review"] = False

    assert list(Draft202012Validator(schema).iter_errors(instance))


@pytest.mark.parametrize("name", NEW_MODELS)
def test_every_new_model_is_in_the_generated_and_the_committed_schema(name: str) -> None:
    for schema in schemas():
        assert name in schema["$defs"]


def test_the_candidates_array_is_optional() -> None:
    for schema in schemas():
        assert "drawing_candidates" in schema["properties"]
        assert "drawing_candidates" not in schema.get("required", [])


def test_the_design_says_a_drawing_root_has_no_configuration() -> None:
    """`design.active_configuration` is the empty string for a drawing root (contracts/attach.md
    section 2), and the schema says so where a reader looks."""
    for schema in schemas():
        description = schema["$defs"]["Design"]["properties"]["active_configuration"]["description"]
        assert "empty for a drawing root, which has none" in description
