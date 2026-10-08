"""A scripted multi-turn case through `benchmark run` and `benchmark score` (feature 014 T100).

`contracts/scripted-answers.md` 7's last file; plan decision RF-13; the US4 Independent Test
("records one answer turn, a scripted re-ask is counted, and the session shows the answer as the
pane would"); quickstart section 6. The questions reader's fictional package (`questions.md` 7's
ids: the plate `doc:0002` with its instance `cmp:0001` and hole `hol:0001`, the bought pin
`doc:0003` with its instances `cmp:0002` and `cmp:0003`) is named by a set entry with a case file
holding `A-1`, the fit of the pin in the plate. `benchmark run` reviews it with
`cli.provider_factory` patched to a scripted model that asks the fit question naming the pin and
the plate's hole, receives "press fit" through `answer_evidence_batch`, then asks for the fit's
numeric limits naming only the plate's hole, which the product's guard refuses
`already_answered`, and ends. `benchmark score` then scores the run against a format 2 key holding
no entry.

The seen re-ask and its re-delivery are `test_benchmark_answers.py`'s and
`test_questions_on_real_tools.py`'s (RF-13); this file pins the command-line path end to end.

No `pytest.mark.integration`: that marker means "needs a saved native evidence package", which
`tests/conftest.py` skips wherever one is absent; this needs none (plan decision RF-26).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.events import replay_events
from swreview.agent.runner import EVENTS_FILE_NAME, SESSION_FILE_NAME, answers_message
from swreview.agent.settings import EfficiencySettings, ProviderSettings
from swreview.benchmark.answers import (
    ANSWER_LOG_FILE_NAME,
    ANSWER_LOG_VERSION,
    AnswerLog,
    AnswerPoint,
    AnswerSent,
    read_answer_log,
)
from swreview.benchmark.scorecard import read_scorecard
from swreview.ir.loader import save_package
from swreview.report.session import load_session
from tests.support.answer_keys import write_key
from tests.support.scripted_answers import FIT, SpyProvider, ask, scripted, turn
from tests.unit.test_benchmark_questions import PACKAGE, PIN_1, PLATE_1, PLATE_HOLE, repeat

PACKAGE_ID = "fict-questions"

A_1: dict[str, Any] = {"id": "A-1", "item": FIT, "ids": [PLATE_1, PIN_1], "answer": "press fit"}
"""The case file's one entry: the fit of the pin in the plate (`scripted-answers.md` 2.2)."""

FIT_QUESTION = ask(PIN_1, PLATE_HOLE, item=FIT, what="Which fit holds the pin in the plate?")
"""The fit question, naming the pin and the plate's hole, which resolves to the plate's instance:
`A-1` asks within it (`questions.md` 2 and 3)."""

LIMITS_QUESTION = ask(
    PLATE_HOLE, item=FIT, what="The numeric limits of the fit at the plate's hole."
)
"""The follow-up naming only the plate's hole: the answered fit question covers it, so the
product answers `already_answered` and records no request (R-3, refused)."""

runner = CliRunner()


def invoke(*args: str) -> Any:
    return runner.invoke(cli.app, list(args))


def scripted_set(tmp_path: Path) -> Path:
    """The fictional package, its case file and a set naming both, written under `tmp_path`."""
    package_dir = tmp_path / "packages" / PACKAGE_ID
    save_package(PACKAGE, package_dir)
    case_file = tmp_path / "case_files" / f"{PACKAGE_ID}.json"
    case_file.parent.mkdir(parents=True)
    case_file.write_text(
        json.dumps({"case_file_version": 1, "package_id": PACKAGE_ID, "answers": [A_1]}),
        encoding="utf-8",
    )
    set_path = tmp_path / "sets" / "scripted.json"
    set_path.parent.mkdir(parents=True)
    set_path.write_text(
        json.dumps(
            {
                "name": "fict-scripted",
                "packages": [
                    {
                        "package_id": PACKAGE_ID,
                        "path": str(package_dir),
                        "case_file": str(case_file),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return set_path


@pytest.fixture
def scripted_model(monkeypatch: pytest.MonkeyPatch) -> list[SpyProvider]:
    """`cli.provider_factory` returning the scripted model: the fit question, then, resumed on
    the answer, the refused follow-up. Every adapter built is kept, so a test reads what each
    turn was sent."""
    built: list[SpyProvider] = []

    def factory(
        settings: ProviderSettings, efficiency: EfficiencySettings | None = None
    ) -> SpyProvider:
        provider = scripted(
            turn(FIT_QUESTION, text="Which fit holds the pin?"),
            turn(LIMITS_QUESTION, text="A press fit, then."),
        )
        built.append(provider)
        return provider

    monkeypatch.setattr(cli, "provider_factory", factory)
    return built


def test_a_scripted_answer_is_one_answer_turn_and_the_refused_follow_up_one_re_ask(
    tmp_path: Path, scripted_model: list[SpyProvider]
) -> None:
    set_path = scripted_set(tmp_path)
    out = tmp_path / "runs" / "scripted"
    keys = tmp_path / "answer_keys"
    write_key(keys, PACKAGE_ID)

    ran = invoke(
        "benchmark", "run", "--set", str(set_path), "--out", str(out), "--provider", "fake"
    )
    assert ran.exit_code == 0, ran.stdout + ran.stderr
    scored = invoke("benchmark", "score", str(out), "--answer-keys", str(keys))
    assert scored.exit_code == 0, scored.stdout + scored.stderr

    # The scripted model played its two turns, the second opening on the pane's answer message.
    [provider] = scripted_model
    assert len(provider.sent) == 2
    assert provider.user_message(1) == answers_message([("ER-001", "press fit")])

    # The log: one point, one delivery of `A-1`, one answer turn, and no answer text.
    folder = out / PACKAGE_ID
    log = read_answer_log(folder)
    assert log == AnswerLog(
        answer_log_version=ANSWER_LOG_VERSION,
        points=[
            AnswerPoint(
                after_turn=0,
                steps_before=1,
                sent=[AnswerSent(request_id="ER-001", entry="A-1")],
                unscripted=[],
                held=[],
            )
        ],
        ended="no_open_questions",
        last_turn_end="end",
        unused_entries=[],
    )
    assert sum(1 for point in log.points if point.sent) == 1
    assert "press fit" not in (folder / ANSWER_LOG_FILE_NAME).read_text(encoding="utf-8")

    # The scorecard: one re-ask, refused, of the answered request.
    [score] = read_scorecard(out).per_package
    assert score.re_asks == [repeat(1, "already_answered", "ER-001", of="ER-001")]
    assert score.open_repeats == []
    assert score.unscripted_questions == []
    assert score.bound_reached is False

    # The session shows the answer as the pane would: the request answered with the entry's
    # text, beside its `evidence.answered` event.
    session = load_session(folder / SESSION_FILE_NAME)
    requests = [(one.id, one.status, one.answer) for one in session.evidence_requests]
    assert requests == [("ER-001", "answered", "press fit")]
    answered = [
        event.body
        for event in replay_events(folder / EVENTS_FILE_NAME)
        if event.type == "evidence.answered"
    ]
    assert answered == [{"request_id": "ER-001", "answer": "press fit"}]
