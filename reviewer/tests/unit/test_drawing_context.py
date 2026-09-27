"""The drawing check's coverage and questions, as pure functions (feature 011 T045, 013 T078).

`contracts/questions.md` sections 3 and 4 are normative, as 013 `contracts/drawing-capability.md`
sections 3 and 4 amend them. `run_drawing_context(package)` writes one `drawing.context` coverage
item per reviewed part or assembly document that is not bought, in traversal (id) order -
`checked` when a usable view of a drawing shows it, `unresolved` when drawings show it and none of
their views is usable, and (013) `unresolved` when none does, with a candidate's or a missing
drawing's reason - and specifies at most four questions: one about every same-name candidate
file beside a reviewed file, only when the host opens closed drawings (013), and one per document
that two or more drawings show usably, three at most. A configuration mismatch or an out-of-date
view is coverage, never a question: an answer cannot change what was extracted.

*Edited deliberately by 013 T078:* a document no drawing shows was `skipped`; it is now
`unresolved` - a candidate beside it, or no drawing of its name - and the candidate question is
asked only with `mode="opens_closed"`, so the candidate-question tests below pass it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.checks.drawing_context import (
    ABSENT_REASON,
    BOUGHT_REASON,
    CANDIDATE_CONFIRM,
    CANDIDATE_OPTIONS,
    CANDIDATE_REASON,
    CANDIDATES_WHY,
    CONTEXT_CHECK,
    DRAWING_STATES,
    GOVERNING_WHY,
    MAYBE_BOUGHT,
    OPEN_THEN_REVIEW,
    SAME_NAME_READ_REASON,
    CandidateFile,
    QuestionSpec,
    candidate_files,
    candidate_question,
    drawing_request_answer,
    drawing_states,
    run_drawing_context,
)
from swreview.drawings.evidence import DrawingIndex, file_key
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import EvidenceRequest
from tests.support.drawings import DrawingBuilder
from tests.support.fake_part_roles import FakePartRoles
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
        ("doc:0001", "unresolved"),
        ("doc:0002", "checked"),
        ("doc:0003", "unresolved"),
        ("doc:0004", "unresolved"),
        ("doc:0005", "unresolved"),
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


def test_a_document_no_drawing_shows_names_its_candidate_or_the_drawing_it_lacks() -> None:
    """013 T078: the candidate's reason follows the host - the instruction line unless it opens
    closed drawings - and a document with no same-name drawing names the file it lacks."""
    package = fixture("plate-drawing")
    coverage = {item.document_id: item for item in run_drawing_context(package).coverage}
    offered = {item.document_id: item for item in run_drawing_context(
        package, mode="opens_closed").coverage}

    assert coverage["doc:0003"].reason == (
        "Open FICT-TULMSORN-3002.SLDDRW in SOLIDWORKS, then press Review again with "
        "FICT-TULMVEN-0000.SLDASM active"
    )
    assert offered["doc:0003"].reason == "a drawing with its name sits beside it (candidate)"
    assert coverage["doc:0003"].candidate == (
        "C:\\Fictional\\Vault\\FICT-TULMSORN-3002.SLDDRW"
    )
    assert coverage["doc:0004"].reason == (
        "no drawing named FICT-PIN-3X12-3003.SLDDRW sits beside it"
    )
    assert offered["doc:0004"].reason == coverage["doc:0004"].reason
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


def test_a_package_with_no_drawing_evidence_covers_every_document_as_missing_its_drawing() -> None:
    base, _ = assembly(2)

    result = run_drawing_context(base.build().package)

    assert [item.status for item in result.coverage] == ["unresolved"] * 3
    assert [item.reason for item in result.coverage] == [
        f"no drawing named {stem}.SLDDRW sits beside it"
        for stem in ("FICT-OKTAVEN-7000", "FICT-KALO-7001", "FICT-KALO-7002")
    ]
    assert result.questions == ()


# --- 2. the candidate question (section 4) ------------------------------------------------------


def test_the_plate_drawing_raises_one_candidate_question_only() -> None:
    """Drawing B shows the plate only in unusable views, so it does not compete with A."""
    result = run_drawing_context(fixture("plate-drawing"), mode="opens_closed")

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

    [question] = run_drawing_context(builder.build(), mode="opens_closed").questions

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

    questions = run_drawing_context(builder.build(), mode="opens_closed").questions

    assert [question.key for question in questions] == [
        "candidates", *(f"governing:{part}" for part in parts[:3])
    ]


@pytest.mark.parametrize("name", ["plate-drawing", "drawing-root", "assembly-drawings"])
def test_every_question_is_a_valid_evidence_request(name: str) -> None:
    for question in run_drawing_context(fixture(name), mode="opens_closed").questions:
        request = as_request(question)
        assert len(request.question or "") <= 140


# --- 4. drawing states: custom documents only, the offer by mode (013 T078) ----------------------
#
# 013 `contracts/drawing-capability.md` sections 3 and 4. Drawings exist for custom parts and
# custom assemblies, the same-name file in the same folder (research R2.26). Each reviewed part or
# assembly document is `bought` (its role, which comes first: no drawing is expected, and none is
# asked for), `attached` (an attached or root drawing shows it), `candidate` (a same-name drawing
# file sits beside it) or `absent` (none does). An unclear document is treated as custom, and while
# the part-roles question is open its reason says it may be bought. Candidates are grouped by file,
# so a part and an assembly of one stem share one; the candidate question is asked only when the
# host opens closed drawings, and otherwise each candidate's reason is the instruction line.

SITTING = "FICT-OKTAVEN-7000"
"""The assembly's stem, shared by the custom plate beside it: one drawing file for the two."""
PIN, LOOSE = "FICT-SORN-7003", "FICT-KALO-7004"
"""The vendor pin (bought, two instances) and the part no rule decides (unclear)."""
INSTRUCTION = (
    f"Open {SITTING}.SLDDRW in SOLIDWORKS, then press Review again with {SITTING}.SLDASM active"
)


def sitting(*, pin_candidate: bool = True) -> EvidencePackage:
    """A fictional package shaped like the 2026-09-26 sitting: the assembly (doc:0001) and its
    custom plate (doc:0002) of one stem, each with a candidate row for the one file; the vendor pin
    (doc:0003, two instances) with a candidate row the check must ignore; and an unclear part
    (doc:0004) with no drawing beside it."""
    base = PackageBuilder(design_stem=SITTING, schema_version="1.6.0")
    plate = base.document(SITTING, "part")
    pin = base.document(PIN, "part")
    loose = base.document(LOOSE, "part")
    for document in (plate, pin, pin, loose):
        base.component(document)
    builder = DrawingBuilder(base.build().package)
    builder.candidate(base.root_id)
    builder.candidate(plate)
    if pin_candidate:
        builder.candidate(pin)
    return builder.build()


def sitting_roles(**changes: Any) -> FakePartRoles:
    table: dict[str, Any] = {
        "doc:0001": "custom", "doc:0002": "custom", "doc:0003": "bought", "doc:0004": "unclear"
    }
    return FakePartRoles(roles=table, root="doc:0001", **changes)


def states_of(package: EvidencePackage, roles: Any, mode: str) -> dict[str, tuple[str, str, bool]]:
    return {
        document_id: (state.state, state.reason, state.maybe_bought)
        for document_id, state in drawing_states(
            DrawingIndex.for_package(package), roles, mode
        ).items()
    }


def test_the_words_are_the_contracts() -> None:
    assert DRAWING_STATES == ("attached", "candidate", "absent", "bought")
    assert BOUGHT_REASON == "a bought part: no drawing is expected, and none is asked for"
    assert CANDIDATE_REASON == "a drawing with its name sits beside it (candidate)"
    assert ABSENT_REASON == "no drawing named {stem}.SLDDRW sits beside it"
    assert OPEN_THEN_REVIEW == (
        "Open {drawing} in SOLIDWORKS, then press Review again with {model} active"
    )
    assert MAYBE_BOUGHT == "(may be a bought part)"


@pytest.mark.parametrize("mode", ["none", "open_only"])
def test_the_state_matrix_while_the_host_cannot_open_a_closed_drawing(mode: str) -> None:
    assert states_of(sitting(), sitting_roles(), mode) == {
        "doc:0001": ("candidate", INSTRUCTION, False),
        "doc:0002": ("candidate", INSTRUCTION, False),
        "doc:0003": ("bought", BOUGHT_REASON, False),
        "doc:0004": (
            "absent", f"no drawing named {LOOSE}.SLDDRW sits beside it (may be a bought part)", True
        ),
    }


def test_the_state_matrix_when_the_host_opens_closed_drawings() -> None:
    assert states_of(sitting(), sitting_roles(), "opens_closed") == {
        "doc:0001": ("candidate", CANDIDATE_REASON, False),
        "doc:0002": ("candidate", CANDIDATE_REASON, False),
        "doc:0003": ("bought", BOUGHT_REASON, False),
        "doc:0004": (
            "absent", f"no drawing named {LOOSE}.SLDDRW sits beside it (may be a bought part)", True
        ),
    }


def test_an_unclear_candidate_says_it_may_be_bought_whatever_the_mode() -> None:
    package = sitting()
    roles = FakePartRoles(roles={"doc:0002": "unclear"}, root="doc:0001")

    assert states_of(package, roles, "open_only")["doc:0002"] == (
        "candidate", f"{INSTRUCTION} (may be a bought part)", True
    )
    assert states_of(package, roles, "opens_closed")["doc:0002"] == (
        "candidate", f"{CANDIDATE_REASON} (may be a bought part)", True
    )


def test_no_note_while_no_question_is_open() -> None:
    """The absent state and the zero-match guard write no note (`part-roles.md` sections 1, 2):
    an unclear document is then a subject like any other, its reason unmarked."""
    states = states_of(sitting(), sitting_roles(question_open=False), "open_only")

    assert states["doc:0004"] == (
        "absent", f"no drawing named {LOOSE}.SLDDRW sits beside it", False
    )


def test_a_document_an_attached_drawing_shows_is_attached_with_todays_reason() -> None:
    base, (part,) = assembly(1)
    package = drawn(base, {"FICT-KALO-7001": [part]})

    states = states_of(package, FakePartRoles(roles={part: "custom"}), "open_only")

    assert states[part] == ("attached", "read from FICT-KALO-7001.SLDDRW; 1 view usable", False)
    assert states["doc:0001"][0] == "absent"


def test_an_attached_documents_unusable_views_keep_it_attached_and_unresolved() -> None:
    base, (part,) = assembly(1)
    package = drawn(base, {"FICT-KALO-7001": [part]}, out_of_date=True)

    [state] = [
        item for item in drawing_states(DrawingIndex.for_package(package), None, "none").values()
        if item.document_id == part
    ]
    [item] = [item for item in run_drawing_context(package).coverage if item.document_id == part]

    assert state.state == "attached"
    assert (item.status, item.reason) == (
        "unresolved", "view Drawing View1 of doc:0003 is out of date with its model"
    )


@pytest.mark.parametrize(
    "spelled",
    [
        pytest.param(lambda path: path, id="as-written"),
        pytest.param(lambda path: path.lower().replace("\\", "/"), id="another-spelling"),
    ],
)
def test_a_same_name_drawing_that_was_read_but_shows_it_nowhere_is_named(spelled: Any) -> None:
    """The assembly's same-name drawing is open and attached but shows only the part: "no drawing
    named ... sits beside it" would be false, so the reason says the drawing was read and shows it
    in no view. The state is still `absent` - nothing shows the assembly."""
    base, (part,) = assembly(1)
    package = drawn(base, {"FICT-OKTAVEN-7000": [part]})
    documents = [
        row.model_copy(update={"path": spelled(row.path)}) if row.kind == "drawing" else row
        for row in package.documents
    ]
    package = package.model_copy(update={"documents": documents})

    states = states_of(package, None, "open_only")

    assert states["doc:0001"] == (
        "absent",
        "its same-name drawing FICT-OKTAVEN-7000.SLDDRW was read, and no view of it shows it",
        False,
    )
    assert SAME_NAME_READ_REASON == (
        "its same-name drawing {drawing} was read, and no view of it shows it"
    )
    assert states[part][0] == "attached"


def test_a_bought_document_is_bought_even_where_a_drawing_shows_it() -> None:
    """Drawings are for custom documents: a pin the assembly drawing shows is not asked about."""
    base, (part,) = assembly(1)
    package = drawn(base, {"FICT-OKTAVEN-7000": [part]})
    roles = FakePartRoles(roles={part: "bought"}, root="doc:0001")

    states = states_of(package, roles, "opens_closed")
    coverage = run_drawing_context(package, roles=roles, mode="opens_closed").coverage

    assert states[part] == ("bought", BOUGHT_REASON, False)
    assert part not in [item.document_id for item in coverage]


def test_the_root_is_never_bought_it_is_the_document_under_review() -> None:
    roles = FakePartRoles(roles={"doc:0001": "bought"}, root="doc:0001")

    assert states_of(sitting(), roles, "open_only")["doc:0001"] == ("candidate", INSTRUCTION, False)


def test_an_id_the_roles_do_not_hold_is_a_subject_errors_fail_toward_grading() -> None:
    assert states_of(sitting(), FakePartRoles(roles={}), "open_only")["doc:0003"] == (
        "candidate", f"Open {PIN}.SLDDRW in SOLIDWORKS, then press Review again with "
        f"{SITTING}.SLDASM active", False
    )


def test_without_roles_every_document_is_a_subject_as_before_013() -> None:
    states = states_of(sitting(), None, "open_only")

    assert [state for state, _, _ in states.values()] == [
        "candidate", "candidate", "candidate", "absent"
    ]
    assert not any(maybe for _, _, maybe in states.values())


def test_a_shared_stem_gives_one_candidate_file_and_a_bought_documents_row_is_ignored() -> None:
    package = sitting()
    index = DrawingIndex.for_package(package)

    [file] = candidate_files(index, sitting_roles())

    assert file == CandidateFile(
        key=file_key(f"C:\\Fictional\\Vault\\{SITTING}.SLDDRW"),
        file_name=f"{SITTING}.SLDDRW",
        document_ids=("doc:0001", "doc:0002"),
    )
    assert [item.file_name for item in candidate_files(index, None)] == [
        f"{SITTING}.SLDDRW", f"{PIN}.SLDDRW"
    ], "with no roles the pin's row counts"


def test_candidate_rows_of_one_file_spelled_two_ways_are_one_file_named_as_first_spelled() -> None:
    package = sitting(pin_candidate=False)
    rows = [
        row.model_copy(update={"path": row.path.upper()}) if row.document_id == "doc:0002" else row
        for row in package.drawing_candidates
    ]
    package = package.model_copy(update={"drawing_candidates": list(reversed(rows))})

    [file] = candidate_files(DrawingIndex.for_package(package), None)

    assert (file.file_name, file.document_ids) == (f"{SITTING}.SLDDRW", ("doc:0001", "doc:0002"))


def test_candidate_files_are_in_their_first_documents_order() -> None:
    base, parts = assembly(3)
    builder = DrawingBuilder(base.build().package)
    for part in reversed(parts):
        builder.candidate(part)

    files = candidate_files(DrawingIndex.for_package(builder.build()), None)

    assert [file.document_ids for file in files] == [(part,) for part in parts]


@pytest.mark.parametrize("mode", ["none", "open_only"])
def test_no_candidate_question_while_the_host_cannot_open_a_closed_drawing(mode: str) -> None:
    package = sitting()
    roles = sitting_roles()

    result = run_drawing_context(package, roles=roles, mode=mode)

    assert result.questions == ()
    assert candidate_question(DrawingIndex.for_package(package), roles, mode) is None


def test_the_candidate_question_names_each_file_once_and_lists_every_document_of_them() -> None:
    [question] = run_drawing_context(
        sitting(), roles=sitting_roles(), mode="opens_closed"
    ).questions

    assert question.key == "candidates"
    assert question.what == (
        f"The same-name drawing {SITTING}.SLDDRW, beside a reviewed file and not open"
    )
    assert question.question == (
        "A drawing with the same name sits beside 1 reviewed file(s) but is not open. Should "
        "the review read it?"
    )
    assert question.entity_ids == ("doc:0001", "doc:0002")
    assert question.options == CANDIDATE_OPTIONS
    assert question.blocks == "drawing.manufacturing_inputs"
    as_request(question)


def test_the_question_counts_files_and_fits_140_characters_with_long_names() -> None:
    long = "FICT-" + "TESSABRUN" * 12
    base = PackageBuilder(design_stem=f"{long}-7000", schema_version="1.6.0")
    parts = [base.document(f"{long}-{7001 + number}", "part") for number in range(11)]
    twins = [base.document(f"{long}-{7001 + number}", "assembly") for number in range(11)]
    for document in (*parts, *twins):
        base.component(document)
    builder = DrawingBuilder(base.build().package)
    for document in (*parts, *twins):
        builder.candidate(document)

    [question] = run_drawing_context(builder.build(), mode="opens_closed").questions

    assert "sits beside 11 reviewed file(s)" in question.question
    assert len(question.question) <= 140
    assert len(question.entity_ids) == 22
    assert question.what.endswith(" and 1 more, each beside a reviewed file and not open")
    as_request(question)


def test_the_instruction_names_the_root_even_when_its_row_is_missing() -> None:
    package = sitting()
    package = package.model_copy(
        update={"documents": [row for row in package.documents if row.document_id != "doc:0001"]}
    )

    states = states_of(package, None, "open_only")

    assert states["doc:0002"][1] == (
        f"Open {SITTING}.SLDDRW in SOLIDWORKS, then press Review again with doc:0001 active"
    )


def test_the_governing_questions_skip_bought_documents() -> None:
    base, (custom, bought) = assembly(2)
    package = drawn(base, {"FICT-A": [custom, bought], "FICT-B": [custom, bought]})
    roles = FakePartRoles(roles={custom: "custom", bought: "bought"}, root="doc:0001")

    questions = run_drawing_context(package, roles=roles, mode="opens_closed").questions

    assert [question.key for question in questions] == [f"governing:{custom}"]


def test_absent_and_candidate_are_unresolved_coverage_never_a_finding() -> None:
    result = run_drawing_context(sitting(), roles=sitting_roles(), mode="open_only")

    assert [(item.document_id, item.status, item.reason) for item in result.coverage] == [
        ("doc:0001", "unresolved", INSTRUCTION),
        ("doc:0002", "unresolved", INSTRUCTION),
        ("doc:0004", "unresolved",
         f"no drawing named {LOOSE}.SLDDRW sits beside it (may be a bought part)"),
    ], "the bought pin has no row: the bought-parts line names it once"
    assert result.conformance.findings == ()


def test_the_states_follow_the_real_classifier_once_it_lands() -> None:
    """Lane P's `classify_parts` (013 T018) through the same states: with no profile, the
    Toolbox pin is bought and every other document unclear with no note (`part-roles.md`
    section 1's absent state), so no reason says a document may be bought."""
    try:
        from swreview.checks.part_roles import classify_parts
    except ImportError:
        pytest.xfail("013 T018 (lane P) lands checks/part_roles.classify_parts")
    package = sitting()
    components = [
        item.model_copy(update={"is_toolbox": True}) if item.document_id == "doc:0003" else item
        for item in package.components
    ]
    package = package.model_copy(update={"components": components})

    roles = classify_parts(package, None)

    assert states_of(package, roles, "open_only") == {
        "doc:0001": ("candidate", INSTRUCTION, False),
        "doc:0002": ("candidate", INSTRUCTION, False),
        "doc:0003": ("bought", BOUGHT_REASON, False),
        "doc:0004": ("absent", f"no drawing named {LOOSE}.SLDDRW sits beside it", False),
    }


# --- 5. code answers the model's drawing requests: the drawings side (013 section 5) --------------
#
# `request_evidence(blocks="drawing.manufacturing_inputs")` (013 T087, lane S) maps its entity ids
# to documents and asks `drawing_request_answer`: while any named document has no attached drawing
# the answer is `closed_by_code` with each such document's state and reason, and nothing is
# recorded; when every one is attached the request is recorded as before.


def answer_for(package: EvidencePackage, roles: Any, mode: str, *documents: str) -> Any:
    return drawing_request_answer(DrawingIndex.for_package(package), roles, mode, documents)


def test_a_request_about_documents_without_a_drawing_is_answered_by_code() -> None:
    answer = answer_for(sitting(), sitting_roles(), "open_only", "doc:0003", "doc:0002")

    assert answer == {
        "status": "closed_by_code",
        "check": "drawing.manufacturing_inputs",
        "drawings": [
            {"document_id": "doc:0003", "state": "bought", "reason": BOUGHT_REASON},
            {"document_id": "doc:0002", "state": "candidate", "reason": INSTRUCTION},
        ],
        "attached": [],
    }, "in the order the request named them"


def test_a_request_about_attached_documents_only_is_left_to_the_model() -> None:
    plate = fixture("plate-drawing")  # the plate, doc:0002, is shown by its open drawings

    assert answer_for(plate, None, "none", "doc:0002") is None


def test_a_mix_names_both_groups() -> None:
    plate = fixture("plate-drawing")

    answer = answer_for(plate, None, "opens_closed", "doc:0002", "doc:0003", "doc:0002")

    assert answer is not None
    assert answer["drawings"] == [
        {"document_id": "doc:0003", "state": "candidate", "reason": CANDIDATE_REASON}
    ]
    assert answer["attached"] == ["doc:0002"], "each document once"


def test_ids_that_are_no_reviewed_part_or_assembly_are_neither() -> None:
    plate = fixture("plate-drawing")  # doc:0006 is a drawing

    assert answer_for(plate, None, "none", "doc:0006", "doc:9999") is None
    assert answer_for(plate, None, "none") is None
    answer = answer_for(plate, None, "none", "doc:0006", "doc:0004")
    assert answer is not None
    assert [row["document_id"] for row in answer["drawings"]] == ["doc:0004"]
    assert answer["attached"] == []


def test_the_answer_reads_the_same_states_the_check_writes() -> None:
    package, roles = sitting(), sitting_roles()
    states = drawing_states(DrawingIndex.for_package(package), roles, "open_only")

    answer = answer_for(package, roles, "open_only", *states)

    assert answer is not None
    assert [(row["document_id"], row["state"], row["reason"]) for row in answer["drawings"]] == [
        (state.document_id, state.state, state.reason) for state in states.values()
    ]
