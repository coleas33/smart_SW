"""The questions a review asked: request calls, the one matcher, and the question columns.

Feature 014 `contracts/questions.md` sections 1 to 4 and 6 (plan decisions RF-6, RF-30, INT-2,
QA-10 to QA-18). The one module the answer driver and the scorer both read questions through:
there is no second matcher (FR-053).

- **Request calls** (section 1): every `request_evidence` step, read with its stored full result
  through `tools/registry.read_stored_result`, the one reader beside its one writer. The stored
  result gives the outcome, `recorded` for a new request or one of the product's three refusals,
  and the request id; an error envelope is no question (QA-10); a result that cannot be read is
  kept as an unreadable call with its reason, and the columns that need every call read as not
  assessed, never guessed (Principle I).
- **Ids** (section 2): `QuestionIds`, one per package, on the lookups `request_evidence`
  validated the call's ids against: a hole or a fastener reads as the instance that owns it, a
  document as every instance of it (itself when it has none), anything else as itself; a
  document is named as the drawing guard names it (`tools/session.documents_named`).
- **The one relation** (section 3): `asks_within` is the product's `report.session.covers`,
  asked of ids resolved to instances, plus one branch, an item asked again with no ids. It holds
  no second copy of `covers`.
- **Scripted answers** (section 3's third use): `scripted_answer_for`, the one decision the
  answer driver makes for an open request, a delivery of the one case-file entry it asks within
  or unscripted with its reason.
- **The part-roles question** (section 4): matched by its identity alone.
- **The columns** (section 6): re-asks, repeats of open questions, unanswerable and unmatched
  requests, question counts, unscripted questions and whether the answer-turn bound was
  reached, each `None` with its reason in `not_assessed` where the section says it cannot be
  assessed.

The key's question entries are refused at load by `question_entry_refusals` (section 5.3), the
key loader's row 11. This module imports `benchmark/answer_key_model.py`,
`benchmark/answers.py` and `benchmark/case_file.py` only for annotations: the scorer passes it
the key's entries and the parsed answer log, and the driver the case file's entries, so the
driver, which imports this module, loads no key module and no import cycle forms
(`scripted-answers.md` 6; FR-032).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from swreview.checks import part_roles
from swreview.findings import ReviewModel
from swreview.ir.models import EvidencePackage
from swreview.report.session import EvidenceRequest, ReviewSession, covers
from swreview.tools.context import ToolContext, context_for
from swreview.tools.registry import Unstored, UnstoredReason, read_stored_result
from swreview.tools.session import (
    ALREADY_ANSWERED,
    ALREADY_ASKED,
    CLOSED_BY_CODE,
    documents_named,
)

if TYPE_CHECKING:
    from swreview.agent.checklist import Checklist
    from swreview.benchmark.answer_key_model import (
        AnswerKey,
        QuestionCount,
        UnanswerableRequest,
    )
    from swreview.benchmark.answers import AnswerLog, UnscriptedReason, UnscriptedRequest
    from swreview.benchmark.case_file import ScriptedAnswer

REQUEST_TOOL = "request_evidence"
"""The one tool a question is asked with; every call of it is a request call (section 1)."""

Outcome = Literal["recorded", "already_answered", "already_asked", "closed_by_code"]
"""What a request call came to (section 1's table): `recorded`, seen by the engineer, or one of
the product's three refusals."""

_OUTCOMES: dict[str, Outcome] = {
    "open": "recorded",
    ALREADY_ANSWERED: "already_answered",
    ALREADY_ASKED: "already_asked",
    CLOSED_BY_CODE: "closed_by_code",
}
"""The stored result's `payload.status`, as `request_evidence` writes it, to its outcome."""

NO_UNANSWERABLE_REQUEST = "the key holds no unanswerable request"
NO_QUESTION_COUNT_RULE = "the key holds no question-count rule"
NO_ANSWER_LOG = "the package has no answer log"
ANSWERED_WITHOUT_LOG = (
    "the session holds answered requests and the package has no answer log to place them in time"
)
"""`not_assessed`'s reasons for the question columns (section 6), beside the unreadable
calls' reason, which names each step."""


# --- section 2: ids ----------------------------------------------------------------------------


class QuestionIds:
    """One package's ids, as the questions are compared (section 2; plan decision QA-11).

    Built on `tools/context.context_for(package)`, whose lookups are the ones `request_evidence`
    validated a call's ids against. Ids are read as instances for re-asks, repeats of open
    questions, scripted answers and question-count rules, and as documents, the drawing guard's
    rule, for unanswerable requests only.
    """

    def __init__(self, package: EvidencePackage) -> None:
        self.context: ToolContext = context_for(package)
        self._instances_of: dict[str, list[str]] = {}
        for component in package.components:
            self._instances_of.setdefault(component.document_id, []).append(component.id)

    def instances(self, entity_ids: Iterable[str]) -> frozenset[str]:
        """Each id as instances: a hole or a fastener its instance, a document every instance
        of it or itself when it has none (the root assembly), any other id itself. Two
        instances of one pin stay two."""
        return frozenset(
            instance for entity_id in entity_ids for instance in self._instance_of(entity_id)
        )

    def _instance_of(self, entity_id: str) -> list[str]:
        hole = self.context.hole(entity_id)
        if hole is not None:
            return [hole.component_id]
        fastener = self.context.fastener(entity_id)
        if fastener is not None:
            return [fastener.component_id]
        if self.context.document(entity_id) is not None:
            return self._instances_of.get(entity_id, [entity_id])
        return [entity_id]

    def documents(self, entity_ids: Sequence[str]) -> list[str]:
        """The documents the ids name, as the drawing guard names them (`documents_named`)."""
        return documents_named(self.context, entity_ids)


# --- section 1: request calls --------------------------------------------------------------------


@dataclass(frozen=True)
class RequestCall:
    """A `request_evidence` step with its stored result: a question (data-model section 6)."""

    step: int
    item: str | None
    """`arguments.blocks`, the checklist item, `None` when the call named none."""
    ids: tuple[str, ...]
    """`arguments.entity_ids`, raw."""
    instances: frozenset[str]
    """The same ids resolved to instances (section 2)."""
    outcome: Outcome
    request_id: str | None
    """The recorded request's id, or the one a refusal cites; `None` when closed by code."""


@dataclass(frozen=True)
class UnreadableCall:
    """A `request_evidence` step whose stored result could not be read, and why."""

    step: int
    reason: UnstoredReason


def request_calls(
    session: ReviewSession, run_dir: Path, ids: QuestionIds
) -> list[RequestCall | UnreadableCall]:
    """Every request call of `session`, in step order, each read with its stored result through
    `read_stored_result`, passing the step's tool and arguments (plan decision RF-30).

    An error envelope is no question and is left out (QA-10). A stored result that is not
    `request_evidence`'s answer, a status outside section 1's table or a request it does not
    name, is `unreadable`, as one the reader cannot read.
    """
    calls: list[RequestCall | UnreadableCall] = []
    for step in session.steps:
        if step.tool != REQUEST_TOOL:
            continue
        stored = read_stored_result(
            run_dir, session.session_id, step.index, tool=step.tool, arguments=step.arguments
        )
        if isinstance(stored, Unstored):
            calls.append(UnreadableCall(step.index, stored.reason))
            continue
        if stored.status == "error":
            continue
        outcome = _OUTCOMES.get(str(stored.payload.get("status")))
        cited = stored.payload.get("evidence_request")
        request_id = cited.get("id") if isinstance(cited, dict) else None
        if outcome is None or (outcome != "closed_by_code" and not isinstance(request_id, str)):
            calls.append(UnreadableCall(step.index, "unreadable"))
            continue
        raw = tuple(step.arguments.get("entity_ids") or ())
        calls.append(
            RequestCall(
                step=step.index,
                item=step.arguments.get("blocks"),
                ids=raw,
                instances=ids.instances(raw),
                outcome=outcome,
                request_id=request_id if outcome != "closed_by_code" else None,
            )
        )
    return calls


# --- section 3: the one relation -----------------------------------------------------------------


def asks_within(
    later_item: str | None,
    later_ids: Collection[str],
    earlier_item: str | None,
    earlier_ids: Collection[str],
    *,
    ids: QuestionIds,
) -> bool:
    """Whether a later request on `later_item` naming `later_ids` asks within an earlier
    question on `earlier_item` naming `earlier_ids` (section 3; plan decision RF-6).

    `covers`, the product's predicate, asked of both id sets resolved to instances, widened by
    one branch: a later request naming an item and no ids asks within any earlier question on
    that item, where the product covers it only when the earlier one named no ids either
    (R-3's "now give numeric limits"). A request naming neither an item nor an id asks within
    nothing, as `covers` never covers one.
    """
    later = ids.instances(later_ids)
    if covers(later_item, later, earlier_item, ids.instances(earlier_ids)):
        return True
    return later_item is not None and not later and later_item == earlier_item


# --- section 4: the part-roles question ----------------------------------------------------------


def is_part_roles_question(request: EvidenceRequest) -> bool:
    """Whether `request` is the part-roles question (section 4; plan decision QA-14): written by
    code, in `part_roles.QUESTION`'s words, offering its two options, blocking no item. Its
    entity ids are not compared: the spec needs the profile, which the scorer has only as a
    digest. A model question in its words is not it."""
    return (
        request.source == "code"
        and request.question == part_roles.QUESTION
        and tuple(request.options) == (part_roles.OPTION_ALL, part_roles.OPTION_NONE)
        and request.blocks is None
    )


# --- section 3's third use: a scripted answer ----------------------------------------------------


@dataclass(frozen=True)
class Delivery:
    """An open request answered at a point by the one case-file entry it asks within."""

    entry_id: str


@dataclass(frozen=True)
class Unscripted:
    """An open request given nothing at a point, and why: no entry asks within it, several do,
    or it names no item and no id."""

    reason: UnscriptedReason
    entries: tuple[str, ...] = ()
    """The entries an `ambiguous` request matched, in file order; empty for the other reasons."""


def scripted_answer_for(
    request: EvidenceRequest, answers: Sequence[ScriptedAnswer], *, ids: QuestionIds
) -> Delivery | Unscripted:
    """The case-file entry that answers the open `request`, or why none does (section 3's third
    use; FR-053, QA-13, QA-14): the one decision the answer driver makes for each request.

    The part-roles question is answered by the `part_roles` entry alone, matched by its identity
    and never by ids (section 4). Any other request, model- or code-written, is matched against
    every entry that is not `part_roles` through `asks_within`, the request as the later one:
    exactly one match is a delivery; several are `ambiguous`, naming them in file order (the case
    file's row 8 leaves only a request naming an item and no ids able to match two); none is
    `no_answer`, or `names_nothing` when the request names no item and no id, which asks within
    nothing.
    """
    if is_part_roles_question(request):
        entry_id = next((answer.id for answer in answers if answer.part_roles), None)
        return Delivery(entry_id) if entry_id is not None else Unscripted("no_answer")
    matched = tuple(
        answer.id
        for answer in answers
        if not answer.part_roles
        and asks_within(request.blocks, request.entity_ids, answer.item, answer.ids, ids=ids)
    )
    if len(matched) == 1:
        return Delivery(matched[0])
    if matched:
        return Unscripted("ambiguous", matched)
    if _names_nothing(request.blocks, request.entity_ids):
        return Unscripted("names_nothing")
    return Unscripted("no_answer")


# --- section 5.3: the key's question entries, refused at load ------------------------------------


def question_entry_refusals(
    key: AnswerKey, *, checklist: Checklist, ids: QuestionIds | None
) -> Iterator[str | None]:
    """Section 5.3's refusals of the key's unanswerable and question-count entries, in its
    order, each the reason it refuses the key naming the entry, or `None`: the key loader's row
    11 (`answer-key.md` 4).

    `ids` is the package's resolver, or `None` when the package is not on disk: the rows that
    resolve an id then do not run, and the ids stay unchecked, as row 13's do (D7).
    """
    items = {item.id for item in checklist.items}
    yield from _unanswerable_refusals(key.unanswerable_requests, items, ids)
    yield from _count_rule_refusals(key, items, ids)


def _unanswerable_refusals(
    entries: Sequence[UnanswerableRequest], items: set[str], ids: QuestionIds | None
) -> Iterator[str | None]:
    """The unanswerable rows of section 5.3, each over every entry before the next row runs."""
    for entry in entries:
        if not entry.documents:
            yield f"{entry.id} names no documents: documents is empty (questions.md 5.3)"
    if ids is not None:
        for entry in entries:
            for document_id in entry.documents:
                if ids.context.document(document_id) is None:
                    yield (
                        f"{entry.id} names {document_id}, which is not a document of the "
                        "package (questions.md 5.3)"
                    )
    for entry in entries:
        if entry.item is not None and entry.item not in items:
            yield f"{entry.id} names the item {entry.item}, which is not a checklist item"
    for entry in entries:
        repeated = sorted({doc for doc in entry.documents if entry.documents.count(doc) > 1})
        if repeated:
            yield f"{entry.id} names {', '.join(repeated)} twice in documents"
    for index, first in enumerate(entries):
        for second in entries[index + 1 :]:
            shared = set(first.documents) & set(second.documents)
            if shared and (first.item is None or second.item is None or first.item == second.item):
                yield (
                    f"{first.id} and {second.id} both name {', '.join(sorted(shared))} on one "
                    "item: one call would count twice (questions.md 5.3)"
                )


def _count_rule_refusals(
    key: AnswerKey, items: set[str], ids: QuestionIds | None
) -> Iterator[str | None]:
    """The count-rule rows of section 5.3, each over every rule before the next row runs."""
    rules = key.question_counts
    for rule in rules:
        if (rule.part_roles is None) == (rule.item is None):
            yield f"{rule.id} counts the part-roles question or an item: name exactly one"
    for rule in rules:
        if rule.part_roles and rule.ids:
            yield f"{rule.id} names ids beside part_roles: the part-roles question names none"
    for rule in rules:
        if rule.min == 0 and rule.max is None:
            yield f"{rule.id} states neither min nor max, so it bounds nothing (a min of 0 is none)"
    for rule in rules:
        if rule.min not in (0, 1):
            yield f"{rule.id} states min {rule.min}: min is 0 or 1 (questions.md 5.2)"
    for rule in rules:
        if rule.max is not None and rule.max < rule.min:
            yield f"{rule.id} states max {rule.max}, below its min {rule.min}"
    for rule in rules:
        if rule.item is not None and rule.item not in items:
            yield f"{rule.id} names the item {rule.item}, which is not a checklist item"
    if ids is not None:
        for rule in rules:
            for entity_id in rule.ids:
                if ids.context.entity_kind(entity_id) not in ("component", "document"):
                    yield (
                        f"{rule.id} names {entity_id}, which is not a component instance or a "
                        "document of the package (questions.md 5.3)"
                    )
    roles_rules = [rule.id for rule in rules if rule.part_roles]
    if len(roles_rules) > 1:
        yield f"{' and '.join(roles_rules)} both count the part-roles question"
    item_rules = [rule for rule in rules if rule.item is not None]
    for index, first in enumerate(item_rules):
        for second in item_rules[index + 1 :]:
            if first.item == second.item and _rule_ids_meet(first.ids, second.ids, ids):
                yield (
                    f"{first.id} and {second.id} both count {first.item} on the same ids: one "
                    "call would count under both (questions.md 5.3)"
                )
    if ids is not None:
        for rule in item_rules:
            if rule.min != 1:
                continue
            for entry in key.unanswerable_requests:
                if _matches_unanswerable(rule.item, rule.ids, entry, ids):
                    yield (
                        f"{rule.id} demands a question {entry.id} calls unanswerable: the one "
                        "question the oracle asks for it would match it (questions.md 5.3)"
                    )


def _rule_ids_meet(first: Sequence[str], second: Sequence[str], ids: QuestionIds | None) -> bool:
    """Whether two rules on one item could count one call: either names no ids, or their ids,
    resolved to instances when the package is present, intersect."""
    if not first or not second:
        return True
    if ids is None:
        return not set(first).isdisjoint(second)
    return not ids.instances(first).isdisjoint(ids.instances(second))


def _matches_unanswerable(
    item: str | None, entity_ids: Sequence[str], entry: UnanswerableRequest, ids: QuestionIds
) -> bool:
    """Section 5.1's match: a call's ids name one of the entry's documents, and the entry names
    no item or the call's."""
    named = set(ids.documents(entity_ids))
    return not named.isdisjoint(entry.documents) and entry.item in (None, item)


# --- section 6: the columns ----------------------------------------------------------------------


class CallRow(ReviewModel):
    """A request call as a question column lists it."""

    step: int = Field(ge=0)
    outcome: Outcome
    request_id: str | None
    """The recorded request's id or the one a refusal cites; `None` when closed by code."""


class RepeatRow(CallRow):
    """A re-ask, or a repeat of an open question: the call, and the question it asks again."""

    of: str


class UnanswerableRow(CallRow):
    """A call matching an unanswerable request: the call, and the entry it matched."""

    entry: str


class CountRow(ReviewModel):
    """A question-count rule's count, and its bounds; a miss is derived, never stored (SP-14)."""

    entry: str
    count: int = Field(ge=0)
    min: int
    max: int | None

    @property
    def missed(self) -> bool:
        """Section 5.2's miss: a count below `min` or above `max`."""
        return self.count < self.min or (self.max is not None and self.count > self.max)


@dataclass(frozen=True)
class QuestionColumns:
    """The question columns of one package (section 6), each `None` when it cannot be assessed,
    with the reason in `not_assessed`."""

    re_asks: list[RepeatRow] | None
    open_repeats: list[RepeatRow] | None
    unanswerable_requests: list[UnanswerableRow] | None
    unmatched_requests: list[CallRow] | None
    question_counts: list[CountRow] | None
    unscripted_questions: list[UnscriptedRequest] | None
    bound_reached: bool | None
    not_assessed: dict[str, str]


def question_columns(
    session: ReviewSession,
    *,
    run_dir: Path,
    ids: QuestionIds,
    answer_log: AnswerLog | None,
    unanswerable: Sequence[UnanswerableRequest],
    count_rules: Sequence[QuestionCount],
) -> QuestionColumns:
    """The question columns of the package in `run_dir`, its `session` and its answer log
    (section 6), against the key's unanswerable requests and question-count rules.

    The log is checked against the session first: a disagreement refuses the package with one
    line naming the request. A question is answered before a call when the log's point that
    sent it has `steps_before` at most the call's index, and open at a call when the call that
    recorded it came earlier and it was not answered before the call (section 1). Only
    model-written questions are earlier questions (QA-12): a code question covers only itself.
    """
    if answer_log is not None:
        _check_log(session, answer_log, run_dir)
    calls = request_calls(session, run_dir, ids)
    readable = [call for call in calls if isinstance(call, RequestCall)]
    unreadable = [call for call in calls if isinstance(call, UnreadableCall)]
    not_assessed: dict[str, str] = {}
    unreadable_reason = _unreadable_reason(unreadable)
    placed = _answer_points(answer_log)
    answered = any(request.status == "answered" for request in session.evidence_requests)

    re_asks: list[RepeatRow] | None = None
    open_repeats: list[RepeatRow] | None = None
    if unreadable_reason is not None:
        not_assessed["re_asks"] = not_assessed["open_repeats"] = unreadable_reason
    elif answer_log is None and answered:
        not_assessed["re_asks"] = not_assessed["open_repeats"] = ANSWERED_WITHOUT_LOG
    else:
        re_asks, open_repeats = _repeats(readable, placed, ids)

    unmatched: list[CallRow] | None = None
    if unreadable_reason is not None:
        not_assessed["unmatched_requests"] = unreadable_reason
    else:
        unmatched = [
            CallRow.model_validate(_row_fields(call))
            for call in readable
            if _names_nothing(call.item, call.ids)
        ]

    unanswerable_rows: list[UnanswerableRow] | None = None
    if not unanswerable:
        not_assessed["unanswerable_requests"] = NO_UNANSWERABLE_REQUEST
    elif unreadable_reason is not None:
        not_assessed["unanswerable_requests"] = unreadable_reason
    else:
        unanswerable_rows = [
            UnanswerableRow.model_validate({**_row_fields(call), "entry": entry.id})
            for call in readable
            for entry in unanswerable
            if _matches_unanswerable(call.item, call.ids, entry, ids)
        ]

    counts: list[CountRow] | None = None
    if not count_rules:
        not_assessed["question_counts"] = NO_QUESTION_COUNT_RULE
    elif unreadable_reason is not None and any(rule.item is not None for rule in count_rules):
        not_assessed["question_counts"] = unreadable_reason
    else:
        counts = [
            CountRow(
                entry=rule.id,
                count=_count(rule, session, readable, ids),
                min=rule.min,
                max=rule.max,
            )
            for rule in count_rules
        ]

    unscripted: list[UnscriptedRequest] | None = None
    bound_reached: bool | None = None
    if answer_log is None:
        not_assessed["unscripted_questions"] = not_assessed["bound_reached"] = NO_ANSWER_LOG
    else:
        unscripted = _first_unscripted(answer_log)
        bound_reached = answer_log.ended == "bound_reached"

    return QuestionColumns(
        re_asks=re_asks,
        open_repeats=open_repeats,
        unanswerable_requests=unanswerable_rows,
        unmatched_requests=unmatched,
        question_counts=counts,
        unscripted_questions=unscripted,
        bound_reached=bound_reached,
        not_assessed=not_assessed,
    )


def _check_log(session: ReviewSession, answer_log: AnswerLog, run_dir: Path) -> None:
    """Section 6's "the log against the session": every `sent` id names a request the session
    holds answered, and every answered request was sent at exactly one point. Raises one
    `ValueError` line naming the request."""
    answered = [request.id for request in session.evidence_requests if request.status == "answered"]
    sent = [one.request_id for point in answer_log.points for one in point.sent]
    for request_id in sent:
        if request_id not in answered:
            raise ValueError(
                f"{run_dir}: the answer log sends {request_id}, which the session does not hold "
                "answered; the folder was altered, or written by something other than the driver"
            )
    for request_id in answered:
        times = sent.count(request_id)
        if times != 1:
            where = "at no point" if times == 0 else f"at {times} points"
            raise ValueError(
                f"{run_dir}: the session holds {request_id} answered, and the answer log sends "
                f"it {where}; the folder was altered, or written by something other than the "
                "driver"
            )


def _answer_points(answer_log: AnswerLog | None) -> dict[str, tuple[int, int]]:
    """Each sent request's point: `(point index, steps_before)`; empty with no log."""
    if answer_log is None:
        return {}
    return {
        one.request_id: (index, point.steps_before)
        for index, point in enumerate(answer_log.points)
        for one in point.sent
    }


def _unreadable_reason(unreadable: Sequence[UnreadableCall]) -> str | None:
    """`not_assessed`'s reason naming each request call whose stored result cannot be read."""
    if not unreadable:
        return None
    steps = ", ".join(f"step {call.step} ({call.reason})" for call in unreadable)
    return (
        f"the stored result of {steps} cannot be read, so not every request call is known "
        "(questions.md 1)"
    )


def _names_nothing(item: str | None, entity_ids: Collection[str]) -> bool:
    """A call or request naming no item and no id (FR-053), which asks within nothing: an
    unmatched call (US3-7), in no other column, and an unscripted request `names_nothing`."""
    return item is None and not entity_ids


def _repeats(
    calls: Sequence[RequestCall],
    placed: dict[str, tuple[int, int]],
    ids: QuestionIds,
) -> tuple[list[RepeatRow], list[RepeatRow]]:
    """Each call's re-ask or repeat of an open question (section 3's first two uses).

    The earlier questions are the model-written ones, each recorded by a call; a re-ask
    outranks a repeat, as the guard answers `already_answered` before `already_asked`, and cites
    the latest answered by point, then session order; a repeat cites the latest open.
    """
    questions = [call for call in calls if call.outcome == "recorded"]
    re_asks: list[RepeatRow] = []
    open_repeats: list[RepeatRow] = []
    for call in calls:
        if _names_nothing(call.item, call.ids):
            continue
        earlier = [
            question
            for question in questions
            if question.step < call.step
            and asks_within(call.item, call.ids, question.item, question.ids, ids=ids)
        ]
        answered = [
            question for question in earlier if _answered_before(question, call.step, placed)
        ]
        if answered:
            cited = max(answered, key=lambda question: (placed[_id(question)][0], question.step))
            re_asks.append(RepeatRow.model_validate({**_row_fields(call), "of": _id(cited)}))
            continue
        if earlier:
            cited = max(earlier, key=lambda question: question.step)
            open_repeats.append(RepeatRow.model_validate({**_row_fields(call), "of": _id(cited)}))
    return re_asks, open_repeats


def _answered_before(question: RequestCall, step: int, placed: dict[str, tuple[int, int]]) -> bool:
    """Whether the question was answered before the call at `step` (section 1, in time)."""
    point = placed.get(_id(question))
    return point is not None and point[1] <= step


def _id(question: RequestCall) -> str:
    """A recorded call's request id, which `request_calls` always reads."""
    assert question.request_id is not None
    return question.request_id


def _count(
    rule: QuestionCount,
    session: ReviewSession,
    calls: Sequence[RequestCall],
    ids: QuestionIds,
) -> int:
    """Section 5.2's count: a `part_roles` rule the code-written part-roles questions on the
    session; an item rule the request calls asked within its item and ids (by the item alone
    when it names none), refused ones included."""
    if rule.part_roles:
        return sum(1 for request in session.evidence_requests if is_part_roles_question(request))
    return sum(
        1
        for call in calls
        if not _names_nothing(call.item, call.ids)
        and (
            asks_within(call.item, call.ids, rule.item, rule.ids, ids=ids)
            if rule.ids
            else call.item == rule.item
        )
    )


def _first_unscripted(answer_log: AnswerLog) -> list[UnscriptedRequest]:
    """Each request an answer point gave nothing, once, with its first reason (FR-024)."""
    first: dict[str, UnscriptedRequest] = {}
    for point in answer_log.points:
        for unscripted in point.unscripted:
            first.setdefault(unscripted.request_id, unscripted)
    return list(first.values())


def _row_fields(call: RequestCall) -> dict[str, object]:
    """The fields every question column's row takes from its call."""
    return {"step": call.step, "outcome": call.outcome, "request_id": call.request_id}
