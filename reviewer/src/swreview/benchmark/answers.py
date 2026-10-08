"""Scripted answers in a benchmark run (feature 014, `contracts/scripted-answers.md`).

For now this module holds the answer log's record (section 5; data-model section 3; plan
decisions QA-9, RF-31): `answer-log.json`, written into each package folder by the driver
alone, through the one atomic writer, and read by the scorer in place of the case file, which
only the driver ever opens. It is the driver's record of its own decisions at each answer
point, which nothing else records: what it sent, which open questions it gave nothing and why,
and what the answer-turn bound held back. `load_case_file` and `drive_review` join it with
US4 (T090, T099).

The log holds ids only: request ids and case-file entry ids, no answer text (the session
already holds every delivered answer's) and no path (FR-051). Its models are strict, so a
field this build does not know, another version, or a value outside a closed set is refused
when the log is read, never ignored.

This module imports no answer-key module (runs never read keys, FR-032), and nothing under
`tools/`, `agent/` or `checks/` imports it (T098's structural test).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    field_validator,
    model_serializer,
    model_validator,
)

from swreview import atomic
from swreview.agent.providers import TurnEndReason
from swreview.findings import ReviewModel, omit_at_default

ANSWER_LOG_FILE_NAME = "answer-log.json"
"""Where the log sits: `<run>/<package_id>/answer-log.json`, beside the package's session."""

ANSWER_LOG_VERSION = 1
"""The one answer-log version this build writes and reads."""

Ended = Literal[
    "no_open_questions", "all_unscripted", "bound_reached", "turn_did_not_end", "stopped"
]
"""Why the driver stopped answering (`scripted-answers.md` 3 and 5). `stopped`, the attempt's
stop set at an answer point, is part of the format now and written only once US7 gives the
driver its stop (plan decision INT-7)."""

UnscriptedReason = Literal["no_answer", "ambiguous", "names_nothing"]
"""Why an open request was given nothing at a point (`questions.md` 3): no entry asks within it,
several do, or it names no item and no id."""


class AnswerSent(ReviewModel):
    """One delivery: an open request answered at a point, and the case-file entry that answered
    it."""

    request_id: str
    entry: str
    outside_options: bool = False
    """The entry's answer is not one of the question's options while the question offers no
    text box: sent, shown, never scored (plan decision QA-8). Omitted when false, as the
    session omits its false fields."""

    @model_serializer(mode="wrap")
    def _omit_outside_options_when_false(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        return omit_at_default(handler(self), self, "outside_options")


class UnscriptedRequest(ReviewModel):
    """An open request given nothing at a point, with the reason; an ambiguous one names the
    entries it matched, in file order, and no other carries `entries`."""

    request_id: str
    reason: UnscriptedReason
    entries: list[str] | None = None

    @model_validator(mode="after")
    def _entries_on_ambiguous_only(self) -> Self:
        if self.reason == "ambiguous":
            if self.entries is None or len(self.entries) < 2:
                raise ValueError(
                    f"{self.request_id}: an ambiguous request names the two or more entries "
                    f"it matched, not {self.entries!r}"
                )
        elif self.entries is not None:
            raise ValueError(
                f"{self.request_id}: only an ambiguous request names entries; "
                f"this one is {self.reason}"
            )
        return self

    @model_serializer(mode="wrap")
    def _omit_entries_when_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if self.entries is None:
            data.pop("entries", None)
        return data


class AnswerPoint(ReviewModel):
    """One answer point: the moment after a turn ended normally and before the next one."""

    after_turn: int = Field(ge=0)
    """The turn the point follows: 0 for the opening turn, `k` for the `k`-th answer turn."""
    steps_before: int = Field(ge=0)
    """`len(session.steps)` at the point: every step with this index or later comes after this
    point's answers, the restated regrade steps included (`questions.md` 1 places answers in
    time with it)."""
    sent: list[AnswerSent]
    """The deliveries, in session order."""
    unscripted: list[UnscriptedRequest]
    held: list[str]
    """The request ids a delivery was ready for when the answer-turn bound stopped the review."""


class AnswerLog(ReviewModel):
    """One package's `answer-log.json` (`scripted-answers.md` 5).

    Answer turns played are the points with a non-empty `sent`; the count is derived where it is
    rendered, never stored.
    """

    answer_log_version: int
    points: list[AnswerPoint]
    ended: Ended
    last_turn_end: TurnEndReason
    """The last `turn.ended` reason the driver's listener saw."""
    unused_entries: list[str]
    """The case file's entry ids no point delivered, held ones included."""

    @field_validator("answer_log_version")
    @classmethod
    def _version_1(cls, value: int) -> int:
        if value != ANSWER_LOG_VERSION:
            raise ValueError(
                f"answer_log_version is {value!r}; this build reads answer log version "
                f"{ANSWER_LOG_VERSION}"
            )
        return value


def write_answer_log(folder: Path | str, log: AnswerLog) -> Path:
    """Write `log` to `folder / ANSWER_LOG_FILE_NAME`, returning where it landed.

    UTF-8 bytes with `\\n` line endings and a final newline through the one atomic writer, so
    the record is the same bytes on every platform and a reader never sees half of it. The
    folder is the package's, which the review made.
    """
    path = Path(folder) / ANSWER_LOG_FILE_NAME
    atomic.write_atomic(path, (log.model_dump_json(indent=2) + "\n").encode("utf-8"))
    return path


def read_answer_log(folder: Path | str) -> AnswerLog | None:
    """The log in `folder`, or `None` when it holds none.

    `None` rather than an error: a run folder recorded before this feature, or a session scored
    on its own, has no log, and the columns that read it are not assessed (`questions.md` 6).
    A log that is there and does not validate is refused with one `ValueError` line naming the
    folder.
    """
    folder = Path(folder)
    try:
        raw = (folder / ANSWER_LOG_FILE_NAME).read_bytes()
    except FileNotFoundError:
        return None
    try:
        return AnswerLog.model_validate_json(raw)
    except ValidationError as error:
        first = error.errors(include_url=False)[0]
        field = ".".join(str(part) for part in first["loc"])
        where = f"{field}: " if field else ""
        raise ValueError(
            f"{folder}: {ANSWER_LOG_FILE_NAME} does not validate: {where}{first['msg']}"
        ) from None
