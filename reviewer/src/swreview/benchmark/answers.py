"""Scripted answers in a benchmark run (feature 014, `contracts/scripted-answers.md`).

This module holds the case file's one reader and the answer log's record; `drive_review` joins
them with US4 (T099).

`load_case_file` (sections 2.3 and 3; plan decisions QA-5, QA-11) reads a case file into
`benchmark/case_file.py`'s data-only model, whose own rows refuse first, then runs the rows that
need the set entry, the checklist, the package or the profile, the first failing row ending the
load. It is the only reader of a case file (section 6); it opens no file but the case file, beyond
the product's own checklist the context under `QuestionIds` loads, and it writes nothing. Every
refusal is a `CaseFileError` of one line, "case file {name}: set entry {package_id}: ...",
naming the case-file entry where there is one; `{name}` is the file's path relative to the
running checkout when it lies inside it, its file name otherwise, so no local folder reaches the
line (FR-051).

The answer log (section 5; data-model section 3; plan decisions QA-9, RF-31): `answer-log.json`,
written into each package folder by the driver alone, through the one atomic writer, and read by
the scorer in place of the case file, which only the driver ever opens. It is the driver's record
of its own decisions at each answer point, which nothing else records: what it sent, which open
questions it gave nothing and why, and what the answer-turn bound held back.

The log holds ids only: request ids and case-file entry ids, no answer text (the session
already holds every delivered answer's) and no path (FR-051). Its models are strict, so a
field this build does not know, another version, or a value outside a closed set is refused
when the log is read, never ignored.

This module imports no answer-key module (runs never read keys, FR-032), and nothing under
`tools/`, `agent/` or `checks/` imports it (T098's structural test).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self

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
from swreview.benchmark import sets
from swreview.benchmark.case_file import CaseFile, ScriptedAnswer
from swreview.benchmark.questions import QuestionIds
from swreview.checks import part_roles
from swreview.findings import ReviewModel, omit_at_default

if TYPE_CHECKING:
    from swreview.agent.checklist import Checklist, ChecklistItem
    from swreview.checks.standards.profile import StandardsProfile
    from swreview.ir.models import EvidencePackage

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


# --- the case file's reader (sections 2.3 and 3) ---------------------------------------------


class CaseFileError(ValueError):
    """A case file this build refuses to load: one line, "case file {name}: set entry
    {package_id}: ...", naming the case-file entry where there is one (section 2.3)."""


NO_UNCLEAR_PART = "no part is unclear: every part's role is decided"
"""Row 10's reason when the classifier left no part unclear, so the part-roles question would
list nothing (`checks/part_roles.roles_question`)."""


def load_case_file(
    path: Path | str,
    *,
    entry: sets.BenchmarkPackageRef,
    package: EvidencePackage,
    checklist: Checklist,
    profile: StandardsProfile | None,
) -> CaseFile:
    """Read the case file at `path` for the set entry `entry`, refusing it by section 2.3's rows.

    Row 1's unreadable or not-JSON file first, then the model's rows (1, 3 and 4), then rows 2
    and 5 to 10 in order, the first failing row ending the load. `package` and `profile` are the
    ones the review will load, so row 10 asks the product's own classifier what the review will
    ask. A file that is missing, cannot be read or is not UTF-8 is refused like one that is not
    JSON; an `OSError` is named by its `strerror`, or its type when it has none, since its text
    carries the absolute path the read was given.
    """
    path = Path(path)
    prefix = f"case file {_case_file_name(path)}: set entry {entry.package_id}:"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        reason = error.strerror or type(error).__name__
        raise CaseFileError(f"{prefix} cannot be read ({reason})") from None
    except UnicodeDecodeError as error:
        raise CaseFileError(f"{prefix} not UTF-8 ({error})") from None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise CaseFileError(f"{prefix} not JSON ({error})") from None
    try:
        case = CaseFile.model_validate(payload)
    except ValidationError as error:
        raise CaseFileError(f"{prefix} {_model_refusal(error)}") from None
    for reason in _loader_refusals(case, entry, package, checklist, profile):
        if reason is not None:
            raise CaseFileError(f"{prefix} {reason}")
    return case


def _case_file_name(path: Path) -> str:
    """How a refusal names the case file (FR-051): its path relative to the running checkout,
    `sets.REPO_ROOT` read at call time as `benchmark run` reads it, when it lies inside it, else
    its file name."""
    relative = sets.checkout_relative(path, root=sets.REPO_ROOT)
    return relative.as_posix() if relative is not None else path.name


def _model_refusal(error: ValidationError) -> str:
    """The model's refusals as one clause each: its own rows' sentences as they are written,
    which name the entry, and pydantic's as `<field>: <message>`, joined by `; `. The answer
    key's reader words its model's refusals the same way (`answer_key._model_refusal`); this
    module imports no answer-key module (FR-032), so the clause is written here."""
    clauses = []
    for line in error.errors(include_url=False):
        if line["type"] == "value_error":
            clauses.append(line["msg"].removeprefix("Value error, "))
        else:
            field = ".".join(str(part) for part in line["loc"])
            clauses.append(f"{field}: {line['msg']}" if field else line["msg"])
    return "; ".join(clauses)


def _loader_refusals(
    case: CaseFile,
    entry: sets.BenchmarkPackageRef,
    package: EvidencePackage,
    checklist: Checklist,
    profile: StandardsProfile | None,
) -> Iterator[str | None]:
    """Section 2.3's rows that need more than the model, in order, each the reason it refuses
    the file or `None`: every entry through one row before any through the next. The package's
    ids are read only once rows 2, 5 and 6 have passed."""
    yield _package_refusal(case, entry)
    asked = [answer for answer in case.answers if not answer.part_roles]
    items = {item.id: item for item in checklist.items}
    yield from (_unknown_item_refusal(answer, items) for answer in asked)
    yield from (_code_owned_refusal(answer, items) for answer in asked)
    ids = QuestionIds(package)
    yield from (_id_refusal(answer, ids) for answer in asked)
    yield from (_overlap_refusal(first, second, ids) for first, second in combinations(asked, 2))
    roles_answers = [answer for answer in case.answers if answer.part_roles]
    yield _second_roles_answer_refusal(roles_answers)
    yield _never_asked_refusal(roles_answers, package, profile)


def _package_refusal(case: CaseFile, entry: sets.BenchmarkPackageRef) -> str | None:
    """Row 2: the file answers its own set entry's package."""
    if case.package_id != entry.package_id:
        return (
            f"package_id is {case.package_id}, not the set entry's {entry.package_id} "
            "(scripted-answers.md 2.2)"
        )
    return None


def _unknown_item_refusal(answer: ScriptedAnswer, items: dict[str, ChecklistItem]) -> str | None:
    """Row 5: a stated item is a checklist item (`agent/checklist.py:64-66`)."""
    if answer.item is not None and answer.item not in items:
        return f"{answer.id} answers on {answer.item}, which is not a checklist item"
    return None


def _code_owned_refusal(answer: ScriptedAnswer, items: dict[str, ChecklistItem]) -> str | None:
    """Row 6: a code-owned item's question can never be open. `request_evidence` answers it
    `closed_by_code` and records nothing (`tools/session.py:112`)."""
    if answer.item is not None and items[answer.item].owner == "code":
        return (
            f"{answer.id} answers on {answer.item}, which code closes: request_evidence records "
            "no question on it, so it can never be asked"
        )
    return None


def _id_refusal(answer: ScriptedAnswer, ids: QuestionIds) -> str | None:
    """Row 7: every id a component instance or a document of the package. A hole or a fastener
    is refused too: a request naming one resolves to its instance (`questions.md` 2), so an entry
    names the instance."""
    for entity_id in answer.ids:
        kind = ids.context.entity_kind(entity_id)
        if kind in ("component", "document"):
            continue
        what = f"the {kind} {entity_id}" if kind is not None else f"{entity_id}, not in the package"
        return (
            f"{answer.id} names {what}: an entry names component instances or documents "
            "(scripted-answers.md 2.2)"
        )
    return None


def _overlap_refusal(first: ScriptedAnswer, second: ScriptedAnswer, ids: QuestionIds) -> str | None:
    """Row 8 (research §8.3; RR3-4; QA-11): two entries on one item, or two on no item, whose ids
    resolved to instances intersect, so a request naming a shared instance would match both.
    Disjoint entries on one item are two answers."""
    if first.item != second.item:
        return None
    shared = ids.instances(first.ids) & ids.instances(second.ids)
    if not shared:
        return None
    on = f"on {first.item}" if first.item is not None else "on no item"
    return (
        f"{first.id} and {second.id} both answer {on} and share {', '.join(sorted(shared))}: a "
        "request naming a shared instance would match both (scripted-answers.md 2.3)"
    )


def _second_roles_answer_refusal(roles_answers: list[ScriptedAnswer]) -> str | None:
    """Row 9: the part-roles question has one answer."""
    if len(roles_answers) > 1:
        first, second = roles_answers[:2]
        return f"{first.id} and {second.id} both answer the part-roles question"
    return None


def _never_asked_refusal(
    roles_answers: list[ScriptedAnswer],
    package: EvidencePackage,
    profile: StandardsProfile | None,
) -> str | None:
    """Row 10 (QA-5; US4-8): a part-roles answer when the product's classifier, over the package
    and profile the review will load, asks no part-roles question, for its reason: no profile or
    another absent state, the zero-match guard, or no unclear part."""
    if not roles_answers:
        return None
    roles = part_roles.classify_parts(package, profile, None, profile_refusal=None)
    if part_roles.roles_question(roles, package) is not None:
        return None
    if roles.state == "absent":
        reason = roles.state_reason or part_roles.STATE_NO_PROFILE
    else:
        reason = part_roles.guard_sentence(roles) or NO_UNCLEAR_PART
    return (
        f"{roles_answers[0].id} answers the part-roles question, which this review never asks: "
        f"{reason}"
    )
