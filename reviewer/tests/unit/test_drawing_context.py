"""The drawing check's coverage and questions, as pure functions (feature 011 T045).

`contracts/questions.md` sections 3 and 4 are normative. `run_drawing_context(package)` writes
one `drawing.context` coverage item per reviewed part or assembly document, in traversal (id)
order - `checked` when a usable view of a drawing shows it, `unresolved` when drawings show it
and none of their views is usable, `skipped` when none does - and specifies at most four
questions: one about every same-name candidate beside a reviewed file, and one per document
that two or more drawings show usably, three at most. A configuration mismatch or an
out-of-date view is coverage, never a question: an answer cannot change what was extracted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.checks.drawing_context import (
    CANDIDATE_CONFIRM,
    CANDIDATE_OPTIONS,
    CANDIDATES_WHY,
    CONTEXT_CHECK,
    GOVERNING_WHY,
    QuestionSpec,
    run_drawing_context,
)
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import EvidenceRequest
from tests.support.drawings import DrawingBuilder
from tests.support.mechanical import PackageBuilder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"


def fixture(name: str) -> EvidencePackage:
    return load_package(FIXTURES / name).package


def assembly(parts: int, stem: str = "FICT-KALO") -> tuple[PackageBuilder, list[str]]:
    base = PackageBuilder(design_stem="FICT-OKTAVEN-7000", schema_version="1.6.0")
    documents = [base.document(f"{stem}-{7001 + number}", "part") for number in range(parts)]
    for document in documents:
        base.component(document)
    return base, documents


def drawn(base: PackageBuilder, shows: dict[str, list[str]], **view: Any) -> EvidencePackage:
    """`shows` maps a drawing stem to the documents its one view each shows."""
    builder = DrawingBuilder(base.build().package)
    for stem, documents in shows.items():
        record = builder.drawing(builder.drawing_document(stem))
        sheet = builder.sheet(record, "Sheet1")
        for number, document in enumerate(documents, start=1):
            builder.view(sheet, f"Drawing View{number}", references=document, **view)
    return builder.build()


def as_request(spec: QuestionSpec) -> EvidenceRequest:
    """Every spec must be a valid `EvidenceRequest`: the writer would refuse it otherwise."""
    return EvidenceRequest(
        id="ER-001", what=spec.what, why=spec.why, entity_ids=list(spec.entity_ids),
        status="open", answer=None, answered_at=None, question=spec.question,
        options=list(spec.options), blocks=spec.blocks,
    )


# --- 1. the coverage (section 3) ----------------------------------------------------------------


def test_one_item_per_reviewed_part_or_assembly_in_id_order() -> None:
    result = run_drawing_context(fixture("plate-drawing"))

    assert [(item.document_id, item.status) for item in result.coverage] == [
        ("doc:0001", "skipped"),
        ("doc:0002", "checked"),
        ("doc:0003", "skipped"),
        ("doc:0004", "skipped"),
        ("doc:0005", "skipped"),
    ], "the two drawing documents are not subjects"
    assert CONTEXT_CHECK == "drawing.context"


def test_a_checked_document_names_its_drawings_its_usable_views_and_every_unusable_one() -> None:
    [plate] = [item for item in run_drawing_context(fixture("plate-drawing")).coverage
               if item.document_id == "doc:0002"]

    assert plate.read == ("doc:0006", "doc:0007")
    assert plate.reason == (
        "read from FICT-TULMKALO-3001.SLDDRW and FICT-TULMKALO-3001-B.SLDDRW; 1 view usable; "
        "view Drawing View1 of doc:0007 shows configuration 'FICT-VENTA'; the review read "
        "'Default'; view Drawing View2 of doc:0007 is out of date with its model"
    )
    assert [why for _, why in plate.unusable] == [
        "view Drawing View1 of doc:0007 shows configuration 'FICT-VENTA'; the review read "
        "'Default'",
        "view Drawing View2 of doc:0007 is out of date with its model",
    ]
    item = plate.coverage_item()
    assert (item.check, item.scope.document_ids, item.reason) == (
        "drawing.context", ["doc:0002"], plate.reason
    )


def test_a_skipped_document_says_no_drawing_shows_it_and_names_its_candidate() -> None:
    coverage = {item.document_id: item for item in run_drawing_context(
        fixture("plate-drawing")).coverage}

    assert coverage["doc:0003"].reason == (
        "no open drawing shows it; a drawing with its name sits beside it (candidate)"
    )
    assert coverage["doc:0003"].candidate == (
        "C:\\Fictional\\Vault\\FICT-TULMSORN-3002.SLDDRW"
    )
    assert coverage["doc:0004"].reason == "no open drawing shows it"
    assert coverage["doc:0004"].candidate is None


def test_a_document_every_view_of_which_is_unusable_is_unresolved_naming_each() -> None:
    base, (part,) = assembly(1)
    package = drawn(base, {"FICT-KALO-7001": [part]}, out_of_date=True)

    [_, item] = run_drawing_context(package).coverage

    assert item.status == "unresolved"
    assert item.reason == "view Drawing View1 of doc:0003 is out of date with its model"


def test_a_drawing_roots_own_document_is_not_a_subject_its_references_are() -> None:
    root = fixture("drawing-root")
    result = run_drawing_context(root)
    root_id = root.design.root_assembly_document_id

    subjects = [item.document_id for item in result.coverage]
    assert root_id not in subjects
    assert len(subjects) == 3
    assert {item.status for item in result.coverage if item.document_id != "doc:4"} == {"checked"}


def test_a_package_with_no_drawing_evidence_covers_every_document_as_skipped() -> None:
    base, _ = assembly(2)

    result = run_drawing_context(base.build().package)

    assert [item.status for item in result.coverage] == ["skipped"] * 3
    assert result.questions == ()


# --- 2. the candidate question (section 4) ------------------------------------------------------


def test_the_plate_drawing_raises_one_candidate_question_only() -> None:
    """Drawing B shows the plate only in unusable views, so it does not compete with A."""
    result = run_drawing_context(fixture("plate-drawing"))

    [question] = result.questions
    assert question.key == "candidates"
    assert question.question == (
        "A drawing with the same name sits beside 1 reviewed file(s) but is not open. Should "
        "the review read it?"
    )
    assert question.options == CANDIDATE_OPTIONS == (
        CANDIDATE_CONFIRM, "Review without it", "It is not the right drawing"
    )
    assert CANDIDATE_CONFIRM == "Yes, open it read-only and read it"
    assert question.blocks == "drawing.manufacturing_inputs"
    assert question.entity_ids == ("doc:0003",)
    assert question.what == (
        "The same-name drawing FICT-TULMSORN-3002.SLDDRW, beside a reviewed file and not open"
    )
    assert question.why == CANDIDATES_WHY == (
        "Fits, stacks and callouts stay unresolved without a drawing. The review opens a file "
        "only when you confirm it, read-only, and closes it again."
    )
    as_request(question)


def test_the_candidate_question_names_the_first_ten_and_counts_the_rest() -> None:
    base, documents = assembly(12)
    builder = DrawingBuilder(base.build().package)
    for document in documents:
        builder.candidate(document)

    [question] = run_drawing_context(builder.build()).questions

    assert question.entity_ids == tuple(documents)
    assert "12 reviewed file(s)" in question.question
    names = ", ".join(f"FICT-KALO-{7001 + number}.SLDDRW" for number in range(10))
    assert question.what == (
        f"The same-name drawings {names} and 2 more, each beside a reviewed file and not open"
    )
    as_request(question)


# --- 3. the governing question (section 4) ------------------------------------------------------


def test_the_assembly_drawings_fixture_raises_one_governing_question() -> None:
    package = fixture("assembly-drawings")
    kalo = next(item for item in package.documents if item.file_name == "FICT-OKTAKALO-5001.SLDPRT")

    [question] = run_drawing_context(package).questions

    drawings = [
        item.document_id for item in package.documents
        if item.file_name.startswith("FICT-OKTAKALO-5001") and item.kind == "drawing"
    ]
    assert question.key == f"governing:{kalo.document_id}"
    assert question.question == "3 open drawings show FICT-OKTAKALO-5001. Which one governs it?"
    assert question.options == (
        "FICT-OKTAKALO-5001.SLDDRW",
        "FICT-OKTAKALO-5001-B.SLDDRW",
        "FICT-OKTAKALO-5001-C.SLDDRW",
        "They all apply",
    )
    assert question.blocks is None
    assert question.entity_ids == (kalo.document_id, *drawings)
    assert question.why == GOVERNING_WHY == (
        "Open drawings of one part can disagree; the review uses them all, in a fixed order, "
        "until you say which governs."
    )
    for drawing in drawings:
        assert drawing in question.what
    as_request(question)


def test_five_drawings_of_one_part_are_asked_about_with_no_buttons() -> None:
    base, (part,) = assembly(1)
    stems = [f"FICT-KALO-7001-{letter}" for letter in "ABCDE"]
    package = drawn(base, {stem: [part] for stem in stems})

    [question] = run_drawing_context(package).questions

    assert question.question.startswith("5 open drawings show FICT-KALO-7001.")
    assert question.options == ()
    as_request(question)


def test_a_drawing_name_longer_than_an_option_allows_takes_the_buttons_away() -> None:
    base, (part,) = assembly(1)
    long = "FICT-KALO-7001-" + "X" * 50
    package = drawn(base, {"FICT-KALO-7001": [part], long: [part]})

    [question] = run_drawing_context(package).questions

    assert question.options == ()
    as_request(question)


def test_two_drawings_with_one_file_name_take_the_buttons_away() -> None:
    """Two buttons with the same words could not say which drawing was meant."""
    base, (part,) = assembly(1)
    package = drawn(base, {"FICT-KALO-7001": [part], "FICT-KALO-7001-B": [part]})
    documents = [
        item.model_copy(update={"file_name": "FICT-KALO-7001.SLDDRW"})
        if item.file_name == "FICT-KALO-7001-B.SLDDRW" else item
        for item in package.documents
    ]
    package = package.model_copy(update={"documents": documents})

    [question] = run_drawing_context(package).questions

    assert question.options == ()


def test_a_long_stem_is_shortened_with_an_ellipsis_until_the_question_fits() -> None:
    base, (part,) = assembly(1, stem="FICT-" + "KALO" * 40)
    stem = f"FICT-{'KALO' * 40}-7001"
    package = drawn(base, {"FICT-A": [part], "FICT-B": [part]})

    [question] = run_drawing_context(package).questions

    assert len(question.question) == 140
    assert question.question.startswith("2 open drawings show FICT-KALOKALO")
    assert question.question.endswith("…. Which one governs it?")
    assert stem not in question.question
    as_request(question)


def test_at_most_three_governing_questions_in_traversal_order() -> None:
    base, parts = assembly(5)
    package = drawn(base, {"FICT-A": parts, "FICT-B": parts})

    questions = run_drawing_context(package).questions

    assert [question.key for question in questions] == [
        f"governing:{part}" for part in parts[:3]
    ]


def test_a_drawing_whose_views_are_all_unusable_does_not_compete() -> None:
    base, (part,) = assembly(1)
    builder = DrawingBuilder(base.build().package)
    for stem, view in (("FICT-A", {}), ("FICT-B", {"configuration": "FICT-VENTA"})):
        record = builder.drawing(builder.drawing_document(stem))
        builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references=part, **view)

    assert run_drawing_context(builder.build()).questions == ()


def test_there_is_no_question_when_there_is_nothing_to_ask() -> None:
    base, (part,) = assembly(1)

    assert run_drawing_context(drawn(base, {"FICT-A": [part]})).questions == ()


def test_both_kinds_come_candidates_first_and_never_more_than_four() -> None:
    base, parts = assembly(6)
    builder = DrawingBuilder(base.build().package)
    for stem in ("FICT-A", "FICT-B"):
        record = builder.drawing(builder.drawing_document(stem))
        sheet = builder.sheet(record, "Sheet1")
        for number, part in enumerate(parts[:4], start=1):
            builder.view(sheet, f"Drawing View{number}", references=part)
    for part in parts[4:]:
        builder.candidate(part)

    questions = run_drawing_context(builder.build()).questions

    assert [question.key for question in questions] == [
        "candidates", *(f"governing:{part}" for part in parts[:3])
    ]


@pytest.mark.parametrize("name", ["plate-drawing", "drawing-root", "assembly-drawings"])
def test_every_question_is_a_valid_evidence_request(name: str) -> None:
    for question in run_drawing_context(fixture(name)).questions:
        request = as_request(question)
        assert len(request.question or "") <= 140
