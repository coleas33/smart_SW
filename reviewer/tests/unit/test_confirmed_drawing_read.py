"""The engineer confirms a candidate; the product reads it read-only before resuming (T075).

`contracts/confirmed-open.md` section 1 is normative (owner, 2026-09-23, research R5 Q2). When
an answered request **is** the candidate question - its `question`, `options` and `entity_ids`
equal the one `checks/drawing_context.candidate_question` builds for this package - and its
answer is exactly `CANDIDATE_CONFIRM`, `ReviewRun.answer_evidence_batch` asks the bridge once
per candidate, in the question's order and before the resumed turn, `drawing_read(run_id,
document_id)` with the run folder's own name, while the package holds fewer than ten drawing
records; then it reloads the package from the run folder, so the resumed turn sees what the
host appended. Each candidate's outcome is one `drawing.confirmed_open` coverage item. Every
other answer, and a request with the same options but another question or other entity ids,
opens nothing; a review with no bridge calls nothing and says why.

The fake bridge here plays the host (the add-in, extractor lane T072-T074): it answers with the
result shape of section 2, or raises `BridgeError` with the host's refusal, and on a read writes
the package the host's `PackageAppender.MergeDrawing` would leave in the run folder.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import ReviewRun, answers_message, start_review
from swreview.bridge.client import BridgeError
from swreview.checks.drawing_context import CANDIDATE_CONFIRM, CANDIDATE_OPTIONS
from swreview.ir.loader import load_package, save_package
from swreview.ir.models import EvidencePackage
from swreview.tools.drawings import (
    CONFIRMED_OPEN_CHECK,
    NO_CONNECTION,
    TEN_DRAWINGS,
    read_confirmed_candidates,
)
from tests.support.drawings import DrawingBuilder
from tests.support.mechanical import PackageBuilder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"
NOT_VALIDATED_BY_THE_HOST = (
    "the read-only open of a confirmed drawing is not yet validated on a seat (feature 011 "
    "probe D14)"
)

Answer = dict[str, Any] | BridgeError | Callable[[], dict[str, Any]]


class FakeHost:
    """The bridge as the add-in answers `drawing.read`: one scripted answer per document."""

    def __init__(self, folder: Path, answers: dict[str, Answer]) -> None:
        self.folder = folder
        self.answers = answers
        self.calls: list[tuple[str, str]] = []
        self.user_messages_at_call: list[int] = []
        self.run: ReviewRun | None = None

    def drawing_read(self, run_id: str, document_id: str) -> dict[str, Any]:
        self.calls.append((run_id, document_id))
        if self.run is not None:
            self.user_messages_at_call.append(
                sum(1 for message in self.run.messages if message["role"] == "user")
            )
        answer = self.answers[document_id]
        if isinstance(answer, BridgeError):
            raise answer
        return answer() if callable(answer) else answer

    def close(self) -> None:
        pass


def merged(folder: Path, document_id: str) -> Callable[[], dict[str, Any]]:
    """What the host does on a read: append the drawing and drop the candidate row, then say so."""

    def read() -> dict[str, Any]:
        package = load_package(folder).package
        builder = DrawingBuilder(package)
        candidate = next(item for item in package.drawing_candidates if item.document_id ==
                         document_id)
        stem = candidate.path.rsplit("\\", 1)[-1].rsplit(".", 1)[0]
        drawing = builder.drawing_document(stem)
        record = builder.drawing(drawing)
        builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references=document_id)
        after = builder.build()
        after = after.model_copy(
            update={
                "drawing_records": [
                    *after.drawing_records[:-1],
                    after.drawing_records[-1].model_copy(update={"opened_by_review": True}),
                ],
                "drawing_candidates": [
                    item for item in package.drawing_candidates if item.document_id != document_id
                ],
            }
        )
        save_package(after, folder)
        return {"document_id": document_id, "drawing_document_id": drawing, "opened": True,
                "closed": True, "sheets": 1, "gaps": 0}

    return read


def candidates_package(count: int, drawings: int = 0) -> EvidencePackage:
    """An assembly of `count` parts, each with a same-name drawing beside it, and `drawings`
    drawings of other parts already read."""
    base = PackageBuilder(design_stem="FICT-OKTAVEN-8000", schema_version="1.6.0")
    parts = [base.document(f"FICT-KALO-{8001 + number}", "part") for number in range(count)]
    extra = [base.document(f"FICT-SORN-{8101 + number}", "part") for number in range(drawings)]
    for document in (*parts, *extra):
        base.component(document)
    builder = DrawingBuilder(base.build().package)
    for number, document in enumerate(extra):
        record = builder.drawing(builder.drawing_document(f"FICT-SORN-{8101 + number}"))
        builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references=document)
    for document in parts:
        builder.candidate(document)
    return builder.build()


def reviewed(
    tmp_path: Path,
    package: EvidencePackage | None,
    answers: Callable[[Path], dict[str, Answer]] | None,
    *,
    bridge: bool = True,
) -> tuple[ReviewRun, FakeHost | None, list[tuple[str, dict[str, Any]]]]:
    """A review whose first turn calls `check_drawings`, so the candidate question is asked."""
    folder = tmp_path / "run-0001"
    if package is None:
        shutil.copytree(FIXTURES / "plate-drawing", folder)
    else:
        save_package(package, folder)
    host = FakeHost(folder, answers(folder)) if answers is not None else None
    events: list[tuple[str, dict[str, Any]]] = []
    options: dict[str, Any] = {}
    if bridge and host is not None:
        options = {"bridge": True, "bridge_factory": lambda pipe, secret: host}
    run = start_review(
        folder,
        folder,
        provider=FakeProvider(
            script=[
                ScriptedTurn(text="asked", tool_calls=(ScriptedToolCall("check_drawings"),)),
                ScriptedTurn(text="resumed"),
            ],
            model="fake-scripted",
        ),
        callbacks=[lambda event: events.append((event.type, dict(event.body)))],
        **options,
    )
    if host is not None:
        host.run = run
    run.start()
    return run, host, events


def question_id(run: ReviewRun) -> str:
    [request] = [item for item in run.session.evidence_requests if item.options]
    return request.id


def confirmed(run: ReviewRun) -> dict[str, tuple[str, str]]:
    """`{document id: (bucket, reason)}` of every `drawing.confirmed_open` item."""
    return {
        item.scope.document_ids[0]: (bucket, item.reason)
        for bucket in ("checked", "unresolved")
        for item in getattr(run.session.coverage, bucket)
        if item.check == CONFIRMED_OPEN_CHECK
    }


# --- 1. the trigger -------------------------------------------------------------------------------


def test_confirming_the_plate_drawings_candidate_reads_it_before_the_turn_resumes(
    tmp_path: Path,
) -> None:
    run, host, events = reviewed(tmp_path, None, lambda folder: {"doc:0003": merged(folder,
                                                                                    "doc:0003")})
    assert host is not None
    request = question_id(run)
    users_before = sum(1 for message in run.messages if message["role"] == "user")

    run.answer_evidence_batch([(request, CANDIDATE_CONFIRM)])

    assert host.calls == [("run-0001", "doc:0003")]
    assert host.user_messages_at_call == [users_before], "called before the resumed turn"
    assert confirmed(run) == {
        "doc:0003": ("checked", "opened read-only, read and closed (1 sheet)")
    }
    kinds = [kind for kind, _ in events]
    answered = kinds.index("evidence.answered")
    coverage = next(
        index for index, (kind, body) in enumerate(events)
        if kind == "coverage" and body["item"]["check"] == CONFIRMED_OPEN_CHECK
    )
    assert answered < coverage < len(kinds) - 1 - kinds[::-1].index("turn.ended")
    assert run.messages[-2]["content"] == answers_message([(request, CANDIDATE_CONFIRM)])


def test_after_the_read_the_package_is_reloaded_from_the_run_folder(tmp_path: Path) -> None:
    run, _, _ = reviewed(tmp_path, None, lambda folder: {"doc:0003": merged(folder, "doc:0003")})

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    package = run.context.ir
    assert package.drawing_candidates == []
    [opened] = [record for record in package.drawing_records if record.opened_by_review]
    assert opened.sheets[0].views[0].referenced_document_id == "doc:0003"
    assert run.context.document(opened.document_id) is not None, "the context's caches follow"


def test_every_candidate_is_read_in_the_questions_order(tmp_path: Path) -> None:
    package = candidates_package(3)
    parts = [item.document_id for item in package.drawing_candidates]
    run, host, _ = reviewed(
        tmp_path, package, lambda folder: {part: merged(folder, part) for part in parts}
    )
    assert host is not None

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    assert [document for _, document in host.calls] == parts
    assert {bucket for bucket, _ in confirmed(run).values()} == {"checked"}
    assert run.context.ir.drawing_candidates == []


def test_the_reads_stop_when_the_package_holds_ten_drawings(tmp_path: Path) -> None:
    package = candidates_package(3, drawings=9)
    parts = [item.document_id for item in package.drawing_candidates]
    run, host, _ = reviewed(
        tmp_path, package, lambda folder: {part: merged(folder, part) for part in parts}
    )
    assert host is not None

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    assert [document for _, document in host.calls] == parts[:1]
    outcomes = confirmed(run)
    assert outcomes[parts[0]][0] == "checked"
    assert outcomes[parts[1]] == outcomes[parts[2]] == ("unresolved", TEN_DRAWINGS)
    assert TEN_DRAWINGS == "the package already holds ten drawings, so this one was not opened"


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [
        (
            {"document_id": "doc:0003", "drawing_document_id": "doc:0008", "opened": False,
             "closed": False, "sheets": 2, "gaps": 0},
            ("checked", "read as it stood; it was already open, so it was left open"),
        ),
        (
            {"document_id": "doc:0003", "drawing_document_id": "doc:0008", "opened": True,
             "closed": True, "sheets": 3, "gaps": 1},
            ("checked", "opened read-only, read and closed (3 sheets)"),
        ),
        (
            {"document_id": "doc:0003", "drawing_document_id": "doc:0008", "opened": True,
             "closed": False, "sheets": 2, "gaps": 0},
            ("checked", "opened read-only and read (2 sheets), but not closed again: close it "
                        "in SOLIDWORKS"),
        ),
        (
            BridgeError("the bridge returned status 'error': the drawing file is not there"),
            ("unresolved", "the bridge returned status 'error': the drawing file is not there"),
        ),
        (
            BridgeError(f"the bridge returned status 'error': {NOT_VALIDATED_BY_THE_HOST}"),
            ("unresolved", f"the bridge returned status 'error': {NOT_VALIDATED_BY_THE_HOST}"),
        ),
        (
            BridgeError("the bridge pipe closed while the request was in flight"),
            ("unresolved", "the bridge pipe closed while the request was in flight"),
        ),
    ],
    ids=["already-open", "opened", "not-closed", "refused", "not-validated", "transport"],
)
def test_each_outcome_is_one_coverage_item_with_its_reason(
    tmp_path: Path, answer: Answer, outcome: tuple[str, str]
) -> None:
    run, _, _ = reviewed(tmp_path, None, lambda folder: {"doc:0003": answer})

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    assert confirmed(run) == {"doc:0003": outcome}


# --- 2. what opens nothing ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer", [CANDIDATE_OPTIONS[1], CANDIDATE_OPTIONS[2], "yes, open it read-only and read it",
               "Please open it"],
)
def test_every_other_answer_calls_nothing(tmp_path: Path, answer: str) -> None:
    run, host, _ = reviewed(tmp_path, None, lambda folder: {"doc:0003": merged(folder, "doc:0003")})
    assert host is not None

    run.answer_evidence_batch([(question_id(run), answer)])

    assert host.calls == []
    assert confirmed(run) == {}


def test_a_look_alike_request_calls_nothing(tmp_path: Path) -> None:
    """The same options on another question, or on other entity ids, are not the question."""
    run, host, _ = reviewed(tmp_path, None, lambda folder: {"doc:0003": merged(folder, "doc:0003")})
    assert host is not None
    [original] = run.session.evidence_requests
    other_question = original.model_copy(update={"id": "ER-091", "question": "Something else?"})
    other_entities = original.model_copy(update={"id": "ER-092", "entity_ids": ["doc:0002"]})
    run.session.evidence_requests.extend([other_question, other_entities])

    run.answer_evidence_batch([("ER-091", CANDIDATE_CONFIRM), ("ER-092", CANDIDATE_CONFIRM)])

    assert host.calls == []
    assert confirmed(run) == {}


def test_a_review_with_no_bridge_calls_nothing_and_says_why(tmp_path: Path) -> None:
    run, _, _ = reviewed(tmp_path, None, None, bridge=False)

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    assert confirmed(run) == {"doc:0003": ("unresolved", NO_CONNECTION)}
    assert NO_CONNECTION == (
        "no SOLIDWORKS connection in this review, so the drawing was not opened; open it and "
        "review again"
    )
    assert run.context.ir.drawing_candidates != []


def test_the_other_answers_of_the_batch_are_recorded_as_always(tmp_path: Path) -> None:
    run, _, events = reviewed(tmp_path, None, lambda folder: {"doc:0003": merged(folder,
                                                                                 "doc:0003")})
    candidate = question_id(run)
    extra = run.session.evidence_requests[0].model_copy(
        update={"id": "ER-099", "question": None, "options": [], "blocks": None,
                "what": "a note", "entity_ids": ["doc:0002"]}
    )
    run.session.evidence_requests.append(extra)

    run.answer_evidence_batch([(candidate, CANDIDATE_CONFIRM), ("ER-099", "a free answer")])

    answered = [body for kind, body in events if kind == "evidence.answered"]
    assert answered == [
        {"request_id": candidate, "answer": CANDIDATE_CONFIRM},
        {"request_id": "ER-099", "answer": "a free answer"},
    ]
    assert {request.id: request.answer for request in run.session.evidence_requests} == {
        candidate: CANDIDATE_CONFIRM, "ER-099": "a free answer"
    }


def test_a_package_that_cannot_be_reloaded_leaves_the_read_unresolved_naming_why(
    tmp_path: Path,
) -> None:
    def broken(folder: Path) -> dict[str, Answer]:
        def read() -> dict[str, Any]:
            (folder / "package.json").write_text("{not json", encoding="utf-8")
            return {"document_id": "doc:0003", "drawing_document_id": "doc:0008",
                    "opened": True, "closed": True, "sheets": 1, "gaps": 0}

        return {"doc:0003": read}

    run, _, _ = reviewed(tmp_path, None, broken)

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    bucket, reason = confirmed(run)["doc:0003"]
    assert bucket == "unresolved"
    assert reason.startswith("opened read-only, read and closed (1 sheet); but the package in the "
                             "run folder could not be reloaded:")


def test_the_function_acts_only_on_the_confirmed_candidate_question(tmp_path: Path) -> None:
    run, host, _ = reviewed(tmp_path, None, lambda folder: {"doc:0003": merged(folder, "doc:0003")})
    assert host is not None
    [request] = run.session.evidence_requests

    read_confirmed_candidates(run.context, [request], run.out_dir)

    assert host.calls == [], "an open request is not a confirmation"
