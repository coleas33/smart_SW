"""Scripted answers in a benchmark run (feature 014, `contracts/scripted-answers.md`).

This module holds the case file's one reader, the answer log's record and the driver that joins
them, `drive_review` (section 3; plan decisions QA-1 to QA-4, QA-8, RF-13): it plays a review held
open the way the pane's engineer would, answering each open question from the case file through
`ReviewRun.answer_evidence_batch`, the method the pane's Send reaches, and writes the log.

`load_case_file` (sections 2.3 and 3; plan decisions QA-5, QA-11) reads a case file into
`benchmark/case_file.py`'s data-only model, whose own rows refuse first, then runs the rows that
need the set entry, the checklist, the package or the profile, the first failing row ending the
load. It is the only reader of a case file (section 6); it opens no file but the case file, beyond
the product's own checklist the context under `QuestionIds` loads, and it writes nothing. Every
refusal is a `CaseFileError` of one line, "case file {name}: set entry {package_id}: ...",
naming the case-file entry where there is one; `{name}` is the file's path relative to the
running checkout when it lies inside it, its file name otherwise, so no local folder reaches the
line (FR-051). `unreadable_case_file` words row 1's refusal the same way for a file the set loader
could take no digest of, which `runner.preflight_set` refuses before reading the package.

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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
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
from swreview.agent.runner import open_evidence_requests
from swreview.benchmark import sets
from swreview.benchmark.case_file import CaseFile, ScriptedAnswer
from swreview.benchmark.questions import QuestionIds, Unscripted, scripted_answer_for
from swreview.checks import part_roles
from swreview.findings import ReviewModel, first_refusal, model_refusals, omit_at_default

if TYPE_CHECKING:
    from swreview.agent.checklist import Checklist, ChecklistItem
    from swreview.agent.providers import AgentEvent
    from swreview.agent.runner import ReviewRun
    from swreview.checks.standards.profile import StandardsProfile
    from swreview.ir.models import EvidencePackage
    from swreview.report.session import EvidenceRequest

ANSWER_LOG_FILE_NAME = "answer-log.json"
"""Where the log sits: `<run>/<package_id>/answer-log.json`, beside the package's session."""

ANSWER_LOG_VERSION = 1
"""The one answer-log version this build writes and reads."""

DEFAULT_MAX_ANSWER_TURNS = 3
"""How many answer turns a review may take after its opening turn unless `benchmark run
--max-answer-turns` says otherwise (`contracts/scripted-answers.md` 4; D14.3)."""

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
        return omit_at_default(handler(self), self, "entries")


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
        raise ValueError(
            f"{folder}: {ANSWER_LOG_FILE_NAME} does not validate: {first_refusal(error)}"
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
    prefix = _prefix(path, entry)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CaseFileError(f"{prefix} cannot be read ({_read_failure(error)})") from None
    except UnicodeDecodeError as error:
        raise CaseFileError(f"{prefix} not UTF-8 ({error})") from None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise CaseFileError(f"{prefix} not JSON ({error})") from None
    try:
        case = CaseFile.model_validate(payload)
    except ValidationError as error:
        raise CaseFileError(f"{prefix} {model_refusals(error)}") from None
    for reason in _loader_refusals(case, entry, package, checklist, profile):
        if reason is not None:
            raise CaseFileError(f"{prefix} {reason}")
    return case


def unreadable_case_file(path: Path | str, *, entry: sets.BenchmarkPackageRef) -> CaseFileError:
    """Row 1's refusal of a case file the set loader could take no digest of, which
    `runner.preflight_set` raises before reading the entry's package (`benchmark/sets.py` leaves
    `case_file_sha256` absent for a file it cannot read).

    The reason is the read's own, as `load_case_file` names it. A file that reads by now is
    refused all the same: the saved set would carry no digest of the answers the run read.
    """
    path = Path(path)
    try:
        path.read_bytes()
    except OSError as error:
        return CaseFileError(f"{_prefix(path, entry)} cannot be read ({_read_failure(error)})")
    return CaseFileError(f"{_prefix(path, entry)} could not be read when the set was loaded")


def _prefix(path: Path, entry: sets.BenchmarkPackageRef) -> str:
    """How every refusal starts: the case file, then the set entry it was loaded for."""
    return f"case file {_case_file_name(path)}: set entry {entry.package_id}:"


def _read_failure(error: OSError) -> str:
    """An `OSError` as a refusal names it: its `strerror`, or its type when it has none, never
    its text, which carries the absolute path the read was given (FR-051)."""
    return error.strerror or type(error).__name__


def _case_file_name(path: Path) -> str:
    """How a refusal names the case file (FR-051): its path relative to the running checkout,
    `sets.REPO_ROOT` read at call time as `benchmark run` reads it, when it lies inside it, else
    its file name."""
    relative = sets.checkout_relative(path, root=sets.REPO_ROOT)
    return relative.as_posix() if relative is not None else path.name


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


# --- the driver (sections 3 and 4) -------------------------------------------------------------


@dataclass(frozen=True)
class _Delivery:
    """One open request a point answers: its row in the log, and the text that goes back."""

    sent: AnswerSent
    text: str


def drive_review(
    run: ReviewRun, case_file: CaseFile | None, *, max_answer_turns: int
) -> AnswerLog:
    """Play `run` as the pane's engineer would, answering its questions from `case_file`, and
    write its answer log into `run.out_dir` (sections 3 to 5; QA-1 to QA-4, QA-8, QA-9, RF-13).

    The opening turn is `run.start()`, as the pane plays it. At each answer point after a turn
    that ended normally, the open requests are matched afresh, in session order, through the one
    matcher (`questions.scripted_answer_for`; with no case file every one is `no_answer`), the
    point is recorded with `steps_before` the session's step count, and its deliveries go back
    in one `run.answer_evidence_batch`, each entry's answer trimmed: what the pane's Send sends.
    An entry is delivered at every point where it is the one entry an open request asks within,
    so a question asked again and recorded is answered again (RF-13). Answering stops at the
    first point where the last turn did not end normally (`turn_did_not_end`, D2), nothing is
    open (`no_open_questions`, no point recorded), nothing has a delivery (`all_unscripted`: an
    unscripted question gets nothing, D3), or `max_answer_turns` answer turns have been played
    (`bound_reached`: the deliveries held, nothing sent; QA-3).

    How each turn ended is read off `run.sink`, since `start` and `answer_evidence_batch` return
    the session, not the turn's result. The log is written in a `finally`, so a turn that raises
    leaves one reading `turn_did_not_end` before the exception propagates; when no `turn.ended`
    reached the listener at all, `last_turn_end` reads `error`, the turn having failed before it
    said how it ended. The driver never calls `continue_session` (QA-20), reads no key and
    writes no case-file text, and no product method changes for it: `answer_evidence_batch`'s
    own refusals cannot fire on a batch naming only requests the session holds open.
    """
    if max_answer_turns < 0:
        raise ValueError(f"max_answer_turns is {max_answer_turns}; the bound is 0 or more")
    turn_ends: list[TurnEndReason] = []

    def keep_turn_end(event: AgentEvent) -> None:
        if event.type == "turn.ended":
            turn_ends.append(event.body["reason"])

    run.sink.add_listener(keep_turn_end)
    entries = case_file.answers if case_file is not None else []
    points: list[AnswerPoint] = []
    ended: Ended = "turn_did_not_end"
    try:
        ended = _answer_points(run, case_file, points, turn_ends, max_answer_turns)
    finally:
        delivered = {one.entry for point in points for one in point.sent}
        log = AnswerLog(
            answer_log_version=ANSWER_LOG_VERSION,
            points=points,
            ended=ended,
            last_turn_end=turn_ends[-1] if turn_ends else "error",
            unused_entries=[entry.id for entry in entries if entry.id not in delivered],
        )
        write_answer_log(run.out_dir, log)
    return log


def _answer_points(
    run: ReviewRun,
    case_file: CaseFile | None,
    points: list[AnswerPoint],
    turn_ends: Sequence[TurnEndReason],
    max_answer_turns: int,
) -> Ended:
    """The opening turn, then one answer point after each turn until one stops the review,
    returning why. `points` gains each point as it is recorded, so a turn that raises leaves
    the points before it for the log."""
    run.start()
    played = 0
    while True:
        if not turn_ends or turn_ends[-1] != "end":
            return "turn_did_not_end"
        requests = open_evidence_requests(run.session)
        if not requests:
            return "no_open_questions"
        deliveries, unscripted = _decide(requests, case_file, ids=QuestionIds(run.context.ir))
        held = bool(deliveries) and played == max_answer_turns
        points.append(
            AnswerPoint(
                after_turn=played,
                steps_before=len(run.session.steps),
                sent=[] if held else [delivery.sent for delivery in deliveries],
                unscripted=unscripted,
                held=[delivery.sent.request_id for delivery in deliveries] if held else [],
            )
        )
        if not deliveries:
            return "all_unscripted"
        if held:
            return "bound_reached"
        run.answer_evidence_batch(
            [(delivery.sent.request_id, delivery.text) for delivery in deliveries]
        )
        played += 1


def _decide(
    requests: Sequence[EvidenceRequest], case_file: CaseFile | None, *, ids: QuestionIds
) -> tuple[list[_Delivery], list[UnscriptedRequest]]:
    """Each open request matched (`questions.md` 3's third use), in the order given: a delivery
    of the one entry it asks within, its answer trimmed as the pane trims it, or unscripted with
    its reason, an ambiguous one naming the entries it matched. With no case file every request
    is `no_answer`. `ids` is the package as the review holds it now."""
    answers = {entry.id: entry.answer for entry in case_file.answers} if case_file else {}
    deliveries: list[_Delivery] = []
    unscripted: list[UnscriptedRequest] = []
    for request in requests:
        decided = (
            scripted_answer_for(request, case_file.answers, ids=ids)
            if case_file is not None
            else Unscripted("no_answer")
        )
        if isinstance(decided, Unscripted):
            unscripted.append(
                UnscriptedRequest(
                    request_id=request.id,
                    reason=decided.reason,
                    entries=list(decided.entries) if decided.reason == "ambiguous" else None,
                )
            )
            continue
        text = answers[decided.entry_id].strip()
        sent = AnswerSent(
            request_id=request.id,
            entry=decided.entry_id,
            outside_options=_outside_options(request, text),
        )
        deliveries.append(_Delivery(sent, text))
    return deliveries, unscripted


def _outside_options(request: EvidenceRequest, text: str) -> bool:
    """QA-8: the question offers options and no text box, so the page draws buttons only, and
    `text` is none of them: an answer the page could not have sent, sent all the same."""
    return bool(request.options) and not request.allow_text and text not in request.options
