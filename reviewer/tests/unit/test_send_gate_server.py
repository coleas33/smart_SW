"""T027: one renderer preserves the ticked report and logs secondary failures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview.chat import server
from swreview.chat.sessions import ChatSession
from tests.unit import test_chat_review_routes as routes
from tests.unit import test_chat_server as chat

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir
finished_chat = routes.finished_chat


def test_the_shared_renderer_writes_the_same_report_and_attention_as_a_ticked_chat(
    app: Any, client: TestClient, run_dir: Path, finished_chat: str
) -> None:
    held = routes.held_chat(app, finished_chat)
    expected = {name: (run_dir / name).read_bytes() for name in ("report.md", "attention.json")}
    for name in expected:
        (run_dir / name).unlink()
    app.state.server._render_run(held.run, held.report_path, run_dir)
    assert {name: (run_dir / name).read_bytes() for name in expected} == expected


@pytest.mark.parametrize("point", ["rank", "report", "attention"])
def test_a_ranking_or_write_failure_is_logged_and_never_raises(
    app: Any,
    client: TestClient,
    run_dir: Path,
    finished_chat: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    point: str,
) -> None:
    held = routes.held_chat(app, finished_chat)

    def refused(*args: Any, **kwargs: Any) -> Any:
        raise OSError("FICT-secondary-render-failure")

    if point == "rank":
        monkeypatch.setattr(server, "rank", refused)
    elif point == "report":
        monkeypatch.setattr(Path, "write_text", refused)
    else:
        monkeypatch.setattr(server, "write_attention_record", refused)
    app.state.server._render_run(held.run, held.report_path, run_dir)
    assert "FICT-secondary-render-failure" in caplog.text


def test_render_report_retains_its_no_run_guard_and_delegates_once(
    app: Any,
    client: TestClient,
    finished_chat: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held = routes.held_chat(app, finished_chat)
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(app.state.server, "_render_run", lambda *args: calls.append(args))
    app.state.server._render_report(ChatSession())
    assert calls == []
    app.state.server._render_report(held)
    assert calls == [(held.run, held.report_path, held.run_dir)]
