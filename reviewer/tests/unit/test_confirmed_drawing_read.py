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
the package the host's `PackageAppender.MergeDrawing` would leave in the run folder - including,
since T079, the dump's standing drawing gap reworded in its own place (section 4 below, T088).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

import pytest

from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import ReviewRun, answers_message, start_review
from swreview.agent.settings import EfficiencySettings
from swreview.bridge.client import BridgeClient, BridgeError
from swreview.checks.drawing_context import (
    CANDIDATE_CONFIRM,
    CANDIDATE_OPTIONS,
    CONFORMANCE_CHECK,
    CONTEXT_CHECK,
)
from swreview.ir.loader import load_package, save_package
from swreview.ir.models import EvidencePackage, Gap
from swreview.tools.drawings import (
    CONFIRMED_OPEN_CHECK,
    DRAWINGS_TOOL,
    MAX_DRAWINGS,
    NO_CONNECTION,
    TEN_DRAWINGS,
    read_confirmed_candidates,
)
from tests.support.drawings import DrawingBuilder
from tests.support.mechanical import PackageBuilder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"
PROFILE_A = Path(__file__).resolve().parents[1] / "fixtures" / "standards" / "profile-a.yaml"
NOT_VALIDATED_BY_THE_HOST = (
    "the read-only open of a confirmed drawing is not yet validated on a seat (feature 011 "
    "probe D14)"
)

Answer = dict[str, Any] | BridgeError | Callable[[], dict[str, Any]]

StaleGap = Literal["reworded", "left", "dropped"]
"""What a host does with the dump's standing drawing gap on a read: rewords it, as
`PackageAppender.MergeDrawing` has since feature 011 T079; leaves it, as a host before T079 did;
or drops it."""

NO_DRAWING_GAP = Gap(
    kind="unsupported",
    entity_kind="drawing",
    entity_id=None,
    reason=(
        "No open drawing shows this design, so no drawing was read natively. Open its drawing "
        "in SOLIDWORKS and extract again to include it."
    ),
    error=None,
)
"""The package-level gap the extractor writes when no open drawing showed the design
(`PackageWriter.NoOpenDrawingGapSentence`): stale once a confirmed candidate is read."""


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


def is_drawing_phase_gap(gap: Gap) -> bool:
    """`PackageWriter.IsDrawingPhaseGap`: the dump's standing drawing gap by its shape - kind
    `unsupported`, entity kind `drawing`, naming no entity - never by its words."""
    return gap.kind == "unsupported" and gap.entity_kind == "drawing" and gap.entity_id is None


def drawings_read_afterwards(read: Sequence[tuple[str, bool]]) -> str:
    """`PackageWriter.DrawingsReadAfterExtractionGapSentence`, word for word: every drawing read
    after the extraction, as `(file name, opened by the review)`, in the order it was merged."""
    named = [
        f"'{name}' ("
        + ("opened read-only by the review" if opened else "already open, read as it stood")
        + ")"
        for name, opened in read
    ]
    listed = named[0] if len(named) == 1 else ", ".join(named[:-1]) + " and " + named[-1]
    return (
        "The extraction read no drawing natively: its drawing phase did not run. Read afterwards, "
        f"when the engineer confirmed the candidate question: {listed}."
    )


def host_gaps(package: EvidencePackage, stale_gap: StaleGap) -> list[Gap]:
    """`package.gaps` as the host leaves them after a merge (`PackageAppender.MergeDrawing`): the
    standing drawing gap reworded in its own place from every drawing record, by file name and by
    how it was read - or left, or dropped, as `stale_gap` says. A package with no standing gap
    (its drawing phase ran) keeps its gaps as they are."""
    gaps = list(package.gaps)
    index = next((number for number, gap in enumerate(gaps) if is_drawing_phase_gap(gap)), None)
    if index is None or stale_gap == "left":
        return gaps
    if stale_gap == "dropped":
        return gaps[:index] + gaps[index + 1 :]
    names = {document.document_id: document.file_name for document in package.documents}
    read = [
        (names.get(record.document_id, record.document_id), record.opened_by_review is True)
        for record in package.drawing_records
    ]
    gaps[index] = gaps[index].model_copy(update={"reason": drawings_read_afterwards(read)})
    return gaps


def merged(
    folder: Path, document_id: str, *, stale_gap: StaleGap = "reworded"
) -> Callable[[], dict[str, Any]]:
    """What the host does on a read: append the drawing, drop the candidate row and treat the
    standing drawing gap as `stale_gap` says (the host as built rewords it), then say so."""

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
        after = after.model_copy(update={"gaps": host_gaps(after, stale_gap)})
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


def test_the_bound_and_its_sentence_are_the_hosts() -> None:
    """The backend stops where the host would refuse, in the host's words: `MAX_DRAWINGS` is
    `OpenDrawingDiscovery.MaxAttachedDrawings` and `TEN_DRAWINGS` the sentence
    `ConfirmedDrawingRead` refuses with (`contracts/confirmed-open.md` section 2, item 5)."""
    dump = Path(__file__).resolve().parents[3] / "extractor" / "SwReview.Extractor" / "Dump"
    discovery = (dump / "OpenDrawingDiscovery.cs").read_text(encoding="utf-8")
    host_read = (dump / "ConfirmedDrawingRead.cs").read_text(encoding="utf-8")

    assert f"public const int MaxAttachedDrawings = {MAX_DRAWINGS};" in discovery
    assert f'new ConfirmedDrawingRefused("{TEN_DRAWINGS}")' in host_read


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


# --- 3. the drawing check is restated over the drawing just read ---------------------------------


def prerun_reviewed(
    tmp_path: Path,
    answers: Callable[[Path], dict[str, Answer]],
    resumed: tuple[ScriptedToolCall, ...] = (),
) -> tuple[ReviewRun, FakeHost]:
    """A pane review of `plate-drawing`: checks first and lever 13 on (the pane's defaults), a
    version 3 profile attached, so the pre-run's `check_drawings` asks the candidate question and
    then leaves the array."""
    folder = tmp_path / "run-0001"
    shutil.copytree(FIXTURES / "plate-drawing", folder)
    host = FakeHost(folder, answers(folder))
    run = start_review(
        folder,
        folder,
        provider=FakeProvider(
            script=[ScriptedTurn(text="asked"), ScriptedTurn(text="resumed", tool_calls=resumed)],
            model="fake-scripted",
        ),
        efficiency=EfficiencySettings(prerun_checks=True, withhold_prerun_tools=True),
        standards_profile=PROFILE_A,
        bridge=True,
        bridge_factory=lambda pipe, secret: host,
    )
    host.run = run
    run.start()
    return run, host


def context_items(run: ReviewRun, check: str) -> list[tuple[str, tuple[str, ...], str]]:
    """`(bucket, document ids, reason)` of every coverage item of `check`, in bucket order."""
    return [
        (bucket, tuple(item.scope.document_ids), item.reason)
        for bucket in ("checked", "skipped", "unresolved")
        for item in getattr(run.session.coverage, bucket)
        if item.check == check
    ]


def test_with_checks_first_the_drawing_check_is_restated_over_the_drawing_just_read(
    tmp_path: Path,
) -> None:
    """The pre-run's `check_drawings` described the package before the read; after it, the
    candidate's document is drawn and the new drawing is compared with the profile (FR-046), as
    one recorded step, before the resumed turn - so the session never holds both "opened
    read-only, read and closed" and "a drawing with its name sits beside it (candidate)"."""
    run, _ = prerun_reviewed(tmp_path, lambda folder: {"doc:0003": merged(folder, "doc:0003")})
    [prerun_step] = [step for step in run.session.steps if step.tool == DRAWINGS_TOOL]
    before = context_items(run, CONTEXT_CHECK)
    assert ("skipped", ("doc:0003",)) in [(bucket, ids) for bucket, ids, _ in before]

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    drawn = [step for step in run.session.steps if step.tool == DRAWINGS_TOOL]
    assert len(drawn) == 2, "the pre-run's call, and the one restated after the read"
    restated = drawn[1]
    assert restated.index > prerun_step.index and restated.status == "ok"
    after = context_items(run, CONTEXT_CHECK)
    assert len(after) == len(before), "restated, not added to"
    [plate_block] = [item for item in after if item[1] == ("doc:0003",)]
    assert plate_block[0] == "checked"
    assert "candidate" not in plate_block[2]
    new_drawing = next(
        record.document_id for record in run.context.ir.drawing_records if record.opened_by_review
    )
    compared = {ids for _, ids, _ in context_items(run, CONFORMANCE_CHECK)}
    assert (new_drawing,) in compared, "the drawing just read is compared with the profile"
    assert [step.index for step in run.session.steps] == list(range(len(run.session.steps)))


def test_a_repeat_after_the_read_is_answered_from_the_restated_run(tmp_path: Path) -> None:
    """The re-call guard answers the model's `check_drawings` from the restated call, not from
    the pre-run's outcome over the package as it stood before the read."""
    run, _ = prerun_reviewed(
        tmp_path,
        lambda folder: {"doc:0003": merged(folder, "doc:0003")},
        resumed=(ScriptedToolCall("check_drawings"),),
    )

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    restated, repeat = [step for step in run.session.steps if step.tool == DRAWINGS_TOOL][1:]
    [message] = [
        item["content"] for item in run.messages
        if item.get("role") == "tool" and item.get("name") == DRAWINGS_TOOL
    ]
    assert message["status"] == "already_run"
    assert message["ran_at_step"] == restated.index
    assert (message["outcome"]["drawings"], message["outcome"]["candidates"]) == (3, 0)
    assert repeat.index == restated.index + 1, "the model's call is numbered after the restated one"


def test_without_checks_first_the_drawing_check_is_restated_too(tmp_path: Path) -> None:
    run, _, _ = reviewed(tmp_path, None, lambda folder: {"doc:0003": merged(folder, "doc:0003")})

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    assert len([step for step in run.session.steps if step.tool == DRAWINGS_TOOL]) == 2
    [plate_block] = [item for item in context_items(run, CONTEXT_CHECK) if item[1] == ("doc:0003",)]
    assert plate_block[0] == "checked"


@pytest.mark.parametrize(
    "answer",
    [BridgeError(f"the bridge returned status 'error': {NOT_VALIDATED_BY_THE_HOST}"), None],
    ids=["refused", "no-bridge"],
)
def test_nothing_is_restated_when_nothing_was_read(tmp_path: Path, answer: Answer | None) -> None:
    run, _, _ = reviewed(
        tmp_path,
        None,
        None if answer is None else (lambda folder: {"doc:0003": answer}),
        bridge=answer is not None,
    )
    steps = len(run.session.steps)

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    assert len(run.session.steps) == steps
    assert ("skipped", ("doc:0003",)) in [
        (bucket, ids) for bucket, ids, _ in context_items(run, CONTEXT_CHECK)
    ]


class RefusingHost:
    """The add-in's pipe as the shipped state answers it: every `drawing.read` refused with the
    not-validated sentence (`DrawingOpenScope.SeatValidated` is false), every `ping` answered."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    def request(self, line: str) -> str:
        request = json.loads(line)
        self.commands.append(request["command"])
        if request["command"] == "drawing.read":
            return json.dumps({"id": request["id"], "status": "error", "result": None,
                               "error": NOT_VALIDATED_BY_THE_HOST, "elapsed_ms": 1})
        return json.dumps({"id": request["id"], "status": "ok", "result": {"pong": True},
                           "error": None, "elapsed_ms": 1})

    def close(self) -> None:
        pass


def test_refused_candidates_leave_the_real_bridge_client_working(tmp_path: Path) -> None:
    """Four refusals through the real `BridgeClient`: each candidate is asked and records the
    host's own sentence, and the bridge is still there for the rest of the review - a refusal is
    a definite answer from a healthy host, never a failure the circuit breaker counts."""
    package = candidates_package(4)
    parts = [item.document_id for item in package.drawing_candidates]
    folder = tmp_path / "run-0001"
    save_package(package, folder)
    host = RefusingHost()
    client = BridgeClient(transport=host)
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
        bridge=True,
        bridge_factory=lambda pipe, secret: client,
    )
    run.start()

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    assert host.commands == ["drawing.read"] * 4
    reasons = confirmed(run)
    assert [reasons[part][0] for part in parts] == ["unresolved"] * 4
    assert all(NOT_VALIDATED_BY_THE_HOST in reasons[part][1] for part in parts)
    assert not client.circuit_open
    assert client.ping() == {"pong": True}


def test_the_function_acts_only_on_the_confirmed_candidate_question(tmp_path: Path) -> None:
    run, host, _ = reviewed(tmp_path, None, lambda folder: {"doc:0003": merged(folder, "doc:0003")})
    assert host is not None
    [request] = run.session.evidence_requests

    read_confirmed_candidates(run.context, [request], run.out_dir)

    assert host.calls == [], "an open request is not a confirmation"


# --- 4. the fake host rewords the stale drawing gap as the host does (T088) ----------------------
#
# Since feature 011 T079 the host's `PackageAppender.MergeDrawing` rewords the dump's standing
# drawing gap - written when the extraction's drawing phase did not run - in its own place, once a
# confirmed drawing is read into the package. `merged` plays that, and the words are pinned in both
# languages: `extractor/SwReview.Extractor.Tests/PackageAppenderTests.cs`
# (`TheStandingAndRewordedSentencesAreTheOnesTheBackendsFakeHostPlays`) asserts these same
# literals against `PackageWriter`, so neither side can change them alone.

REWORDED_ONE = (
    "The extraction read no drawing natively: its drawing phase did not run. Read afterwards, "
    "when the engineer confirmed the candidate question: 'FICT-KALO-8001.SLDDRW' (opened "
    "read-only by the review)."
)
REWORDED_THREE = (
    "The extraction read no drawing natively: its drawing phase did not run. Read afterwards, "
    "when the engineer confirmed the candidate question: 'FICT-KALO-8001.SLDDRW' (opened "
    "read-only by the review), 'FICT-KALO-8002.SLDDRW' (already open, read as it stood) and "
    "'FICT-KALO-8003.SLDDRW' (opened read-only by the review)."
)
OTHER_GAPS = (
    Gap(
        kind="not_extracted",
        entity_kind="feature_tree_unavailable",
        entity_id=None,
        reason="The part feature trees were not read: the dump was run with --features none.",
        error=None,
    ),
    Gap(
        kind="not_extracted",
        entity_kind="equations",
        entity_id=None,
        reason="The part equations were not read: the dump was run with --equations off.",
        error=None,
    ),
)
"""Two gaps of other phases, set either side of the standing one, so a merge that moved or
reworded the wrong gap is seen."""


def test_the_fake_host_words_the_stale_gap_as_the_extractor_does() -> None:
    assert NO_DRAWING_GAP.reason == (
        "No open drawing shows this design, so no drawing was read natively. Open its drawing "
        "in SOLIDWORKS and extract again to include it."
    )
    assert drawings_read_afterwards([("FICT-KALO-8001.SLDDRW", True)]) == REWORDED_ONE
    assert drawings_read_afterwards(
        [
            ("FICT-KALO-8001.SLDDRW", True),
            ("FICT-KALO-8002.SLDDRW", False),
            ("FICT-KALO-8003.SLDDRW", True),
        ]
    ) == REWORDED_THREE


def test_the_standing_gap_is_found_by_its_shape_never_its_words() -> None:
    assert is_drawing_phase_gap(NO_DRAWING_GAP)
    assert is_drawing_phase_gap(NO_DRAWING_GAP.model_copy(update={"reason": REWORDED_ONE}))
    assert not is_drawing_phase_gap(NO_DRAWING_GAP.model_copy(update={"entity_id": "doc:0009"}))
    assert not is_drawing_phase_gap(NO_DRAWING_GAP.model_copy(update={"kind": "not_extracted"}))
    assert not is_drawing_phase_gap(
        NO_DRAWING_GAP.model_copy(update={"entity_kind": "drawing_sheet"})
    )


def stale_gap_package(count: int) -> EvidencePackage:
    """`candidates_package(count)` as a review whose extraction read no drawing leaves it: the
    standing gap between two gaps of other phases."""
    package = candidates_package(count)
    return package.model_copy(
        update={"gaps": [*package.gaps, OTHER_GAPS[0], NO_DRAWING_GAP, OTHER_GAPS[1]]}
    )


def test_a_confirmed_read_rewords_the_stale_gap_in_its_own_place(tmp_path: Path) -> None:
    package = stale_gap_package(2)
    parts = [item.document_id for item in package.drawing_candidates]
    before = list(package.gaps)
    run, _, _ = reviewed(
        tmp_path, package, lambda folder: {part: merged(folder, part) for part in parts}
    )

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    after = run.context.ir.gaps
    index = before.index(NO_DRAWING_GAP)
    assert len(after) == len(before)
    assert [gap for number, gap in enumerate(after) if number != index] == [
        gap for number, gap in enumerate(before) if number != index
    ]
    assert after[index] == NO_DRAWING_GAP.model_copy(
        update={
            "reason": drawings_read_afterwards(
                [("FICT-KALO-8001.SLDDRW", True), ("FICT-KALO-8002.SLDDRW", True)]
            )
        }
    )


@pytest.mark.parametrize(
    ("stale_gap", "expected"),
    [("left", NO_DRAWING_GAP), ("dropped", None)],
    ids=["a-host-before-T079", "a-host-that-drops-it"],
)
def test_the_fake_host_can_play_a_host_that_leaves_or_drops_the_gap(
    tmp_path: Path, stale_gap: StaleGap, expected: Gap | None
) -> None:
    package = stale_gap_package(1)
    [part] = [item.document_id for item in package.drawing_candidates]
    others = [gap for gap in package.gaps if not is_drawing_phase_gap(gap)]
    run, _, _ = reviewed(
        tmp_path, package, lambda folder: {part: merged(folder, part, stale_gap=stale_gap)}
    )

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    standing = [gap for gap in run.context.ir.gaps if is_drawing_phase_gap(gap)]
    assert standing == ([] if expected is None else [expected])
    assert [gap for gap in run.context.ir.gaps if not is_drawing_phase_gap(gap)] == others


def test_a_package_with_no_stale_gap_gains_none(tmp_path: Path) -> None:
    """The plate fixture's extraction ran its drawing phase: no standing gap, nothing reworded."""
    run, _, _ = reviewed(tmp_path, None, lambda folder: {"doc:0003": merged(folder, "doc:0003")})
    gaps_before = list(run.context.ir.gaps)

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    assert run.context.ir.gaps == gaps_before
    assert not any(is_drawing_phase_gap(gap) for gap in run.context.ir.gaps)
