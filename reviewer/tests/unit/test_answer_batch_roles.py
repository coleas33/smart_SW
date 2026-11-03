"""The engineer's answer to the part-roles question regrades the review at once (013 T037).

`contracts/part-roles.md` section 9. In one batch: the answers are marked; any confirmed drawing
candidate is read first, with the roles its question was built with; then `answered_roles` reads
the part-roles answer and the parts are classified again with it; then one `ReviewRun._restate`
restates the union of what changed - `check_rms_part`, `check_rms_equations`, `check_rms_assembly`,
`check_hygiene` and `check_drawings` when the roles changed, `check_drawings` when a read reloaded
the package - each once, as a recorded step. `_restate` reconciles its own calls: a finding judged
again keeps its id (the `_verdict_key` fold, which ignores coverage limits, so the "may be bought"
note drops in place), and an earlier finding of a restated tool that nothing re-produced is
withdrawn by `ToolContext.withdraw_findings`, which emits `finding.withdrawn`. The bought-parts
rows are restated naming the withdrawn ids, and the resumed message gains one line.

The check tools here are scripted stand-ins for lane P's consumers (T024, T028; section 6): one
finding per graded part document, carrying the unclear note while the question is open. They
read the roles the runner attached, so the runner's regrade is what moves them.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
from swreview.agent.providers.fake import ScriptedToolCall, ScriptedTurn
from swreview.agent.settings import EfficiencySettings
from swreview.checks.drawing_context import CANDIDATE_CONFIRM
from swreview.findings import build_finding
from swreview.prerun import ALREADY_RUN, RMS_PRERUN_TOOLS
from swreview.report.session import EvidenceRequest
from swreview.tools.checks_mechanical import CODE_FIRST_CHECKS
from swreview.tools.context import current_context
from swreview.tools.registry import PART_ROLES_ATTRIBUTE, TOOL_RESULTS_DIR_NAME, ToolRegistry
from swreview.tools.session import record_evidence_request
from tests.support.contracts import contract_validator
from tests.support.mechanical import PackageBuilder
from tests.support.roles_review import (
    PIN_ID,
    PIN_STEM,
    PLATE_ID,
    ROOT_STEM,
    roles_review,
    write_profile,
)

QUESTION = (
    "Are these bought parts? Until you answer, they are graded for modelling practice and "
    "hygiene."
)
BOUGHT_REASON = "bought part (your answer to ER-001)"
ROLE_TOOLS: tuple[str, ...] = (*RMS_PRERUN_TOOLS, "check_hygiene")
SCRIPTED_TOOLS: tuple[str, ...] = tuple(dict.fromkeys((*RMS_PRERUN_TOOLS, *CODE_FIRST_CHECKS)))

Events = list[tuple[str, dict[str, Any]]]


def scripted_check(name: str, custom: str = "low") -> Callable[[], dict[str, Any]]:
    """A check tool named `name`: one finding per graded part document with an instance, and
    the roles' note on each unclear one. Tools outside `ROLE_TOOLS` find nothing. Each finding is
    low, or `custom` on a part with no note, so a regrade can change a severity (cycle 6's Tier 1
    review)."""

    def check() -> dict[str, Any]:
        context = current_context()
        roles = getattr(context, PART_ROLES_ATTRIBUTE)
        recorded: list[str] = []
        if name not in ROLE_TOOLS:
            return {"status": "recorded", "finding_ids": recorded}
        for document in context.ir.documents:
            if document.kind != "part" or not roles.graded(document.document_id):
                continue
            components = [
                item.id
                for item in context.ir.components
                if item.document_id == document.document_id
            ]
            note = roles.note_for(document.document_id)
            finding = build_finding(
                finding_id=next(context.finding_ids),
                check=f"{name}.scripted",
                title=f"{document.file_name} is scripted",
                status="suspected",
                severity="low" if note is not None else custom,
                package=context.ir,
                configuration="Default",
                observed=f"{document.file_name} is scripted",
                requirement="a scripted requirement",
                recommended_action="nothing; it is scripted",
                component_ids=components[:1],
                tool_result_ids=[context.current_step_id],
                coverage_limits=[note] if note is not None else [],
            )
            context.record_finding(finding)
            recorded.append(finding.id)
        return {"status": "recorded", "count": len(recorded)}

    check.__name__ = check.__qualname__ = name
    check.__doc__ = f"The scripted {name}."
    return check


@pytest.fixture
def scripted_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """`start_review` builds its dispatch from the scripted checks and the session tools."""
    from swreview.tools.registry import session_tools

    functions = (*(scripted_check(name) for name in SCRIPTED_TOOLS), *session_tools())
    monkeypatch.setattr(runner, "ToolRegistry", functools.partial(ToolRegistry, functions))


def first_turn(*names: str) -> ScriptedTurn:
    return ScriptedTurn(text="graded", tool_calls=tuple(ScriptedToolCall(name) for name in names))


def graded(
    tmp_path: Path,
    *,
    resumed: Sequence[ScriptedTurn] = (ScriptedTurn(text="resumed"),),
    events: Events | None = None,
    efficiency: EfficiencySettings | None = None,
    **options: Any,
) -> runner.ReviewRun:
    """The fictional review, its first turn running the part and hygiene checks."""
    opening = (
        ScriptedTurn(text="graded")
        if efficiency is not None
        else first_turn("check_rms_part", "check_hygiene")
    )
    run = roles_review(
        tmp_path,
        turns=(opening, *resumed),
        events=events,
        efficiency=efficiency,
        **options,
    )
    run.start()
    return run


def ids_on(run: runner.ReviewRun, document_id: str) -> list[str]:
    components = {
        item.id for item in run.context.ir.components if item.document_id == document_id
    }
    return [
        finding.id
        for finding in run.session.findings
        if set(finding.component_ids) & components
    ]


def withdrawn(events: Events) -> list[dict[str, Any]]:
    """The findings the regrade withdrew, each no longer produced.

    *Changed 2026-11-01 on purpose (002 T340; the backlog's cycle 3 section):* a fold's
    withdrawal of the id a restated finding was first announced under, which names the id it
    folded onto (`folded_into`), is not one: its verdict stands under that id."""
    return [
        body for kind, body in events if kind == "finding.withdrawn" and "folded_into" not in body
    ]


def announced(events: Events) -> dict[str, str]:
    """Each finding id's title as its last `finding` event named it, the display title: what a
    withdrawal of it names (002 T382; cycle 16)."""
    return {body["id"]: body["title"] for kind, body in events if kind == "finding"}


def resumed_message(run: runner.ReviewRun) -> str:
    return str([message for message in run.messages if message["role"] == "user"][1]["content"])


# --- 1. "All bought" -----------------------------------------------------------------------------


def test_all_bought_withdraws_the_unclear_parts_findings_with_an_event_each(
    tmp_path: Path, scripted_registry: None
) -> None:
    """*Changed 2026-11-03 on purpose (002 T382; cycle 16):* each withdrawal also names its
    finding's title, as its `finding` event announced it."""
    events: Events = []
    run = graded(tmp_path, events=events)
    pin_findings = ids_on(run, PIN_ID)
    plate_findings = ids_on(run, PLATE_ID)
    assert len(pin_findings) == 2 and len(plate_findings) == 2
    titles = announced(events)

    run.answer_evidence_batch([("ER-001", "All bought")])

    assert ids_on(run, PIN_ID) == []
    assert ids_on(run, PLATE_ID) == plate_findings
    assert withdrawn(events) == [
        {"finding_id": finding_id, "title": titles[finding_id], "reason": BOUGHT_REASON}
        for finding_id in pin_findings
    ]


def test_the_withdrawal_events_validate_against_the_contract(
    tmp_path: Path, scripted_registry: None
) -> None:
    """*Changed 2026-11-01 on purpose (002 T340):* every withdrawal is validated, a fold's among
    them, not only the ones `withdrawn` counts."""
    events: Events = []
    graded(tmp_path, events=events).answer_evidence_batch([("ER-001", "All bought")])

    validator = contract_validator("chat-events.schema.json")
    bodies = [body for kind, body in events if kind == "finding.withdrawn"]
    for seq, body in enumerate(bodies, start=1):
        validator.validate(
            {"seq": seq, "at": "2026-09-26T09:00:00+00:00", "type": "finding.withdrawn",
             "body": body}
        )
    with pytest.raises(Exception, match="additional"):
        validator.validate(
            {"seq": 1, "at": "2026-09-26T09:00:00+00:00", "type": "finding.withdrawn",
             "body": {"finding_id": "F-001", "reason": "r", "extra": 1}}
        )


def test_after_all_bought_no_two_findings_share_a_verdict_key_and_kept_ids_hold(
    tmp_path: Path, scripted_registry: None
) -> None:
    run = graded(tmp_path)
    kept = ids_on(run, PLATE_ID)

    run.answer_evidence_batch([("ER-001", "All bought")])

    keys = [runner._verdict_key(finding) for finding in run.session.findings]
    assert len(keys) == len(set(keys))
    assert [finding.id for finding in run.session.findings] == kept


def test_all_bought_attaches_roles_that_say_so(tmp_path: Path, scripted_registry: None) -> None:
    run = graded(tmp_path)

    run.answer_evidence_batch([("ER-001", "All bought")])

    roles = getattr(run.context, PART_ROLES_ATTRIBUTE)
    assert roles.by_document[PIN_ID].role == "bought"
    # The classifier's own record of rule A (lane P names it a decision; integration of lanes
    # P and S, 2026-09-27, edited deliberately).
    assert roles.by_document[PIN_ID].decision == "answer"
    assert not roles.graded(PIN_ID)
    assert roles.note_for(PIN_ID) is None


def test_the_resumed_message_gains_one_line_naming_what_was_withdrawn(
    tmp_path: Path, scripted_registry: None
) -> None:
    run = graded(tmp_path)
    pin_findings = ids_on(run, PIN_ID)

    run.answer_evidence_batch([("ER-001", "All bought")])

    assert resumed_message(run) == (
        runner.answers_message([("ER-001", "All bought")])
        + "\nChecks first graded again after your answer: withdrew "
        + ", ".join(pin_findings)
        + " (bought parts)."
    )


def test_the_bought_parts_row_is_restated_naming_the_withdrawn_ids(
    tmp_path: Path, scripted_registry: None
) -> None:
    run = graded(tmp_path)
    pin_findings = ids_on(run, PIN_ID)

    run.answer_evidence_batch([("ER-001", "All bought")])

    [row] = [item for item in run.session.coverage.skipped
             if item.check == "coverage.prerun.bought_parts"]
    assert row.scope.document_ids == [PIN_ID]
    assert all(finding_id in row.reason for finding_id in pin_findings)
    assert not [item for item in run.session.coverage.unresolved
                if item.check == "coverage.prerun.maybe_bought"]


def test_each_restated_tool_is_one_recorded_step_after_the_answer(
    tmp_path: Path, scripted_registry: None
) -> None:
    run = graded(tmp_path)
    before = len(run.session.steps)

    run.answer_evidence_batch([("ER-001", "All bought")])

    restated = [step.tool for step in run.session.steps[before:]]
    assert restated == ["check_rms_part", "check_hygiene"]


def test_the_resumed_turn_numbers_its_calls_after_the_restated_steps(
    tmp_path: Path, scripted_registry: None
) -> None:
    events: Events = []
    run = graded(
        tmp_path,
        events=events,
        resumed=(ScriptedTurn(text="looked", tool_calls=(ScriptedToolCall("check_joints"),)),),
    )
    before = len(run.session.steps)

    run.answer_evidence_batch([("ER-001", "All bought")])

    started = [body["step_index"] for kind, body in events if kind == "tool.started"]
    assert started[-1] == before + 2
    assert run.session.steps[-1].tool == "check_joints"


# --- 2. "None bought", a typed list, an unmatched piece ------------------------------------------


def test_none_bought_keeps_every_id_and_drops_the_note_in_place(
    tmp_path: Path, scripted_registry: None
) -> None:
    events: Events = []
    run = graded(tmp_path, events=events)
    ids = [finding.id for finding in run.session.findings]
    assert all(
        finding.coverage_limits for finding in run.session.findings
        if finding.id in ids_on(run, PIN_ID)
    )

    run.answer_evidence_batch([("ER-001", "None bought")])

    assert [finding.id for finding in run.session.findings] == ids
    assert all(not finding.coverage_limits for finding in run.session.findings)
    assert withdrawn(events) == []
    assert resumed_message(run) == runner.answers_message([("ER-001", "None bought")])


def two_unclear_review(tmp_path: Path, events: Events | None = None) -> runner.ReviewRun:
    """The plate, the pin and a second unclear part, a bush."""
    builder = PackageBuilder(design_stem=ROOT_STEM)
    builder.component(builder.document("FICT-7001", "part"))
    pin = builder.document(PIN_STEM, "part")
    builder.component(pin)
    bush = builder.document("FICT-KALO-BUSH", "part")
    builder.component(bush)
    folder = tmp_path / "run-0001"
    builder.build().write(folder)
    from swreview.agent.providers.fake import FakeProvider

    callbacks = [] if events is None else [
        lambda event: events.append((event.type, dict(event.body)))
    ]
    run = runner.start_review(
        folder,
        folder,
        provider=FakeProvider(
            script=[first_turn("check_rms_part", "check_hygiene"), ScriptedTurn(text="resumed")],
            model="fake-scripted",
        ),
        standards_profile=write_profile(tmp_path),
        callbacks=callbacks,
    )
    run.start()
    return run


def test_a_typed_list_buys_the_named_parts_and_keeps_the_others(
    tmp_path: Path, scripted_registry: None
) -> None:
    run = two_unclear_review(tmp_path)
    bush_id = "doc:0004"
    bush_findings = ids_on(run, bush_id)

    run.answer_evidence_batch([("ER-001", "fict-kalo-pin")])

    roles = getattr(run.context, PART_ROLES_ATTRIBUTE)
    assert roles.by_document[PIN_ID].role == "bought"
    assert roles.by_document[bush_id].role == "custom"
    assert ids_on(run, PIN_ID) == []
    assert ids_on(run, bush_id) == bush_findings


def test_an_unmatched_piece_is_quoted_in_one_row_and_changes_nothing_else(
    tmp_path: Path, scripted_registry: None
) -> None:
    run = two_unclear_review(tmp_path)

    run.answer_evidence_batch([("ER-001", f"{PIN_STEM}.SLDPRT; FICT-NOTHING-9")])

    rows = [item for item in run.session.coverage.unresolved
            if item.check == "coverage.prerun.part_roles"]
    assert [row.reason for row in rows] == ["'FICT-NOTHING-9' names none of the listed parts"]
    assert getattr(run.context, PART_ROLES_ATTRIBUTE).by_document[PIN_ID].role == "bought"


# --- 3. only the question itself regrades ---------------------------------------------------------


def test_the_models_look_alike_question_does_nothing(
    tmp_path: Path, scripted_registry: None
) -> None:
    events: Events = []
    run = graded(tmp_path, events=events)
    look_alike = record_evidence_request(
        run.context,
        "Parts no rule tells apart: FICT-7001.SLDPRT",
        "a model's own copy",
        [PLATE_ID],
        question=QUESTION,
        options=["All bought", "None bought"],
    )
    ids = [finding.id for finding in run.session.findings]
    steps = len(run.session.steps)

    run.answer_evidence_batch([(look_alike.id, "All bought")])

    assert [finding.id for finding in run.session.findings] == ids
    assert withdrawn(events) == []
    assert len(run.session.steps) == steps
    assert resumed_message(run) == runner.answers_message([(look_alike.id, "All bought")])


def test_an_unanswered_question_changes_nothing(tmp_path: Path, scripted_registry: None) -> None:
    run = graded(tmp_path)
    other = record_evidence_request(run.context, "a value", "a reason", [PLATE_ID])
    ids = [finding.id for finding in run.session.findings]

    run.answer_evidence_batch([(other.id, "a free answer")])

    assert [finding.id for finding in run.session.findings] == ids
    [question] = [item for item in run.session.evidence_requests if item.question == QUESTION]
    assert question.status == "open"


def test_a_tool_that_never_ran_is_not_restated(tmp_path: Path, scripted_registry: None) -> None:
    """Restating supersedes the call it restates; a check nobody ran has nothing to supersede."""
    run = roles_review(
        tmp_path, turns=(first_turn("check_rms_part"), ScriptedTurn(text="resumed"))
    )
    run.start()
    before = len(run.session.steps)

    run.answer_evidence_batch([("ER-001", "All bought")])

    assert [step.tool for step in run.session.steps[before:]] == ["check_rms_part"]


# --- 4. checks first: the guard and lever 13 follow the restated calls ---------------------------


def test_with_checks_first_a_repeat_is_answered_from_the_restated_call(
    tmp_path: Path, scripted_registry: None
) -> None:
    run = graded(
        tmp_path,
        efficiency=EfficiencySettings(prerun_checks=True),
        resumed=(ScriptedTurn(text="again", tool_calls=(ScriptedToolCall("check_rms_part"),)),),
    )

    run.answer_evidence_batch([("ER-001", "All bought")])

    prerun, restated, repeat = [
        step.index for step in run.session.steps if step.tool == "check_rms_part"
    ]
    assert prerun < restated < repeat
    envelope = json.loads(
        (run.out_dir / TOOL_RESULTS_DIR_NAME / f"step-{repeat}.json").read_text(encoding="utf-8")
    )
    assert envelope["payload"]["status"] == ALREADY_RUN
    assert envelope["payload"]["ran_at_step"] == restated
    assert ids_on(run, PIN_ID) == []


def test_with_lever_13_the_offered_array_is_unchanged_by_the_regrade(
    tmp_path: Path, scripted_registry: None
) -> None:
    run = graded(
        tmp_path, efficiency=EfficiencySettings(prerun_checks=True, withhold_prerun_tools=True)
    )
    offered = [tool.name for tool in run.tools]

    run.answer_evidence_batch([("ER-001", "All bought")])

    assert [tool.name for tool in run.tools] == offered
    assert not set(ROLE_TOOLS) & set(offered)


# --- 5. one batch: a confirmed drawing read and the part-roles answer --------------------------


def test_a_batch_reads_the_candidate_first_then_regrades_then_restates_drawings_once(
    tmp_path: Path, scripted_registry: None
) -> None:
    from swreview.ir.loader import load_package, save_package
    from tests.support.drawings import DrawingBuilder
    from tests.unit.test_confirmed_drawing_read import FakeHost, merged

    builder = PackageBuilder(design_stem=ROOT_STEM, schema_version="1.6.0")
    plate = builder.document("FICT-7001", "part")
    builder.component(plate)
    pin = builder.document(PIN_STEM, "part")
    builder.component(pin)
    drawings = DrawingBuilder(builder.build().package)
    drawings.candidate(plate)
    folder = tmp_path / "run-0001"
    save_package(drawings.build(), folder)
    host = FakeHost(folder, {plate: merged(folder, plate)})
    roles_at_read: list[str] = []

    def read(run_id: str, document_id: str) -> dict[str, Any]:
        roles_at_read.append(
            getattr(run_holder[0].context, PART_ROLES_ATTRIBUTE).by_document[PIN_ID].role
        )
        return FakeHost.drawing_read(host, run_id, document_id)

    host.drawing_read = read  # type: ignore[method-assign]
    run_holder: list[runner.ReviewRun] = []
    from swreview.agent.providers.fake import FakeProvider

    run = runner.start_review(
        folder,
        folder,
        provider=FakeProvider(
            script=[
                first_turn("check_drawings", "check_rms_part", "check_hygiene"),
                ScriptedTurn(text="resumed"),
            ],
            model="fake-scripted",
        ),
        standards_profile=write_profile(tmp_path),
        bridge=True,
        bridge_factory=lambda pipe, secret: host,
    )
    run_holder.append(run)
    run.start()
    [candidate] = [
        item for item in run.session.evidence_requests if CANDIDATE_CONFIRM in item.options
    ]
    before = len(run.session.steps)

    run.answer_evidence_batch([("ER-001", "All bought"), (candidate.id, CANDIDATE_CONFIRM)])

    assert roles_at_read == ["unclear"]
    restated = [step.tool for step in run.session.steps[before:]]
    assert restated.count("check_drawings") == 1
    assert restated == ["check_rms_part", "check_hygiene", "check_drawings"]
    assert load_package(folder).package.drawing_records
    assert ids_on(run, PIN_ID) == []


# --- 6. ToolContext.withdraw_findings, the one place a finding leaves ------------------------


def context_with_findings(count: int) -> tuple[Any, Events]:
    from swreview.tools.context import context_for
    from tests.support.packages import build_package

    events: Events = []
    context = context_for(build_package())
    context.emit = lambda kind, body: events.append((kind, dict(body)))
    for _ in range(count):
        context.require_session().findings.append(
            build_finding(
                finding_id=next(context.finding_ids),
                check="fit.scripted",
                title="t",
                status="suspected",
                severity="low",
                package=context.ir,
                configuration="Default",
                observed="o",
                requirement="r",
                recommended_action="a",
                component_ids=["cmp:0001"],
            )
        )
    return context, events


def test_withdraw_findings_removes_them_in_session_order_and_announces_each() -> None:
    """*Changed 2026-11-03 on purpose (002 T382; cycle 16):* each body also names its finding's
    display title, here the title "t" as written, since it is not the one `title_from` records.
    *Changed 2026-11-03 on purpose (002 T386; cycle 16's Tier 2 review):* "t" names none of the
    finding's parts, so the name of its part, housing-1, follows it."""
    context, events = context_with_findings(3)

    gone = context.withdraw_findings(["F-003", "F-001"], "a reason")

    assert gone == ["F-001", "F-003"]
    assert [finding.id for finding in context.require_session().findings] == ["F-002"]
    assert events == [
        (
            "finding.withdrawn",
            {"finding_id": "F-001", "title": "t; housing-1", "reason": "a reason"},
        ),
        (
            "finding.withdrawn",
            {"finding_id": "F-003", "title": "t; housing-1", "reason": "a reason"},
        ),
    ]


def test_withdrawing_an_id_the_session_does_not_hold_announces_nothing() -> None:
    context, events = context_with_findings(1)

    assert context.withdraw_findings(["F-009"], "a reason") == []
    assert context.withdraw_findings([], "a reason") == []
    assert [finding.id for finding in context.require_session().findings] == ["F-001"]
    assert events == []


def test_withdraw_findings_needs_a_session() -> None:
    context, _ = context_with_findings(0)
    context.session = None

    with pytest.raises(ValueError, match="review session"):
        context.withdraw_findings(["F-001"], "a reason")


def test_a_withdrawal_names_the_decision_and_triage_it_took() -> None:
    """002 T358 (roadmap hole H-g-010): a finding withdrawn with a decision takes it with it, and
    its `finding.withdrawn` body says so - the disposition it held, and the words file's clause
    naming the decision and, when one was recorded, its triage, which the Transcript prints after
    the reason - while an undecided finding's body is as before.

    *Changed 2026-11-03 on purpose (002 T382; cycle 16):* each body also names its finding's
    display title, here the title "t" as written, decided or not. *Changed 2026-11-03 on purpose
    (002 T386; cycle 16's Tier 2 review):* "t" names none of the finding's parts, so the name of
    its part, housing-1, follows it."""
    from swreview.report.dispositions import set_disposition

    context, events = context_with_findings(3)
    session = context.require_session()
    set_disposition(session, "F-001", "rejected", "FICT not a problem", "FICT-ENG", triage="wrong")
    set_disposition(session, "F-002", "accepted", "FICT to fix", "FICT-ENG")
    held = {
        finding.id: finding.disposition.model_dump(mode="json")
        for finding in session.findings
        if finding.disposition is not None
    }

    context.withdraw_findings(["F-001", "F-002", "F-003"], "a reason")

    assert events == [
        (
            "finding.withdrawn",
            {
                "finding_id": "F-001",
                "title": "t; housing-1",
                "reason": "a reason",
                "disposition": held["F-001"],
                "taken": "your Reject (wrong) went with it",
            },
        ),
        (
            "finding.withdrawn",
            {
                "finding_id": "F-002",
                "title": "t; housing-1",
                "reason": "a reason",
                "disposition": held["F-002"],
                "taken": "your Accept went with it",
            },
        ),
        (
            "finding.withdrawn",
            {"finding_id": "F-003", "title": "t; housing-1", "reason": "a reason"},
        ),
    ]


def test_a_withdrawn_pass_names_its_miss_as_a_miss() -> None:
    """Owner decision 187A: a pass's one triage, `wrong`, is a miss, so the clause names it as the
    pass's card and the cleared line do."""
    from swreview.report.dispositions import set_disposition

    context, events = context_with_findings(1)
    session = context.require_session()
    session.findings[0] = session.findings[0].model_copy(
        update={"status": "checked_within_scope", "severity": "info"}
    )
    set_disposition(session, "F-001", "accepted", "FICT checked", "FICT-ENG", triage="wrong")

    context.withdraw_findings(["F-001"], "a reason")

    [(_, body)] = events
    assert body["taken"] == "your Accept (wrong: a miss) went with it"


def test_a_withdrawal_names_its_findings_display_title() -> None:
    """002 T382 (cycle 16; FR-031): each `finding.withdrawn` body names its finding's display title,
    `title`, decided or not - the title its `finding` event names: the whole first sentence of what
    it observed, its part named, where the recorded title is cut and names the part by its id. A
    line printed from the body alone, `report.md`'s or a read-only restore's, then says which
    finding went."""
    from swreview.report.dispositions import set_disposition
    from swreview.report.titles import title_from

    context, events = context_with_findings(2)
    session = context.require_session()
    observed = (
        "cmp:0001 holds a fine-pitch thread that is not in the standard list for its nominal "
        "size, so the drawing must call it out. FICT a second sentence."
    )
    session.findings[:] = [
        finding.model_copy(update={"title": title_from(observed), "observed": observed})
        for finding in session.findings
    ]
    assert session.findings[0].title.startswith("cmp:0001 holds")
    assert session.findings[0].title.endswith("…")
    set_disposition(session, "F-001", "accepted", "FICT to fix", "FICT-ENG")

    context.withdraw_findings(["F-001", "F-002"], "a reason")

    whole = (
        "housing-1 holds a fine-pitch thread that is not in the standard list for its nominal "
        "size, so the drawing must call it out"
    )
    assert [(body["finding_id"], body.get("title"), "taken" in body) for _, body in events] == [
        ("F-001", whole, True),
        ("F-002", whole, False),
    ]


def test_a_withdrawal_names_its_findings_parts_where_its_title_names_none() -> None:
    """002 T386 (cycle 16's Tier 2 review; FR-031): a check's title can name no part - "the
    equation manager holds no equations" - so findings on two parts share it, and a withdrawal whose
    title names none of its finding's parts names them after it: a line printed from the body alone
    then says which part went, decided or not. A title that names its part, here by its document's
    file name, is the display title alone."""
    from swreview.report.dispositions import set_disposition

    context, events = context_with_findings(3)
    session = context.require_session()
    shared = "the equation manager holds no equations"
    session.findings[:] = [
        session.findings[0].model_copy(update={"title": shared}),
        session.findings[1].model_copy(update={"title": shared, "component_ids": ["cmp:0002"]}),
        session.findings[2].model_copy(update={"title": "housing.SLDPRT has no part number"}),
    ]
    set_disposition(session, "F-002", "accepted", "FICT to fix", "FICT-ENG")

    context.withdraw_findings(["F-001", "F-002", "F-003"], "a reason")

    assert [(body["finding_id"], body.get("title"), "taken" in body) for _, body in events] == [
        ("F-001", f"{shared}; housing-1", False),
        ("F-002", f"{shared}; housing-2", True),
        ("F-003", "housing.SLDPRT has no part number", False),
    ]


def test_a_look_alike_request_is_an_evidence_request_like_any_other() -> None:
    """The look-alike above is a plain model request: `source` model, no text box."""
    request = EvidenceRequest(
        id="ER-002", what="w", why="y", entity_ids=[], status="open", answer=None,
        answered_at=None, question=QUESTION, options=["All bought", "None bought"],
    )
    assert (request.source, request.allow_text) == ("model", False)


# --- 7. a restated finding keeps the engineer's disposition (010 T125, owner decision 58A) ------
#
# Feature 010's amendment of 2026-10-08 (research R2.26, 58A): the restate folds every finding it
# judges again onto its earlier id, and the disposition the engineer recorded on the earlier one
# - through `chat/sessions.record_disposition`, the live chat's path - goes with it. Accept is how
# the engineer confirms a fine thread (51A), and the part-roles answer restates the check. The
# section imports where it uses, as section 5 does, so no line above it moves (T119 cites them).

Recorded = list[tuple[str, dict[str, Any] | None]]


def recorded_dispositions(findings: Sequence[Any]) -> Recorded:
    """Each finding's id and its disposition as JSON (decision, note, by and at), in order."""
    return [
        (
            finding.id,
            None if finding.disposition is None else finding.disposition.model_dump(mode="json"),
        )
        for finding in findings
    ]


def saved_dispositions(run: runner.ReviewRun) -> Recorded:
    """`recorded_dispositions` of the `session.json` the run last wrote."""
    from swreview.report.session import load_session

    return recorded_dispositions(load_session(run.session_path).findings)


def disposed(run: runner.ReviewRun, *, pin_decision: str = "deferred") -> Recorded:
    """`accepted` on the plate's first finding, `rejected` on its second and `pin_decision` on
    the pin's first, each with its own note and `by`; the pin's second finding gets none.
    Returns what the session then holds."""
    from swreview.chat.sessions import record_disposition

    plate, pin = ids_on(run, PLATE_ID), ids_on(run, PIN_ID)
    for finding_id, decision, note, by in (
        (plate[0], "accepted", "the plate is right as modelled", "a.engineer"),
        (plate[1], "rejected", "the plate needs no change here", "b.engineer"),
        (pin[0], pin_decision, "the pin is to be confirmed", "c.engineer"),
    ):
        record_disposition(run, finding_id, decision=decision, note=note, by=by)
    recorded = recorded_dispositions(run.session.findings)
    assert sum(disposition is None for _, disposition in recorded) == 1  # the pin's second
    return recorded


def test_none_bought_folds_every_finding_onto_its_id_with_its_disposition(
    tmp_path: Path, scripted_registry: None
) -> None:
    run = graded(tmp_path)
    recorded = disposed(run)
    steps = len(run.session.steps)

    run.answer_evidence_batch([("ER-001", "None bought")])

    # Every finding is the restated one: it cites only the steps the answer's restate recorded.
    restated = {step.index for step in run.session.steps[steps:]}
    assert all(
        finding.tool_result_ids and set(finding.tool_result_ids) <= restated
        for finding in run.session.findings
    )
    assert recorded_dispositions(run.session.findings) == recorded


def test_none_bought_writes_the_kept_dispositions_to_session_json(
    tmp_path: Path, scripted_registry: None
) -> None:
    run = graded(tmp_path)
    recorded = disposed(run)

    run.answer_evidence_batch([("ER-001", "None bought")])

    assert saved_dispositions(run) == recorded


def test_none_bought_re_announces_each_finding_with_its_disposition(
    tmp_path: Path, scripted_registry: None
) -> None:
    events: Events = []
    run = graded(tmp_path, events=events)
    recorded = disposed(run)
    mark = len(events)

    run.answer_evidence_batch([("ER-001", "None bought")])

    ids = {finding_id for finding_id, _ in recorded}
    announced = [
        (body["id"], body["disposition"])
        for kind, body in events[mark:]
        if kind == "finding" and body["id"] in ids
    ]
    assert announced == recorded


def test_the_restate_withdraws_each_id_it_folded(tmp_path: Path, scripted_registry: None) -> None:
    """002 T340 (the backlog's cycle 3 section; FR-031, the stream agrees with the fold): each
    restated call announced its finding under a new id, and the restate folded it onto the
    earlier finding it re-judges, so each new id is withdrawn - naming the id it folded onto - right
    before that id's `finding` event. A reader of the stream then holds the session's ids, and no
    card is left under a new one."""
    events: Events = []
    run = graded(tmp_path, events=events)
    earlier = [finding.id for finding in run.session.findings]
    mark = len(events)

    run.answer_evidence_batch([("ER-001", "None bought")])

    after = events[mark:]
    folds = [
        (index, body) for index, (kind, body) in enumerate(after) if kind == "finding.withdrawn"
    ]
    assert sorted(body["folded_into"] for _, body in folds) == sorted(earlier)
    for index, body in folds:
        assert body["finding_id"] not in earlier
        assert body["reason"] == (
            f"a second verdict on what {body['folded_into']} judges, shown as {body['folded_into']}"
        )
        kind, announced = after[index + 1]
        assert (kind, announced["id"]) == ("finding", body["folded_into"])
    held: set[str] = set()
    for kind, body in events:
        if kind == "finding":
            held.add(body["id"])
        elif kind == "finding.withdrawn":
            held.discard(body["finding_id"])
    assert held == {finding.id for finding in run.session.findings} == set(earlier)


def test_all_bought_withdraws_an_accepted_pin_finding_as_before(
    tmp_path: Path, scripted_registry: None
) -> None:
    """*Changed 2026-11-02 on purpose (002 T358; roadmap hole H-g-010):* the accepted pin finding
    is still withdrawn, and its withdrawal now names the Accept it took, with the disposition; the
    undecided pin finding's is as before.

    *Changed 2026-11-03 on purpose (002 T382; cycle 16):* each withdrawal also names its finding's
    title, as its `finding` event announced it."""
    events: Events = []
    run = graded(tmp_path, events=events)
    pin_findings = ids_on(run, PIN_ID)
    recorded = dict(disposed(run, pin_decision="accepted"))
    titles = announced(events)
    mark = len(events)

    run.answer_evidence_batch([("ER-001", "All bought")])

    assert pin_findings[0] not in [finding.id for finding in run.session.findings]
    assert withdrawn(events[mark:]) == [
        {
            "finding_id": pin_findings[0],
            "title": titles[pin_findings[0]],
            "reason": BOUGHT_REASON,
            "disposition": recorded[pin_findings[0]],
            "taken": "your Accept went with it",
        },
        {
            "finding_id": pin_findings[1],
            "title": titles[pin_findings[1]],
            "reason": BOUGHT_REASON,
        },
    ]
    [row] = [item for item in run.session.coverage.skipped
             if item.check == "coverage.prerun.bought_parts"]
    assert pin_findings[0] in row.reason


def test_all_bought_keeps_the_plate_findings_dispositions(
    tmp_path: Path, scripted_registry: None
) -> None:
    run = graded(tmp_path)
    plate_findings = ids_on(run, PLATE_ID)
    recorded = disposed(run, pin_decision="accepted")

    run.answer_evidence_batch([("ER-001", "All bought")])

    kept = [
        (finding_id, disposition)
        for finding_id, disposition in recorded
        if finding_id in plate_findings
    ]
    assert recorded_dispositions(run.session.findings) == kept
    assert saved_dispositions(run) == kept


def test_a_restated_finding_keeps_its_triage(tmp_path: Path, scripted_registry: None) -> None:
    """Owner decision 185A (002 T308): a disposition's triage rides through the restate's fold
    with its decision, note and `by` - 58A carries the whole disposition - in memory, in
    `session.json` and in each finding's re-announcement. Set through `set_disposition`, the
    record that `record_disposition` applies to the live session."""
    from swreview.report.dispositions import set_disposition

    events: Events = []
    run = graded(tmp_path, events=events)
    plate, pin = ids_on(run, PLATE_ID), ids_on(run, PIN_ID)
    triages = {plate[0]: "already_known", plate[1]: "wrong", pin[0]: "new_and_real"}
    decisions = ((plate[0], "accepted"), (plate[1], "rejected"), (pin[0], "deferred"))
    for finding_id, decision in decisions:
        set_disposition(
            run.session, finding_id, decision, "FICT note", "FICT-ENG", triage=triages[finding_id]
        )
    recorded = recorded_dispositions(run.session.findings)
    mark = len(events)

    run.answer_evidence_batch([("ER-001", "None bought")])

    assert recorded_dispositions(run.session.findings) == recorded
    assert saved_dispositions(run) == recorded
    assert {
        finding_id: disposition["triage"]
        for finding_id, disposition in recorded
        if disposition is not None
    } == triages
    announced = {
        body["id"]: body["disposition"]["triage"]
        for kind, body in events[mark:]
        if kind == "finding" and body["id"] in triages
    }
    assert announced == triages


# --- 8. report.md says what a withdrawal took (002 T358; roadmap hole H-g-010) ---------------


def test_the_views_name_a_decided_withdrawal_from_the_sessions_own_stream(
    tmp_path: Path, scripted_registry: None
) -> None:
    """002 T358 (roadmap hole H-g-010): `ReviewRun.write_views`, the report every live writer
    renders - a turn's end, a decision, the minutes, Send's saves - names the finding the answer
    withdrew with the Accept recorded on it, read from the stream the session wrote; and after a
    re-run's rotation moved that stream aside and left another session's in its place, from the
    rotated one (cycle 6's `_own_stream` rule).

    *Changed 2026-11-03 on purpose (002 T382; cycle 16):* the line names the finding's title, as
    its `finding` event announced it, right after the id; and the undecided pin finding's id now
    starts no line at all, where "- <id> withdrawn:" alone would let a titled line of it pass."""
    from swreview.agent.providers import AgentEvent

    events: Events = []
    run = graded(tmp_path, events=events)
    pin = ids_on(run, PIN_ID)
    titles = announced(events)
    disposed(run, pin_decision="accepted")
    run.answer_evidence_batch([("ER-001", "All bought")])
    named = f"- {pin[0]} ({titles[pin[0]]}) withdrawn: {BOUGHT_REASON}; your Accept went with it"

    run.write_views(save=False, best_effort=False)

    assert named in report_lines(run)
    assert not any(line.startswith(f"- {pin[1]} ") for line in report_lines(run))

    stream = run.events_path
    stream.rename(stream.with_name("events.1.jsonl"))
    another = AgentEvent(
        seq=1,
        at="2026-11-02T09:00:00+00:00",
        type="session.started",
        body={"session_id": "00000000-0000-4000-8000-000000000357"},
    )
    stream.write_text(another.model_dump_json() + "\n", encoding="utf-8")

    run.write_views(save=False, best_effort=False)

    assert named in report_lines(run)


def report_lines(run: runner.ReviewRun) -> list[str]:
    """The lines of the `report.md` the run last wrote."""
    return (run.out_dir / "report.md").read_text(encoding="utf-8").splitlines()
