"""The question columns on what the product actually records (feature 014 T098).

`contracts/questions.md` 7 and 9's last bullet; US3-5, US3-6; RF-13; research §2's lesson
(`no-oracle-null-tests`): the counting pinned on the real `request_evidence` and its re-ask guard,
not only on sessions built as data. Each anchor is one review of the questions reader's fictional
package (`questions.md` 7's ids: the plate `doc:0002` with its instance `cmp:0001` and hole
`hol:0001`, the bought pin `doc:0003` with its instances `cmp:0002` and `cmp:0003`) under the
convention-only profile of `tests/support/roles_review.py`, so the part-roles question is
`ER-001`, as the table numbers it. The scripted model calls the real tool, `drive_review` answers
between turns from the case file, and `benchmark.scorecard.score_run` reads the run folder
against a format 2 key: the guard's outcomes are the table's, and so are the columns.

- R-2: the pin asked on no item, then the same call again, refused `already_asked`; scored
  against `U-1`, the pin's document unanswerable.
- R-2, US3-5: among other calls, a drawing request on the pin's document `doc:0003`, answered
  `closed_by_code` on a package carrying drawing evidence (the candidate drawing beside the
  plate; the pin has none attached).
- R-3: the fit asked naming the pin and the plate's hole, answered "press fit"; the item-only
  follow-up is recorded, so the driver answers it again at the next point and the script plays
  that second answer turn (`scripted-answers.md` 3's re-delivery): one re-ask, seen.
- R-3, refused: the follow-up naming the plate's hole alone, refused `already_answered`.

No `pytest.mark.integration`: that marker means "needs a saved native evidence package", which
`tests/conftest.py` skips wherever one is absent; this needs none (plan decision RF-26).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from swreview.agent.providers.fake import ScriptedTurn
from swreview.benchmark.scorecard import PackageScore, score_run
from swreview.benchmark.sets import BenchmarkPackageRef, BenchmarkSet
from swreview.checks.standards.profile import load_profile
from swreview.ir.loader import save_package
from swreview.tools.registry import StoredResult, read_stored_result
from tests.support.answer_keys import write_key
from tests.support.roles_review import write_profile
from tests.support.scripted_answers import (
    FASTENERS,
    FIT,
    Driven,
    ask,
    case_file,
    drive,
    scripted,
    turn,
)
from tests.unit.test_answer_key import count_rule, unanswerable
from tests.unit.test_benchmark_questions import (
    DRAWING,
    PACKAGE,
    PIN_1,
    PIN_DOC,
    PLATE_1,
    PLATE_HOLE,
    counted,
    no_answer,
    repeat,
    unanswered,
)

PACKAGE_ID = "fict-questions"

A_1: dict[str, Any] = {"id": "A-1", "item": FIT, "ids": [PLATE_1, PIN_1], "answer": "press fit"}
"""R-3's scripted answer: the fit of the pin in the plate."""

FIT_QUESTION = ask(PIN_1, PLATE_HOLE, item=FIT)


def scored(
    tmp_path: Path,
    *turns: ScriptedTurn,
    unanswerable_requests: Sequence[dict[str, Any]] = (),
) -> tuple[Driven, PackageScore]:
    """One review of the package played by `turns` through the driver with `A-1`, then the run
    folder scored against a key holding `unanswerable_requests` and R-1's part-roles rule."""
    profile = write_profile(tmp_path)
    package_dir = tmp_path / "packages" / PACKAGE_ID
    save_package(PACKAGE, package_dir)
    run_dir = tmp_path / "run"
    driven = drive(
        package_dir,
        run_dir / PACKAGE_ID,
        scripted(*turns),
        case_file(
            tmp_path / "case_files",
            PACKAGE_ID,
            A_1,
            package=PACKAGE,
            profile=load_profile(profile),
        ),
        standards_profile=profile,
    )
    keys = tmp_path / "answer_keys"
    write_key(
        keys,
        PACKAGE_ID,
        unanswerable_requests=unanswerable_requests,
        question_counts=[count_rule()],
    )
    benchmark_set = BenchmarkSet(
        name="fict-questions",
        packages=[BenchmarkPackageRef(package_id=PACKAGE_ID, path=package_dir)],
    )
    [score] = score_run(run_dir, keys, benchmark_set).per_package
    return driven, score


def guard_outcomes(driven: Driven) -> list[str]:
    """Each `request_evidence` call's status, from its stored result: what the product said."""
    session = driven.run.session
    statuses: list[str] = []
    for step in session.steps:
        if step.tool != "request_evidence":
            continue
        stored = read_stored_result(
            driven.run.out_dir,
            session.session_id,
            step.index,
            tool=step.tool,
            arguments=step.arguments,
        )
        assert isinstance(stored, StoredResult), stored
        statuses.append(str(stored.payload["status"]))
    return statuses


def asked(driven: Driven) -> list[tuple[str, str, str]]:
    """Each request on the session: id, who wrote it, status."""
    return [
        (request.id, request.source, request.status)
        for request in driven.run.session.evidence_requests
    ]


def test_r_2_two_requests_on_the_pin(tmp_path: Path) -> None:
    driven, score = scored(
        tmp_path, turn(ask(PIN_1), ask(PIN_1)), unanswerable_requests=[unanswerable()]
    )

    assert guard_outcomes(driven) == ["open", "already_asked"]
    assert asked(driven) == [("ER-001", "code", "open"), ("ER-002", "model", "open")]
    assert score.unanswerable_requests == [
        unanswered(0, "recorded", "ER-002"),
        unanswered(1, "already_asked", "ER-002"),
    ]
    assert score.open_repeats == [repeat(1, "already_asked", "ER-002", of="ER-002")]
    assert score.re_asks == []
    assert score.question_counts == [counted("Q-1", 1, 1, 1)]
    assert score.unscripted_questions == [no_answer("ER-001"), no_answer("ER-002")]
    assert score.bound_reached is False


def test_r_2_a_drawing_request_on_the_pin_closed_by_code_is_one_unanswerable_request(
    tmp_path: Path,
) -> None:
    """US3-5: every matching call counts, whatever its outcome. The fit call among them is
    `A-1`'s, so the driver answers it and the script closes in the answer turn."""
    driven, score = scored(
        tmp_path,
        turn(ask(PLATE_1, item=FASTENERS), ask(PIN_DOC, item=DRAWING), ask(PLATE_HOLE, item=FIT)),
        turn(text="Noted."),
        unanswerable_requests=[unanswerable()],
    )

    assert guard_outcomes(driven) == ["open", "closed_by_code", "open"]
    assert score.unanswerable_requests == [unanswered(1, "closed_by_code", None)]
    assert score.re_asks == []
    assert score.open_repeats == []


def test_r_3_an_item_only_follow_up_is_answered_again_and_is_one_re_ask_seen(
    tmp_path: Path,
) -> None:
    driven, score = scored(
        tmp_path, turn(FIT_QUESTION), turn(ask(item=FIT)), turn(text="A press fit.")
    )

    assert guard_outcomes(driven) == ["open", "open"]
    assert asked(driven) == [
        ("ER-001", "code", "open"),
        ("ER-002", "model", "answered"),
        ("ER-003", "model", "answered"),
    ]
    assert [[one.request_id for one in point.sent] for point in driven.log.points] == [
        ["ER-002"],
        ["ER-003"],
        [],
    ]
    assert len(driven.provider.sent) == 3
    assert score.re_asks == [repeat(1, "recorded", "ER-003", of="ER-002")]
    assert score.open_repeats == []
    assert score.unanswerable_requests is None
    assert score.question_counts == [counted("Q-1", 1, 1, 1)]
    assert score.unscripted_questions == [no_answer("ER-001")]


def test_r_3_refused_a_follow_up_naming_the_hole_alone_is_one_re_ask_refused(
    tmp_path: Path,
) -> None:
    driven, score = scored(tmp_path, turn(FIT_QUESTION), turn(ask(PLATE_HOLE, item=FIT)))

    assert guard_outcomes(driven) == ["open", "already_answered"]
    assert asked(driven) == [("ER-001", "code", "open"), ("ER-002", "model", "answered")]
    assert len(driven.provider.sent) == 2
    assert score.re_asks == [repeat(1, "already_answered", "ER-002", of="ER-002")]
    assert score.open_repeats == []
