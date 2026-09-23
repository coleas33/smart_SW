"""The two restore routes (feature 009 T050), against contracts/sessions.md sections 3 and 4.

A chip restores a review without spending a token. Two routes answer the same snapshot
(`report/snapshot.review_snapshot`):

- `GET /sessions/{chat_id}/snapshot` from the run the backend holds - its live session, its
  ledger, the chat's state and the stream's last seq, so a page reloaded mid-turn reopens the
  stream where the snapshot ends;
- `GET /reviews/{run_id}` from a run folder, read-only, after a settings save restarted the
  backend and dropped every chat.

Both **compute and never write**: every file under the run folder keeps its bytes and its
modification time. And the disk route takes a caller-supplied name, so it goes through the
same path rule as `run_dir` and `check_id`, and every refusal - a name the rule refuses, no
such folder, no session, a check folder, an unreadable file - is the same `404 UnknownReview`
naming only the id, so the route cannot be used to probe the workstation.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import pytest
from pydantic_core import to_jsonable_python
from starlette.testclient import TestClient

from swreview.chat.server import UnknownReview, create_app
from swreview.ir.loader import load_package
from swreview.report.attention import rank
from swreview.report.session import load_session
from swreview.report.snapshot import review_snapshot
from swreview.report.summary import load_words
from tests.support.attention import CHECK_FOLDER
from tests.unit import test_chat_server as chat
from tests.unit.test_chat_server import (
    DRAWING_FINDING_ARGUMENTS,
    ORIGIN,
    ROUTES,
    TOKEN,
    ProviderControl,
    call,
    events_of,
    settle,
    start_session,
    text_turns,
    turn,
)

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir

UNKNOWN_CHAT = "8a1d6f60-0000-4000-8000-000000000000"

SECOND_FINDING = {**DRAWING_FINDING_ARGUMENTS, "observed": "The second tapped hole has no depth"}


@pytest.fixture
def finished_chat(client: TestClient, run_dir: Path, provider_control: ProviderControl) -> str:
    """A settled review that recorded two findings and asked one question."""
    provider_control.script = [
        turn(
            "Two findings and a question.",
            call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS),
            call("record_drawing_finding", **SECOND_FINDING),
            call("request_evidence", **chat.EVIDENCE_ARGUMENTS),
        ),
        *text_turns(2),
    ]
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)
    return chat_id


def tree_state(folder: Path) -> dict[str, tuple[bytes, int]]:
    """Every file under `folder`, recursively: its bytes and its modification time."""
    return {
        str(path.relative_to(folder)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def held_chat(app: Any, chat_id: str) -> Any:
    return app.state.server.chats[UUID(chat_id)]


# --- 1. GET /sessions/{chat_id}/snapshot ----------------------------------------------------


def test_the_live_snapshot_is_the_runs_session_package_ledger_state_and_seq(
    app: Any, client: TestClient, run_dir: Path, finished_chat: str
) -> None:
    held = held_chat(app, finished_chat)
    run = held.run

    response = client.get(f"/sessions/{finished_chat}/snapshot")

    assert response.status_code == 200, response.text
    assert response.json() == to_jsonable_python(
        review_snapshot(
            run.session,
            run.context.ir,
            run_id=run_dir.name,
            usage=run.usage_ledger,
            chat_state=held.state.value,
            last_seq=run.sink.seq,
        )
    )
    body = response.json()
    assert (body["run_id"], body["read_only"], body["read_only_reason"]) == (
        run_dir.name,
        False,
        None,
    )
    assert body["chat_state"] == held.state.value
    assert body["last_seq"] == max(event["seq"] for event in events_of(run_dir))


def test_the_live_snapshots_findings_come_in_the_order_of_the_finding_events(
    client: TestClient, run_dir: Path, finished_chat: str
) -> None:
    body = client.get(f"/sessions/{finished_chat}/snapshot").json()

    streamed = [event["body"]["id"] for event in events_of(run_dir) if event["type"] == "finding"]
    assert [finding["id"] for finding in body["findings"]] == streamed == ["F-001", "F-002"]
    assert [request["id"] for request in body["evidence_requests"]] == ["ER-001"]


def test_the_live_snapshot_writes_nothing(
    client: TestClient, run_dir: Path, finished_chat: str
) -> None:
    before = tree_state(run_dir)

    assert client.get(f"/sessions/{finished_chat}/snapshot").status_code == 200

    assert tree_state(run_dir) == before


def test_an_unknown_chat_has_no_snapshot(client: TestClient) -> None:
    response = client.get(f"/sessions/{UNKNOWN_CHAT}/snapshot")

    assert response.status_code == 404
    assert response.json()["error_class"] == "UnknownChat"


# --- 2. GET /reviews/{run_id} --------------------------------------------------------------


def test_the_run_folder_restores_read_only_with_the_words_files_reason(
    client: TestClient, run_dir: Path, finished_chat: str
) -> None:
    response = client.get(f"/reviews/{run_dir.name}")

    assert response.status_code == 200, response.text
    body = response.json()
    session = load_session(run_dir / "session.json")
    package = load_package(run_dir).package
    assert body == to_jsonable_python(
        review_snapshot(
            session, package, run_id=run_dir.name, read_only_reason=load_words().read_only
        )
    )
    assert (body["read_only"], body["read_only_reason"]) == (True, load_words().read_only)
    assert (body["chat_state"], body["last_seq"]) == (None, None)
    ranking = dict(body["ranking"])
    summary = ranking.pop("summary")
    assert ranking == to_jsonable_python(rank(session))
    assert summary["resume_input_tokens"] is None
    assert summary["resume_text"] == "Sending resumes the review once."


def test_the_run_folder_route_writes_nothing(
    client: TestClient, run_dir: Path, finished_chat: str
) -> None:
    before = tree_state(run_dir)

    assert client.get(f"/reviews/{run_dir.name}").status_code == 200

    assert tree_state(run_dir) == before


def test_a_restarted_backend_still_serves_the_run_folder(
    client: TestClient,
    run_root: Path,
    run_dir: Path,
    finished_chat: str,
    provider_control: ProviderControl,
    models: Any,
) -> None:
    """A settings save restarts the backend and drops every chat; the folder remains."""
    restarted = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=provider_control.factory,
        list_models=models,
    )
    with TestClient(
        restarted, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as fresh:
        assert fresh.get(f"/sessions/{finished_chat}/snapshot").status_code == 404
        response = fresh.get(f"/reviews/{run_dir.name}")

    assert response.status_code == 200, response.text
    assert [finding["id"] for finding in response.json()["findings"]] == ["F-001", "F-002"]


# --- 3. every refusal is the same 404, naming only the id -------------------------------------


def assert_unknown_review(response: Any, run_root: Path) -> None:
    assert response.status_code == 404, response.text
    body = response.json()
    assert body["error_class"] == "UnknownReview"
    assert str(run_root) not in body["message"]
    assert str(run_root.resolve()) not in body["message"]


@pytest.mark.parametrize(
    "raw",
    [
        "..",
        "\\\\server\\share",
        "\\\\.\\pipe\\x",
        "C:\\Windows",
        "..\\elsewhere",
        "20260913-120000-no-such-run",
    ],
    ids=["dot-dot", "unc", "device", "outside-the-root", "dot-dot-in-a-name", "missing-folder"],
)
def test_a_name_the_rule_refuses_or_no_folder_is_unknown(
    client: TestClient, run_root: Path, raw: str
) -> None:
    # Every character encoded, dots too: a client normalizes a literal `/reviews/..` away
    # before sending it, and the point is that the route itself refuses the name.
    encoded = quote(raw, safe="").replace(".", "%2E")
    assert_unknown_review(client.get("/reviews/" + encoded), run_root)


@pytest.mark.parametrize("raw", ["..", "\\\\server\\share", "C:\\Windows"])
def test_the_resolver_itself_refuses_as_unknown(app: Any, raw: str) -> None:
    """The HTTP client may normalize a path before it is sent; the rule does not rely on it."""
    with pytest.raises(UnknownReview):
        app.state.server._review_dir(raw)


def test_a_folder_with_no_session_is_unknown(
    client: TestClient, run_root: Path, run_dir: Path
) -> None:
    assert (run_dir / "package.json").is_file()
    assert not (run_dir / "session.json").exists()

    assert_unknown_review(client.get(f"/reviews/{run_dir.name}"), run_root)


def test_a_check_folder_is_unknown(client: TestClient, run_root: Path) -> None:
    target = run_root / "20260918-220310-check"
    shutil.copytree(CHECK_FOLDER, target)
    assert (target / "check.json").is_file() and (target / "session.json").is_file()

    assert_unknown_review(client.get(f"/reviews/{target.name}"), run_root)


@pytest.mark.parametrize("broken", ["session.json", "package.json"])
def test_an_unreadable_session_or_package_is_unknown(
    client: TestClient, run_root: Path, run_dir: Path, finished_chat: str, broken: str
) -> None:
    (run_dir / broken).write_text("{ not json", encoding="utf-8")

    assert_unknown_review(client.get(f"/reviews/{run_dir.name}"), run_root)


def test_a_package_that_does_not_validate_is_unknown(
    client: TestClient, run_root: Path, run_dir: Path, finished_chat: str
) -> None:
    (run_dir / "package.json").write_text(json.dumps({"schema_version": "0.0.1"}), encoding="utf-8")

    assert_unknown_review(client.get(f"/reviews/{run_dir.name}"), run_root)


# --- 4. the door ----------------------------------------------------------------------------


def test_both_routes_are_in_the_door_tests_census() -> None:
    assert ("GET", "/sessions/{chat}/snapshot") in ROUTES
    assert any(method == "GET" and path.startswith("/reviews/") for method, path in ROUTES)
