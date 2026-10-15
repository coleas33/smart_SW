"""The answer driver's tests (feature 014, `contracts/scripted-answers.md` section 7).

This half holds the answer log's record (T077; `scripted-answers.md` 5, data-model section 3
"AnswerLog"; plan decisions QA-9, RF-31): `answer-log.json`, the driver's record of its own
decisions at each answer point, which the scorer reads in place of the case file.

- `benchmark.answers.AnswerLog` is strict: its fields and each point's are the contract's and
  no more; an unknown field, another `answer_log_version` and an `ended` outside the five are
  refused, never ignored; `last_turn_end` is one of the product's `TurnEndReason`s; `entries`
  belongs to an `ambiguous` unscripted request and to no other; and section 5's example
  validates and dumps back to itself.
- `write_answer_log` lands the record through the one atomic writer as UTF-8 JSON with `\\n`
  line endings and a final newline, `outside_options` and `entries` left out when absent;
  `read_answer_log` reads it back, `None` when the folder holds none, and refuses a file that
  does not validate with one `ValueError` naming the folder.

The rest is the driver (T098, for T099; `scripted-answers.md` 3, 4, 5 and 6's structural bullet;
plan decisions QA-1 to QA-4, QA-8, QA-9, INT-8, RF-13; FR-022 to FR-026, FR-032, D3, D16): each
review is started with `start_review(..., bridge=False)` over the questions reader's fictional
package (`questions.md` 7's ids: the plate `doc:0002` with its instance `cmp:0001` and hole
`hol:0001`, the bought pin `doc:0003` with its instances `cmp:0002` and `cmp:0003`) and played by
`drive_review`, the scripted model scripting exactly the turns each test expects: a turn beyond
its script is refused, which is itself the assertion that no answer turn was played. A delivery
goes back through `ReviewRun.answer_evidence_batch`, as the pane's Send does; an unscripted
question gets nothing; the driver answers only after a turn that ended normally, stops at the
bound, and records its decisions in `answer-log.json`, ids only, in a `finally`.
"""

from __future__ import annotations

import ast
import copy
import json
import re
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

import swreview
from swreview import atomic
from swreview.agent.events import replay_events
from swreview.agent.providers import TurnEndReason, TurnResult
from swreview.agent.providers.fake import ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import EVIDENCE_CHECK, ReviewRun, answers_message, start_review
from swreview.benchmark import answers, case_file
from swreview.benchmark.answers import (
    ANSWER_LOG_FILE_NAME,
    ANSWER_LOG_VERSION,
    AnswerLog,
    AnswerPoint,
    AnswerSent,
    UnscriptedRequest,
    drive_review,
    read_answer_log,
    write_answer_log,
)
from swreview.benchmark.case_file import CaseFile
from swreview.checks.drawing_context import candidate_question
from swreview.drawings.evidence import DrawingIndex
from swreview.ir.loader import save_package
from swreview.report.session import load_session
from swreview.tools.registry import PART_ROLES_ATTRIBUTE, StoredResult, read_stored_result
from tests.support.local_paths import scan_file
from tests.support.scripted_answers import (
    FASTENERS,
    FIT,
    MODEL,
    Driven,
    SpyProvider,
    ask,
    drive,
    scripted,
    turn,
)
from tests.support.scripted_answers import case_file as write_case_file
from tests.unit import test_benchmark_answers_roles as roles
from tests.unit.test_benchmark_questions import (
    PACKAGE,
    PIN_1,
    PIN_2,
    PLATE_1,
    PLATE_DOC,
    PLATE_HOLE,
)

ENDED = ("no_open_questions", "all_unscripted", "bound_reached", "turn_did_not_end", "stopped")
"""`ended`'s five values (`scripted-answers.md` 5), including the attempt's stop (INT-7)."""

UNSCRIPTED_REASONS = ("no_answer", "ambiguous", "names_nothing")

SECTION_5_EXAMPLE: dict[str, Any] = {
    "answer_log_version": 1,
    "points": [
        {
            "after_turn": 0,
            "steps_before": 14,
            "sent": [
                {"request_id": "ER-002", "entry": "A-1"},
                {"request_id": "ER-001", "entry": "A-3"},
            ],
            "unscripted": [{"request_id": "ER-003", "reason": "no_answer"}],
            "held": [],
        },
        {
            "after_turn": 1,
            "steps_before": 27,
            "sent": [],
            "unscripted": [
                {"request_id": "ER-003", "reason": "no_answer"},
                {"request_id": "ER-005", "reason": "ambiguous", "entries": ["A-4", "A-5"]},
            ],
            "held": [],
        },
    ],
    "ended": "all_unscripted",
    "last_turn_end": "end",
    "unused_entries": ["A-2"],
}
"""`scripted-answers.md` section 5's example, verbatim."""


def log_payload(**changes: Any) -> dict[str, Any]:
    """A copy of section 5's example with `changes` applied at the log's top level."""
    return {**copy.deepcopy(SECTION_5_EXAMPLE), **changes}


def a_log() -> AnswerLog:
    """A log holding each optional field both present and absent: an `outside_options`
    delivery beside a plain one, an ambiguous unscripted request beside one with no entries,
    and a held request."""
    return AnswerLog(
        answer_log_version=ANSWER_LOG_VERSION,
        points=[
            AnswerPoint(
                after_turn=0,
                steps_before=9,
                sent=[
                    AnswerSent(request_id="ER-001", entry="A-1", outside_options=True),
                    AnswerSent(request_id="ER-002", entry="A-2"),
                ],
                unscripted=[
                    UnscriptedRequest(request_id="ER-003", reason="names_nothing"),
                    UnscriptedRequest(
                        request_id="ER-004", reason="ambiguous", entries=["A-3", "A-4"]
                    ),
                ],
                held=[],
            ),
            AnswerPoint(
                after_turn=1,
                steps_before=17,
                sent=[],
                unscripted=[],
                held=["ER-005"],
            ),
        ],
        ended="bound_reached",
        last_turn_end="end",
        unused_entries=["A-5"],
    )


# --- the record (scripted-answers.md 5; data-model section 3) ----------------------------------


def test_the_file_name_and_the_version_are_the_contracts() -> None:
    assert ANSWER_LOG_FILE_NAME == "answer-log.json"
    assert ANSWER_LOG_VERSION == 1


def test_the_log_and_its_point_hold_the_contracts_fields_and_no_more() -> None:
    assert list(AnswerLog.model_fields) == [
        "answer_log_version",
        "points",
        "ended",
        "last_turn_end",
        "unused_entries",
    ]
    assert list(AnswerPoint.model_fields) == [
        "after_turn",
        "steps_before",
        "sent",
        "unscripted",
        "held",
    ]
    assert list(AnswerSent.model_fields) == ["request_id", "entry", "outside_options"]
    assert list(UnscriptedRequest.model_fields) == ["request_id", "reason", "entries"]


def test_the_section_5_example_validates_and_dumps_back_to_itself() -> None:
    log = AnswerLog.model_validate_json(json.dumps(SECTION_5_EXAMPLE))

    assert [point.after_turn for point in log.points] == [0, 1]
    assert [point.steps_before for point in log.points] == [14, 27]
    assert [(sent.request_id, sent.entry) for sent in log.points[0].sent] == [
        ("ER-002", "A-1"),
        ("ER-001", "A-3"),
    ]
    assert all(sent.outside_options is False for sent in log.points[0].sent)
    assert log.points[1].unscripted[0].entries is None
    assert log.points[1].unscripted[1].entries == ["A-4", "A-5"]
    assert log.ended == "all_unscripted"
    assert log.last_turn_end == "end"
    assert log.unused_entries == ["A-2"]
    assert json.loads(log.model_dump_json()) == SECTION_5_EXAMPLE


@pytest.mark.parametrize("ended", ENDED)
def test_ended_takes_each_of_its_five_values(ended: str) -> None:
    assert AnswerLog.model_validate(log_payload(ended=ended)).ended == ended


@pytest.mark.parametrize("ended", ["finished", "max_steps", "", None])
def test_an_ended_outside_the_five_is_refused(ended: Any) -> None:
    with pytest.raises(ValidationError, match="ended"):
        AnswerLog.model_validate(log_payload(ended=ended))


def test_ended_holds_exactly_the_five() -> None:
    assert get_args(answers.Ended) == ENDED


@pytest.mark.parametrize("reason", get_args(TurnEndReason))
def test_last_turn_end_takes_each_turn_end_reason(reason: str) -> None:
    """`last_turn_end` is the last `turn.ended` reason the driver's listener saw, one of the
    product's `TurnEndReason` (`agent/providers/__init__.py`), restated nowhere."""
    assert AnswerLog.model_validate(log_payload(last_turn_end=reason)).last_turn_end == reason


@pytest.mark.parametrize("reason", ["ended", "turn_did_not_end", None])
def test_a_last_turn_end_that_is_no_turn_end_reason_is_refused(reason: Any) -> None:
    with pytest.raises(ValidationError, match="last_turn_end"):
        AnswerLog.model_validate(log_payload(last_turn_end=reason))


@pytest.mark.parametrize("reason", UNSCRIPTED_REASONS)
def test_an_unscripted_request_takes_each_of_its_three_reasons(reason: str) -> None:
    payload: dict[str, Any] = {"request_id": "ER-001", "reason": reason}
    if reason == "ambiguous":
        payload["entries"] = ["A-1", "A-2"]
    assert UnscriptedRequest.model_validate(payload).reason == reason


def test_unscripted_reasons_hold_exactly_the_three() -> None:
    assert get_args(answers.UnscriptedReason) == UNSCRIPTED_REASONS


def test_an_unscripted_reason_outside_the_three_is_refused() -> None:
    with pytest.raises(ValidationError, match="reason"):
        UnscriptedRequest.model_validate({"request_id": "ER-001", "reason": "skipped"})


@pytest.mark.parametrize("reason", ["no_answer", "names_nothing"])
def test_entries_on_an_unscripted_request_that_is_not_ambiguous_are_refused(reason: str) -> None:
    with pytest.raises(ValidationError, match="entries"):
        UnscriptedRequest.model_validate(
            {"request_id": "ER-001", "reason": reason, "entries": ["A-1", "A-2"]}
        )


@pytest.mark.parametrize("entries", [None, [], ["A-1"]], ids=["absent", "empty", "one"])
def test_an_ambiguous_request_names_the_two_or_more_entries_it_matched(entries: Any) -> None:
    """An ambiguous request matched several entries (`questions.md` 3: exactly one is a
    delivery), and the log names them (`scripted-answers.md` 5)."""
    payload: dict[str, Any] = {"request_id": "ER-001", "reason": "ambiguous"}
    if entries is not None:
        payload["entries"] = entries
    with pytest.raises(ValidationError, match="entries"):
        UnscriptedRequest.model_validate(payload)


@pytest.mark.parametrize("version", [2, 0, "1", True, None])
def test_an_answer_log_version_other_than_1_is_refused(version: Any) -> None:
    with pytest.raises(ValidationError, match="answer_log_version"):
        AnswerLog.model_validate(log_payload(answer_log_version=version))


def test_a_log_stating_no_version_is_refused() -> None:
    payload = log_payload()
    del payload["answer_log_version"]
    with pytest.raises(ValidationError, match="answer_log_version"):
        AnswerLog.model_validate(payload)


def _with_unknown_field(where: str) -> dict[str, Any]:
    payload = log_payload()
    target = {
        "log": payload,
        "point": payload["points"][0],
        "sent": payload["points"][0]["sent"][0],
        "unscripted": payload["points"][0]["unscripted"][0],
    }[where]
    target["answer"] = "press fit"
    return payload


@pytest.mark.parametrize("where", ["log", "point", "sent", "unscripted"])
def test_an_unknown_field_is_refused_at_every_level(where: str) -> None:
    """Strict, never ignored: an `answer` field anywhere is refused, so no answer text rides
    in the log (FR-051's ids only)."""
    with pytest.raises(ValidationError) as refused:
        AnswerLog.model_validate(_with_unknown_field(where))

    [error] = refused.value.errors()
    assert error["type"] == "extra_forbidden"
    assert error["loc"][-1] == "answer"


@pytest.mark.parametrize("field", ["after_turn", "steps_before"])
def test_a_negative_turn_or_step_count_is_refused(field: str) -> None:
    payload = log_payload()
    payload["points"][0][field] = -1
    with pytest.raises(ValidationError, match=field):
        AnswerLog.model_validate(payload)


def test_outside_options_is_dumped_only_when_true_and_entries_only_when_present() -> None:
    dumped = json.loads(a_log().model_dump_json())

    assert dumped["points"][0]["sent"] == [
        {"request_id": "ER-001", "entry": "A-1", "outside_options": True},
        {"request_id": "ER-002", "entry": "A-2"},
    ]
    assert dumped["points"][0]["unscripted"] == [
        {"request_id": "ER-003", "reason": "names_nothing"},
        {"request_id": "ER-004", "reason": "ambiguous", "entries": ["A-3", "A-4"]},
    ]


def test_both_omissions_are_findings_omit_at_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """One rule omits a field at its default: `findings.omit_at_default`, which the log's two
    models call by name, `outside_options` at false and `entries` at `None`."""
    omitted: list[tuple[str, tuple[str, ...]]] = []
    real = answers.omit_at_default

    def spy(data: dict[str, Any], model: Any, *names: str) -> dict[str, Any]:
        omitted.append((type(model).__name__, names))
        return real(data, model, *names)

    monkeypatch.setattr(answers, "omit_at_default", spy)

    a_log().model_dump_json()

    assert set(omitted) == {
        ("AnswerSent", ("outside_options",)),
        ("UnscriptedRequest", ("entries",)),
    }


# --- write_answer_log and read_answer_log (scripted-answers.md 5; RF-31) ------------------------


def test_the_log_is_written_through_the_one_atomic_writer_as_utf8_json_with_lf_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write_atomic = atomic.write_atomic
    calls: list[tuple[Path, bytes]] = []

    def spy(path: Path, data: bytes) -> None:
        calls.append((path, data))
        real_write_atomic(path, data)

    monkeypatch.setattr(atomic, "write_atomic", spy)
    written = write_answer_log(tmp_path, a_log())

    assert written == tmp_path / ANSWER_LOG_FILE_NAME
    assert [path for path, _ in calls] == [tmp_path / ANSWER_LOG_FILE_NAME]
    data = calls[0][1]
    assert written.read_bytes() == data
    assert data.endswith(b"}\n")
    assert not data.endswith(b"\n\n")
    assert b"\r" not in data
    assert b"\n" in data.rstrip(b"\n")
    assert json.loads(data.decode("utf-8")) == json.loads(a_log().model_dump_json())


def test_the_written_file_leaves_out_outside_options_and_entries_when_absent(
    tmp_path: Path,
) -> None:
    written = write_answer_log(tmp_path, a_log())

    record = json.loads(written.read_text(encoding="utf-8"))
    assert record["points"][0]["sent"][1] == {"request_id": "ER-002", "entry": "A-2"}
    assert record["points"][0]["unscripted"][0] == {
        "request_id": "ER-003",
        "reason": "names_nothing",
    }
    assert record["points"][1] == {
        "after_turn": 1,
        "steps_before": 17,
        "sent": [],
        "unscripted": [],
        "held": ["ER-005"],
    }


def test_a_written_log_reads_back_equal(tmp_path: Path) -> None:
    write_answer_log(tmp_path, a_log())

    assert read_answer_log(tmp_path) == a_log()
    assert read_answer_log(str(tmp_path)) == a_log()


def test_a_folder_holding_no_log_reads_none(tmp_path: Path) -> None:
    """A run folder recorded before this feature, or a session scored on its own, has no
    answer log, and its log columns read not assessed (`questions.md` 6)."""
    (tmp_path / "session.json").write_text("{}", encoding="utf-8")

    assert read_answer_log(tmp_path) is None


@pytest.mark.parametrize(
    "content",
    [
        b"not json\n",
        b"",
        json.dumps(log_payload(answer_log_version=2)).encode("utf-8"),
        json.dumps(log_payload(ended="finished")).encode("utf-8"),
        json.dumps(_with_unknown_field("sent")).encode("utf-8"),
    ],
    ids=["not-json", "empty", "version-2", "ended-outside-the-five", "unknown-field"],
)
def test_a_log_that_does_not_validate_is_refused_naming_the_folder(
    tmp_path: Path, content: bytes
) -> None:
    (tmp_path / ANSWER_LOG_FILE_NAME).write_bytes(content)

    with pytest.raises(ValueError, match=re.escape(str(tmp_path))) as refused:
        read_answer_log(tmp_path)

    assert ANSWER_LOG_FILE_NAME in str(refused.value)
    assert "\n" not in str(refused.value)


# --- the driver (T098; scripted-answers.md 3 and 4) ---------------------------------------------

PACKAGE_ID = "fict-questions"

A_1: dict[str, Any] = {"id": "A-1", "item": FIT, "ids": [PLATE_1, PIN_1], "answer": "press fit"}
"""The fit of the pin in the plate (`scripted-answers.md` 2.2's `A-1`)."""
A_2: dict[str, Any] = {
    "id": "A-2",
    "item": FASTENERS,
    "ids": [PLATE_DOC],
    "answer": "the screws are in a separate assembly",
}
"""Which fasteners go in the plate (`scripted-answers.md` 2.2's `A-2`)."""

FIT_QUESTION = ask(PIN_1, PLATE_HOLE, item=FIT)
"""The fit question, blocking `interfaces.fit` and naming the pin and the plate's hole, which
resolves to the plate's instance: `A-1` asks within it (`questions.md` 2 and 3)."""


def package_folder(tmp_path: Path) -> Path:
    """The fictional package, written where a set entry would name it."""
    folder = tmp_path / "packages" / PACKAGE_ID
    save_package(PACKAGE, folder)
    return folder


def case(tmp_path: Path, entries: Sequence[dict[str, Any]] | None) -> CaseFile | None:
    """The package's case file holding `entries`, read through `load_case_file`; `None` for a
    set entry naming no case file."""
    if entries is None:
        return None
    return write_case_file(tmp_path / "case_files", PACKAGE_ID, *entries, package=PACKAGE)


def review(
    tmp_path: Path,
    *turns: ScriptedTurn,
    entries: Sequence[dict[str, Any]] | None = (A_1, A_2),
    max_answer_turns: int = 3,
    **options: Any,
) -> Driven:
    """The fictional package reviewed into `<tmp_path>/run/<package id>`, as a benchmark run lays
    it out, by a model playing exactly `turns`, driven with a case file holding `entries` and
    the bound. `options` are `start_review`'s."""
    return drive(
        package_folder(tmp_path),
        tmp_path / "run" / PACKAGE_ID,
        scripted(*turns),
        case(tmp_path, entries),
        max_answer_turns=max_answer_turns,
        **options,
    )


def sent(request_id: str, entry: str, **fields: Any) -> AnswerSent:
    return AnswerSent(request_id=request_id, entry=entry, **fields)


def unscripted(request_id: str, reason: str = "no_answer", **fields: Any) -> UnscriptedRequest:
    return UnscriptedRequest.model_validate({"request_id": request_id, "reason": reason, **fields})


def point(
    after_turn: int,
    steps_before: int,
    *,
    delivered: Sequence[AnswerSent] = (),
    given_nothing: Sequence[UnscriptedRequest] = (),
    held: Sequence[str] = (),
) -> AnswerPoint:
    return AnswerPoint(
        after_turn=after_turn,
        steps_before=steps_before,
        sent=list(delivered),
        unscripted=list(given_nothing),
        held=list(held),
    )


def log_of(
    points: Sequence[AnswerPoint], ended: str, unused: Sequence[str], last_turn_end: str = "end"
) -> AnswerLog:
    return AnswerLog.model_validate(
        {
            "answer_log_version": ANSWER_LOG_VERSION,
            "points": [one.model_dump() for one in points],
            "ended": ended,
            "last_turn_end": last_turn_end,
            "unused_entries": list(unused),
        }
    )


def requests_of(driven: Driven) -> list[tuple[str, str, str | None]]:
    """Each request `session.json` holds: id, status, answer."""
    session = load_session(driven.run.session_path)
    return [(request.id, request.status, request.answer) for request in session.evidence_requests]


def still_open(driven: Driven) -> list[str]:
    """The reasons of the unresolved rows finalization wrote for the open requests."""
    session = load_session(driven.run.session_path)
    return [item.reason for item in session.coverage.unresolved if item.check == EVIDENCE_CHECK]


def spy_on_batches(monkeypatch: pytest.MonkeyPatch) -> list[list[tuple[str, str]]]:
    """Every `ReviewRun.answer_evidence_batch` call, answered by the real method."""
    batches: list[list[tuple[str, str]]] = []
    real = ReviewRun.answer_evidence_batch

    def spy(self: ReviewRun, answered: Sequence[tuple[str, str]]) -> Any:
        batches.append(list(answered))
        return real(self, answered)

    monkeypatch.setattr(ReviewRun, "answer_evidence_batch", spy)
    return batches


def test_an_attempt_never_asks_the_drawing_candidate_question(tmp_path: Path) -> None:
    """INT-8: the candidate question is asked only when the host opens closed drawings, and an
    attempt has no bridge, so its read mode is `none` and no confirmed read can be answered."""
    driven = review(tmp_path, turn(ScriptedToolCall("check_drawings")))

    index = DrawingIndex.for_package(driven.run.context.ir)
    roles = getattr(driven.run.context, PART_ROLES_ATTRIBUTE)
    assert candidate_question(index, roles, "opens_closed") is not None
    assert driven.run.session.drawing_read == "none"
    assert candidate_question(index, roles, driven.run.session.drawing_read) is None
    assert driven.run.session.evidence_requests == []
    assert (driven.log.points, driven.log.ended) == ([], "no_open_questions")


def test_the_fit_question_is_answered_by_its_entry_through_one_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """US4-1, FR-023: one `answer_evidence_batch` call, one `evidence.answered` event with the
    entry's text, and the review continuing into the turn that opens on `answers_message`, as
    the pane's batch opens it."""
    batches = spy_on_batches(monkeypatch)

    driven = review(
        tmp_path, turn(FIT_QUESTION, text="Which fit?"), turn(text="A press fit, then.")
    )

    assert batches == [[("ER-001", "press fit")]]
    assert driven.answered() == [{"request_id": "ER-001", "answer": "press fit"}]
    assert len(driven.provider.sent) == 2
    assert driven.provider.user_message(1) == answers_message([("ER-001", "press fit")])
    kinds = [event.type for event in driven.events]
    said = [event.body["text"] for event in driven.events if event.type == "text.done"]
    assert said == ["Which fit?", "A press fit, then."]
    last_said = len(kinds) - 1 - kinds[::-1].index("text.done")
    assert kinds.index("evidence.answered") < last_said
    assert requests_of(driven) == [("ER-001", "answered", "press fit")]
    assert driven.log == log_of(
        [point(0, 1, delivered=[sent("ER-001", "A-1")])], "no_open_questions", ["A-2"]
    )
    assert read_answer_log(driven.run.out_dir) == driven.log


def test_the_log_is_written_once_through_write_answer_log_into_the_run_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[tuple[Path, AnswerLog]] = []
    real = answers.write_answer_log

    def spy(folder: Path, log: AnswerLog) -> Path:
        written.append((Path(folder), log))
        return real(folder, log)

    monkeypatch.setattr(answers, "write_answer_log", spy)

    driven = review(tmp_path, turn(FIT_QUESTION), turn())

    assert written == [(driven.run.out_dir, driven.log)]


def test_an_unscripted_question_is_given_nothing_and_stays_unresolved(tmp_path: Path) -> None:
    """US4-2, FR-024, D3: Skip sends nothing, so the request stays open and finalization lists it
    as unresolved coverage; the log names it `no_answer`."""
    driven = review(tmp_path, turn(ask(PIN_1, item=FASTENERS)))

    assert driven.answered() == []
    assert requests_of(driven) == [("ER-001", "open", None)]
    [request] = driven.run.session.evidence_requests
    assert still_open(driven) == [f"ER-001 is still open: {request.what}"]
    assert driven.log.points == [point(0, 1, given_nothing=[unscripted("ER-001")])]


def test_a_turn_whose_open_questions_are_all_unscripted_ends_the_answering(
    tmp_path: Path,
) -> None:
    """US4-3: the fake, scripted with one turn, is asked for no second."""
    driven = review(tmp_path, turn(ask(PIN_1, item=FASTENERS), ask()))

    assert len(driven.provider.sent) == 1
    nothing = [unscripted("ER-001"), unscripted("ER-002", "names_nothing")]
    assert driven.log == log_of(
        [point(0, 2, given_nothing=nothing)], "all_unscripted", ["A-1", "A-2"]
    )


def test_two_scripted_and_one_unscripted_question_go_back_as_one_batch_in_session_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """US4-4: one batch per point, as Send sends one, in the order the session holds them."""
    batches = spy_on_batches(monkeypatch)

    driven = review(
        tmp_path,
        turn(ask(PLATE_1, item=FASTENERS), ask(PIN_1, item="interference"), FIT_QUESTION),
        turn(text="Noted."),
    )

    answered = [("ER-001", A_2["answer"]), ("ER-003", "press fit")]
    assert batches == [answered]
    assert driven.answered() == [
        {"request_id": request_id, "answer": text} for request_id, text in answered
    ]
    assert len(driven.provider.sent) == 2
    assert driven.provider.user_message(1) == answers_message(answered)
    assert driven.log.points == [
        point(
            0,
            3,
            delivered=[sent("ER-001", "A-2"), sent("ER-003", "A-1")],
            given_nothing=[unscripted("ER-002")],
        ),
        point(1, 3, given_nothing=[unscripted("ER-002")]),
    ]
    assert driven.log.ended == "all_unscripted"


def test_a_recorded_follow_up_on_an_answered_item_is_answered_again_by_the_same_entry(
    tmp_path: Path,
) -> None:
    """RF-13: an item-only follow-up is recorded by the product (`report/session.py:208`), and
    `A-1` is the one entry it asks within, so it is delivered again at the next point."""
    driven = review(tmp_path, turn(FIT_QUESTION), turn(ask(item=FIT)), turn(text="Done."))

    assert len(driven.provider.sent) == 3
    assert driven.answered() == [
        {"request_id": "ER-001", "answer": "press fit"},
        {"request_id": "ER-002", "answer": "press fit"},
    ]
    assert driven.provider.user_message(2) == answers_message([("ER-002", "press fit")])
    assert driven.log.points == [
        point(0, 1, delivered=[sent("ER-001", "A-1")]),
        point(1, 2, delivered=[sent("ER-002", "A-1")]),
    ]
    assert driven.log.ended == "no_open_questions"


def test_a_follow_up_the_guard_refuses_opens_nothing_and_the_next_point_has_no_question(
    tmp_path: Path,
) -> None:
    """RF-13's other half: naming only the plate's hole, the follow-up is covered by the answered
    question, so the product answers `already_answered` and records no request."""
    driven = review(tmp_path, turn(FIT_QUESTION), turn(ask(PLATE_HOLE, item=FIT)))

    follow_up = driven.run.session.steps[-1]
    stored = read_stored_result(
        driven.run.out_dir,
        driven.run.session.session_id,
        follow_up.index,
        tool=follow_up.tool,
        arguments=follow_up.arguments,
    )
    assert isinstance(stored, StoredResult)
    assert stored.payload["status"] == "already_answered"
    assert requests_of(driven) == [("ER-001", "answered", "press fit")]
    assert len(driven.provider.sent) == 2
    assert driven.log.points == [point(0, 1, delivered=[sent("ER-001", "A-1")])]
    assert driven.log.ended == "no_open_questions"


ASKS_AGAIN = (
    turn(ask(PLATE_HOLE, item=FIT)),
    turn(ask(PIN_1, item=FIT)),
    turn(ask(item=FIT)),
    turn(ask(PLATE_1, item=FIT)),
)
"""A model that asks the fit again in every turn, each request one the product records (no
earlier question covers it) and `A-1` asks within."""


def test_the_bound_holds_the_delivery_ready_after_the_third_answer_turn(tmp_path: Path) -> None:
    """US4-5, FR-025, D16: three answer turns, the fourth point's delivery held, nothing sent for
    it, and the session finalized with the held question open."""
    driven = review(tmp_path, *ASKS_AGAIN)

    assert len(driven.provider.sent) == 4
    assert [body["request_id"] for body in driven.answered()] == ["ER-001", "ER-002", "ER-003"]
    assert driven.log == log_of(
        [
            point(0, 1, delivered=[sent("ER-001", "A-1")]),
            point(1, 2, delivered=[sent("ER-002", "A-1")]),
            point(2, 3, delivered=[sent("ER-003", "A-1")]),
            point(3, 4, held=["ER-004"]),
        ],
        "bound_reached",
        ["A-2"],
    )
    assert load_session(driven.run.session_path).ended_at is not None
    assert requests_of(driven)[-1] == ("ER-004", "open", None)
    [held] = still_open(driven)
    assert held.startswith("ER-004 is still open")


def test_the_bound_at_0_plays_the_opening_turn_only(tmp_path: Path) -> None:
    driven = review(tmp_path, turn(FIT_QUESTION), max_answer_turns=0)

    assert len(driven.provider.sent) == 1
    assert driven.answered() == []
    assert driven.log == log_of(
        [point(0, 1, held=["ER-001"])], "bound_reached", ["A-1", "A-2"]
    )


def test_a_last_question_answered_on_the_third_answer_turn_is_not_bound_reached(
    tmp_path: Path,
) -> None:
    """QA-3: the review asked nothing more by the point after its third answer turn."""
    driven = review(tmp_path, *ASKS_AGAIN[:3], turn(text="Done."))

    assert len(driven.provider.sent) == 4
    assert [len(one.sent) for one in driven.log.points] == [1, 1, 1]
    assert driven.log.ended == "no_open_questions"


def test_open_questions_all_unscripted_at_the_bound_are_not_bound_reached(tmp_path: Path) -> None:
    """`scripted-answers.md` 4: bound-reached needs a delivery ready at the bound."""
    driven = review(
        tmp_path, turn(FIT_QUESTION), turn(ask(PIN_1, item=FASTENERS)), max_answer_turns=1
    )

    assert driven.log.points == [
        point(0, 1, delivered=[sent("ER-001", "A-1")]),
        point(1, 2, given_nothing=[unscripted("ER-002")]),
    ]
    assert driven.log.ended == "all_unscripted"


@pytest.mark.parametrize("reason", ["max_steps", "truncated", "error", "stopped"])
def test_no_answer_follows_a_turn_that_did_not_end_normally(tmp_path: Path, reason: str) -> None:
    """QA-4, D2: a turn cut at its step or output limit, or ended otherwise than normally, is the
    arm's own outcome; the scripted question it left open is not answered."""
    if reason == "max_steps":
        driven = review(tmp_path, turn(FIT_QUESTION, ask(PLATE_1, item=FASTENERS)), max_steps=1)
    else:
        driven = review(tmp_path, turn(FIT_QUESTION, end_reason=reason))

    assert len(driven.provider.sent) == 1
    assert driven.answered() == []
    assert requests_of(driven) == [("ER-001", "open", None)]
    assert driven.log == log_of([], "turn_did_not_end", ["A-1", "A-2"], last_turn_end=reason)


class FailingProvider(SpyProvider):
    """The scripted model, whose turn `fail_on` (0 the opening turn) raises."""

    def __init__(self, *, fail_on: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.fail_on = fail_on

    def run(self, **kwargs: Any) -> TurnResult:
        if len(self.sent) == self.fail_on:
            self.sent.append([dict(message) for message in kwargs["messages"]])
            raise RuntimeError("the fictional provider failed")
        return super().run(**kwargs)


@pytest.mark.parametrize(
    ("fail_on", "points", "unused"),
    [(0, [], ["A-1", "A-2"]), (1, [point(0, 1, delivered=[sent("ER-001", "A-1")])], ["A-2"])],
    ids=["opening-turn", "answer-turn"],
)
def test_a_turn_that_raises_leaves_its_log_and_then_propagates(
    tmp_path: Path, fail_on: int, points: list[AnswerPoint], unused: list[str]
) -> None:
    out = tmp_path / "run" / PACKAGE_ID
    provider = FailingProvider(fail_on=fail_on, script=[turn(FIT_QUESTION)][:fail_on], model=MODEL)

    with pytest.raises(RuntimeError, match="the fictional provider failed"):
        drive(package_folder(tmp_path), out, provider, case(tmp_path, (A_1, A_2)))

    assert len(provider.sent) == fail_on + 1
    assert read_answer_log(out) == log_of(points, "turn_did_not_end", unused, last_turn_end="error")


def test_a_turn_that_raises_before_it_says_how_it_ended_reads_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `turn.ended` reached the listener: the log still validates, the last turn read as one
    that failed, and the exception that propagates is the turn's, not the log's."""

    def start(self: ReviewRun) -> Any:
        raise RuntimeError("the turn failed before it ended")

    monkeypatch.setattr(ReviewRun, "start", start)
    out = tmp_path / "run" / PACKAGE_ID

    with pytest.raises(RuntimeError, match="the turn failed before it ended"):
        drive(package_folder(tmp_path), out, scripted(), case(tmp_path, (A_1,)))

    assert read_answer_log(out) == log_of([], "turn_did_not_end", ["A-1"], last_turn_end="error")


def test_an_item_only_request_on_an_item_with_two_entries_is_ambiguous(tmp_path: Path) -> None:
    """Spec Edge Cases: given nothing, the ambiguity named with both entries in file order."""
    on_the_plate = {**A_1, "ids": [PLATE_1]}
    on_the_pin = {**A_1, "id": "A-2", "ids": [PIN_1, PIN_2], "answer": "a slip fit"}

    driven = review(tmp_path, turn(ask(item=FIT)), entries=(on_the_plate, on_the_pin))

    assert driven.answered() == []
    ambiguous = unscripted("ER-001", "ambiguous", entries=["A-1", "A-2"])
    assert driven.log == log_of(
        [point(0, 1, given_nothing=[ambiguous])], "all_unscripted", ["A-1", "A-2"]
    )


@pytest.mark.parametrize(
    ("answer", "text", "outside"),
    [
        ("an interference fit", "an interference fit", True),
        ("  press fit \n", "press fit", False),
    ],
    ids=["outside-the-options", "one-of-them-once-trimmed"],
)
def test_an_answer_outside_a_closed_set_of_options_is_sent_verbatim_and_marked(
    tmp_path: Path, answer: str, text: str, outside: bool
) -> None:
    """QA-8: a question offering options and no text box draws buttons only, so an answer that is
    none of them is one the page could not have sent; it is sent all the same, trimmed, and
    marked `outside_options`, which the file carries only when true."""
    closed = ask(
        PIN_1, PLATE_HOLE, item=FIT, question="Which fit?", options=["press fit", "slip fit"]
    )

    driven = review(tmp_path, turn(closed), turn(), entries=({**A_1, "answer": answer},))

    [request] = driven.run.session.evidence_requests
    assert (request.options, request.allow_text) == (["press fit", "slip fit"], False)
    assert driven.answered() == [{"request_id": "ER-001", "answer": text}]
    assert driven.log.points[0].sent == [sent("ER-001", "A-1", outside_options=outside)]
    record = json.loads((driven.run.out_dir / ANSWER_LOG_FILE_NAME).read_text(encoding="utf-8"))
    assert ("outside_options" in record["points"][0]["sent"][0]) is outside


def test_an_answer_to_a_question_with_no_options_is_never_outside_them(tmp_path: Path) -> None:
    driven = review(tmp_path, turn(FIT_QUESTION), turn(), entries=({**A_1, "answer": "any"},))

    assert driven.log.points[0].sent == [sent("ER-001", "A-1")]


def test_the_log_holds_no_answer_text_and_no_path_and_names_the_unused_entries(
    tmp_path: Path,
) -> None:
    """FR-051: ids only. The delivered answer is the session's to hold; an unused answer's text
    is written nowhere in the run folder."""
    unused = {**A_2, "id": "A-3", "item": "interference", "answer": "a fictional unused answer"}

    driven = review(tmp_path, turn(FIT_QUESTION), turn(), entries=(A_1, A_2, unused))

    path = driven.run.out_dir / ANSWER_LOG_FILE_NAME
    raw = path.read_text(encoding="utf-8")
    for entry in (A_1, A_2, unused):
        assert entry["answer"] not in raw
    assert scan_file(path) == []
    assert driven.log.unused_entries == ["A-2", "A-3"]
    for written in driven.run.out_dir.rglob("*"):
        if written.is_file():
            assert b"a fictional unused answer" not in written.read_bytes(), written.name


def test_with_no_case_file_every_open_question_is_unscripted_no_answer(tmp_path: Path) -> None:
    """D3: a set entry naming no case file has no scripted answers, so even a request naming
    nothing is given nothing as `no_answer`, and no answer turn is played."""
    driven = review(tmp_path, turn(FIT_QUESTION, ask()), entries=None)

    assert len(driven.provider.sent) == 1
    nothing = [unscripted("ER-001"), unscripted("ER-002")]
    assert driven.log == log_of([point(0, 2, given_nothing=nothing)], "all_unscripted", [])


def test_the_driver_never_continues_the_session_with_text_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA-20: case files script answers only; nothing reaches `continue_session`."""

    def continue_session(self: ReviewRun, text: str) -> Any:
        raise AssertionError(f"the driver said {text!r}")

    monkeypatch.setattr(ReviewRun, "continue_session", continue_session)

    driven = review(
        tmp_path,
        turn(FIT_QUESTION, ask(PIN_1, item=FASTENERS)),
        turn(ask(item=FIT)),
        max_answer_turns=1,
    )

    assert driven.log.ended == "bound_reached"


def test_a_negative_bound_is_refused_before_any_turn(tmp_path: Path) -> None:
    provider = scripted(turn(FIT_QUESTION))
    out = tmp_path / "run" / PACKAGE_ID
    run = start_review(package_folder(tmp_path), out, provider=provider, bridge=False)

    try:
        with pytest.raises(ValueError, match="max_answer_turns"):
            drive_review(run, None, max_answer_turns=-1, stop_requested=lambda: False)
    finally:
        run.close()

    assert provider.sent == []
    assert not (out / ANSWER_LOG_FILE_NAME).exists()


def test_drive_review_requires_the_stop_requested_keyword(tmp_path: Path) -> None:
    """T191, INT-7: every caller deliberately supplies the attempt's stop predicate."""
    provider = scripted(turn())
    out = tmp_path / "run" / PACKAGE_ID
    run = start_review(package_folder(tmp_path), out, provider=provider, bridge=False)
    try:
        with pytest.raises(TypeError, match="stop_requested"):
            drive_review(run, None, max_answer_turns=3)
    finally:
        run.close()

    assert provider.sent == []
    assert not (out / ANSWER_LOG_FILE_NAME).exists()


def test_a_stop_before_an_answer_point_sends_nothing_and_writes_the_log(tmp_path: Path) -> None:
    """T191: the one scripted turn is all that may be requested after the stop is set."""
    provider = scripted(turn(FIT_QUESTION))
    out = tmp_path / "run" / PACKAGE_ID
    stop = threading.Event()
    stop.set()
    run = start_review(package_folder(tmp_path), out, provider=provider, bridge=False)
    try:
        log = drive_review(
            run,
            case(tmp_path, (A_1, A_2)),
            max_answer_turns=3,
            stop_requested=stop.is_set,
        )
    finally:
        run.close()

    assert len(provider.sent) == 1
    assert [(request.status, request.answer) for request in run.session.evidence_requests] == [
        ("open", None)
    ]
    assert log == log_of([], "stopped", ["A-1", "A-2"])
    assert read_answer_log(out) == log


# --- steps_before against the event stream (scripted-answers.md 5; questions.md 1) --------------

scripted_registry = roles.scripted_registry


def stream_steps_before(events_path: Path, request_id: str) -> int:
    """The step count the stream shows before the first `evidence.answered` for `request_id`:
    one more than the highest `tool.started` `step_index` before it, 0 when none."""
    highest = -1
    for event in replay_events(events_path):
        if event.type == "evidence.answered" and event.body["request_id"] == request_id:
            return highest + 1
        if event.type == "tool.started":
            highest = max(highest, int(event.body["step_index"]))
    raise AssertionError(f"no evidence.answered for {request_id}")


def test_each_point_s_steps_before_is_the_step_count_the_stream_shows_before_its_answers(
    tmp_path: Path, scripted_registry: None
) -> None:
    """Two answer turns and a regrade, on the roles review of `test_benchmark_answers_roles.py`:
    the restated checks are steps after point 0's answers and before point 1's, and the two
    records agree at every point that sent."""
    driven = roles.graded(
        tmp_path,
        turn(ask(item=FIT)),
        turn(text="Done."),
        entries=(roles.FIT_ANSWER, roles.ALL_BOUGHT),
        opening=ask(roles.PLATE_1, roles.PIN_1, item=FIT),
    )

    first, second = driven.log.points
    assert first.sent == [sent("ER-001", "A-3"), sent("ER-002", "A-1")]
    assert second.sent == [sent("ER-003", "A-1")]
    restated = [step.index for step in driven.run.session.steps if step.origin_mark == "regrade"]
    assert restated
    assert all(first.steps_before <= index < second.steps_before for index in restated)
    assert any(event.type == "finding.withdrawn" for event in driven.events)
    for answered_at in (first, second):
        assert answered_at.steps_before == stream_steps_before(
            driven.run.events_path, answered_at.sent[0].request_id
        )


# --- structural: runs never read a key (scripted-answers.md 6; FR-032) --------------------------

KEY_MODULES = frozenset({"swreview.benchmark.answer_key", "swreview.benchmark.answer_key_model"})
CASE_MODULES = frozenset({"swreview.benchmark.answers", "swreview.benchmark.case_file"})
SOURCE_ROOT = Path(swreview.__file__).resolve().parent


def imported_modules(path: Path) -> set[str]:
    """Every module `path` imports, `TYPE_CHECKING` imports included: `from a import b` names `a`
    and `a.b`, since `b` may be a module. The source tree imports absolutely; a relative import
    is refused here rather than read as something it is not."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module, f"{path.name}: a relative import"
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


@pytest.mark.parametrize(
    ("module", "imports"),
    [(answers, "swreview.benchmark.case_file"), (case_file, "swreview.findings")],
    ids=["answers", "case_file"],
)
def test_the_driver_and_the_case_file_import_no_answer_key_module(
    module: Any, imports: str
) -> None:
    imported = imported_modules(Path(module.__file__))

    assert imports in imported
    assert imported.isdisjoint(KEY_MODULES)


def test_importing_the_driver_loads_no_answer_key_module() -> None:
    """In a fresh interpreter, transitively: the driver's imports reach no key module."""
    code = (
        "import sys\n"
        "import swreview.benchmark.answers\n"
        "print('\\n'.join(sorted(sys.modules)))\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    loaded = completed.stdout.split()
    assert "swreview.benchmark.answers" in loaded, completed.stderr
    assert sorted(KEY_MODULES.intersection(loaded)) == []


@pytest.mark.parametrize("folder", ["tools", "agent", "checks"])
def test_no_tool_agent_or_check_module_imports_the_driver_the_case_file_or_a_key(
    folder: str,
) -> None:
    files = sorted((SOURCE_ROOT / folder).rglob("*.py"))
    assert files

    offending = {
        path.relative_to(SOURCE_ROOT).as_posix(): sorted(
            imported_modules(path) & (CASE_MODULES | KEY_MODULES)
        )
        for path in files
    }

    assert {name: found for name, found in offending.items() if found} == {}

