"""`GET /sessions/{chat_id}/attention` (T035), against `contracts/attention.md` section 5.

The Review tab pins the ranking above the transcript when a session ends, and it has
nowhere to read it from today: `GET /sessions/{chat_id}` answers `ChatSession.public()`,
which carries no findings, and `GET /sessions/{chat_id}/report` answers markdown, which the
page's `call` helper turns into `null` (research R2.8). So one read-only route, answering
the same `Ranking` block the two check bodies carry.

Three rules decide every test here.

**It computes, and it never writes.** The ranking is derived from the session the run is
holding, on every call. The record beside the session is written where the session is
written - `finalize`, the two check entry points, `rerender_run_folder`, the pane's
every-turn render - and a page refresh must not touch it, so the folder's whole hash map is
asserted unchanged across the call.

**It answers the live session, not the file.** A disposition recorded a moment ago, or a
follow-up turn's findings, are in the run's session before they are anywhere else; a route
that loaded `session.json` would answer the run as it stood at the last write.

**An empty ranking is words, not an empty list.** A review that ended before its first
finding gets `rows: []` *and* `empty_reason`, because "nothing to start with" and "the panel
failed to load" must not look the same to the engineer (FR-024).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic_core import to_jsonable_python
from starlette.testclient import TestClient

from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage
from swreview.prerun import RMS_PRERUN_TOOLS
from swreview.report.attention import rank
from swreview.report.attention_record import read_attention_record
from swreview.report.session import load_session
from swreview.report.summary import load_words, review_summary
from tests.support.packages import build_package
from tests.unit import test_chat_server as chat
from tests.unit.test_chat_server import (
    DRAWING_FINDING_ARGUMENTS,
    ROUTES,
    ProviderControl,
    call,
    settle,
    start_session,
    text_turns,
    turn,
)

# The application, its door and its scripted provider are `test_chat_server`'s, so this
# module drives the same real app rather than standing up a second one, exactly as
# `test_chat_timing_route.py` does.
app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir

UNKNOWN_CHAT = "8a1d6f60-0000-4000-8000-000000000000"

NOTHING_FOUND = "no findings were recorded"
"""`rank`'s reason for a session that recorded none (`contracts/attention.md` section 3)."""


@pytest.fixture
def reviewed_chat(client: TestClient, run_dir: Path, provider_control: ProviderControl) -> str:
    """A settled review that recorded one finding."""
    provider_control.script = [
        turn("One finding.", call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS)),
        *text_turns(2),
    ]
    chat_id = start_session(client, run_dir)["chat_id"]
    settle(client, chat_id)
    return chat_id


def nothing_to_find_package() -> EvidencePackage:
    """The fixture package with its one part document dumped as a sub-assembly.

    Feature 008 T047: the pane runs checks first, and on the ordinary fixture package the
    RMS rules record three findings before the model speaks (missing folders, no global
    variables, no equation-driven dimensions). A package with no part document gives every
    pre-run check - part and equation rules, the assembly rules (no mates, so none to
    faces), the joint map - nothing to report, which is the FR-024 case this module needs.
    """
    package = build_package()
    return package.model_copy(
        update={
            "documents": [
                document.model_copy(update={"kind": "assembly"})
                if document.kind == "part"
                else document
                for document in package.documents
            ]
        }
    )


@pytest.fixture
def empty_chat(
    client: TestClient, run_root: Path, provider_control: ProviderControl
) -> tuple[str, Path]:
    """A settled review that recorded nothing: the FR-024 case the panel has to say."""
    folder = run_root / "20260913-130000-nothing"
    save_package(nothing_to_find_package(), folder)
    provider_control.script = text_turns(3)
    chat_id = start_session(client, folder)["chat_id"]
    settle(client, chat_id)
    return chat_id, folder


def get(client: TestClient, chat_id: str) -> Any:
    return client.get(f"/sessions/{chat_id}/attention")


def files_in(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


# --- 1. the ranking a settled review answers with --------------------------------------


def test_a_settled_review_answers_the_ranking_of_its_live_session(
    client: TestClient, run_dir: Path, reviewed_chat: str
) -> None:
    response = get(client, reviewed_chat)

    assert response.status_code == 200, response.text
    body = response.json()
    body.pop("summary")
    assert body == to_jsonable_python(rank(load_session(run_dir / "session.json")))


def test_the_body_is_the_block_the_check_bodies_carry(
    client: TestClient, reviewed_chat: str
) -> None:
    """One shape on all three surfaces: the `Ranking` of `contracts/attention.md` section
    4 minus `session_id`, which the route's own path already names - plus, on this route
    alone, the Review tab's `summary` (feature 009, contracts/review-summary.md section 1)."""
    body = get(client, reviewed_chat).json()

    assert set(body) == {
        "policy_version",
        "rows",
        "top_n",
        "not_amplified",
        "coverage",
        "empty_reason",
        "summary",
    }
    assert body["policy_version"] == "attention_policy_v1"
    assert body["empty_reason"] is None


def test_every_row_carries_its_reason_and_its_nine_key_values(
    client: TestClient, reviewed_chat: str
) -> None:
    """The panel renders reason lines and nothing else; the keys are what makes a
    placement arguable by pointing at a line."""
    rows = get(client, reviewed_chat).json()["rows"]

    assert rows, "the scripted review recorded a finding"
    for row in rows:
        assert row["reason"]
        assert "%" not in row["reason"], "no percent sign in any rendered attention text"
        assert set(row["key"]) == {
            "suppressed",
            "judgement",
            "consequence",
            "status",
            "severity",
            "reach",
            "carried",
            "check",
            "finding_id",
        }
        assert row["finding_id"] in row["member_finding_ids"]


def test_it_agrees_with_the_record_the_run_wrote_beside_the_session(
    client: TestClient, run_dir: Path, reviewed_chat: str
) -> None:
    """The route recomputes; `finalize` and the every-turn render wrote. Reproducible from
    the session alone means the two cannot differ (research R2.7)."""
    body = get(client, reviewed_chat).json()

    record = read_attention_record(run_dir)
    assert [row["finding_id"] for row in body["rows"]] == [row.finding_id for row in record.rows]
    assert body["policy_version"] == record.policy_version


# --- 2. it never writes ----------------------------------------------------------------


def test_the_call_writes_nothing_into_the_run_folder(
    client: TestClient, run_dir: Path, reviewed_chat: str
) -> None:
    """A page refresh must not rewrite the record of the order the engineer was shown, nor
    touch the session an engineer's disposition lives in (`contracts/attention.md` 4)."""
    before = files_in(run_dir)
    assert "attention.json" in before, "the run wrote one; the read must leave it alone"

    assert get(client, reviewed_chat).status_code == 200

    assert files_in(run_dir) == before


def test_two_calls_answer_the_same_bytes(client: TestClient, reviewed_chat: str) -> None:
    """Recomputed on every call, and deterministic, so the panel does not reorder itself
    when the engineer reopens the tab (FR-014)."""
    first = get(client, reviewed_chat)
    second = get(client, reviewed_chat)

    assert first.json() == second.json()


def test_it_answers_the_live_session_after_a_disposition(
    client: TestClient, reviewed_chat: str
) -> None:
    """The run holds the session in memory; a route reading `session.json` would answer
    the run as it stood at the last write."""
    before = get(client, reviewed_chat).json()
    finding_id = before["rows"][0]["finding_id"]

    decided = client.post(
        f"/sessions/{reviewed_chat}/findings/{finding_id}/disposition",
        json={"decision": "accepted", "note": "checked at the desk", "by": "a.engineer"},
    )
    assert decided.status_code == 200, decided.text

    after = get(client, reviewed_chat).json()
    row = next(item for item in after["rows"] if item["finding_id"] == finding_id)
    assert row["key"]["suppressed"] == 1, "an accepted finding sorts into the last bucket"
    assert after != before


# --- 3. the empty case is words ---------------------------------------------------------


def test_a_review_that_found_nothing_answers_no_rows_and_a_reason(
    client: TestClient, empty_chat: tuple[str, Path]
) -> None:
    """FR-024: the panel says there is nothing to start with, and why.

    Feature 008 T047, edited deliberately: the chat is started on a package in which the
    checks find nothing, and the pre-run's steps are asserted to exist, so "nothing found"
    is a statement about a review whose checks ran, not one that never ran them."""
    chat_id, folder = empty_chat
    response = get(client, chat_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows"] == []
    assert body["empty_reason"] == NOTHING_FOUND
    assert body["not_amplified"]["total"] == 0
    steps = [step.tool for step in load_session(folder / "session.json").steps]
    assert steps[: len(RMS_PRERUN_TOOLS)] == list(RMS_PRERUN_TOOLS)


def test_the_empty_answer_still_carries_the_coverage_block(
    client: TestClient, empty_chat: tuple[str, Path]
) -> None:
    """What the run could not reach is the useful half of an empty panel."""
    coverage = get(client, empty_chat[0]).json()["coverage"]

    assert set(coverage) >= {
        "checked",
        "skipped",
        "unresolved",
        "failed",
        "out_of_scope",
        "not_closed",
        "open_evidence_requests",
        "rules",
    }
    assert coverage["unresolved"] >= 1, "a review that said nothing closed no checklist item"


# --- 4. the door and the unknown chat ----------------------------------------------------


def test_an_unknown_chat_is_a_404(client: TestClient) -> None:
    response = get(client, UNKNOWN_CHAT)

    assert response.status_code == 404
    assert response.json()["error_class"] == "UnknownChat"


# --- 5. the summary beside the ranking (feature 009 T014) -----------------------------------


def live_run(app: Any, chat_id: str) -> Any:
    """The run the backend holds for `chat_id`: its live session and its package."""
    return app.state.server.chats[UUID(chat_id)].run


def test_the_body_is_the_live_ranking_plus_the_live_summary(
    app: Any, client: TestClient, reviewed_chat: str
) -> None:
    run = live_run(app, reviewed_chat)

    body = get(client, reviewed_chat).json()
    summary = body.pop("summary")

    assert body == to_jsonable_python(rank(run.session))
    assert summary == to_jsonable_python(
        review_summary(rank(run.session), run.session, run.context.ir, usage=run.usage_ledger)
    )
    assert summary["headline"] == "1 finding in 1 issue"


def test_the_summary_carries_the_live_ledgers_resume_figure(
    app: Any, client: TestClient, reviewed_chat: str
) -> None:
    """T039: the resume cost is the live run's measured figure (contracts/questions.md 5)."""
    run = live_run(app, reviewed_chat)
    tokens = run.usage_ledger.last_conversation_input()
    assert tokens is not None, "the scripted provider reports usage and a text.done"

    summary = get(client, reviewed_chat).json()["summary"]

    assert summary["resume_input_tokens"] == tokens
    assert summary["resume_text"] == (
        f"Sending resumes the review once. Its last round sent {tokens:,} input tokens."
    )


def test_a_review_that_found_nothing_answers_the_words_three_groups_and_every_goal(
    client: TestClient, empty_chat: str
) -> None:
    summary = get(client, empty_chat).json()["summary"]

    assert summary["headline"] == "No findings were recorded"
    assert [(group["kind"], group["count"]) for group in summary["groups"]] == [
        ("decide", 0),
        ("fix", 0),
        ("verify", 0),
    ]
    assert [line["goal"] for line in summary["goals"]] == [goal.id for goal in load_words().goals]


def test_the_summary_follows_a_disposition_like_the_ranking(
    client: TestClient, reviewed_chat: str
) -> None:
    """Computed from the live session, so a decision moves the finding into "Decided"."""
    finding_id = get(client, reviewed_chat).json()["rows"][0]["finding_id"]

    decided = client.post(
        f"/sessions/{reviewed_chat}/findings/{finding_id}/disposition",
        json={"decision": "rejected", "note": "intended", "by": "a.engineer"},
    )
    assert decided.status_code == 200, decided.text

    groups = {
        group["kind"]: group["count"]
        for group in get(client, reviewed_chat).json()["summary"]["groups"]
    }
    assert groups["decided"] == 1


def test_the_attention_record_carries_no_summary(
    client: TestClient, run_dir: Path, reviewed_chat: str
) -> None:
    """`attention.json` is the ranking as the engineer was shown it, and nothing more."""
    assert get(client, reviewed_chat).status_code == 200

    record = json.loads((run_dir / "attention.json").read_text(encoding="utf-8"))
    assert "summary" not in record


def test_the_route_is_in_the_door_test_s_census() -> None:
    """`test_chat_server.py`'s `ROUTES` is what parameterizes the no-token test, so a
    route missing from it is a route nobody proved the door covers."""
    assert ("GET", "/sessions/{chat}/attention") in ROUTES
