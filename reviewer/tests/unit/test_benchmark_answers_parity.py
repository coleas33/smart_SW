"""The driver's answers are the pane's (feature 014 T098; `contracts/scripted-answers.md` 3, 7).

FR-023; the US4 Independent Test's "as the pane would", and US4-6's "both arms get the same
scripted answers", which rests on this and on the saved set's `case_file_sha256` (T095). One
fictional package and one scripted model, played twice with the pane's settings
(`pane_defaults`, as `chat/server._start_review` reads them):

- through the chat server, as the chat-server tests drive it: `POST /sessions`, then
  `POST /sessions/{id}/evidence` carrying what the pane's Send carries, every answered question in
  session order and nothing for a skipped one (`app.js:2154-2166, 2233-2242`);
- through `start_review` and `drive_review`, with a case file answering the same question.

The requests (id, status, answer), the `evidence.answered` events, the resumed user message the
scripted model received and the findings are equal: the only differences are the HTTP layer and
the page.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview.agent.providers import AgentProvider, ProviderName
from swreview.agent.settings import ProviderSettings, pane_defaults
from swreview.chat.server import create_app
from swreview.chat.sessions import ChatState
from swreview.ir.loader import save_package
from swreview.report.session import ReviewSession, load_session
from tests.support.scripted_answers import (
    FASTENERS,
    FIT,
    SpyProvider,
    ask,
    case_file,
    drive,
    turn,
)
from tests.unit.test_benchmark_questions import PACKAGE, PIN_1, PLATE_1, PLATE_HOLE
from tests.unit.test_chat_server import ORIGIN, TOKEN, Models, events_of, settle, start_session

PACKAGE_ID = "fict-questions"
RUN_NAME = "20261008-090000-fict-questions"
FIT_ANSWER = "press fit"

SCRIPT = (
    turn(ask(PIN_1, PLATE_HOLE, item=FIT), ask(PIN_1, item=FASTENERS), text="Two questions."),
    turn(text="A press fit; the fasteners stay open."),
)
"""The model asks the fit, which the engineer answers, and which fasteners go in the pin, which
the engineer skips; the resumed turn closes."""


@pytest.fixture
def built() -> list[tuple[ProviderSettings, SpyProvider]]:
    """Each adapter the chat server built, with the settings it was built from."""
    return []


@pytest.fixture
def client(
    tmp_path: Path, built: list[tuple[ProviderSettings, SpyProvider]]
) -> Iterator[TestClient]:
    """The pane's client on a chat server whose adapter is the scripted model."""

    def factory(settings: ProviderSettings) -> AgentProvider:
        provider = SpyProvider(script=list(SCRIPT), model=settings.model)
        built.append((settings, provider))
        return provider

    run_root = tmp_path / "runs"
    run_root.mkdir()
    app = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=factory,
        list_models=Models(),
    )
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}) as test:
        yield test


def requests_of(session: ReviewSession) -> list[tuple[str, str, str | None]]:
    return [(request.id, request.status, request.answer) for request in session.evidence_requests]


def answered_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event["body"] for event in events if event["type"] == "evidence.answered"]


def findings_of(session: ReviewSession) -> list[dict[str, Any]]:
    return [finding.model_dump(mode="json") for finding in session.findings]


def test_the_driver_answers_as_the_pane_s_send_does(
    tmp_path: Path, client: TestClient, built: list[tuple[ProviderSettings, SpyProvider]]
) -> None:
    pane_dir = tmp_path / "runs" / RUN_NAME
    save_package(PACKAGE, pane_dir)
    chat_id = start_session(client, pane_dir)["chat_id"]
    assert settle(client, chat_id) == ChatState.WAITING_ENGINEER.value
    asked = load_session(pane_dir / "session.json").evidence_requests
    [fit] = [request.id for request in asked if request.blocks == FIT]
    response = client.post(
        f"/sessions/{chat_id}/evidence",
        json={"answers": [{"request_id": fit, "answer": FIT_ANSWER}]},
    )
    assert response.status_code == 202, response.text
    assert settle(client, chat_id) == ChatState.WAITING_ENGINEER.value
    [(settings, pane_model)] = built

    package_dir = tmp_path / "packages" / PACKAGE_ID
    save_package(PACKAGE, package_dir)
    defaults = pane_defaults(ProviderName.FAKE)
    driver_model = SpyProvider(script=list(SCRIPT), model=settings.model)
    driven = drive(
        package_dir,
        tmp_path / "run" / PACKAGE_ID,
        driver_model,
        case_file(
            tmp_path / "case_files",
            PACKAGE_ID,
            {"id": "A-1", "item": FIT, "ids": [PLATE_1, PIN_1], "answer": FIT_ANSWER},
            package=PACKAGE,
        ),
        model=settings.model,
        effort=settings.effort,
        key_source=settings.key_source,
        efficiency=defaults.efficiency,
        model_view=defaults.model_view,
        explain_findings=defaults.explain_findings,
    )

    pane = load_session(pane_dir / "session.json")
    benchmark = load_session(driven.run.session_path)
    assert requests_of(benchmark) == requests_of(pane)
    assert ("answered", FIT_ANSWER) in {(status, answer) for _, status, answer in requests_of(pane)}
    assert answered_events(events_of(driven.run.out_dir)) == answered_events(events_of(pane_dir))
    assert answered_events(events_of(pane_dir)) == [{"request_id": fit, "answer": FIT_ANSWER}]
    assert len(driver_model.sent) == len(pane_model.sent) == 2
    assert driver_model.user_message(1) == pane_model.user_message(1)
    assert findings_of(benchmark) == findings_of(pane)
    assert findings_of(pane)
    assert driven.log.ended == "all_unscripted"
