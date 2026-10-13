"""T052: waiting page acceptance uses fresh snapshots from the actual unticked backend."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from swreview.agent.settings import ProviderSettings
from swreview.report.session import load_session
from swreview.report.summary import load_words
from tests.support.mechanical import load_generator
from tests.support.roles_review import PIN_ID, PLATE_ID
from tests.support.scramble import FICTIONAL_ROOT

REPO = Path(__file__).resolve().parents[3]
GENERATOR = REPO / "reviewer/tests/fixtures/pane/generate_waiting_fixtures.py"
WRITE_COMMAND = "uv run python tests/fixtures/pane/generate_waiting_fixtures.py --write"
NAMES = ("waiting", "waiting-big-assembly")
TARGETS = {
    name: REPO / "extractor/SwReview.AddIn.Tests/Fixtures" / f"review-{name}.json"
    for name in NAMES
}


@pytest.mark.parametrize("name", NAMES)
def test_each_waiting_fixture_is_committed(name: str) -> None:
    assert TARGETS[name].is_file(), f"{TARGETS[name].name} is missing; run `{WRITE_COMMAND}`"


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    return load_generator(GENERATOR)


@pytest.fixture(scope="module")
def generated(generator: ModuleType) -> dict[str, dict[str, Any]]:
    built: list[ProviderSettings] = []
    observed: list[str] = []

    def forbidden_provider(settings: ProviderSettings) -> Any:
        built.append(settings)
        raise AssertionError("A waiting fixture must build no provider")

    def inspect_run(name: str, folder: Path, app: Any) -> None:
        session = load_session(folder / "session.json")
        assert session.started_at == generator.PINNED
        assert session.ended_at == generator.PINNED
        assert session.model_status is not None
        assert session.model_status.state == "not_sent"
        assert session.model_status.checked_at == generator.PINNED
        assert session.model_status.sent_at is None
        events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
        assert events and events[-1]["type"] == "session.ended"
        assert all(datetime.fromisoformat(event["at"]) == generator.PINNED for event in events)
        assert not any(event["type"] in ("usage", "turn.started", "turn.ended") for event in events)
        [chat] = app.state.server.chats.values()
        assert chat.run is not None and chat.run.turns == 0
        assert session.timing.unattended_runtime_minutes == 0
        assert (folder / "report.md").is_file()
        assert "- Model: not sent to the model (checked by code only)" in (
            folder / "report.md"
        ).read_text()
        assert len(app.state.server.chats) == 1
        observed.append(name)

    result = generator.waiting_fixtures(provider_factory=forbidden_provider, observe=inspect_run)
    assert built == []
    assert observed == list(NAMES)
    return result


@pytest.mark.parametrize("name", NAMES)
def test_each_committed_fixture_equals_fresh_backend_bytes(
    name: str, generator: ModuleType, generated: dict[str, dict[str, Any]]
) -> None:
    assert TARGETS[name].read_bytes() == generator.render_bytes(generated[name]), (
        f"{TARGETS[name].name} differs from fresh backend bytes; run `{WRITE_COMMAND}` "
        "from reviewer/ and commit the result"
    )


@pytest.mark.parametrize("name", NAMES)
def test_the_live_snapshot_and_labels_have_the_exact_us2_shape(
    name: str, generated: dict[str, dict[str, Any]]
) -> None:
    fixture = generated[name]
    keys = ["labels", "waiting"]
    if name == "waiting":
        keys.append("sending")
    assert list(fixture) == [*keys, "failed_send"]
    assert fixture["labels"] == load_words().labels.model_dump(mode="json")
    waiting = fixture["waiting"]
    assert waiting["run_id"] == f"fict-{name}"
    assert waiting["chat_state"] == "awaiting_send"
    assert waiting["read_only"] is False
    assert waiting["read_only_reason"] is None
    assert waiting["last_seq"] > 0
    assert waiting["document"]["path"].startswith(FICTIONAL_ROOT)
    send = waiting["ranking"]["summary"]["send"]
    assert list(send) == [
        "state", "input_tokens", "approximate", "text", "failure", "rerun_failed_text"
    ]
    assert send["state"] == "waiting"
    assert isinstance(send["input_tokens"], int) and send["input_tokens"] > 0
    assert send["approximate"] is False
    assert send["failure"] is None
    assert send["rerun_failed_text"] is None
    assert send["text"] == load_words().send.first_request.format(
        tokens=f"{send['input_tokens']:,}"
    )


def test_the_small_fixture_carries_both_real_code_questions(
    generated: dict[str, dict[str, Any]]
) -> None:
    waiting = generated["waiting"]["waiting"]
    requests = waiting["evidence_requests"]
    assert len(requests) == 2
    assert {request["source"] for request in requests} == {"code"}
    assert {request.get("blocks") for request in requests} == {
        None, "drawing.manufacturing_inputs"
    }
    assert PIN_ID in requests[0]["entity_ids"]
    assert "All bought" in requests[0]["options"]
    assert PLATE_ID in requests[1]["entity_ids"]
    assert all(request["status"] == "open" for request in requests)
    assert len(waiting["ranking"]["summary"]["questions"]["items"]) == 2


def test_generator_targets_are_the_page_acceptance_files(generator: ModuleType) -> None:
    assert generator.WRITE_COMMAND == WRITE_COMMAND
    assert generator.TARGETS == TARGETS


def test_both_waiting_fixtures_are_in_the_existing_hygiene_scan() -> None:
    from tests.unit import test_replay_fixture_hygiene as hygiene

    for name in NAMES:
        assert hygiene.committed_files(name) == (TARGETS[name],)


@pytest.mark.parametrize("kind", ("candidate", "fit", "joint_map"))
def test_hygiene_removes_only_the_exact_public_code_reason(
    kind: str, generated: dict[str, dict[str, Any]]
) -> None:
    from swreview.checks.drawing_context import CANDIDATES_WHY
    from tests.support.scramble import tokens_of, without_reviewer_text

    if kind == "candidate":
        reason = generated["waiting"]["waiting"]["evidence_requests"][1]["why"]
        assert reason == CANDIDATES_WHY
    else:
        rows = generated["waiting-big-assembly"]["waiting"]["coverage"]
        fragment = "no interface was evaluated:" if kind == "fit" else "as a joint member"
        reason = next(row["item"]["reason"] for row in rows if fragment in row["item"]["reason"])
    assert {"bore", "callouts"}.intersection(tokens_of(without_reviewer_text(reason))) == set()

    # An extra word inside the public clause breaks its exact match. Its tokens remain
    # subject to the unchanged denylist, as do unrelated words beside an exact clause.
    token = "callouts" if kind == "candidate" else "bore"
    foreign = reason.replace(token, f"FICT foreign {token}")
    assert without_reviewer_text(foreign) == foreign
    mixed = without_reviewer_text(f"FICT supplier bore; {reason}; FICT foreign callouts")
    assert "FICT supplier bore" in mixed
    assert "FICT foreign callouts" in mixed


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("source", ("committed", "fresh"))
def test_failed_send_is_an_actual_live_waiting_snapshot_with_the_words_failure(
    name: str, source: str, generated: dict[str, dict[str, Any]]
) -> None:
    """015 T071: both page fixtures carry a failed first request, ready for another Send."""
    fixture = (
        json.loads(TARGETS[name].read_bytes()) if source == "committed" else generated[name]
    )
    before = fixture["waiting"]
    failed = fixture["failed_send"]
    assert failed["run_id"] == before["run_id"]
    assert failed["document"] == before["document"]
    assert failed["chat_state"] == "awaiting_send"
    assert failed["read_only"] is False
    assert "send_in_flight" not in failed
    assert failed["last_seq"] > before["last_seq"]
    block = failed["ranking"]["summary"]["send"]
    assert block["state"] == "waiting"
    assert block["input_tokens"] == before["ranking"]["summary"]["send"]["input_tokens"]
    assert block["text"] == before["ranking"]["summary"]["send"]["text"]
    assert block["failure"] == load_words().send.failed.format(
        reason="FICT scripted first request failed", time="12:00"
    )


@pytest.mark.parametrize("source", ("committed", "fresh"))
def test_sending_is_the_live_snapshot_while_the_first_request_is_held(
    source: str, generated: dict[str, dict[str, Any]]
) -> None:
    """015 T071: the reload snapshot comes before first usage, with Send still in flight."""
    fixture = (
        json.loads(TARGETS["waiting"].read_bytes())
        if source == "committed"
        else generated["waiting"]
    )
    before = fixture["waiting"]
    sending = fixture["sending"]
    failed = fixture["failed_send"]
    assert sending["run_id"] == before["run_id"]
    assert sending["document"] == before["document"]
    assert sending["chat_state"] == "running"
    assert sending["send_in_flight"] is True
    assert sending["read_only"] is False
    assert before["last_seq"] < sending["last_seq"] < failed["last_seq"]
