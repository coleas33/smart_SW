"""The questions reader's tests (feature 014, `contracts/questions.md` section 9).

The first half holds the product-side bullets (T073; plan decisions RF-6, QA-11, QA-13): the two
product rules the eval's one matcher is built on, made callable without moving anything the
model reads.

- `report.session.covers` is the covering test `covering_requests` wrote inline (`questions.md`
  3): tested here on its four cases, and a spy shows the guard asking it once per model-written
  request. The guard's own tests (`test_tools_session.py`, `test_questions.py`) pass unchanged
  after the extraction.
- `tools.session.documents_named` is the drawing guard's document rule made public
  (`questions.md` 2): a document names itself, a component instance its document, a hole and a
  fastener their component's document, and any other id nothing, first-named first.

The rest (T081, for T082; QA-10 to QA-18, RF-6, RF-30) is `benchmark/questions.py`, the one
question matcher, over `questions_package()`, a fictional package with `questions.md` 7's ids:
the plate `doc:0002` with its instance `cmp:0001` and hole `hol:0001`, the bought pin `doc:0003`
with its instances `cmp:0002` and `cmp:0003`. Each review is played call by call through the
real `request_evidence`, so every request call's stored result is the one the registry's `_store`
writes; the answer points are recorded as the driver logs them, through `answers.AnswerLog`, and
each request is answered on the session as the product answers it. Key entries are built through
`answer_key_model`. Where `questions.md` 7 numbers the part-roles question `ER-001`, a review
records it first, through the one writer of code questions, so the table's ids hold.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from swreview.benchmark import questions
from swreview.benchmark.answer_key_model import QuestionCount, UnanswerableRequest
from swreview.benchmark.answers import (
    ANSWER_LOG_VERSION,
    AnswerLog,
    AnswerPoint,
    AnswerSent,
    Ended,
    UnscriptedRequest,
)
from swreview.benchmark.questions import (
    CallRow,
    CountRow,
    QuestionColumns,
    QuestionIds,
    RepeatRow,
    RequestCall,
    UnanswerableRow,
    UnreadableCall,
)
from swreview.checks import part_roles
from swreview.checks.drawing_context import candidate_question
from swreview.checks.questions import QuestionSpec
from swreview.drawings.evidence import DrawingIndex
from swreview.findings import Source
from swreview.ir.models import EvidencePackage
from swreview.report import session as report_session
from swreview.report.session import EvidenceRequest, InvestigationStep, ReviewSession
from swreview.tools import registry
from swreview.tools import session as tools_session
from swreview.tools.context import ToolContext, context_for, new_session
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME, StoredResult, ToolRegistry, Unstored
from tests.support.drawings import DrawingBuilder
from tests.support.mechanical import PackageBuilder
from tests.support.packages import build_package, persist_ref
from tests.support.roles_review import roles_review
from tests.unit.test_answer_key import count_rule, item_rule, unanswerable

FIT = "interfaces.fit"
FASTENERS = "fasteners"


def ids(*values: str) -> frozenset[str]:
    return frozenset(values)


# --- covers: the product's covering test, extracted (questions.md 3; RF-6) -----------------------


@pytest.mark.parametrize(
    ("later", "earlier", "covered"),
    [
        (ids("cmp:0002"), ids("cmp:0002", "hol:0001"), True),
        (ids("hol:0001", "cmp:0002"), ids("cmp:0002", "hol:0001"), True),
        (ids("cmp:0002", "hol:0001"), ids("cmp:0002"), False),
        (ids("cmp:0002", "hol:0001"), ids("cmp:0002", "cmp:0003"), False),
    ],
    ids=["subset", "same-ids", "superset", "partial-overlap"],
)
def test_an_item_and_ids_are_covered_by_an_earlier_question_holding_the_ids_on_that_item(
    later: frozenset[str], earlier: frozenset[str], covered: bool
) -> None:
    assert report_session.covers(FIT, later, FIT, earlier) is covered


def test_an_item_and_ids_are_not_covered_under_another_item() -> None:
    assert report_session.covers(FIT, ids("cmp:0002"), FASTENERS, ids("cmp:0002")) is False
    assert report_session.covers(FIT, ids("cmp:0002"), None, ids("cmp:0002")) is False


def test_an_item_alone_is_covered_only_by_an_earlier_question_on_it_naming_no_ids() -> None:
    assert report_session.covers(FIT, ids(), FIT, ids()) is True
    assert report_session.covers(FIT, ids(), FIT, ids("cmp:0002")) is False
    assert report_session.covers(FIT, ids(), FASTENERS, ids()) is False


def test_no_item_and_no_ids_is_covered_by_nothing() -> None:
    """`report/session.py:201-202`: nothing says two such questions are the same one."""
    assert report_session.covers(None, ids(), None, ids()) is False
    assert report_session.covers(None, ids(), None, ids("cmp:0002")) is False
    assert report_session.covers(None, ids(), FIT, ids()) is False


def test_a_null_item_with_ids_is_covered_by_a_null_item_question_holding_them() -> None:
    """`null` equals `null`, and only `null` (research R2.22's pinned case)."""
    assert report_session.covers(None, ids("cmp:0002"), None, ids("cmp:0002", "cmp:0003")) is True
    assert report_session.covers(None, ids("cmp:0002", "cmp:0003"), None, ids("cmp:0002")) is False
    assert report_session.covers(None, ids("cmp:0002"), FIT, ids("cmp:0002")) is False


def request(
    request_id: str,
    blocks: str | None,
    entity_ids: list[str],
    *,
    source: Source = "model",
    answered: bool = False,
) -> EvidenceRequest:
    return EvidenceRequest(
        id=request_id,
        what=f"The value {request_id} asks for",
        why="A check cannot be graded without it.",
        entity_ids=entity_ids,
        status="answered" if answered else "open",
        answer="press fit" if answered else None,
        answered_at=datetime(2026, 9, 26, 10, 0, tzinfo=UTC) if answered else None,
        blocks=blocks,
        source=source,
    )


def session_with(*requests: EvidenceRequest) -> ReviewSession:
    session = new_session(build_package())
    session.evidence_requests.extend(requests)
    return session


def spy_on_covers(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str | None, frozenset[str], str | None, frozenset[str]]]:
    """Every call `covering_requests` makes to `covers`, answered by the real one."""
    asked: list[tuple[str | None, frozenset[str], str | None, frozenset[str]]] = []
    real = report_session.covers

    def spy(
        blocks: str | None,
        ids: frozenset[str],
        earlier_blocks: str | None,
        earlier_ids: frozenset[str],
    ) -> bool:
        asked.append((blocks, ids, earlier_blocks, earlier_ids))
        return real(blocks, ids, earlier_blocks, earlier_ids)

    monkeypatch.setattr(report_session, "covers", spy)
    return asked


def test_covering_requests_asks_covers_once_per_model_written_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard's predicate is `covers` and nothing else; a code-written request is never asked
    (it covers only itself, `report/session.py:194-199`)."""
    session = session_with(
        request("ER-001", FIT, ["cmp:0002", "hol:0001"], answered=True),
        request("ER-002", None, ["cmp:0002"], source="code"),
        request("ER-003", FASTENERS, ["cmp:0001"]),
        request("ER-004", FIT, ["cmp:0002"]),
    )
    asked = spy_on_covers(monkeypatch)

    covering = report_session.covering_requests(session, FIT, ["cmp:0002"])

    assert asked == [
        (FIT, ids("cmp:0002"), FIT, ids("cmp:0002", "hol:0001")),
        (FIT, ids("cmp:0002"), FASTENERS, ids("cmp:0001")),
        (FIT, ids("cmp:0002"), FIT, ids("cmp:0002")),
    ]
    assert all(type(call[1]) is frozenset and type(call[3]) is frozenset for call in asked)
    assert covering.answered is not None and covering.answered.id == "ER-001"
    assert covering.open is not None and covering.open.id == "ER-004"


def test_covering_requests_asks_nothing_for_a_question_with_no_item_and_no_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The early return stays (`report/session.py:201-202`)."""
    session = session_with(request("ER-001", None, [], answered=True), request("ER-002", None, []))
    asked = spy_on_covers(monkeypatch)

    covering = report_session.covering_requests(session, None, [])

    assert asked == []
    assert covering == report_session.CoveringRequests(answered=None, open=None)


# --- documents_named: the drawing guard's document rule, public (questions.md 2; QA-11) -----------

ROOT = "doc:1"
PLATE = "doc:2"
PLATE_1 = "cmp:0001"
HOLE = "hole:1"
SCREW = "fst:1"


def plate_package() -> EvidencePackage:
    """`build_package`'s fictional package cut to one part instance: its part `doc:2`, the plate
    here, has the one instance `cmp:0001`, holding the hole `hole:1` and, moved onto it, the
    fastener `fst:1`; the root assembly `doc:1` has no instance."""
    base = build_package()
    plate_1 = base.components[0]
    return build_package(
        components=[plate_1],
        fasteners=[base.fasteners[0].model_copy(update={"component_id": plate_1.id})],
    )


def test_documents_named_is_public_and_the_private_name_is_gone() -> None:
    assert callable(tools_session.documents_named)
    assert not hasattr(tools_session, "_documents_named")


@pytest.mark.parametrize(
    ("entity_ids", "documents"),
    [
        ([PLATE], [PLATE]),
        ([ROOT], [ROOT]),
        ([PLATE_1], [PLATE]),
        ([HOLE], [PLATE]),
        ([SCREW], [PLATE]),
        (["fea:0001"], []),
        (["dsn:1"], []),
        ([], []),
    ],
    ids=["document", "root-document", "instance", "hole", "fastener", "feature", "design", "none"],
)
def test_documents_named_names_each_id_s_document_as_the_drawing_guard_reads_it(
    entity_ids: list[str], documents: list[str]
) -> None:
    """`tools/session.py:280-298`: a document is itself, a component its document, a hole or a
    fastener its component's document; any other id names none."""
    context = context_for(plate_package())

    assert context.hole(HOLE) is not None and context.fastener(SCREW) is not None
    assert tools_session.documents_named(context, entity_ids) == documents


def test_documents_named_names_each_document_once_first_named_first() -> None:
    context = context_for(plate_package())

    named = tools_session.documents_named(
        context, [HOLE, "fea:0001", ROOT, SCREW, PLATE_1, PLATE, ROOT]
    )

    assert named == [PLATE, ROOT]


# --- the questions reader: questions_package() and a review played call by call (T081) -----------

ASSEMBLY = "doc:0001"
PLATE_DOC = "doc:0002"
PLATE_HOLE = "hol:0001"
PIN_DOC = "doc:0003"
PIN_1 = "cmp:0002"
PIN_2 = "cmp:0003"
PIN_SCREW = "fst:0001"
"""`questions.md` 7's ids; the plate's instance is `PLATE_1`, `cmp:0001`, as above."""

FIT = "interfaces.fit"
DRAWING = "drawing.manufacturing_inputs"
ANSWERED_AT = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)


def questions_package() -> EvidencePackage:
    """The assembly `doc:0001`, the plate `doc:0002` with one instance and the hole `hol:0001`
    on it, and the bought pin `doc:0003` with two instances, the second carrying the screw
    `fst:0001`; a candidate drawing beside the plate gives the package drawing evidence, so a
    drawing request on the pin, which has none, is closed by code (`tools/session.py:301-340`)."""
    builder = PackageBuilder(design_stem="FICT-7000", schema_version="1.6.0")
    plate = builder.document("FICT-7001", "part")
    pin = builder.document("FICT-KALO-PIN", "part")
    for document in (plate, pin, pin):
        builder.component(document)
    drawings = DrawingBuilder(builder.build().package)
    drawings.candidate(plate)
    package = drawings.build()
    base = build_package()
    return package.model_copy(
        update={
            "holes": [
                base.holes[0].model_copy(
                    update={
                        "id": PLATE_HOLE,
                        "persist_ref": persist_ref(PLATE_HOLE),
                        "persist_ref_scope": PLATE_DOC,
                        "component_id": PLATE_1,
                    }
                )
            ],
            "fasteners": [
                base.fasteners[0].model_copy(
                    update={
                        "id": PIN_SCREW,
                        "persist_ref": persist_ref(PIN_SCREW),
                        "persist_ref_scope": ASSEMBLY,
                        "component_id": PIN_2,
                    }
                )
            ],
        }
    )


PACKAGE = questions_package()

PART_ROLES_SPEC = QuestionSpec(
    key=part_roles.QUESTION_KEY,
    what=part_roles.WHAT.format(names="FICT-KALO-PIN.SLDPRT"),
    why=part_roles.WHY,
    entity_ids=(PIN_DOC,),
    question=part_roles.QUESTION,
    options=(part_roles.OPTION_ALL, part_roles.OPTION_NONE),
    blocks=None,
    allow_text=True,
)
"""The part-roles question on the pin, worded as `checks/part_roles.roles_question` words it."""


def unanswerable_entry(**fields: Any) -> UnanswerableRequest:
    """`test_answer_key.unanswerable`'s `U-1` on the pin's document, built through the model."""
    return UnanswerableRequest.model_validate(unanswerable(**fields))


def part_roles_rule(**fields: Any) -> QuestionCount:
    """`test_answer_key.count_rule`'s `Q-1`, exactly one part-roles question."""
    return QuestionCount.model_validate(count_rule(**fields))


def item_count_rule(**fields: Any) -> QuestionCount:
    """`test_answer_key.item_rule`'s `Q-2` with `fields`, built through the model."""
    return QuestionCount.model_validate(item_rule(**fields))


@dataclass
class Review:
    """A review of `PACKAGE` played call by call, its stored results written under `folder`."""

    folder: Path
    context: ToolContext = field(init=False)
    points: list[AnswerPoint] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.context = context_for(PACKAGE)
        self.context.tool_results_dir = self.folder / TOOL_RESULTS_DIR_NAME

    @property
    def session(self) -> ReviewSession:
        return self.context.require_session()

    def ask(self, *entity_ids: str, item: str | None = None) -> InvestigationStep:
        """One `request_evidence` call through the real dispatch, which records its step and
        stores its result; returns the step."""
        arguments: dict[str, Any] = {
            "what": "A fictional value the review needs.",
            "why": "A check cannot be graded without it.",
            "entity_ids": list(entity_ids),
        }
        if item is not None:
            arguments["blocks"] = item
        ToolRegistry().dispatch(self.context).call("request_evidence", arguments)
        return self.session.steps[-1]

    def call(self, tool: str, arguments: dict[str, Any]) -> InvestigationStep:
        """Any other tool call, recorded as a review records it."""
        ToolRegistry().dispatch(self.context).call(tool, arguments)
        return self.session.steps[-1]

    def ask_part_roles(self) -> EvidenceRequest:
        """The part-roles question, recorded as `agent/runner.ask_part_roles` records it."""
        return tools_session.record_question(self.context, PART_ROLES_SPEC)

    def answer(
        self, *request_ids: str, unscripted: Sequence[UnscriptedRequest] = ()
    ) -> AnswerPoint:
        """One answer point after the calls so far: each request answered on the session as
        `ReviewRun.answer_evidence_batch` answers it, and the point logged as the driver logs
        it, a minute after the point before, as the engineer's answers arrive in turn."""
        for request_id in request_ids:
            request = next(one for one in self.session.evidence_requests if one.id == request_id)
            request.status = "answered"
            request.answer = "press fit"
            request.answered_at = ANSWERED_AT + timedelta(minutes=len(self.points))
        point = AnswerPoint(
            after_turn=len(self.points),
            steps_before=len(self.session.steps),
            sent=[
                AnswerSent(request_id=request_id, entry=f"A-{number}")
                for number, request_id in enumerate(request_ids, start=1)
            ],
            unscripted=list(unscripted),
            held=[],
        )
        self.points.append(point)
        return point

    def log(self, ended: Ended = "no_open_questions") -> AnswerLog:
        return AnswerLog(
            answer_log_version=ANSWER_LOG_VERSION,
            points=list(self.points),
            ended=ended,
            last_turn_end="end",
            unused_entries=[],
        )

    def columns(
        self,
        answer_log: AnswerLog | None,
        *,
        unanswerable: Sequence[UnanswerableRequest] = (),
        count_rules: Sequence[QuestionCount] = (),
    ) -> QuestionColumns:
        return questions.question_columns(
            self.session,
            run_dir=self.folder,
            ids=QuestionIds(PACKAGE),
            answer_log=answer_log,
            unanswerable=unanswerable,
            count_rules=count_rules,
        )

    def stored_file(self, step: InvestigationStep) -> Path:
        return self.folder / TOOL_RESULTS_DIR_NAME / f"step-{step.index}.json"


def no_answer(request_id: str) -> UnscriptedRequest:
    return UnscriptedRequest(request_id=request_id, reason="no_answer")


def repeat(step: int, outcome: str, request_id: str | None, *, of: str) -> RepeatRow:
    return RepeatRow.model_validate(
        {"step": step, "outcome": outcome, "request_id": request_id, "of": of}
    )


def unanswered(
    step: int, outcome: str, request_id: str | None, entry: str = "U-1"
) -> UnanswerableRow:
    return UnanswerableRow.model_validate(
        {"step": step, "outcome": outcome, "request_id": request_id, "entry": entry}
    )


def counted(entry: str, count: int, minimum: int, maximum: int | None) -> CountRow:
    return CountRow(entry=entry, count=count, min=minimum, max=maximum)


# --- request calls (questions.md 1; QA-10) -----------------------------------------------------


def test_each_outcome_is_read_from_the_step_and_its_stored_result(tmp_path: Path) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1)
    review.ask(PIN_1)
    review.answer("ER-001")
    review.ask(PIN_1)
    review.ask(PIN_DOC, item=DRAWING)

    calls = questions.request_calls(review.session, tmp_path, QuestionIds(PACKAGE))

    assert calls == [
        RequestCall(0, None, (PIN_1,), frozenset({PIN_1}), "recorded", "ER-001"),
        RequestCall(1, None, (PIN_1,), frozenset({PIN_1}), "already_asked", "ER-001"),
        RequestCall(2, None, (PIN_1,), frozenset({PIN_1}), "already_answered", "ER-001"),
        RequestCall(3, DRAWING, (PIN_DOC,), frozenset({PIN_1, PIN_2}), "closed_by_code", None),
    ]


def test_an_error_answer_is_no_question_and_in_no_column(tmp_path: Path) -> None:
    """QA-10: an unknown id is refused with an error envelope; the model's next call is the
    question."""
    review = Review(tmp_path)
    error = review.ask("cmp:9999", item=FIT)
    review.ask(PLATE_1, item=FIT)
    assert error.status == "error"

    calls = questions.request_calls(review.session, tmp_path, QuestionIds(PACKAGE))
    columns = review.columns(
        review.log(),
        unanswerable=[unanswerable_entry(documents=[PLATE_DOC])],
        count_rules=[item_count_rule(ids=[], max=1)],
    )

    assert [call.step for call in calls] == [1]
    assert columns.unanswerable_requests == [unanswered(1, "recorded", "ER-001")]
    assert columns.question_counts == [counted("Q-2", 1, 0, 1)]
    assert columns.re_asks == columns.open_repeats == columns.unmatched_requests == []


def test_steps_of_other_tools_are_no_request_calls(tmp_path: Path) -> None:
    review = Review(tmp_path)
    review.call("get_component", {"component_id": PLATE_1})
    review.ask(PLATE_1, item=FIT)

    calls = questions.request_calls(review.session, tmp_path, QuestionIds(PACKAGE))

    assert [call.step for call in calls] == [1]


# --- unreadable stored results (questions.md 1; RF-30; FR-021) ---------------------------------

CALL_COLUMNS = ("re_asks", "open_repeats", "unanswerable_requests", "unmatched_requests")


def spoil(path: Path, how: str) -> None:
    """One of `read_stored_result`'s four `Unstored` reasons, made on disk."""
    if how == "missing":
        path.unlink()
        return
    if how == "unreadable":
        path.write_text("{not json", encoding="utf-8")
        return
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if how == "other_session":
        envelope["session_id"] = str(UUID(int=7))
    else:
        envelope["step"] = envelope["step"] + 1
    path.write_text(json.dumps(envelope), encoding="utf-8")


@pytest.mark.parametrize("how", ["missing", "unreadable", "other_session", "other_call"])
def test_an_unreadable_stored_result_makes_the_call_columns_not_assessed(
    tmp_path: Path, how: str
) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1)
    spoiled = review.ask(PIN_1)
    spoil(review.stored_file(spoiled), how)

    columns = review.columns(
        review.log(),
        unanswerable=[unanswerable_entry()],
        count_rules=[item_count_rule(ids=[], max=1)],
    )

    for column in (*CALL_COLUMNS, "question_counts"):
        assert getattr(columns, column) is None, column
        reason = columns.not_assessed[column]
        assert "step 1" in reason and how in reason, reason
    calls = questions.request_calls(review.session, tmp_path, QuestionIds(PACKAGE))
    assert calls[1] == UnreadableCall(1, how)


def test_a_part_roles_rule_alone_is_still_assessed_beside_an_unreadable_call(
    tmp_path: Path,
) -> None:
    """Only item rules count request calls (questions.md 6)."""
    review = Review(tmp_path)
    review.ask_part_roles()
    spoil(review.stored_file(review.ask(PIN_1)), "missing")

    columns = review.columns(review.log(), count_rules=[part_roles_rule()])

    assert columns.question_counts == [counted("Q-1", 1, 1, 1)]
    assert "question_counts" not in columns.not_assessed


def test_a_session_recorded_before_feature_008_reads_the_same(tmp_path: Path) -> None:
    """No `tool-results/` at all: every request call is missing."""
    review = Review(tmp_path)
    review.ask(PIN_1)
    review.ask(PLATE_1, item=FIT)
    for path in (tmp_path / TOOL_RESULTS_DIR_NAME).iterdir():
        path.unlink()
    (tmp_path / TOOL_RESULTS_DIR_NAME).rmdir()

    columns = review.columns(review.log(), unanswerable=[unanswerable_entry()])

    for column in CALL_COLUMNS:
        assert getattr(columns, column) is None, column
        reason = columns.not_assessed[column]
        assert "step 0" in reason and "step 1" in reason and "missing" in reason, reason


def test_the_reader_reads_each_request_call_through_read_stored_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RF-30: once per request call, with the step's tool and arguments."""
    review = Review(tmp_path)
    review.call("get_component", {"component_id": PLATE_1})
    first = review.ask(PIN_1)
    second = review.ask(PLATE_1, item=FIT)
    seen: list[tuple[Path, UUID, int, str | None, Any]] = []

    def spy(
        run_dir: Path,
        session_id: UUID,
        step: int,
        *,
        tool: str | None = None,
        arguments: Any = None,
    ) -> StoredResult | Unstored:
        seen.append((run_dir, session_id, step, tool, arguments))
        return registry.read_stored_result(
            run_dir, session_id, step, tool=tool, arguments=arguments
        )

    monkeypatch.setattr(questions, "read_stored_result", spy)

    review.columns(review.log())

    session_id = review.session.session_id
    assert seen == [
        (tmp_path, session_id, step.index, "request_evidence", step.arguments)
        for step in (first, second)
    ]


# --- ids (questions.md 2; QA-11) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("entity_ids", "instances"),
    [
        ([PLATE_1], {PLATE_1}),
        ([PLATE_HOLE], {PLATE_1}),
        ([PIN_SCREW], {PIN_2}),
        ([PIN_DOC], {PIN_1, PIN_2}),
        ([PLATE_DOC], {PLATE_1}),
        ([ASSEMBLY], {ASSEMBLY}),
        (["fea:0001"], {"fea:0001"}),
        ([PIN_1], {PIN_1}),
        ([PIN_1, PLATE_HOLE], {PIN_1, PLATE_1}),
        ([], set()),
    ],
    ids=[
        "an instance itself",
        "a hole its instance",
        "a fastener its instance",
        "a document every instance of it",
        "a one-instance document its instance",
        "a document with no instance itself",
        "any other id itself",
        "two instances of one pin stay two",
        "several",
        "none",
    ],
)
def test_question_ids_resolve_each_id_to_instances(
    entity_ids: list[str], instances: set[str]
) -> None:
    assert QuestionIds(PACKAGE).instances(entity_ids) == frozenset(instances)


def test_question_ids_name_documents_as_the_drawing_guard_does() -> None:
    ids = QuestionIds(PACKAGE)
    entity_ids = [PLATE_HOLE, PIN_SCREW, PIN_1, ASSEMBLY, "fea:0001"]

    assert ids.documents(entity_ids) == [PLATE_DOC, PIN_DOC, ASSEMBLY]
    assert ids.documents(entity_ids) == tools_session.documents_named(ids.context, entity_ids)


# --- the relation: asks_within, covers widened twice (questions.md 3; RF-6) --------------------


def test_asks_within_is_built_on_the_product_s_covers() -> None:
    assert questions.covers is report_session.covers


def test_ids_are_resolved_to_instances_before_covers_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hole and a document read as their instances; `covers` alone, on raw ids, says no."""
    asked: list[tuple[str | None, frozenset[str], str | None, frozenset[str]]] = []
    real = report_session.covers

    def spy(
        blocks: str | None,
        ids: frozenset[str],
        earlier_blocks: str | None,
        earlier_ids: frozenset[str],
    ) -> bool:
        asked.append((blocks, ids, earlier_blocks, earlier_ids))
        return real(blocks, ids, earlier_blocks, earlier_ids)

    monkeypatch.setattr(questions, "covers", spy)
    ids = QuestionIds(PACKAGE)

    assert questions.asks_within(FIT, [PLATE_HOLE], FIT, [PLATE_1], ids=ids) is True
    assert questions.asks_within(FIT, [PIN_1], FIT, [PIN_DOC], ids=ids) is True
    assert questions.asks_within(FIT, [PIN_DOC], FIT, [PIN_1], ids=ids) is False
    assert asked == [
        (FIT, frozenset({PLATE_1}), FIT, frozenset({PLATE_1})),
        (FIT, frozenset({PIN_1}), FIT, frozenset({PIN_1, PIN_2})),
        (FIT, frozenset({PIN_1, PIN_2}), FIT, frozenset({PIN_1})),
    ]
    assert real(FIT, frozenset({PLATE_HOLE}), FIT, frozenset({PLATE_1})) is False


def test_a_later_item_with_no_ids_asks_within_an_earlier_question_on_that_item() -> None:
    """R-3's "now give numeric limits": the product covers it only when the earlier question
    named no ids either (`report/session.py:208`)."""
    ids = QuestionIds(PACKAGE)

    assert questions.asks_within(FIT, [], FIT, [PIN_1, PLATE_HOLE], ids=ids) is True
    assert report_session.covers(FIT, frozenset(), FIT, frozenset({PIN_1})) is False
    assert questions.asks_within(FIT, [], FIT, [], ids=ids) is True
    assert questions.asks_within(FIT, [], "fasteners", [PIN_1], ids=ids) is False


def test_everything_else_is_covers_own_answer() -> None:
    ids = QuestionIds(PACKAGE)

    assert questions.asks_within(None, [], None, [], ids=ids) is False
    assert questions.asks_within(None, [], FIT, [PIN_1], ids=ids) is False
    assert questions.asks_within(None, [PIN_1], None, [PIN_1, PIN_2], ids=ids) is True
    assert questions.asks_within(FIT, [PIN_1], "fasteners", [PIN_1], ids=ids) is False
    assert questions.asks_within(FIT, [PIN_1, PLATE_1], FIT, [PIN_1], ids=ids) is False


# --- the anchors of US3-6 (questions.md 7) -----------------------------------------------------

U_1 = unanswerable_entry()
"""`U-1`: the pin's document, no item."""


def test_r_2_two_requests_on_the_pin(tmp_path: Path) -> None:
    review = Review(tmp_path)
    assert review.ask_part_roles().id == "ER-001"
    review.ask(PIN_1)
    review.ask(PIN_1)
    review.answer(unscripted=[no_answer("ER-001"), no_answer("ER-002")])

    columns = review.columns(review.log("all_unscripted"), unanswerable=[U_1])

    assert columns.unanswerable_requests == [
        unanswered(0, "recorded", "ER-002"),
        unanswered(1, "already_asked", "ER-002"),
    ]
    assert columns.open_repeats == [repeat(1, "already_asked", "ER-002", of="ER-002")]
    assert columns.re_asks == []


def test_r_2_a_drawing_request_on_the_pin_closed_by_code_is_one_unanswerable_request(
    tmp_path: Path,
) -> None:
    """US3-5: every matching call counts, whatever its outcome."""
    review = Review(tmp_path)
    review.ask(PLATE_1, item="fasteners")
    review.ask(PIN_DOC, item=DRAWING)
    review.ask(PLATE_HOLE, item=FIT)

    columns = review.columns(review.log(), unanswerable=[U_1])

    assert columns.unanswerable_requests == [unanswered(1, "closed_by_code", None)]


def r_3(tmp_path: Path, follow_up: Sequence[str]) -> Review:
    """R-3: the fit asked naming the pin and the plate's hole, answered "press fit" at point 1
    (point 0 answered the part-roles question); in the next answer turn the fit asked again
    naming `follow_up`, answered again at the next point when the product recorded it."""
    review = Review(tmp_path)
    review.ask_part_roles()
    review.answer("ER-001")
    review.ask(PIN_1, PLATE_HOLE, item=FIT)
    review.answer("ER-002")
    follow = review.ask(*follow_up, item=FIT)
    recorded = [one.id for one in review.session.evidence_requests if one.status == "open"]
    review.answer(*recorded)
    assert follow.index == 1
    return review


def test_r_3_an_item_only_follow_up_is_one_re_ask_seen(tmp_path: Path) -> None:
    review = r_3(tmp_path, ())

    columns = review.columns(review.log())

    assert columns.re_asks == [repeat(1, "recorded", "ER-003", of="ER-002")]
    assert columns.open_repeats == []


def test_r_3_refused_a_follow_up_naming_the_hole_alone_is_one_re_ask_refused(
    tmp_path: Path,
) -> None:
    review = r_3(tmp_path, (PLATE_HOLE,))

    columns = review.columns(review.log())

    assert columns.re_asks == [repeat(1, "already_answered", "ER-002", of="ER-002")]
    assert columns.open_repeats == []


def test_r_3_against_a_key_with_q_2_is_also_one_question_count_miss(tmp_path: Path) -> None:
    """Two columns by definition (questions.md 6)."""
    review = r_3(tmp_path, ())

    columns = review.columns(
        review.log(), count_rules=[item_count_rule(ids=[PLATE_1, PIN_1], max=1)]
    )

    assert columns.re_asks == [repeat(1, "recorded", "ER-003", of="ER-002")]
    assert columns.question_counts == [counted("Q-2", 2, 0, 1)]


def test_r_6_one_fasteners_question_answered_and_nothing_asked_after(tmp_path: Path) -> None:
    review = Review(tmp_path)
    review.ask(PLATE_1, item="fasteners")
    review.answer("ER-001")
    q_3 = item_count_rule(id="Q-3", item="fasteners", ids=[], max=1)

    columns = review.columns(review.log(), count_rules=[q_3])

    assert columns.question_counts == [counted("Q-3", 1, 0, 1)]
    assert columns.re_asks == []


def test_another_item_after_r_6_s_answer_is_no_re_ask(tmp_path: Path) -> None:
    review = Review(tmp_path)
    review.ask(PLATE_1, item="fasteners")
    review.answer("ER-001")
    review.ask(PLATE_1, item=FIT)

    columns = review.columns(review.log())

    assert columns.re_asks == []
    assert columns.open_repeats == []


@pytest.mark.parametrize(("asked", "miss"), [(1, False), (0, True), (2, True)])
def test_r_1_the_part_roles_question_counted_by_identity(
    tmp_path: Path, asked: int, miss: bool
) -> None:
    review = Review(tmp_path)
    for _ in range(asked):
        tools_session.record_evidence_request(
            review.context,
            PART_ROLES_SPEC.what,
            PART_ROLES_SPEC.why,
            list(PART_ROLES_SPEC.entity_ids),
            question=PART_ROLES_SPEC.question,
            options=list(PART_ROLES_SPEC.options),
            allow_text=True,
            source="code",
        )

    columns = review.columns(review.log(), count_rules=[part_roles_rule()])

    assert columns.question_counts == [counted("Q-1", asked, 1, 1)]
    (row,) = columns.question_counts or []
    assert (row.count < row.min or (row.max is not None and row.count > row.max)) is miss


# --- in time: answered before, open at (questions.md 1 and 3; FR-020, D3) ----------------------


def test_a_repeat_of_an_unscripted_question_after_an_answer_turn_is_a_repeat_of_an_open_one(
    tmp_path: Path,
) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1, item=FIT)
    review.answer(unscripted=[no_answer("ER-001")])
    review.ask(PIN_1, item=FIT)

    columns = review.columns(review.log("all_unscripted"))

    assert columns.open_repeats == [repeat(1, "already_asked", "ER-001", of="ER-001")]
    assert columns.re_asks == []


def test_a_call_before_an_answer_point_is_a_repeat_and_the_same_call_after_it_a_re_ask(
    tmp_path: Path,
) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1, item=FIT)
    review.ask(PIN_1, item=FIT)
    review.answer("ER-001")
    review.ask(PIN_1, item=FIT)

    columns = review.columns(review.log())

    assert columns.open_repeats == [repeat(1, "already_asked", "ER-001", of="ER-001")]
    assert columns.re_asks == [repeat(2, "already_answered", "ER-001", of="ER-001")]


def test_a_re_ask_outranks_a_repeat_when_an_answered_and_an_open_question_match(
    tmp_path: Path,
) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1, item=FIT)
    review.answer("ER-001")
    review.ask(PIN_1, PIN_2, item=FIT)
    review.ask(PIN_1, item=FIT)

    columns = review.columns(review.log())

    assert columns.re_asks == [repeat(2, "already_answered", "ER-001", of="ER-001")]
    assert columns.open_repeats == []


def test_a_re_ask_cites_the_latest_answered_by_point_then_session_order(tmp_path: Path) -> None:
    """The product cites the latest answer too (`report/session.latest_answered`), so the cited
    request and the column's `of` agree; the hole read as the plate's instance makes step 4 a
    repeat of an open question the product recorded."""
    review = Review(tmp_path)
    review.ask(PIN_1, PIN_2, item=FIT)
    review.ask(PIN_1, PLATE_1, item=FIT)
    review.answer("ER-002")
    review.answer("ER-001")
    review.ask(PIN_1, item=FIT)
    review.ask(PLATE_1, PIN_2, item=FIT)
    review.ask(PLATE_1, PIN_2, PLATE_HOLE, item=FIT)
    review.answer("ER-003", "ER-004")
    review.ask(PLATE_1, item=FIT)

    columns = review.columns(review.log())

    assert columns.re_asks == [
        repeat(2, "already_answered", "ER-001", of="ER-001"),
        repeat(5, "already_answered", "ER-004", of="ER-004"),
    ]
    assert columns.open_repeats == [repeat(4, "recorded", "ER-004", of="ER-003")]


def test_a_repeat_cites_the_latest_open_question(tmp_path: Path) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1, PIN_2, PLATE_1, item=FIT)
    review.ask(PIN_1, PIN_2, PLATE_HOLE, PLATE_1, item=FIT)
    review.ask(PIN_1, item=FIT)

    columns = review.columns(review.log())

    assert columns.open_repeats == [
        repeat(1, "recorded", "ER-002", of="ER-001"),
        repeat(2, "already_asked", "ER-002", of="ER-002"),
    ]
    assert columns.re_asks == []


def test_a_code_question_is_no_earlier_question(tmp_path: Path) -> None:
    """QA-12: a model question naming a part the answered part-roles question named is no
    re-ask of "All bought"."""
    review = Review(tmp_path)
    review.ask_part_roles()
    review.answer("ER-001")
    review.ask(PIN_DOC)

    columns = review.columns(review.log())

    assert columns.re_asks == []
    assert columns.open_repeats == []


def test_a_call_naming_no_item_and_no_id_is_unmatched_twice_and_never_a_re_ask(
    tmp_path: Path,
) -> None:
    """US3-7: listed in its own column, and in no other."""
    review = Review(tmp_path)
    review.ask()
    review.answer("ER-001")
    review.ask()

    columns = review.columns(
        review.log(), count_rules=[item_count_rule(ids=[], max=0)], unanswerable=[U_1]
    )

    assert columns.unmatched_requests == [
        CallRow(step=0, outcome="recorded", request_id="ER-001"),
        CallRow(step=1, outcome="recorded", request_id="ER-002"),
    ]
    assert columns.re_asks == []
    assert columns.open_repeats == []
    assert columns.unanswerable_requests == []
    assert columns.question_counts == [counted("Q-2", 0, 0, 0)]


# --- the part-roles question, by identity (questions.md 4; QA-14) ------------------------------


def test_the_question_start_review_records_is_the_part_roles_question(tmp_path: Path) -> None:
    run = roles_review(tmp_path)
    (asked,) = run.session.evidence_requests

    assert asked.source == "code"
    assert questions.is_part_roles_question(asked) is True


def test_a_model_question_in_its_words_is_not_the_part_roles_question(tmp_path: Path) -> None:
    real = Review(tmp_path).ask_part_roles()
    look_alike = real.model_copy(update={"source": "model"})

    assert questions.is_part_roles_question(real) is True
    assert questions.is_part_roles_question(look_alike) is False
    assert questions.is_part_roles_question(real.model_copy(update={"blocks": FIT})) is False
    assert (
        questions.is_part_roles_question(
            real.model_copy(update={"options": [part_roles.OPTION_ALL]})
        )
        is False
    )


def test_the_drawing_candidate_question_is_not_the_part_roles_question(tmp_path: Path) -> None:
    review = Review(tmp_path)
    spec = candidate_question(DrawingIndex.for_package(PACKAGE), None, "opens_closed")
    assert spec is not None

    asked = tools_session.record_question(review.context, spec)

    assert asked.source == "code"
    assert questions.is_part_roles_question(asked) is False


def test_the_part_roles_question_s_entity_ids_are_not_compared(tmp_path: Path) -> None:
    real = Review(tmp_path).ask_part_roles()

    renamed = real.model_copy(update={"entity_ids": [PLATE_DOC, PIN_DOC]})

    assert questions.is_part_roles_question(renamed) is True


# --- not assessed, never 0 (questions.md 6; US3-8, FR-021) -------------------------------------


def test_a_key_with_no_question_entries_reads_their_columns_not_assessed(tmp_path: Path) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1)

    columns = review.columns(review.log())

    assert columns.unanswerable_requests is None
    assert columns.question_counts is None
    assert columns.not_assessed["unanswerable_requests"] == questions.NO_UNANSWERABLE_REQUEST
    assert columns.not_assessed["question_counts"] == questions.NO_QUESTION_COUNT_RULE


def test_answered_requests_with_no_answer_log_read_re_asks_and_repeats_not_assessed(
    tmp_path: Path,
) -> None:
    """A pane session scored on its own holds answered requests and no log."""
    review = Review(tmp_path)
    review.ask(PIN_1, item=FIT)
    review.answer("ER-001")
    review.ask(PIN_1, item=FIT)

    columns = review.columns(None, unanswerable=[U_1])

    assert columns.re_asks is None and columns.open_repeats is None
    assert columns.not_assessed["re_asks"] == questions.ANSWERED_WITHOUT_LOG
    assert columns.not_assessed["open_repeats"] == questions.ANSWERED_WITHOUT_LOG
    assert columns.unanswerable_requests == [
        unanswered(0, "recorded", "ER-001"),
        unanswered(1, "already_answered", "ER-001"),
    ]
    assert columns.unmatched_requests == []


def test_with_no_answer_log_the_two_log_columns_are_not_assessed(tmp_path: Path) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1)

    columns = review.columns(None)

    assert columns.unscripted_questions is None
    assert columns.bound_reached is None
    assert columns.not_assessed["unscripted_questions"] == questions.NO_ANSWER_LOG
    assert columns.not_assessed["bound_reached"] == questions.NO_ANSWER_LOG
    assert columns.re_asks == [] and columns.open_repeats == [], (
        "no answered request: nothing to place in time, so the call columns are assessed"
    )


def test_with_everything_to_read_nothing_is_not_assessed(tmp_path: Path) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1)

    columns = review.columns(review.log(), unanswerable=[U_1], count_rules=[part_roles_rule(min=0)])

    assert columns.not_assessed == {}
    assert columns.bound_reached is False
    assert columns.unscripted_questions == []


# --- the log against the session (questions.md 6; FR-024, FR-025) ------------------------------


def test_a_sent_id_naming_no_answered_request_refuses_the_package(tmp_path: Path) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1)
    review.answer()
    review.points[0].sent.append(AnswerSent(request_id="ER-001", entry="A-1"))

    with pytest.raises(ValueError, match="ER-001") as caught:
        review.columns(review.log())

    assert "\n" not in str(caught.value)


def test_an_answered_request_sent_at_no_point_refuses_the_package(tmp_path: Path) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1)
    review.ask(PLATE_1, item=FIT)
    review.answer("ER-001")
    review.answer("ER-002")
    review.points[1].sent.clear()

    with pytest.raises(ValueError, match="ER-002") as caught:
        review.columns(review.log())

    assert "\n" not in str(caught.value)


def test_an_answered_request_sent_at_two_points_refuses_the_package(tmp_path: Path) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1)
    review.answer("ER-001")
    review.answer()
    review.points[1].sent.append(AnswerSent(request_id="ER-001", entry="A-1"))

    with pytest.raises(ValueError, match="ER-001") as caught:
        review.columns(review.log())

    assert "\n" not in str(caught.value)


def test_unscripted_questions_list_each_request_once_with_its_first_reason(
    tmp_path: Path,
) -> None:
    review = Review(tmp_path)
    review.ask(PIN_1)
    review.ask(PLATE_1, item=FIT)
    ambiguous = UnscriptedRequest(request_id="ER-002", reason="ambiguous", entries=["A-1", "A-2"])
    review.answer(unscripted=[no_answer("ER-001"), ambiguous])
    review.answer(
        unscripted=[
            UnscriptedRequest(request_id="ER-002", reason="no_answer"),
            no_answer("ER-001"),
        ]
    )

    columns = review.columns(review.log("all_unscripted"))

    assert columns.unscripted_questions == [no_answer("ER-001"), ambiguous]


@pytest.mark.parametrize(
    ("ended", "reached"),
    [("bound_reached", True), ("no_open_questions", False), ("turn_did_not_end", False)],
)
def test_bound_reached_reads_the_log_s_ended(tmp_path: Path, ended: Ended, reached: bool) -> None:
    review = Review(tmp_path)

    assert review.columns(review.log(ended)).bound_reached is reached


def test_a_session_cut_short_at_its_step_limit_keeps_the_counts_before_the_stop(
    tmp_path: Path,
) -> None:
    """FR-041: the log reads `turn_did_not_end`; the calls up to the stop are counted."""
    review = Review(tmp_path)
    review.ask(PIN_1)
    review.ask(PIN_1)

    columns = review.columns(review.log("turn_did_not_end"), unanswerable=[U_1])

    assert columns.unanswerable_requests == [
        unanswered(0, "recorded", "ER-001"),
        unanswered(1, "already_asked", "ER-001"),
    ]
    assert columns.open_repeats == [repeat(1, "already_asked", "ER-001", of="ER-001")]
