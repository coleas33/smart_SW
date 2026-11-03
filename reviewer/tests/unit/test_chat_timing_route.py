"""`POST /sessions/{chat_id}/timing` (T013), against `contracts/timing.md` section 3.

The command line can time any run folder, but a pane review's session is **held in memory**
by the run and written again at the end of every turn, so a recording that only reached the
disk would be overwritten by the next finalize - exactly the reason `record_disposition`
exists beside `apply_disposition`. This route writes the live session, so the four inputs
survive the next turn, and it re-renders the report with the package the run is holding.

The body may carry only the four input names. `net_saved_minutes` is refused **by name**
rather than ignored, because `Timing.model_validate` would silently accept a supplied net
and the derived figure is the one number the pilot must never type (FR-004).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview.report.session import load_session
from tests.unit import test_chat_server as chat
from tests.unit.test_chat_server import (
    DRAWING_FINDING_ARGUMENTS,
    ProviderControl,
    call,
    settle,
    start_session,
    text_turns,
    turn,
    types_of,
    wait_until,
)

# The application, its door and its scripted provider are `test_chat_server`'s, so this
# module drives the same real app rather than standing up a second one. pytest resolves a
# fixture by the name bound in the module using it, which is what these eight lines do
# (*changed 2026-11-03, 002 T406:* the last two, a review held at its final render).
app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir
final_render = chat.final_render
review_ending = chat.review_ending

PLACEHOLDER = "_The evidence package was not supplied to the renderer._"

FOUR: dict[str, Any] = {
    "baseline": 45,
    "supervision": 6,
    "verification": 9,
    "false_alarms": 2,
    "setup": 0,
    "by_hand": 0,
}
"""Quickstart scenario 1's recording; the derived net is 28.0.

*Changed 2026-11-01 on purpose (owner decision 183A; 007 T065):* with setup and the review by
hand recorded as 0, since the net is unknown without them; every figure read from it, here and
in `test_waiting_answers.py`, keeps its value."""


@pytest.fixture
def timed_chat(client: TestClient, run_dir: Path, provider_control: ProviderControl) -> str:
    """A settled review of the run folder, ready to be timed."""
    provider_control.script = [
        turn("One finding.", call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS)),
        *text_turns(2),
    ]
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)
    return chat_id


def post(client: TestClient, chat_id: str, body: dict[str, Any]) -> Any:
    return client.post(f"/sessions/{chat_id}/timing", json=body)


def files_in(directory: Path) -> dict[str, bytes]:
    """Every file under `directory`, keyed by its relative path.

    Feature 008 T066, edited deliberately: a review writes `tool-results/step-<n>.json`, so
    the folder holds a sub-folder, and the snapshot walks it - a write into `tool-results/`
    is then caught too, which the flat listing could not see."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


# --- 1. the recording ----------------------------------------------------------------


def test_the_four_inputs_are_recorded_and_the_net_is_derived(
    client: TestClient, timed_chat: str
) -> None:
    response = post(client, timed_chat, FOUR)

    assert response.status_code == 200, response.text
    timing = response.json()
    assert timing["baseline_minutes"] == 45.0
    assert timing["assisted_supervision_minutes"] == 6.0
    assert timing["assisted_verification_minutes"] == 9.0
    assert timing["false_alarm_handling_minutes"] == 2.0
    assert timing["net_saved_minutes"] == 28.0


def test_the_write_reaches_the_session_file(
    client: TestClient, run_dir: Path, timed_chat: str
) -> None:
    post(client, timed_chat, FOUR)

    timing = load_session(run_dir / "session.json").timing
    assert timing.baseline_minutes == 45.0
    assert timing.net_saved_minutes == 28.0


def test_the_report_is_re_rendered_with_the_run_s_package(
    client: TestClient, run_dir: Path, timed_chat: str
) -> None:
    post(client, timed_chat, FOUR)

    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "- Net saved minutes: 28.0" in report
    assert PLACEHOLDER not in report


def test_the_values_survive_the_next_turn(
    client: TestClient, run_dir: Path, timed_chat: str
) -> None:
    """The live session is written again at the end of every turn; a disk-only write loses."""
    post(client, timed_chat, FOUR)

    client.post(f"/sessions/{timed_chat}/messages", json={"text": "carry on"})
    settle(client, timed_chat)

    assert load_session(run_dir / "session.json").timing.net_saved_minutes == 28.0


def test_an_omitted_input_keeps_the_value_already_recorded(
    client: TestClient, timed_chat: str
) -> None:
    post(client, timed_chat, FOUR)

    timing = post(client, timed_chat, {"supervision": 7}).json()

    assert timing["baseline_minutes"] == 45.0
    assert timing["assisted_supervision_minutes"] == 7.0
    assert timing["net_saved_minutes"] == 27.0


def test_an_explicit_null_keeps_the_value_already_recorded(
    client: TestClient, timed_chat: str
) -> None:
    """`null` is "not supplied", the same as leaving the key out (contract section 3)."""
    post(client, timed_chat, FOUR)

    timing = post(client, timed_chat, {"baseline": None}).json()

    assert timing["baseline_minutes"] == 45.0


def test_the_route_records_setup_and_the_review_left_by_hand(
    client: TestClient, run_dir: Path, timed_chat: str
) -> None:
    """Owner decision 183A (007 T065): the body takes `setup` and `by_hand` beside the four, and
    the live session and its file carry them: 120 less 57 (User Story 1, scenario 7). A field's
    own name is still refused by name, as every key outside the six is."""
    body = {
        "baseline": 120,
        "supervision": 6,
        "verification": 9,
        "false_alarms": 2,
        "setup": 10,
        "by_hand": 30,
    }

    response = post(client, timed_chat, body)

    assert response.status_code == 200, response.text
    timing = response.json()
    assert (timing["setup_minutes"], timing["review_by_hand_minutes"]) == (10.0, 30.0)
    assert timing["net_saved_minutes"] == 63.0
    saved = load_session(run_dir / "session.json").timing
    assert (saved.setup_minutes, saved.review_by_hand_minutes) == (10.0, 30.0)
    assert saved.net_saved_minutes == 63.0
    for key in ("setup_minutes", "review_by_hand_minutes"):
        refused = post(client, timed_chat, {key: 5})
        assert refused.status_code == 400, refused.text
        assert refused.json()["error_class"] == "InvalidTiming"
        assert key in refused.json()["message"]


def test_timing_is_not_a_review_event(client: TestClient, run_dir: Path, timed_chat: str) -> None:
    before = types_of(run_dir)

    post(client, timed_chat, FOUR)

    assert types_of(run_dir) == before


# --- 2. what the body may not carry ---------------------------------------------------


@pytest.mark.parametrize(
    ("body", "named"),
    [
        ({"net_saved_minutes": 999}, "net_saved_minutes"),
        ({"baseline": 45, "net_saved_minutes": 999}, "net_saved_minutes"),
        ({"unattended_runtime_minutes": 5}, "unattended_runtime_minutes"),
        ({"baseline_minutes": 45}, "baseline_minutes"),
        ({"nonsense": 1}, "nonsense"),
        ({"baseline": "forty-five"}, "baseline"),
        ({"supervision": True}, "supervision"),
        ({"verification": [9]}, "verification"),
        ({"false_alarms": -1}, "false_alarms"),
        ({"baseline": -0.5}, "baseline"),
    ],
)
def test_a_body_that_is_not_the_four_numbers_is_refused_by_name(
    client: TestClient, timed_chat: str, body: dict[str, Any], named: str
) -> None:
    response = post(client, timed_chat, body)

    assert response.status_code == 400, response.text
    error = response.json()
    assert error["error_class"] == "InvalidTiming"
    assert named in error["message"]


def test_a_refused_body_writes_nothing(client: TestClient, run_dir: Path, timed_chat: str) -> None:
    post(client, timed_chat, FOUR)
    before = files_in(run_dir)

    assert post(client, timed_chat, {"net_saved_minutes": 999}).status_code == 400

    assert files_in(run_dir) == before


# --- 3. the two states that cannot take a recording -----------------------------------


def test_a_running_turn_is_refused(
    client: TestClient, timed_chat: str, provider_control: ProviderControl
) -> None:
    provider_control.hold()
    client.post(f"/sessions/{timed_chat}/messages", json={"text": "keep going"})
    wait_until(provider_control.started.is_set, "the follow-up turn to reach the gate")

    response = post(client, timed_chat, FOUR)

    assert response.status_code == 409
    assert response.json()["error_class"] == "TurnRunning"
    provider_control.release()


def test_a_save_sent_as_the_review_ends_waits_for_the_settle_and_is_recorded(
    client: TestClient, run_dir: Path, review_ending: tuple[str, chat.FinalRender]
) -> None:
    """002 cycle 24: minutes saved between the runner's `session.ended` and the chat leaving
    `running` met `409 TurnRunning`, which the minutes form tried once more a second later. The
    save waits for the settle and is recorded as a save a moment later is, `report.md` written
    after the turn's own render."""
    chat_id, held = review_ending

    response = chat.sent_as_the_review_ends(held, lambda: post(client, chat_id, FOUR))

    assert response.status_code == 200, response.text
    assert response.json()["net_saved_minutes"] == 28.0
    assert load_session(run_dir / "session.json").timing.net_saved_minutes == 28.0
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "- Net saved minutes: 28.0" in report
    assert PLACEHOLDER not in report


def test_an_unknown_chat_is_a_404(client: TestClient) -> None:
    response = post(client, "8a1d6f60-0000-4000-8000-000000000000", FOUR)

    assert response.status_code == 404
    assert response.json()["error_class"] == "UnknownChat"
