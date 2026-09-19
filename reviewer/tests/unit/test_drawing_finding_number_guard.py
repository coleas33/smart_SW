"""`record_drawing_finding` may not carry a number the drawing does not say (T052, FR-033).

`record_drawing_finding` is the one tool whose finding text is written by the model rather
than computed: the numeric tools take `SourceRef`s and put the calculation's own result in
the finding, but this one takes free prose for `observed` and `requirement` and records it.
So it is the one path on which a number the model invented reaches the report looking
exactly like a number that was read off a sheet.

The guard is a **sixth refusal**, before `build_finding`: every number-like token in
`observed` or `requirement` has to appear in the drawing evidence the citations reach - the
cited sheets' `dimensions[].text_as_read`, their `general_notes`, and the native sheets'
`DrawingNote.text` and annotation text. A token that appears nowhere is refused as an
`error_result` naming the token and the sheets that were searched, which is a result the
model may answer once, never an exception (research R2.13).

**What counts as a number-like token** is the whole of the design, and the two halves of
`contracts/gate.md` section 5's table are both asserted below:

- `0.05`, `12`, `12.5 mm`, `1/4-20` and `±0.1` are values, and a value nothing backs is
  the hallucination this guard exists to catch;
- `F-003`, `cmp:0002`, `dnt:0007`, `Sheet 2` and `2026-09-18` are a finding id, two entity
  ids, a sheet name and a date. Refusing those would make the tool unusable for saying
  where it looked, which is the sentence an engineer most needs.

The package here is this module's own and every string in it is fictional: two ingested
sheets of one drawing, so that citing one sheet does not source the other sheet's numbers,
and one natively dumped drawing, so the note and annotation paths are exercised rather than
assumed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from swreview.ir.models import Dimension as IRDimension
from swreview.ir.models import (
    Document,
    DrawingAnnotation,
    DrawingNote,
    DrawingRecord,
    DrawingSheet,
    DrawingSheetRecord,
    DrawingView,
    EvidencePackage,
    Manifest,
    ManifestEntry,
    Note,
    Quantity,
    SheetView,
    SourceRef,
    Tolerance,
)
from swreview.tools import session
from swreview.tools.context import ToolContext, context_for, use_context
from tests.support.packages import build_manifest

MakePackage = Callable[..., EvidencePackage]

INGESTED = "doc:3"
"""The PDF-ingested drawing: two sheets, each carrying numbers the other does not."""

NATIVE = "doc:4"
"""The natively dumped drawing: one sheet, one view, one note and one annotation."""

FIRST = "Sheet1"
SECOND = "Sheet2"
PLATE = "Plate"

FIRST_SHEET_VALUE = "0.05"
"""On `Sheet1` as a dimension, and on no other sheet."""

SECOND_SHEET_VALUE = "77.70"
GENERAL_NOTE_VALUE = "0.30"
NATIVE_NOTE_VALUE = "0.20"
NATIVE_ANNOTATION_VALUE = "9.90"


def mm(value: float) -> Quantity:
    return Quantity(value=value, unit="mm")


def source(sheet: str, annotation: str) -> SourceRef:
    return SourceRef(document_id=INGESTED, sheet=sheet, annotation=annotation)


def dimension(sheet: str, annotation: str, nominal: float, text: str) -> IRDimension:
    return IRDimension(
        nominal=mm(nominal),
        tolerance=Tolerance(kind="none", upper=None, lower=None, source=source(sheet, annotation)),
        source=source(sheet, annotation),
        text_as_read=text,
    )


def ingested_sheet(sheet: str, dimensions: list[IRDimension], notes: list[Note]) -> DrawingSheet:
    return DrawingSheet(
        document_id=INGESTED,
        sheet_name=sheet,
        page=1 if sheet == FIRST else 2,
        scale="1:1",
        units="mm",
        general_notes=notes,
        dimensions=dimensions,
        views=[SheetView(name="TOP", bbox=[0.0, 0.0, 100.0, 100.0])],
        parse_status="text",
        parser="pymupdf",
    )


def general_note() -> Note:
    return Note(
        text=f"Unless noted, general tolerance is ±{GENERAL_NOTE_VALUE}",
        source=source(FIRST, "NOTE-1"),
        kind="general_tolerance",
    )


def native_drawing() -> DrawingRecord:
    view = DrawingView(
        id="dvw:0001",
        sheet_id="dsh:0001",
        name="SECTION B-B",
        notes=[
            DrawingNote(
                id="dnt:0007",
                owner_id="dvw:0001",
                text=f"Break edges {NATIVE_NOTE_VALUE} max",
            )
        ],
        annotations=[
            DrawingAnnotation(
                id="dan:0003",
                owner_id="dvw:0001",
                name=f"DATUM {NATIVE_ANNOTATION_VALUE}",
            )
        ],
    )
    return DrawingRecord(
        document_id=NATIVE,
        active_sheet_name=PLATE,
        sheets=[
            DrawingSheetRecord(id="dsh:0001", name=PLATE, index=0, was_active=True, views=[view])
        ],
    )


def drawing_entry(document_id: str, name: str, method: str) -> ManifestEntry:
    return ManifestEntry(
        document_id=document_id,
        vault_path=f"/Drawings/{name}",
        vault_version=1,
        revision="A",
        configuration="Default",
        local_modified=False,
        export_method=method,  # type: ignore[arg-type]
    )


def drawing_document(document_id: str, name: str, path: str) -> Document:
    return Document(
        document_id=document_id,
        kind="drawing",
        file_name=name,
        path=path,
        configurations=["Default"],
        active_configuration="Default",
        custom_properties={},
        config_properties={},
        material=None,
        mass=None,
    )


def guarded_package(make_package: MakePackage) -> EvidencePackage:
    """The fixture package plus two ingested sheets and one natively dumped drawing."""
    base = make_package()
    return make_package(
        documents=[
            *base.documents,
            drawing_document(INGESTED, "bracket.SLDDRW", "pdf/bracket.pdf"),
            drawing_document(NATIVE, "plate.SLDDRW", "native/plate.SLDDRW"),
        ],
        manifest=Manifest(
            entries=[
                *build_manifest().entries,
                drawing_entry(INGESTED, "bracket.SLDDRW", "pdf"),
                drawing_entry(NATIVE, "plate.SLDDRW", "native"),
            ],
            discrepancies=[],
        ),
        drawings=[
            ingested_sheet(
                FIRST,
                [dimension(FIRST, "DIM-1", 0.05, FIRST_SHEET_VALUE)],
                [general_note()],
            ),
            ingested_sheet(SECOND, [dimension(SECOND, "DIM-2", 77.7, SECOND_SHEET_VALUE)], []),
        ],
        drawing_records=[native_drawing()],
    )


@pytest.fixture
def context(make_package: MakePackage) -> Iterator[ToolContext]:
    tool_context = context_for(guarded_package(make_package))
    with use_context(tool_context):
        yield tool_context


def record(
    observed: str = "the callout states no thread depth",
    requirement: str = "a tapped hole callout states its usable thread depth",
    *,
    document_id: str = INGESTED,
    sheet: str = FIRST,
    refs: list[SourceRef] | None = None,
) -> dict[str, Any]:
    return session.record_drawing_finding(
        document_id=document_id,
        sheet=sheet,
        observed=observed,
        requirement=requirement,
        source_refs=(
            refs if refs is not None else [SourceRef(document_id=document_id, sheet=sheet)]
        ),
        status="suspected",
        recommended_action="state the value on the drawing",
    )


def refusal(result: dict[str, Any]) -> str:
    assert isinstance(result, dict), result
    assert "error" in result, result
    return str(result["error"])


# --- the guard fires, and does not fire ---------------------------------------------------


def test_a_value_no_cited_sheet_carries_is_refused(context: ToolContext) -> None:
    """The worked example of contracts/gate.md section 5: a wall thickness nothing backs."""
    result = record("the wall is 0.05 mm thick", sheet=SECOND)

    message = refusal(result)
    assert "0.05 mm" in message
    assert SECOND in message
    assert context.session.findings == []


def test_the_same_value_is_recorded_when_a_cited_dimension_carries_it(
    context: ToolContext,
) -> None:
    result = record("the wall is 0.05 mm thick", sheet=FIRST)

    assert result["status"] == "recorded"
    assert [finding.observed for finding in context.session.findings] == [
        "the wall is 0.05 mm thick"
    ]


def test_the_refusal_is_a_returned_dict_and_never_a_raise(context: ToolContext) -> None:
    """The model answers an `error_result` once; an exception would end the turn."""
    result = record("the wall is 0.05 mm thick", sheet=SECOND)

    assert isinstance(result, dict)
    assert set(result) == {"error"}


def test_the_refusal_names_every_sheet_it_searched(context: ToolContext) -> None:
    result = record(
        "the wall is 0.05 mm thick",
        sheet=SECOND,
        refs=[
            SourceRef(document_id=INGESTED, sheet=SECOND),
            SourceRef(document_id=NATIVE, sheet=PLATE),
        ],
    )

    message = refusal(result)
    assert f"{INGESTED} sheet {SECOND}" in message
    assert f"{NATIVE} sheet {PLATE}" in message


def test_text_with_no_number_at_all_is_recorded(context: ToolContext) -> None:
    assert record()["status"] == "recorded"


# --- what is number-like, and what is not (contracts/gate.md section 5) -------------------


@pytest.mark.parametrize("token", ["0.05", "12", "12.5 mm", "1/4-20", "±0.1"])
def test_a_number_like_token_no_sheet_carries_is_refused(context: ToolContext, token: str) -> None:
    result = record(f"the drawing calls out {token} at the boss", sheet=SECOND)

    assert token in refusal(result)
    assert context.session.findings == []


@pytest.mark.parametrize("token", ["F-003", "cmp:0002", "dnt:0007", "Sheet 2", "2026-09-18"])
def test_an_id_a_sheet_name_and_a_date_are_not_number_like(
    context: ToolContext, token: str
) -> None:
    """Refusing these would stop the tool saying where it looked or what it answers."""
    result = record(f"the callout at {token} is missing its depth", sheet=SECOND)

    assert result["status"] == "recorded", result


def test_a_standard_reference_is_not_read_as_a_value(context: ToolContext) -> None:
    """`Y14.5` is a standard, not a claim that the drawing says five.

    The narrow identifier rule - a digit only after `-` or `:` - split it and refused a
    finding whose one real number was correct, which is how the rule came to accept any
    letter-led token that goes on to contain a digit."""
    result = record(
        requirement="the callout follows ASME Y14.5 hole callout practice", sheet=SECOND
    )

    assert result["status"] == "recorded", result


@pytest.mark.parametrize("designation", ["M6", "M6x1.0", "ISO-2768", "Y14.5"])
def test_a_letter_led_designation_is_not_read_as_the_numbers_inside_it(
    context: ToolContext, designation: str
) -> None:
    """Thread sizes and standard numbers name a thing, not a measurement."""
    result = record(f"the callout reads {designation} and states no depth", sheet=SECOND)

    assert result["status"] == "recorded", result


def test_a_digit_led_designation_is_guarded_on_the_number_it_starts_with(
    context: ToolContext,
) -> None:
    """The line is drawn at the first character, and it is drawn there deliberately.

    A letter-led token names a thing; a digit-led one opens with a size. `40H7` is a bore
    the drawing has to state somewhere, and a nominal diameter nothing backs is precisely
    the claim this guard exists to stop - so the `40` is checked and the `H7` is not."""
    assert "40" in refusal(record("the bore is called out 40H7", sheet=SECOND))


@pytest.mark.parametrize("written", ["77.7", "77.700", "+77.70", "-77.70", "±77.70"])
def test_a_value_spelled_differently_is_still_the_value_the_sheet_states(
    context: ToolContext, written: str
) -> None:
    """The sheet says `77.70`. Sending the model back to change `77.7` into `77.70` would
    cost a round and improve nothing, so the key is the magnitude, not the spelling."""
    result = record(f"the boss measures {written}", sheet=SECOND)

    assert result["status"] == "recorded", result


def test_a_sheet_with_no_readable_text_sources_nothing(context: ToolContext) -> None:
    """Deliberately strict: a number cannot have been read off a sheet that was not read.

    The finding for an unreadable sheet is `unresolved` and says what is missing, which
    needs no number; one that quoted a value would be quoting something nobody saw."""
    result = record(
        "the sheet is unreadable and the wall appears to be 0.05 mm",
        refs=[SourceRef(document_id=INGESTED, sheet="Sheet9")],
        sheet="Sheet9",
    )

    assert "0.05 mm" in refusal(result)


def test_both_fields_are_guarded(context: ToolContext) -> None:
    """`requirement` states the governing value and is as forgeable as `observed`."""
    result = record(
        observed="the callout states no tolerance",
        requirement="the governing tolerance is 0.44 mm",
        sheet=SECOND,
    )

    assert "0.44 mm" in refusal(result)


def test_a_requirement_value_a_cited_sheet_carries_is_recorded(
    context: ToolContext,
) -> None:
    result = record(
        observed="the callout states no tolerance",
        requirement=f"the governing tolerance is {SECOND_SHEET_VALUE}",
        sheet=SECOND,
    )

    assert result["status"] == "recorded", result


def test_every_unsourced_token_is_named_in_one_refusal(context: ToolContext) -> None:
    """One refusal the model can answer completely, rather than one round trip per token."""
    result = record(
        observed="the boss is 3.14 mm across",
        requirement="it must be 2.72 mm",
        sheet=SECOND,
    )

    message = refusal(result)
    assert "3.14 mm" in message
    assert "2.72 mm" in message


# --- where the evidence is read from ------------------------------------------------------


def test_a_value_only_a_general_note_carries_is_sourced(context: ToolContext) -> None:
    result = record(f"the sheet note allows ±{GENERAL_NOTE_VALUE} and the boss is outside it")

    assert result["status"] == "recorded", result


def test_a_value_only_a_native_note_carries_is_sourced(context: ToolContext) -> None:
    result = record(
        f"the break-edge note says {NATIVE_NOTE_VALUE} and the model does not match it",
        document_id=NATIVE,
        sheet=PLATE,
    )

    assert result["status"] == "recorded", result


def test_a_value_only_a_native_annotation_carries_is_sourced(context: ToolContext) -> None:
    result = record(
        f"the datum is labelled {NATIVE_ANNOTATION_VALUE} and the callout disagrees",
        document_id=NATIVE,
        sheet=PLATE,
    )

    assert result["status"] == "recorded", result


def test_one_sheet_does_not_source_another_sheet_s_numbers(context: ToolContext) -> None:
    """Citing `Sheet1` must not licence a number that only `Sheet2` carries."""
    assert SECOND_SHEET_VALUE in refusal(record(f"it reads {SECOND_SHEET_VALUE}", sheet=FIRST))
    assert record(f"it reads {SECOND_SHEET_VALUE}", sheet=SECOND)["status"] == "recorded"


def test_a_citation_that_names_no_sheet_searches_the_whole_document(
    context: ToolContext,
) -> None:
    """A `page` or `persist_ref` locator reaches the document and cannot be narrowed, so
    every sheet of it is searched rather than none of them."""
    result = record(
        f"it reads {SECOND_SHEET_VALUE}",
        sheet=FIRST,
        refs=[SourceRef(document_id=INGESTED, page=2)],
    )

    assert result["status"] == "recorded", result


def test_a_second_citation_widens_what_is_sourced(context: ToolContext) -> None:
    result = record(
        f"{FIRST_SHEET_VALUE} on one sheet against {SECOND_SHEET_VALUE} on the other",
        sheet=FIRST,
        refs=[
            SourceRef(document_id=INGESTED, sheet=FIRST),
            SourceRef(document_id=INGESTED, sheet=SECOND),
        ],
    )

    assert result["status"] == "recorded", result


# --- the guard's place in the order of refusals -------------------------------------------


def test_the_five_earlier_refusals_still_come_first(context: ToolContext) -> None:
    """The guard is the sixth: an unknown document is still an unknown document, even in a
    call whose prose also carries an unsourced number."""
    result = record("the wall is 0.05 mm thick", document_id="doc:404", sheet=FIRST)

    assert "doc:404" in refusal(result)
    assert "0.05" not in refusal(result)


def test_an_unsourced_number_is_refused_before_a_finding_is_built(
    context: ToolContext,
) -> None:
    """No finding, and no finding id spent: the counter must not advance on a refusal."""
    record("the wall is 0.05 mm thick", sheet=SECOND)
    recorded = record("the wall is 0.05 mm thick", sheet=FIRST)

    assert recorded["finding"]["id"] == "F-001"
    assert [finding.id for finding in context.session.findings] == ["F-001"]
