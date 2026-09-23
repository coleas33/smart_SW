"""A drawing root at IR 1.6.0 is graded exactly as feature 006 grades one (feature 011 T017).

Feature 011 makes a drawing extractable on its own (User Story 1, FR-001, FR-004): the attach
accepts it and the Standards tab grades it live. The reasoning side has nothing to change for
that - feature 006's four drawing checks were written for a drawing root and have only ever
run over fakes - so this file is a test only, and it pins two things over the committed
`tests/fixtures/drawings/drawing-root/` package (`contracts/fixtures.md` section 2):

- `run_standards_check` grades the drawing root, the four `standards.drawing.*` checks run,
  every document the drawing references is graded once, and the sheet whose views could not
  be enumerated is unresolved naming its gap - the promise feature 006 made;
- **the 1.6.0 members change no grading.** The same package with every member feature 011
  added stripped back to its 1.4.0 shape grades to the same checks, buckets, findings and
  coverage, so the new evidence is read by nobody in `checks/standards/` and the Standards
  tab's sixteen checks and verdict are exactly feature 006's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.standards.run import StandardsCheckRun, run_standards_check
from swreview.ir.loader import load_package, save_package
from swreview.ir.models import (
    DisplayDimensionRecord,
    DrawingAnnotation,
    DrawingRecord,
    DrawingSheetRecord,
    DrawingView,
    EvidencePackage,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DRAWING_ROOT = FIXTURES / "drawings" / "drawing-root"
PROFILE_PATH = FIXTURES / "standards" / "profile-a.yaml"

DRAWING_CHECKS = (
    "standards.drawing.dimensions_not_overridden",
    "standards.drawing.annotations_not_dangling",
    "standards.drawing.revision_matches",
    "standards.drawing.no_itar_statement",
)

# --- the 1.4.0 shape of the same package --------------------------------------------------

_DRAWING_1_6 = {
    "is_detailing_mode": None,
    "length_unit_raw": None,
    "dimension_precision_raw": None,
    "units_decimal_places_raw": None,
    "tolerance_precision_raw": None,
    "drafting_standard_name": None,
    "opened_by_review": None,
}
_SHEET_1_6 = {
    "sheet_format_path": None,
    "scale_numerator": None,
    "scale_denominator": None,
    "first_angle": None,
    "tables": [],
}
_VIEW_1_6 = {
    "referenced_configuration": None,
    "is_model_out_of_date": None,
    "is_model_loaded": None,
    "scale_decimal": None,
    "orientation_name": None,
}
_DIMENSION_1_6 = {
    "text_prefix": None,
    "text_suffix": None,
    "text_above": None,
    "text_below": None,
    "precision_raw": None,
    "tolerance_precision_raw": None,
    "uses_document_precision": None,
    "units_raw": None,
    "uses_document_units": None,
    "tolerance": None,
    "tolerance_type_raw": None,
    "fit_hole_class": None,
    "fit_shaft_class": None,
    "is_reference": None,
    "driven_state_raw": None,
    "is_hole_callout": None,
    "hole_callout_variables_raw": [],
    "attached_faces": [],
}
_ANNOTATION_1_6 = {
    "gtol_frames": [],
    "datum_identifier_raw": None,
    "datum_label": None,
    "surface_finish_symbol_raw": None,
    "surface_finish_texts_raw": [],
    "attached_faces": [],
}


def _dimension(record: DisplayDimensionRecord) -> DisplayDimensionRecord:
    return record.model_copy(update=_DIMENSION_1_6)


def _annotation(record: DrawingAnnotation) -> DrawingAnnotation:
    return record.model_copy(update=_ANNOTATION_1_6)


def _view(view: DrawingView) -> DrawingView:
    return view.model_copy(
        update={
            **_VIEW_1_6,
            "display_dimensions": [_dimension(item) for item in view.display_dimensions],
            "annotations": [_annotation(item) for item in view.annotations],
        }
    )


def _sheet(sheet: DrawingSheetRecord) -> DrawingSheetRecord:
    return sheet.model_copy(update={**_SHEET_1_6, "views": [_view(item) for item in sheet.views]})


def _record(record: DrawingRecord) -> DrawingRecord:
    return record.model_copy(
        update={**_DRAWING_1_6, "sheets": [_sheet(item) for item in record.sheets]}
    )


def as_1_4_0(package: EvidencePackage) -> EvidencePackage:
    """`package` with every member feature 011 added left out, at schema 1.4.0."""
    return package.model_copy(
        update={
            "schema_version": "1.4.0",
            "drawing_records": [_record(record) for record in package.drawing_records],
            "drawing_candidates": [],
        }
    )


# --- the runs --------------------------------------------------------------------------------


def _grade(package: EvidencePackage, tmp_path: Path, name: str) -> StandardsCheckRun:
    directory = tmp_path / name / "package"
    save_package(package, directory)
    return run_standards_check(directory, PROFILE_PATH, tmp_path / name / "run")


@pytest.fixture(scope="module")
def fixture_package() -> EvidencePackage:
    return load_package(DRAWING_ROOT).package


@pytest.fixture(scope="module")
def graded(tmp_path_factory: pytest.TempPathFactory) -> StandardsCheckRun:
    """The committed fixture graded in place: read, never written."""
    out = tmp_path_factory.mktemp("drawing-root") / "run"
    return run_standards_check(DRAWING_ROOT, PROFILE_PATH, out)


@pytest.fixture(scope="module")
def graded_1_4_0(
    fixture_package: EvidencePackage, tmp_path_factory: pytest.TempPathFactory
) -> StandardsCheckRun:
    return _grade(as_1_4_0(fixture_package), tmp_path_factory.mktemp("as-1-4-0"), "run")


def _check_rows(run: StandardsCheckRun) -> dict[str, dict[str, Any]]:
    return {row["check"]: row for row in run.checks}


def _normalized_findings(run: StandardsCheckRun) -> list[dict[str, Any]]:
    """The findings with what differs by run alone - timestamps and paths - left out."""
    return [
        {key: value for key, value in finding.items() if key not in ("created_at",)}
        for finding in run.findings
    ]


# --- 1. the drawing root is graded (FR-001, FR-004) ----------------------------------------


def test_the_fixture_is_a_1_6_0_drawing_root(fixture_package: EvidencePackage) -> None:
    root = fixture_package.design.root_assembly_document_id
    kinds = {document.document_id: document.kind for document in fixture_package.documents}
    assert fixture_package.schema_version == "1.6.0"
    assert kinds[root] == "drawing"
    assert fixture_package.design.active_configuration == ""
    assert [record.document_id for record in fixture_package.drawing_records] == [root]


def test_the_four_drawing_checks_grade_the_drawing_root(graded: StandardsCheckRun) -> None:
    rows = _check_rows(graded)
    for check in DRAWING_CHECKS:
        assert rows[check]["worst_bucket"] not in (None, "out_of_scope"), check


def test_every_referenced_document_is_graded_once(
    graded: StandardsCheckRun, fixture_package: EvidencePackage
) -> None:
    root = fixture_package.design.root_assembly_document_id
    assert len(graded.documents) == len(set(graded.documents))
    assert graded.documents[0] == root
    assert graded.document_reached_by[root] == "root"
    assert set(graded.documents) == {document.document_id for document in fixture_package.documents}
    assert "drawing_reference" in set(graded.document_reached_by.values())


def test_the_sheet_whose_views_could_not_be_enumerated_is_unresolved_naming_its_gap(
    graded: StandardsCheckRun, fixture_package: EvidencePackage
) -> None:
    (record,) = fixture_package.drawing_records
    third = next(sheet for sheet in record.sheets if sheet.name == "Sheet3")
    gap = next(
        gap
        for gap in fixture_package.gaps
        if gap.entity_id == third.id and gap.entity_kind == "drawing_sheet_views"
    )
    unresolved = [
        item
        for item in graded.coverage
        if item["check"] in DRAWING_CHECKS and item["bucket"] == "unresolved"
    ]
    assert unresolved, "no drawing check is unresolved for the sheet it could not read"
    assert any("Sheet3" in json.dumps(item) for item in unresolved)
    assert any(gap.reason in json.dumps(item) or "drawing_sheet_views" in json.dumps(item)
               for item in unresolved)


def test_the_committed_fixture_is_read_and_never_written(graded: StandardsCheckRun) -> None:
    assert graded.package_dir == DRAWING_ROOT.resolve()
    assert sorted(path.name for path in DRAWING_ROOT.iterdir()) == ["package.json"]


# --- 2. the 1.6.0 members change no grading ------------------------------------------------


def test_the_stripped_package_is_the_1_4_0_shape(fixture_package: EvidencePackage) -> None:
    stripped = as_1_4_0(fixture_package).model_dump(mode="json")
    records = json.dumps(stripped["drawing_records"])
    for member in (*_DRAWING_1_6, *_SHEET_1_6, *_VIEW_1_6, *_DIMENSION_1_6, *_ANNOTATION_1_6):
        assert f'"{member}"' not in records, member
    assert "drawing_candidates" not in stripped
    # ...and the fixture it was stripped from does carry them, so the comparison below is
    # between two different packages, not one package twice.
    carried = json.dumps(fixture_package.model_dump(mode="json")["drawing_records"])
    for member in ("is_detailing_mode", "tables", "referenced_configuration", "attached_faces",
                   "gtol_frames", "hole_callout_variables_raw"):
        assert f'"{member}"' in carried, member


def test_the_same_checks_land_in_the_same_buckets(
    graded: StandardsCheckRun, graded_1_4_0: StandardsCheckRun
) -> None:
    assert graded.checks == graded_1_4_0.checks


def test_the_same_verdict_documents_and_findings(
    graded: StandardsCheckRun, graded_1_4_0: StandardsCheckRun
) -> None:
    assert graded.verdict == graded_1_4_0.verdict
    assert graded.documents == graded_1_4_0.documents
    assert graded.document_reached_by == graded_1_4_0.document_reached_by
    assert _normalized_findings(graded) == _normalized_findings(graded_1_4_0)
    assert graded.subjects == graded_1_4_0.subjects


def test_the_same_coverage(graded: StandardsCheckRun, graded_1_4_0: StandardsCheckRun) -> None:
    assert graded.coverage == graded_1_4_0.coverage
