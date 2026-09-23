"""The model's drawing tools read native sheets, and compute with none before T066 (T036).

`contracts/drawing-source.md` section 2's table is normative. `find_dimensions`,
`get_drawing_sheet` and `refs.resolve_dimension` read the natively dumped sheets through the one
conversion (`drawings/native.py`) beside the PDF-ingested ones, and a native sheet wins over an
ingested sheet of the same name. **Showing a native value is not computing with one**: while
`DRAWING_BINDING_VALIDATED` is false, `resolve_dimension` - the reference every calculating tool
takes - refuses a native dimension with a `LookupError` naming the seat validation, so
`check_fit`, `check_axial_stack` and `check_hole_alignment` return an error result and record no
finding (FR-024, research R2.11). A PDF-ingested reference resolves whatever the switch.

A package with no native sheet returns exactly today's payloads (FR-037): `TODAY` holds each
committed package's digest over the three tools, taken from the tree before the change.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from swreview.drawings import binding
from swreview.drawings.binding import NOT_VALIDATED
from swreview.ir.loader import load_package
from swreview.ir.models import (
    Dimension,
    DrawingSheet,
    EvidencePackage,
    Note,
    Quantity,
    SourceRef,
    Tolerance,
)
from swreview.tools.checks_fastener import check_hole_alignment
from swreview.tools.checks_fit import check_axial_stack, check_fit
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.query import find_dimensions, get_drawing_sheet
from swreview.tools.refs import resolve_dimension
from tests.support.drawings import Attach, DrawingBuilder
from tests.support.mechanical import load_generator

TESTS = Path(__file__).resolve().parents[1]
DRAWINGS = TESTS / "fixtures" / "drawings"
MECHANICAL = TESTS / "fixtures" / "mechanical" / "generate_fixtures.py"

TODAY: dict[str, str] = {
    # sha256[:16] of `payloads(package)` below, before feature 011 T037.
    "fixtures/attention/check-folder": "b6b42268a0ac2058",
    "fixtures/attention/review-folder": "b6b42268a0ac2058",
    "fixtures/mechanical/big-assembly": "f0f1127794eab2bf",
    "fixtures/mechanical/small-assembly": "f224e1a2ddeb9712",
    "fixtures/mechanical/tolerances": "875a581dfd4742fc",
    "fixtures/replay/big-assembly": "6ff073295cf7f7b7",
    "fixtures/replay/small-assembly-a": "ff54b0e544ea751d",
    "fixtures/replay/small-assembly-b": "ff54b0e544ea751d",
    "golden/fixtures/_smoke": "49126b32cbbb2628",
    "golden/fixtures/angle-not-length": "99d9b73128dd823b",
    "golden/fixtures/bracket-assy-interference": "0867b71418afeafd",
    "golden/fixtures/cover-blind-tap": "5f8828844f3d8cf3",
    "golden/fixtures/joint-bottoming": "49126b32cbbb2628",
    "golden/fixtures/joint-ok": "49126b32cbbb2628",
    "golden/fixtures/joint-unsupported": "49126b32cbbb2628",
    "golden/fixtures/mixed-units": "e0c95d9d1db0b529",
    "golden/fixtures/plate-stack": "b073c80e46fe3789",
    "golden/fixtures/remodel-plan/remodel-cycle": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-duplicate-names": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-ordered": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-pinned": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-refusal-3d-interconnect": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-refusal-mesh-body": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-refusal-multibody": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-refusal-rms-folder": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-refusal-sheet-metal": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-refusal-two-signals": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-refusal-weldment": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-reversed": "8b1de92b1250a72d",
    "golden/fixtures/remodel-plan/remodel-unplaceable": "8b1de92b1250a72d",
    "golden/fixtures/rms-assembly": "f6552c0938cf8c9a",
    "golden/fixtures/rms-equations": "00f6fcfe760015f2",
    "golden/fixtures/rms-exceptions": "b6b42268a0ac2058",
    "golden/fixtures/rms-part": "0a20bb5cdededd73",
    "golden/fixtures/shaft-bore": "b3f0fd06c5e859f7",
    "golden/fixtures/standards-drawings/standards-drawings-ingested": "25cecba539f1bdab",
    "golden/fixtures/standards-multiplicity": "0867b71418afeafd",
    "golden/fixtures/thread-mismatch": "49126b32cbbb2628",
    "golden/fixtures/tool-envelope": "49126b32cbbb2628",
}


def payloads(package: EvidencePackage) -> list[Any]:
    """Every answer the three tools give over `package`, in a fixed order."""
    out: list[Any] = []
    with use_context(context_for(package)):
        for document in package.documents:
            out.append(get_drawing_sheet(document.document_id))
            for sheet in package.drawings:
                if sheet.document_id == document.document_id:
                    out.append(get_drawing_sheet(document.document_id, sheet.sheet_name))
            out.append(get_drawing_sheet(document.document_id, "no such sheet"))
            out.append(find_dimensions(document.document_id))
        out.append(find_dimensions())
        out.append(find_dimensions(None, "[0-9]"))
        for sheet in package.drawings:
            for dimension in sheet.dimensions:
                try:
                    out.append(resolve_dimension(package, dimension.source).model_dump(mode="json"))
                except LookupError as error:
                    out.append(str(error))
    return out


@pytest.fixture
def validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binding, "DRAWING_BINDING_VALIDATED", True)


@pytest.fixture(scope="module")
def plate() -> EvidencePackage:
    return load_package(DRAWINGS / "plate-drawing").package


def run(package: EvidencePackage) -> ToolContext:
    return context_for(package)


def ingested(document_id: str, name: str, *annotations: str) -> DrawingSheet:
    """A PDF-ingested sheet of `document_id`, one untoleranced dimension per annotation."""
    dimensions = [
        Dimension(
            nominal=Quantity(value=3.0, unit="mm"),
            tolerance=Tolerance(
                kind="none",
                upper=None,
                lower=None,
                source=SourceRef(document_id=document_id, sheet=name, annotation=label),
            ),
            source=SourceRef(document_id=document_id, sheet=name, annotation=label),
            text_as_read="3.0",
        )
        for label in annotations
    ]
    return DrawingSheet(
        document_id=document_id,
        sheet_name=name,
        page=1,
        scale=None,
        units="mm",
        general_notes=[
            Note(text="FICTIONAL NOTE", kind="other",
                 source=SourceRef(document_id=document_id, sheet=name))
        ],
        dimensions=dimensions,
        views=[],
        parse_status="text",
        parser="fictional",
        source="pdf_ingest",
    )


def with_ingested(package: EvidencePackage, *sheets: DrawingSheet) -> EvidencePackage:
    return package.model_copy(update={"drawings": [*package.drawings, *sheets]})


def native_ref(annotation: str, document: str = "doc:0006", sheet: str = "Sheet1") -> SourceRef:
    return SourceRef(document_id=document, sheet=sheet, annotation=annotation)


def fit_package() -> EvidencePackage:
    """The tolerances assembly with one drawing showing the plate's dowel hole and the pin."""
    builder = DrawingBuilder(load_generator(MECHANICAL).build_tolerances_assembly().package)
    record = builder.drawing(builder.drawing_document("FICT-TULMVEN-0000"))
    sheet = builder.sheet(record, "Sheet1")
    hole = builder.view(sheet, "Drawing View1", references="doc:0002")
    pin = builder.view(sheet, "Drawing View2", references="doc:0004")
    builder.dimension(hole, "KALOMIR91@FICT-TULMKALO-3001", value_mm=3.0,
                      tolerance=("bilateral", 0.010, 0.0), tolerance_type_raw=2,
                      attached=[Attach("fac:0001")])
    builder.dimension(pin, "KALOMIR92@FICT-PIN-3X12-3003", value_mm=3.0,
                      tolerance=("bilateral", 0.0, -0.006), tolerance_type_raw=2,
                      attached=[Attach("fac:0006")])
    builder.dimension(pin, "KALOMIR93@FICT-PIN-3X12-3003", value_mm=12.0, type_raw=2, prefix="",
                      tolerance=("symmetric", 0.1, None), tolerance_type_raw=4)
    return builder.build()


# --- 1. find_dimensions ---------------------------------------------------------------------------


def test_find_dimensions_returns_every_native_dimension_that_converts(
    plate: EvidencePackage,
) -> None:
    with use_context(run(plate)):
        found = find_dimensions()

    assert isinstance(found, list)
    assert [entry["source"]["annotation"] for entry in found] == [
        f"ddm:{number:04d}" for number in (1, 2, 3, 4, 5, 6, 7, 9, 10, 11)
    ], "ddm:0008 names no unit and does not convert"
    first = found[0]
    assert first["document_id"] == "doc:0006" and first["sheet_name"] == "Sheet1"
    assert first["text_as_read"] == "<MOD-DIAM>3.00 +0.010/0.000 (composed)"
    assert first["tolerance"]["kind"] == "bilateral"


def test_find_dimensions_filters_by_document_regex_and_view_name(plate: EvidencePackage) -> None:
    with use_context(run(plate)):
        drawing_b = find_dimensions("doc:0007")
        four_fifty = find_dimensions(None, r"4\.50")
        stale = find_dimensions(None, None, "Drawing View2")
        both = find_dimensions("doc:0006", r"4\.50", "Drawing View1")

    assert [entry["source"]["annotation"] for entry in drawing_b] == ["ddm:0010", "ddm:0011"]
    assert [entry["source"]["annotation"] for entry in four_fifty] == [
        "ddm:0003", "ddm:0006", "ddm:0011"
    ]
    assert [entry["source"]["annotation"] for entry in stale] == ["ddm:0011"]
    assert [entry["source"]["annotation"] for entry in both] == ["ddm:0003", "ddm:0006"]


def test_a_native_sheet_hides_an_ingested_sheet_of_the_same_name_from_find(
    plate: EvidencePackage,
) -> None:
    package = with_ingested(
        plate, ingested("doc:0006", "Sheet1", "PDF-A"), ingested("doc:0006", "Page2", "PDF-B")
    )

    with use_context(run(package)):
        found = find_dimensions("doc:0006")

    labels = [entry["source"]["annotation"] for entry in found]
    assert "PDF-A" not in labels, "the native Sheet1 wins over the ingested Sheet1"
    assert labels[0] == "PDF-B"


# --- 2. get_drawing_sheet -------------------------------------------------------------------------


def test_get_drawing_sheet_returns_the_native_sheet(plate: EvidencePackage) -> None:
    with use_context(run(plate)):
        sheet = get_drawing_sheet("doc:0006")

    assert sheet["source"] == "native"
    assert sheet["document_id"] == "doc:0006"
    assert sheet["name"] == "Sheet1"
    assert sheet["available_sheets"] == [{"name": "Sheet1", "source": "native"}]
    assert sheet["reason"] is None
    views = {view["name"]: view for view in sheet["views"]}
    assert len(views["Drawing View1"]["display_dimensions"]) == 9
    assert len(views["Sheet Format1"]["notes"]) == 3
    assert len(sheet["tables"]) == 3 and len(sheet["revision_tables"]) == 1


def test_a_native_sheet_is_preferred_over_an_ingested_one_of_the_same_name(
    plate: EvidencePackage,
) -> None:
    package = with_ingested(
        plate, ingested("doc:0006", "Sheet1", "PDF-A"), ingested("doc:0006", "Page2", "PDF-B")
    )

    with use_context(run(package)):
        native = get_drawing_sheet("doc:0006", "Sheet1")
        page = get_drawing_sheet("doc:0006", "Page2")
        missing = get_drawing_sheet("doc:0006", "Sheet9")

    listed = [
        {"name": "Sheet1", "source": "native"},
        {"name": "Sheet1", "source": "pdf_ingest"},
        {"name": "Page2", "source": "pdf_ingest"},
    ]
    assert native["source"] == "native" and native["available_sheets"] == listed
    assert page["sheet_name"] == "Page2" and page["source"] == "pdf_ingest"
    assert page["available_sheets"] == listed
    assert "error" in missing and "Sheet9" in missing["error"]
    assert "'source': 'native'" in missing["error"]


def test_a_sheet_whose_views_could_not_be_read_says_why() -> None:
    root = load_package(DRAWINGS / "drawing-root").package
    document = root.design.root_assembly_document_id

    with use_context(run(root)):
        third = get_drawing_sheet(document, "Sheet3")
        first = get_drawing_sheet(document)

    assert "views" not in third, "an empty list is omitted, as the IR writes it"
    assert "not the active sheet" in third["reason"]
    assert first["name"] == "Sheet1" and first["reason"] is None
    assert [item["name"] for item in first["available_sheets"]] == ["Sheet1", "Sheet2", "Sheet3"]


def test_a_document_with_no_sheet_of_either_kind_is_refused_as_today(
    plate: EvidencePackage,
) -> None:
    with use_context(run(plate)):
        refused = get_drawing_sheet("doc:0002")

    assert refused == {"error": "document 'doc:0002' has no extracted drawing sheets"}


# --- 3. resolve_dimension and the calculating tools -----------------------------------------------


def test_with_the_switch_off_a_native_reference_is_refused_naming_the_seat_validation(
    plate: EvidencePackage,
) -> None:
    with pytest.raises(LookupError) as raised:
        resolve_dimension(plate, native_ref("ddm:0001"))

    assert NOT_VALIDATED in str(raised.value)
    assert "ddm:0001" in str(raised.value)


@pytest.mark.usefixtures("validated")
def test_with_the_switch_set_a_native_reference_resolves(plate: EvidencePackage) -> None:
    dimension = resolve_dimension(plate, native_ref("ddm:0001"))

    assert dimension.source.annotation == "ddm:0001"
    assert dimension.tolerance.kind == "bilateral"


@pytest.mark.usefixtures("validated")
def test_a_native_dimension_with_no_value_is_refused_naming_why(plate: EvidencePackage) -> None:
    with pytest.raises(LookupError) as raised:
        resolve_dimension(plate, native_ref("ddm:0008"))

    assert "names no unit" in str(raised.value)


@pytest.mark.parametrize("switch", [False, True])
def test_a_pdf_ingested_reference_resolves_whatever_the_switch(
    monkeypatch: pytest.MonkeyPatch, switch: bool
) -> None:
    monkeypatch.setattr(binding, "DRAWING_BINDING_VALIDATED", switch)
    package = load_package(TESTS / "golden" / "fixtures" / "shaft-bore").package

    dimension = resolve_dimension(
        package, SourceRef(document_id="doc:3", sheet="Sheet1", annotation="DIM-BORE")
    )

    assert dimension.text_as_read.startswith("40 H7")


@pytest.mark.usefixtures("validated")
def test_resolve_dimension_still_refuses_none_and_two(plate: EvidencePackage) -> None:
    with pytest.raises(LookupError, match="no drawing dimension"):
        resolve_dimension(plate, native_ref("ddm:9999"))
    record = plate.drawing_records[0]
    twin = record.sheets[0].model_copy(update={"id": "dsh:0099", "index": 1})
    doubled = plate.model_copy(
        update={
            "drawing_records": [
                record.model_copy(update={"sheets": [*record.sheets, twin]}),
                *plate.drawing_records[1:],
            ]
        }
    )
    with pytest.raises(LookupError, match="ambiguous"):
        resolve_dimension(doubled, native_ref("ddm:0001"))


def test_with_the_switch_off_check_fit_refuses_native_references_and_records_nothing() -> None:
    context = run(fit_package())
    with use_context(context):
        result = check_fit(native_ref("ddm:0001"), native_ref("ddm:0002"))

    assert "error" in result and NOT_VALIDATED in result["error"]
    assert context.session is not None and context.session.findings == []


def test_with_the_switch_off_check_axial_stack_refuses_a_native_reference() -> None:
    context = run(fit_package())
    with use_context(context):
        result = check_axial_stack([native_ref("ddm:0003")], [1])

    assert "error" in result and NOT_VALIDATED in result["error"]
    assert context.session is not None and context.session.findings == []


def test_with_the_switch_off_check_hole_alignment_refuses_a_native_tolerance() -> None:
    context = run(fit_package())
    with use_context(context):
        result = check_hole_alignment("hol:0001", "hol:0003", native_ref("ddm:0001"))

    assert "error" in result and NOT_VALIDATED in result["error"]
    assert context.session is not None and context.session.findings == []


@pytest.mark.usefixtures("validated")
def test_with_the_switch_set_check_fit_computes_with_native_dimensions_citing_them() -> None:
    context = run(fit_package())
    with use_context(context):
        result = check_fit(native_ref("ddm:0001"), native_ref("ddm:0002"))

    assert result.get("status") == "recorded", result
    assert context.session is not None
    [finding] = context.session.findings
    cited = {(item.document_id, item.sheet, item.annotation) for item in finding.drawing_locations}
    assert cited == {("doc:0006", "Sheet1", "ddm:0001"), ("doc:0006", "Sheet1", "ddm:0002")}


# --- 4. a package with no native sheet is served exactly as before ---------------------------


def committed() -> list[str]:
    names = []
    for path in sorted(TESTS.rglob("package.json")):
        relative = path.parent.relative_to(TESTS).as_posix()
        if relative.startswith("fixtures/drawings/"):
            continue
        package = load_package(path.parent).package
        if not any(record.sheets for record in package.drawing_records):
            names.append(relative)
    return names


def test_every_committed_package_without_native_sheets_is_pinned() -> None:
    assert committed() == sorted(TODAY)


@pytest.mark.parametrize("switch", [False, True])
@pytest.mark.parametrize("relative", sorted(TODAY))
def test_the_three_tools_answer_byte_for_byte_as_before(
    monkeypatch: pytest.MonkeyPatch, relative: str, switch: bool
) -> None:
    monkeypatch.setattr(binding, "DRAWING_BINDING_VALIDATED", switch)
    package = load_package(TESTS / relative).package

    text = json.dumps(payloads(package), ensure_ascii=False, sort_keys=False)

    assert hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] == TODAY[relative]
