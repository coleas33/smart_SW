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

The driver's bullets of this file are T098's.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from swreview import atomic
from swreview.agent.providers import TurnEndReason
from swreview.benchmark import answers
from swreview.benchmark.answers import (
    ANSWER_LOG_FILE_NAME,
    ANSWER_LOG_VERSION,
    AnswerLog,
    AnswerPoint,
    AnswerSent,
    UnscriptedRequest,
    read_answer_log,
    write_answer_log,
)

ENDED = ("no_open_questions", "all_unscripted", "bound_reached", "turn_did_not_end", "stopped")
"""`ended`'s five values (`scripted-answers.md` 5): `stopped` is in the format now and written
only once US7 gives the driver its stop (INT-7)."""

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
