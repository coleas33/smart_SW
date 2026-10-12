"""A scripted part-roles answer regrades the review before the next turn (feature 014 T098).

`contracts/scripted-answers.md` 3 ("one run's answers are the pane's") and 7; US4-4, US4-7, FR-026.
Over `tests/support/roles_review.py`'s package and profile, under which the pin is unclear and the
part-roles question `ER-001` lists it, with the scripted check tools of
`test_answer_batch_roles.py`, which grade each part document and carry the unclear note on the
pin's findings. The driver delivers the case file's `part_roles` entry through
`answer_evidence_batch`, whose `_regrade_roles` and `_restate` withdraw the pin's
modelling-practice and hygiene findings with `finding.withdrawn` before the resumed turn starts,
and the resumed message carries the regrade line below the answers, exactly as the pane's batch
gets it. A model question's answer goes back in the same batch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from swreview.agent.providers.fake import ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import REGRADED_LINE, answers_message
from swreview.benchmark.answers import AnswerSent
from swreview.benchmark.case_file import CaseFile
from swreview.checks.standards.profile import load_profile
from swreview.ir.loader import load_package
from swreview.report.session import load_session
from tests.support import roles_review
from tests.support.scripted_answers import FIT, Driven, ask, case_file, drive, scripted, turn
from tests.unit import test_answer_batch_roles as roles_batch

scripted_registry = roles_batch.scripted_registry

PACKAGE_ID = "fict-roles"
PLATE_1 = "cmp:0001"
PIN_1 = "cmp:0002"
PIN_INSTANCES = frozenset({"cmp:0002", "cmp:0003"})

ALL_BOUGHT: dict[str, Any] = {"id": "A-3", "part_roles": True, "answer": "All bought"}
FIT_ANSWER: dict[str, Any] = {
    "id": "A-1",
    "item": FIT,
    "ids": [PLATE_1, PIN_1],
    "answer": "press fit",
}


def roles_case(
    tmp_path: Path, package_dir: Path, profile: Path, *entries: dict[str, Any]
) -> CaseFile:
    """The roles package's case file holding `entries`, read against its package and profile."""
    return case_file(
        tmp_path / "case_files",
        PACKAGE_ID,
        *entries,
        package=load_package(package_dir).package,
        profile=load_profile(profile),
    )


def graded(
    tmp_path: Path,
    *later: ScriptedTurn,
    entries: tuple[dict[str, Any], ...],
    opening: ScriptedToolCall | None = None,
) -> Driven:
    """The roles review, its opening turn running the part and hygiene checks and then
    `opening` when one is given, played through the driver with `entries`, the model playing
    `later` after the opening turn."""
    profile = roles_review.write_profile(tmp_path)
    package_dir = roles_review.write_package(tmp_path / "packages" / PACKAGE_ID)
    first = roles_batch.first_turn("check_rms_part", "check_hygiene")
    if opening is not None:
        first = turn(*first.tool_calls, opening, text=first.text)
    return drive(
        package_dir,
        tmp_path / "run" / PACKAGE_ID,
        scripted(first, *later),
        roles_case(tmp_path, package_dir, profile, *entries),
        standards_profile=profile,
    )


def pin_findings(driven: Driven) -> list[str]:
    """The findings the opening turn raised on the pin, from the stream."""
    return [
        event.body["id"]
        for event in driven.events
        if event.type == "finding" and PIN_INSTANCES & set(event.body["component_ids"])
    ]


def test_a_scripted_all_bought_withdraws_the_pin_s_findings_before_the_resumed_turn(
    tmp_path: Path, scripted_registry: None
) -> None:
    """US4-7, FR-026: each withdrawal is on the stream before the resumed turn's first `usage`,
    the resumed message ends with the regrade line, and the final session holds none of them."""
    driven = graded(tmp_path, turn(text="Regraded."), entries=(ALL_BOUGHT,))

    on_the_pin = pin_findings(driven)
    assert on_the_pin
    kinds = [event.type for event in driven.events]
    answered = kinds.index("evidence.answered")
    resumed_usage = kinds.index("usage", answered)
    withdrawn = [
        (index, event.body["finding_id"])
        for index, event in enumerate(driven.events)
        if event.type == "finding.withdrawn"
    ]
    assert sorted(finding_id for _, finding_id in withdrawn) == sorted(on_the_pin)
    assert all(answered < index < resumed_usage for index, _ in withdrawn)
    regrade_line = REGRADED_LINE.format(ids=", ".join(finding_id for _, finding_id in withdrawn))
    assert driven.provider.user_message(1) == (
        answers_message([("ER-001", "All bought")]) + "\n" + regrade_line
    )
    final = {finding.id for finding in load_session(driven.run.session_path).findings}
    assert final and final.isdisjoint(on_the_pin)
    assert driven.log.points[0].sent == [AnswerSent(request_id="ER-001", entry="A-3")]
    assert driven.log.ended == "no_open_questions"


def test_the_part_roles_answer_and_a_model_question_s_answer_go_back_in_one_batch(
    tmp_path: Path, scripted_registry: None
) -> None:
    """US4-4: the code question and the model's, in session order, one resumed turn."""
    driven = graded(
        tmp_path,
        turn(text="Both noted."),
        entries=(FIT_ANSWER, ALL_BOUGHT),
        opening=ask(PLATE_1, PIN_1, item=FIT),
    )

    assert len(driven.provider.sent) == 2
    assert driven.answered() == [
        {"request_id": "ER-001", "answer": "All bought"},
        {"request_id": "ER-002", "answer": "press fit"},
    ]
    assert driven.provider.user_message(1).startswith(
        answers_message([("ER-001", "All bought"), ("ER-002", "press fit")]) + "\n"
    )
    assert driven.log.points[0].sent == [
        AnswerSent(request_id="ER-001", entry="A-3"),
        AnswerSent(request_id="ER-002", entry="A-1"),
    ]
    assert driven.log.ended == "no_open_questions"


def test_a_typed_list_is_never_outside_the_part_roles_question_s_options(
    tmp_path: Path, scripted_registry: None
) -> None:
    """QA-8: the part-roles question offers a text box beside its two options, so an answer that
    is neither is one the page could send, and is not marked."""
    typed = {**ALL_BOUGHT, "answer": "fict-kalo-pin"}

    driven = graded(tmp_path, turn(text="Regraded."), entries=(typed,))

    [question] = [one for one in driven.run.session.evidence_requests if one.id == "ER-001"]
    assert question.options and question.allow_text
    assert "fict-kalo-pin" not in question.options
    assert driven.answered() == [{"request_id": "ER-001", "answer": "fict-kalo-pin"}]
    assert driven.log.points[0].sent == [AnswerSent(request_id="ER-001", entry="A-3")]
