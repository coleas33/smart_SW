"""Feature 016's saved engineering context on feature 015's send gate (owner decision 99A).

The T116 integration review found that 016, written before 015, started reviews on its own path.
These tests pin each of its findings on the adapted branch: an unticked context review sends
nothing and Send's first request carries the context once (blocker A and the combined test 99A
names); the opening rebuilt after a waiting answer keeps the context (blocker B); a restored
waiting review's re-run carries its attachment and never loses its summary (should-fix C); and
saved context cannot change while a review that carries it is set up or waits (should-fix D).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview.agent import runner
from swreview.engineering_context.brief import compact_json
from tests.support.recording_provider import RecordingProvider
from tests.unit import test_chat_engineering_context as ctx
from tests.unit import test_chat_server as chat
from tests.unit import test_waiting_answers as waiting_cases

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir

ENGINEERING_LEAD = "Engineer-supplied inputs for the saved evidence snapshot follow as JSON data."
"""The first sentence of the opening's engineering block (`runner._opening_message`)."""
SUMMARY_FILE = "engineering-context-summary.json"


def attachment_of(client: TestClient, folder: Path, entity_id: str = "cmp:0001") -> dict[str, Any]:
    """Initialize the folder's private context with one draft requirement; its exact attachment."""
    head = ctx.initialize(client, folder)
    saved = client.post(
        ctx.endpoint(folder, "/requirement"), json=ctx.requirement(head, entity_id=entity_id)
    )
    assert saved.status_code == 200, saved.text
    published = saved.json()
    return {key: published[key] for key in ("context_id", "head_digest", "package_sha256")}


def waiting_with_context(app: Any, client: TestClient, folder: Path) -> waiting_cases.Waiting:
    """015's unticked questions review, started with a saved context attached."""
    return waiting_cases.waiting_review(
        app,
        client,
        folder,
        attach=lambda written: {"engineering_context": attachment_of(client, written)},
    )


def block_of(folder: Path) -> str:
    """The retained summary, as the opening carries it."""
    return compact_json(json.loads((folder / SUMMARY_FILE).read_text(encoding="utf-8")))


def assert_block_once(opening: str, folder: Path) -> None:
    assert opening.count(ENGINEERING_LEAD) == 1, opening
    assert opening.count(block_of(folder)) == 1, opening


def sent_opening(
    app: Any, client: TestClient, chat_id: str, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Press Send on a waiting chat with a recording provider: the first request's message."""
    provider = RecordingProvider([chat.turn("FICT sent")])
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: provider)
    assert client.post(f"/sessions/{chat_id}/send", json={}).status_code == 202
    chat.settle(client, chat_id)
    return str(provider.log[0].first_message["content"])


# --- blocker A, and the combined test 99A names ------------------------------------------------


def test_an_unticked_context_review_builds_no_provider_and_send_carries_the_block_once(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = run_root / "FICT-context-waits"
    waiting = waiting_with_context(app, client, folder)

    assert provider_control.built == []
    assert waiting.run.context.engineering_context is not None
    assert chat.state_of(client, waiting.chat_id) == "awaiting_send"
    assert_block_once(waiting.run.opening_message, folder)

    opening = sent_opening(app, client, waiting.chat_id, monkeypatch)

    assert provider_control.built == []
    assert_block_once(opening, folder)
    assert opening.endswith(runner.OPENING_MESSAGE)


def test_a_stale_attachment_on_an_unticked_start_is_refused_before_any_setup(
    client: TestClient, run_dir: Path, provider_control: chat.ProviderControl
) -> None:
    head = ctx.initialize(client, run_dir)
    stale = {
        "context_id": head["context_id"],
        "head_digest": "a" * 64,
        "package_sha256": head["package_sha256"],
    }
    refused = client.post(
        "/sessions",
        json=chat.session_body(run_dir, send_when_checked=False, engineering_context=stale),
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error_class"] == "EngineeringContextConflict"
    assert provider_control.built == []
    assert not (run_dir / "session.json").exists()
    assert not (run_dir / "events.jsonl").exists()
