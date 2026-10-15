"""US4: a waiting review survives a restart (feature 015, `contracts/recheck.md`).

The carried live step (T092): a re-run of a not-sent review's checks carries the first run's
live interference outcome instead of asking SOLIDWORKS again, records one carried step where
the first run recorded its call, and carries the drawing-read capability onto its own record
(FR-028; SC-008; research R2.17). The claim and the rotation (T094): `POST /sessions` with
`recheck: true` copies the earlier record, moves its stream, adopts a re-run the backend
finished, and leaves the earlier record whole whenever a re-run fails or is cut off (FR-041;
RK-4; owner decision 76A). The carry (T096): answers, decisions, outcome lines, timing and
the model status carried by identity, never by number, and what is not carried named once
(FR-021, FR-023, FR-029, FR-032; SC-005, SC-008; owner decisions 71A, 72A and 78A). Every
package, path and seat here is fictional.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import yaml
from starlette.testclient import TestClient

from swreview import atomic, tokens
from swreview.agent import runner
from swreview.agent.providers import ProviderName
from swreview.agent.providers.deferred import DeferredProvider
from swreview.agent.runner import request_prefix
from swreview.agent.settings import ProviderSettings, pane_defaults
from swreview.chat import server
from swreview.chat.sessions import ChatState
from swreview.checks.drawing_context import CANDIDATE_CONFIRM, CANDIDATE_OPTIONS
from swreview.findings import Disposition, Finding, finding_subject_key
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package, save_package
from swreview.ir.models import EvidencePackage
from swreview.prerun import (
    CARRIED_LIVE_NOTE,
    INTERFERENCE_ROWS_NOT_CARRIED,
    INTERFERENCE_TOOL,
    LIVE_INTERFERENCE_TOOL,
    PRERUN_INTERFERENCE_SETTINGS,
)
from swreview.report.names import plural
from swreview.report.session import (
    DrawingOutcome,
    EvidenceRequest,
    ReviewSession,
    SendFailure,
    load_session,
    save_session,
)
from tests.support.prerun import LIVE_ROWS, live_prerun_package, prerun_package
from tests.support.questions_package import build_questions_package
from tests.support.recording_provider import RecordedRequest, RecordingProvider
from tests.support.restart import BEFORE_REPLACE, disk_at, restarted_app
from tests.support.restored import assert_restored_as_waiting
from tests.support.review_bridge import VOLUME_UNIT_GAP, ScriptedReviewBridge
from tests.support.roles_review import PLATE_ID
from tests.unit import test_chat_server as chat
from tests.unit import test_confirmed_drawing_read as confirmed
from tests.unit import test_waiting_answers as waiting_answers
from tests.unit.test_prerun_digest import template_finding

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir

INTERFERENCE_CHECKS = frozenset({
    "interference",
    "coverage.prerun.interference",
    "coverage.prerun.interference_rows",
    f"tool.{LIVE_INTERFERENCE_TOOL}",
})


# --- the runner-level first run and re-run ------------------------------------------------


def checks_only(
    folder: Path,
    bridge: Any | None,
    *,
    earlier: ReviewSession | None = None,
    standards_profile: Path | None = None,
) -> runner.ReviewRun:
    """An unticked start in `folder`, as the pane makes one, with or without a seat."""
    provider = DeferredProvider.for_settings(
        ProviderSettings(provider=ProviderName.FAKE, model="fake-1")
    )
    defaults = pane_defaults(provider.name)
    seat: dict[str, Any] = {}
    if bridge is not None:
        seat = {"bridge": True, "bridge_factory": lambda pipe, secret: bridge}
    return runner.start_review(
        folder,
        folder,
        provider=provider,
        efficiency=defaults.efficiency,
        model_view=defaults.model_view,
        standards_profile=standards_profile,
        send_when_checked=False,
        earlier=earlier,
        **seat,
    )


def waited(run: runner.ReviewRun) -> ReviewSession:
    """Finalize the waiting run as `_open_waiting` does and read its record back."""
    try:
        run.close_waiting()
    finally:
        run.close()
    return load_session(run.session_path)


def set_aside(folder: Path) -> None:
    """What the re-run's rotation leaves: the earlier stream and results moved to index 1."""
    (folder / "events.jsonl").rename(folder / "events.1.jsonl")
    results = folder / "tool-results"
    if results.is_dir():
        results.rename(folder / "tool-results.1")
    shutil.copyfile(folder / "session.json", folder / "session.1.json")


def silent_seat() -> ScriptedReviewBridge:
    """A seat with no answers: any call it receives fails the test loudly."""
    return ScriptedReviewBridge()


def live_answer(rows: tuple[dict[str, Any], ...] = LIVE_ROWS) -> dict[str, Any]:
    return {"interferences": [dict(row) for row in rows], "gaps": [dict(VOLUME_UNIT_GAP)]}


def package_folder(tmp_path: Path, package: EvidencePackage) -> Path:
    folder = tmp_path / "run"
    save_package(package, folder)
    return folder


def interference_rows(session: ReviewSession) -> dict[str, list[dict[str, Any]]]:
    coverage = session.coverage.model_dump(mode="json")
    return {
        bucket: [item for item in items if item["check"] in INTERFERENCE_CHECKS]
        for bucket, items in coverage.items()
    }


def step_rows(session: ReviewSession) -> list[tuple[int, str, Any, str]]:
    return [
        (step.index, step.tool, step.arguments, step.status) for step in session.steps
    ]


def finding_rows(session: ReviewSession) -> list[tuple[str, str, list[int]]]:
    return [
        (finding.id, finding.check, list(finding.tool_result_ids)) for finding in session.findings
    ]


def first_and_rerun(
    folder: Path, first_seat: Any | None, rerun_seat: Any | None
) -> tuple[runner.ReviewRun, ReviewSession, runner.ReviewRun, dict[str, Any]]:
    """The first unticked run, finalized; then its re-run, prepared and not finalized.

    The last item is the first run's interference coverage as its pre-run left it, before
    the finalization added its not-sent rows: what the re-run's pre-run is compared with.
    """
    first = checks_only(folder, first_seat)
    rows = interference_rows(first.session)
    earlier = waited(first)
    set_aside(folder)
    rerun = checks_only(folder, rerun_seat, earlier=earlier)
    return first, earlier, rerun, rows


# --- no new bridge call, one carried step ---------------------------------------------------


@pytest.fixture
def carried(tmp_path: Path) -> Any:
    folder = package_folder(tmp_path, live_prerun_package())
    seat = silent_seat()
    first, earlier, rerun, _ = first_and_rerun(
        folder, ScriptedReviewBridge(results={"interference": [live_answer()]}), seat
    )
    yield folder, seat, first, earlier, rerun
    rerun.close()


def test_a_re_run_asks_solidworks_nothing_before_its_first_request(carried: Any) -> None:
    _, seat, _, earlier, rerun = carried

    assert seat.calls == []
    assert earlier.live_detection is not None and earlier.live_detection.step_index == 0
    assert rerun.session.live_detection == earlier.live_detection


def test_the_carried_step_is_recorded_where_the_first_run_recorded_its_call(
    carried: Any,
) -> None:
    folder, _, _, earlier, rerun = carried
    live = earlier.live_detection
    assert live is not None and live.step_index is not None
    step = rerun.session.steps[live.step_index]

    assert step.tool == LIVE_INTERFERENCE_TOOL
    assert step.arguments == {
        "component_ids": [],
        "configuration": live.configuration,
        "settings": PRERUN_INTERFERENCE_SETTINGS,
    }
    assert step.status == "ok"
    assert step.origin_mark == "prerun"
    stored = json.loads(
        (folder / "tool-results" / f"step-{live.step_index}.json").read_text(encoding="utf-8")
    )
    assert stored["payload"] == {
        "status": "carried",
        "note": CARRIED_LIVE_NOTE,
        "outcome": live.model_dump(mode="json"),
    }
    started = [
        json.loads(line)
        for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    tool_events = [
        event["body"] for event in started if event["type"] in {"tool.started", "tool.finished"}
    ]
    assert tool_events[0]["step_index"] == live.step_index
    assert tool_events[0]["tool"] == LIVE_INTERFERENCE_TOOL


def test_every_later_step_and_finding_citation_is_the_first_runs(carried: Any) -> None:
    _, _, _, earlier, rerun = carried

    assert step_rows(rerun.session) == step_rows(earlier)
    assert finding_rows(rerun.session) == finding_rows(earlier)
    assert [s.tool for s in rerun.session.steps].count(INTERFERENCE_TOOL) == 2


def test_a_repeated_live_call_is_answered_naming_the_carried_step(carried: Any) -> None:
    _, seat, _, earlier, rerun = carried
    live = earlier.live_detection
    assert live is not None

    answer = rerun.tools.call(
        LIVE_INTERFERENCE_TOOL,
        {
            "component_ids": [],
            "configuration": live.configuration,
            "settings": dict(PRERUN_INTERFERENCE_SETTINGS),
        },
        "call-FICT-1",
    )

    assert answer.payload["status"] == "already_run"
    assert answer.payload["ran_at_step"] == live.step_index
    assert seat.calls == []


# --- every outcome carried ------------------------------------------------------------------


def _collided_package() -> EvidencePackage:
    other = prerun_package().interferences[0].model_copy(
        update={"id": "int:0002", "configuration": "Other"}
    )
    return live_prerun_package().model_copy(update={"interferences": [other]})


def _part_root_package() -> EvidencePackage:
    package = live_prerun_package()
    root = package.design.root_assembly_document_id
    return package.model_copy(
        update={
            "documents": [
                d.model_copy(update={"kind": "part"}) if d.document_id == root else d
                for d in package.documents
            ]
        }
    )


OUTCOMES: dict[str, tuple[Any, Any]] = {
    "clean": (live_prerun_package, lambda: {"interference": [live_answer(rows=())]}),
    "rows": (live_prerun_package, lambda: {"interference": [live_answer()]}),
    "collided": (_collided_package, lambda: {"interference": [live_answer()]}),
    "failed": (prerun_package, lambda: {"interference": [_bridge_error()]}),
    "no-bridge": (prerun_package, None),
    "not-an-assembly": (_part_root_package, lambda: {}),
}


def _bridge_error() -> Exception:
    from swreview.bridge.client import BridgeError

    return BridgeError("FICT the host lost the document")


@pytest.mark.parametrize("case", sorted(OUTCOMES))
def test_every_live_outcome_is_carried_as_the_first_run_had_it(
    tmp_path: Path, case: str
) -> None:
    make_package, script = OUTCOMES[case]
    folder = package_folder(tmp_path, make_package())
    first_seat = ScriptedReviewBridge(results=script()) if script is not None else None
    rerun_seat = silent_seat() if script is not None else None

    first, earlier, rerun, first_rows = first_and_rerun(folder, first_seat, rerun_seat)
    try:
        assert rerun.opening_message == first.opening_message
        assert interference_rows(rerun.session) == first_rows
        assert rerun._prerun is not None and first._prerun is not None
        assert rerun._prerun.withheld == first._prerun.withheld
        assert step_rows(rerun.session) == step_rows(earlier)
        assert finding_rows(rerun.session) == finding_rows(earlier)
        if rerun_seat is not None:
            assert rerun_seat.calls == []
        live = earlier.live_detection
        assert live is not None
        if case in {"no-bridge", "not-an-assembly"}:
            assert live.step_index is None
            assert LIVE_INTERFERENCE_TOOL not in [s.tool for s in rerun.session.steps]
        if case == "failed":
            assert live.error is not None
            [failed] = [
                item for item in rerun.session.coverage.failed
                if item.check == f"tool.{LIVE_INTERFERENCE_TOOL}"
            ]
            assert failed.error == live.error
            assert rerun.session.steps[live.step_index].status == "error"
            assert [
                s.arguments["group_key"]
                for s in rerun.session.steps if s.tool == INTERFERENCE_TOOL
            ] == [prerun_package().interferences[0].group_key]
    finally:
        rerun.close()


# --- rows the first run could not write -----------------------------------------------------


def test_rows_the_first_run_could_not_write_are_not_judged_from_the_stale_dump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = package_folder(tmp_path, prerun_package())
    stale = {row.id for row in prerun_package().interferences}
    real_replace = atomic.os.replace

    def refuse(source: Any, target: Any) -> None:
        if Path(target).name == PACKAGE_FILE_NAME:
            raise PermissionError("FICT package.json is locked")
        real_replace(source, target)

    monkeypatch.setattr(atomic.os, "replace", refuse)
    first = checks_only(folder, ScriptedReviewBridge(results={"interference": [live_answer()]}))
    earlier = waited(first)
    monkeypatch.setattr(atomic.os, "replace", real_replace)
    assert earlier.live_detection is not None
    assert earlier.live_detection.persist_error is not None
    assert {row.id for row in load_package(folder).package.interferences} == stale
    set_aside(folder)

    rerun = checks_only(folder, silent_seat(), earlier=earlier)
    try:
        assert not [s for s in rerun.session.steps if s.tool == INTERFERENCE_TOOL]
        assert not [f for f in rerun.session.findings if f.check == "interference.static"]
        assert not rerun.context.ir.interferences
        [row] = [
            item for item in rerun.session.coverage.unresolved
            if item.check == "coverage.prerun.interference_rows"
        ]
        assert row.reason == INTERFERENCE_ROWS_NOT_CARRIED.format(
            rows=plural(earlier.live_detection.rows_added, "row")
        )
        assert f"  interference: {row.reason}" in rerun.opening_message.splitlines()
        assert "could not be written" not in rerun.opening_message
    finally:
        rerun.close()


# --- the drawing-read capability ------------------------------------------------------------


def test_the_drawing_read_capability_is_carried_onto_the_re_runs_record(
    tmp_path: Path,
) -> None:
    fixture = build_questions_package(tmp_path / "run")
    first = checks_only(fixture.folder, fixture.bridge, standards_profile=fixture.profile)
    earlier = waited(first)
    assert earlier.drawing_read == "opens_closed"
    assert ("ping", {}) in fixture.bridge.calls
    set_aside(fixture.folder)

    seat = silent_seat()
    rerun = checks_only(fixture.folder, seat, earlier=earlier, standards_profile=fixture.profile)
    assert seat.calls == []
    assert rerun.session.drawing_read == "opens_closed"
    assert rerun.context.drawing_read_mode() == "opens_closed"
    assert seat.calls == []
    assert [q.question for q in rerun.session.evidence_requests] == [
        q.question for q in earlier.evidence_requests
    ]
    second_earlier = waited(rerun)
    assert second_earlier.drawing_read == "opens_closed"
    for name in ("events.1.jsonl", "session.1.json"):
        (fixture.folder / name).rename(fixture.folder / name.replace(".1.", ".2."))
    shutil.rmtree(fixture.folder / "tool-results.1")
    set_aside(fixture.folder)

    again = silent_seat()
    second = checks_only(
        fixture.folder, again, earlier=second_earlier, standards_profile=fixture.profile
    )
    try:
        assert again.calls == []
        assert second.session.drawing_read == "opens_closed"
    finally:
        second.close()


def test_a_carried_step_that_would_land_off_the_first_runs_index_is_refused(
    tmp_path: Path,
) -> None:
    """Owner decision 87A: every later step and citation is the first run's only if the carried
    step lands where the first run recorded its call, so a re-run whose pre-run holds any other
    number of steps by then is refused before the carried step is recorded or the seat asked.
    By then `session.started` and the pre-run's coverage and provenance events are written."""
    folder = package_folder(tmp_path, live_prerun_package())
    first = checks_only(folder, ScriptedReviewBridge(results={"interference": [live_answer()]}))
    earlier = waited(first)
    set_aside(folder)
    live = earlier.live_detection
    assert live is not None and live.step_index is not None
    moved = earlier.model_copy(
        update={"live_detection": live.model_copy(update={"step_index": live.step_index + 1})}
    )
    seat = silent_seat()

    with pytest.raises(RuntimeError) as refused:
        checks_only(folder, seat, earlier=moved)

    assert str(refused.value) == (
        f"the carried live step would be step {live.step_index}, but the first run recorded "
        f"its call as step {live.step_index + 1}"
    )
    assert seat.calls == []


# --- the claim and the rotation (T094; `contracts/recheck.md` sections 2, 6 and 7) ----------


def server_settings(
    provider_control: chat.ProviderControl, models: chat.Models, seat: Any
) -> dict[str, Any]:
    """A restarted backend's settings: the first app's, with a seat that answers nothing."""
    return {
        "token": chat.TOKEN,
        "allow_origin": chat.ORIGIN,
        "provider_factory": provider_control.factory,
        "list_models": models,
        "bridge_factory": lambda pipe, secret: seat,
    }


def recheck_body(folder: Path, **overrides: Any) -> dict[str, Any]:
    """What the host posts for `review.recheck`: the record's own folder, unticked."""
    body: dict[str, Any] = {
        "standards_profile": str(folder / "profile-v3.yaml"),
        "bridge": {"pipe": "FICT-pipe", "secret": "FICT-secret"},
        "send_when_checked": False,
        "recheck": True,
        **overrides,
    }
    return chat.session_body(folder, **body)


def recheck(client: TestClient, folder: Path, **overrides: Any) -> Any:
    return client.post("/sessions", json=recheck_body(folder, **overrides))


@dataclass(frozen=True)
class Earlier:
    """A waiting review the first app left on disk: its folder and the bytes it wrote."""

    folder: Path
    files: dict[str, bytes]
    record: ReviewSession

    @property
    def session_id(self) -> str:
        return str(self.record.session_id)


CANONICAL = ("session.json", "attention.json", "report.md", "events.jsonl")


def earlier_review(app: Any, client: TestClient, folder: Path) -> Earlier:
    """An unticked review through the first app, as a restart finds it on disk."""
    waiting_answers.waiting_review(app, client, folder)
    return Earlier(
        folder,
        {name: (folder / name).read_bytes() for name in CANONICAL},
        load_session(folder / "session.json"),
    )


def stream_owner(path: Path) -> str | None:
    """The `session_id` the first `session.started` of a stream names."""
    first = path.read_text(encoding="utf-8").splitlines()[0]
    event = json.loads(first)
    assert event["type"] == "session.started"
    return str(event["body"]["session_id"])


def indexes(folder: Path) -> dict[int, set[str]]:
    """Which rotated files each index holds: `session`, `attention`, `events`, `results`."""
    held: dict[int, set[str]] = {}
    patterns = {
        "session": "session.*.json",
        "attention": "attention.*.json",
        "events": "events.*.jsonl",
        "results": "tool-results.*",
    }
    for kind, pattern in patterns.items():
        for path in folder.glob(pattern):
            index = path.name.split(".")[1]
            if index.isdigit():
                held.setdefault(int(index), set()).add(kind)
    return held


@pytest.fixture
def silent() -> ScriptedReviewBridge:
    return silent_seat()


def test_a_re_run_copies_the_record_moves_its_stream_and_waits_again(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    earlier = earlier_review(app, client, run_root / "FICT-recheck")
    earlier_results = sorted(p.name for p in (earlier.folder / "tool-results").iterdir())
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        owner = fresh.app.state.server
        registered: list[bool] = []
        close_waiting = runner.ReviewRun.close_waiting

        def finalized(run: runner.ReviewRun) -> ReviewSession:
            registered.append(bool(owner.chats))
            return close_waiting(run)

        monkeypatch.setattr(runner.ReviewRun, "close_waiting", finalized)
        response = recheck(fresh, earlier.folder)

        assert response.status_code == 201, response.text
        body = response.json()
        assert set(body) == {"chat_id", "review_session_id", "not_examined"}
        assert registered == [False]
        assert chat.state_of(fresh, body["chat_id"]) == "awaiting_send"
        folder = earlier.folder
        assert (folder / "session.1.json").read_bytes() == earlier.files["session.json"]
        assert (folder / "attention.1.json").read_bytes() == earlier.files["attention.json"]
        assert (folder / "events.1.jsonl").read_bytes() == earlier.files["events.jsonl"]
        assert sorted(p.name for p in (folder / "tool-results.1").iterdir()) == earlier_results
        assert indexes(folder) == {1: {"session", "attention", "events", "results"}}
        rerun = load_session(folder / "session.json")
        assert str(rerun.session_id) == body["review_session_id"] != earlier.session_id
        assert rerun.model_status is not None and rerun.model_status.state == "not_sent"
        assert stream_owner(folder / "events.jsonl") == body["review_session_id"]
        assert provider_control.built == []
        assert silent.calls == []


def test_recheck_needs_an_unticked_start(
    app: Any, client: TestClient, run_root: Path, provider_control: chat.ProviderControl,
) -> None:
    earlier = earlier_review(app, client, run_root / "FICT-recheck-ticked")

    response = recheck(client, earlier.folder, send_when_checked=True)

    assert response.status_code == 400, response.text
    assert response.json()["error_class"] == "InvalidRequest"
    assert provider_control.built == []


@pytest.mark.parametrize("case", ["no-record", "unreadable", "deleted"])
def test_a_folder_with_no_readable_record_is_an_unknown_review(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    case: str,
) -> None:
    earlier = earlier_review(app, client, run_root / f"FICT-recheck-{case}")
    if case == "no-record":
        (earlier.folder / "session.json").unlink()
    elif case == "unreadable":
        (earlier.folder / "session.json").write_text("{FICT", encoding="utf-8")
    else:
        shutil.rmtree(earlier.folder)
    before = sorted(str(path) for path in run_root.rglob("*"))
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        response = recheck(fresh, earlier.folder)

        assert response.status_code == 404, response.text
        assert response.json()["error_class"] == "UnknownReview"
        assert sorted(str(path) for path in run_root.rglob("*")) == before
        # 87A: the refusal released the folder it claimed, so the same backend re-runs it once
        # its record is readable again.
        assert fresh.app.state.server._pending_run_dirs == set()
        if case != "deleted":
            (earlier.folder / "session.json").write_bytes(earlier.files["session.json"])
        again = recheck(fresh, earlier.folder)
        assert again.status_code == (404 if case == "deleted" else 201), again.text
    assert provider_control.built == []


def test_the_earlier_record_is_read_off_the_event_loop(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner decision 90A: the claim's read of the waiting record is a blocking read, so it runs
    on the thread pool as the route's other blocking reads do."""
    earlier = earlier_review(app, client, run_root / "FICT-recheck-off-loop")
    on_loop: list[bool] = []
    loading = server.load_session

    def watched(path: Path, *args: Any, **kwargs: Any) -> ReviewSession:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            on_loop.append(False)
        else:
            on_loop.append(True)
        return loading(path, *args, **kwargs)

    monkeypatch.setattr(server, "load_session", watched)
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        assert recheck(fresh, earlier.folder).status_code == 201

    assert on_loop and not any(on_loop)


def test_a_second_re_run_while_the_first_reads_its_record_is_run_dir_in_use(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record's read awaits the thread pool (owner decision 90A), so the folder is held from
    the claim on: a second re-run sent meanwhile meets `RunDirInUse`, as one sent while the first
    is being set up does, and reads nothing."""
    earlier = earlier_review(app, client, run_root / "FICT-recheck-read-held")
    entered, release = threading.Event(), threading.Event()
    reads: list[Path] = []
    reading = server.ChatServer._waiting_record

    def held(run_dir: Path) -> ReviewSession:
        reads.append(run_dir)
        if len(reads) == 1:
            entered.set()
            assert release.wait(chat.TIMEOUT_S), "FICT record barrier was never released"
        return reading(run_dir)

    monkeypatch.setattr(server.ChatServer, "_waiting_record", staticmethod(held))
    with (
        restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh,
        ThreadPoolExecutor(max_workers=1) as worker,
    ):
        first = worker.submit(recheck, fresh, earlier.folder)
        try:
            assert entered.wait(chat.TIMEOUT_S)
            second = recheck(fresh, earlier.folder)
            assert second.status_code == 409, second.text
            assert second.json()["error_class"] == "RunDirInUse"
            assert reads == [earlier.folder.resolve()]
        finally:
            release.set()
            answered = first.result(timeout=chat.TIMEOUT_S)
        assert answered.status_code == 201, answered.text
        assert fresh.app.state.server._pending_run_dirs == set()
    assert indexes(earlier.folder) == {1: {"session", "attention", "events", "results"}}


@pytest.mark.parametrize("state", ["none", "sent"])
def test_a_record_that_is_not_waiting_is_refused(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    state: str,
) -> None:
    earlier = earlier_review(app, client, run_root / f"FICT-recheck-{state}")
    record = earlier.record
    if state == "none":
        record.model_status = None
    else:
        assert record.model_status is not None
        record.model_status.state = "sent"
    save_session(record, earlier.folder / "session.json")
    saved = (earlier.folder / "session.json").read_bytes()
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        response = recheck(fresh, earlier.folder)

        assert response.status_code == 409, response.text
        assert response.json()["error_class"] == "NotWaiting"
        assert (earlier.folder / "session.json").read_bytes() == saved
        assert not (earlier.folder / "session.1.json").exists()
        # 87A: the refusal released the folder it claimed, so the same backend re-runs it once
        # its record waits again.
        assert fresh.app.state.server._pending_run_dirs == set()
        (earlier.folder / "session.json").write_bytes(earlier.files["session.json"])
        again = recheck(fresh, earlier.folder)
        assert again.status_code == 201, again.text
    assert provider_control.built == []


def test_a_running_chat_on_the_folder_is_run_dir_in_use(
    app: Any,
    client: TestClient,
    run_dir: Path,
    provider_control: chat.ProviderControl,
) -> None:
    provider_control.hold()
    started = chat.start_session(client, run_dir)
    assert provider_control.started.wait(chat.TIMEOUT_S)
    try:
        response = client.post(
            "/sessions",
            json=chat.session_body(run_dir, send_when_checked=False, recheck=True),
        )
        assert response.status_code == 409, response.text
        assert response.json()["error_class"] == "RunDirInUse"
    finally:
        provider_control.release()
        chat.settle(client, started["chat_id"])


def test_a_re_run_held_in_the_backend_refuses_a_second_and_is_adopted_after(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same app throughout the re-runs: what a host that gave up and asked again meets."""
    earlier = earlier_review(app, client, run_root / "FICT-recheck-adopt")
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        owner = fresh.app.state.server
        entered, release = threading.Event(), threading.Event()
        starts: list[Path] = []
        starting = owner._start_review

        def held(chat_session: Any, *args: Any, **kwargs: Any) -> runner.ReviewRun:
            starts.append(chat_session.run_dir)
            entered.set()
            assert release.wait(chat.TIMEOUT_S), "FICT re-run barrier was never released"
            return starting(chat_session, *args, **kwargs)

        monkeypatch.setattr(owner, "_start_review", held)
        with ThreadPoolExecutor(max_workers=1) as worker:
            first = worker.submit(recheck, fresh, earlier.folder)
            try:
                assert entered.wait(chat.TIMEOUT_S)
                second = recheck(fresh, earlier.folder)
                assert second.status_code == 409, second.text
                assert second.json()["error_class"] == "RunDirInUse"
                assert starts == [earlier.folder.resolve()]
            finally:
                release.set()
                answered = first.result(timeout=chat.TIMEOUT_S)
        assert answered.status_code == 201, answered.text
        events_before = (earlier.folder / "events.jsonl").read_bytes()
        session_before = (earlier.folder / "session.json").read_bytes()

        adopted = recheck(fresh, earlier.folder)

        assert adopted.status_code == 201, adopted.text
        assert adopted.json() == answered.json()
        assert starts == [earlier.folder.resolve()]
        assert len(owner.chats) == 1
        assert (earlier.folder / "events.jsonl").read_bytes() == events_before
        assert (earlier.folder / "session.json").read_bytes() == session_before
        assert indexes(earlier.folder) == {1: {"session", "attention", "events", "results"}}
    assert provider_control.built == []


# --- failure and cut-off ---------------------------------------------------------------------


def assert_earlier_restorable(
    root: Path,
    folder: Path,
    earlier: Earlier,
    settings: dict[str, Any],
    provider_control: chat.ProviderControl,
) -> dict[int, set[str]]:
    """The folder holds the earlier record whole, a fresh app restores it, and re-runs it.

    The restore is the earlier record's, read-only with its dated line and Send (T099).
    Returns the indexes the successful re-run left.
    """
    assert (folder / "session.json").read_bytes() == earlier.files["session.json"]
    with restarted_app(root, settings) as fresh:
        restored = fresh.get(f"/reviews/{folder.name}")
        assert restored.status_code == 200, restored.text
        assert_restored_as_waiting(restored.json(), earlier.record)
        again = recheck(fresh, folder)
        assert again.status_code == 201, again.text
        assert chat.state_of(fresh, again.json()["chat_id"]) == "awaiting_send"
    assert provider_control.built == []
    assert (folder / "session.1.json").read_bytes() == earlier.files["session.json"]
    assert list(folder.glob("session.*.json")) == [folder / "session.1.json"]
    return indexes(folder)


def test_a_re_run_that_fails_leaves_the_earlier_record_and_the_next_one_succeeds(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
) -> None:
    earlier = earlier_review(app, client, run_root / "FICT-recheck-fails")
    package = earlier.folder / "package.json"
    good = package.read_bytes()
    package.write_text("{FICT", encoding="utf-8")
    settings = server_settings(provider_control, models, silent)
    with restarted_app(run_root, settings) as fresh:
        failed = recheck(fresh, earlier.folder)
        assert failed.status_code == 400, failed.text
        assert failed.json()["error_class"] == "InvalidPackage"
        assert fresh.app.state.server.chats == {}
    assert (earlier.folder / "session.json").read_bytes() == earlier.files["session.json"]
    package.write_bytes(good)

    held = assert_earlier_restorable(
        run_root, earlier.folder, earlier, settings, provider_control
    )

    assert held == {1: {"session", "attention", "events", "results"}}


def test_a_carry_that_raises_fails_the_re_run_and_the_next_one_succeeds(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner decision 87A: the carry runs inside `_open_waiting`'s one failure path, so a carry
    that raises closes its run once, leaves the chat `failed` and unregistered and the earlier
    record byte-equal, answers the pane's bare 500, and the next re-run succeeds."""
    earlier = earlier_review(app, client, run_root / "FICT-recheck-carry-fails")
    settings = server_settings(provider_control, models, silent)
    attempts: list[Any] = []
    closed: list[runner.ReviewRun] = []
    closing = runner.ReviewRun.close

    def refused(run: runner.ReviewRun, record: ReviewSession) -> None:
        raise RuntimeError("FICT the carry cannot be made")

    def counted(run: runner.ReviewRun) -> None:
        closed.append(run)
        closing(run)

    monkeypatch.setattr(runner.ReviewRun, "carry_from", refused)
    monkeypatch.setattr(runner.ReviewRun, "close", counted)
    with restarted_app(run_root, settings, raise_server_exceptions=False) as fresh:
        owner = fresh.app.state.server
        starting = owner._start_review

        def captured(chat_session: Any, *args: Any, **kwargs: Any) -> runner.ReviewRun:
            attempts.append(chat_session)
            return starting(chat_session, *args, **kwargs)

        monkeypatch.setattr(owner, "_start_review", captured)
        failed = recheck(fresh, earlier.folder)

        assert failed.status_code == 500
        assert failed.text == "Internal Server Error"
        assert owner.chats == {}
        assert owner._pending_run_dirs == set()
        (attempt,) = attempts
        assert attempt.state is ChatState.FAILED
        assert attempt.run is None
        assert len(closed) == 1
    assert (earlier.folder / "session.json").read_bytes() == earlier.files["session.json"]
    monkeypatch.undo()

    held = assert_earlier_restorable(
        run_root, earlier.folder, earlier, settings, provider_control
    )

    assert held == {
        1: {"session", "attention", "events", "results"},
        2: {"events", "results"},
    }


def _cut_after_rotation(owner_class: Any, monkeypatch: pytest.MonkeyPatch, captured: Any) -> None:
    rotate = owner_class._rotate_previous

    def rotated(self: Any, *args: Any, **kwargs: Any) -> None:
        rotate(self, *args, **kwargs)
        captured()

    monkeypatch.setattr(owner_class, "_rotate_previous", rotated)


def _cut_before_finalization(
    owner_class: Any, monkeypatch: pytest.MonkeyPatch, captured: Any
) -> None:
    close_waiting = runner.ReviewRun.close_waiting

    def finalized(run: runner.ReviewRun) -> ReviewSession:
        captured()
        return close_waiting(run)

    monkeypatch.setattr(runner.ReviewRun, "close_waiting", finalized)


CUTS = {
    "after-rotation": _cut_after_rotation,
    "before-finalization": _cut_before_finalization,
    BEFORE_REPLACE: None,
}
EXPECTED_AFTER_CUT = {
    "after-rotation": {1: {"session", "attention", "events", "results"}},
    "before-finalization": {
        1: {"session", "attention", "events", "results"},
        2: {"events", "results"},
    },
    BEFORE_REPLACE: {
        1: {"session", "attention", "events", "results"},
        2: {"events", "results"},
    },
}


@pytest.mark.parametrize("point", sorted(CUTS))
def test_a_re_run_cut_off_leaves_the_earlier_record_whole(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    earlier = earlier_review(app, client, run_root / "FICT-recheck-cut")
    settings = server_settings(provider_control, models, silent)
    with disk_at(earlier.folder, point) as captured:
        place = CUTS[point]
        if place is not None:
            place(server.ChatServer, monkeypatch, captured)
        with restarted_app(run_root, settings) as fresh:
            assert recheck(fresh, earlier.folder).status_code == 201
        monkeypatch.undo()
        cut = captured.folder
        assert cut.is_dir()
        temporaries = list(cut.glob(".session.json.*.tmp"))
        assert len(temporaries) == (1 if point == BEFORE_REPLACE else 0)
        assert load_session(cut / "session.json") == earlier.record

        held = assert_earlier_restorable(
            captured.root, cut, earlier, settings, provider_control
        )

        assert held == EXPECTED_AFTER_CUT[point]
        assert list(cut.glob(".session.json.*.tmp")) == temporaries
        stray = cut / "events.2.jsonl"
        if stray.exists():
            assert stream_owner(stray) != earlier.session_id
            assert not (cut / "session.2.json").exists()


# --- the indexes -----------------------------------------------------------------------------


def test_two_failed_re_runs_then_one_that_succeeds_keep_each_index_one_stream(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    earlier = earlier_review(app, client, run_root / "FICT-recheck-indexes")
    settings = server_settings(provider_control, models, silent)
    close_waiting = runner.ReviewRun.close_waiting

    def cannot_finalize(run: runner.ReviewRun) -> ReviewSession:
        raise OSError("FICT the run folder cannot be written")

    monkeypatch.setattr(runner.ReviewRun, "close_waiting", cannot_finalize)
    for _ in range(2):
        with restarted_app(run_root, settings) as fresh, pytest.raises(OSError):
            recheck(fresh, earlier.folder)
        assert (earlier.folder / "session.json").read_bytes() == earlier.files["session.json"]
    monkeypatch.setattr(runner.ReviewRun, "close_waiting", close_waiting)
    with restarted_app(run_root, settings) as fresh:
        succeeded = recheck(fresh, earlier.folder)
        assert succeeded.status_code == 201, succeeded.text

    folder = earlier.folder
    assert indexes(folder) == {
        1: {"session", "attention", "events", "results"},
        2: {"events", "results"},
        3: {"events", "results"},
    }
    assert stream_owner(folder / "events.1.jsonl") == earlier.session_id
    owners = {stream_owner(folder / f"events.{n}.jsonl") for n in (2, 3)}
    assert len(owners) == 2 and earlier.session_id not in owners
    assert stream_owner(folder / "events.jsonl") == succeeded.json()["review_session_id"]
    assert provider_control.built == []


# --- nothing written early -------------------------------------------------------------------


def test_nothing_is_written_to_the_record_before_the_finalization(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    earlier = earlier_review(app, client, run_root / "FICT-recheck-early")
    seen: list[dict[str, bytes]] = []
    close_waiting = runner.ReviewRun.close_waiting

    def finalized(run: runner.ReviewRun) -> ReviewSession:
        seen.append({
            name: (earlier.folder / name).read_bytes()
            for name in ("session.json", "report.md", "attention.json")
        })
        return close_waiting(run)

    monkeypatch.setattr(runner.ReviewRun, "close_waiting", finalized)
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        assert recheck(fresh, earlier.folder).status_code == 201

    assert seen == [{
        name: earlier.files[name] for name in ("session.json", "report.md", "attention.json")
    }]


# --- the carry (T096; `contracts/recheck.md` sections 4 and 5) -------------------------------


DRIFTED_STANDARD = "FICT-DRIFTED-STANDARD"
"""The merged drawing's drafting standard, which the fixture's profile does not accept. The
first run raises its conformance finding after every other check's, when the read reloads the
package; the re-run raises it in the drawing check's own place, so every finding after it moves
up one number (the spec's edge case "Numbers that move across a re-run")."""

REJECTED_CHECK = "standards.document.data_card_complete"
"""The check of the finding the worked review Rejects: one the conformance finding overtakes, so
the re-run gives its earlier number to another finding (owner decision 87A)."""


def merging_seat(bridge: Any, folder: Path) -> None:
    """Make the fixture's seat merge the plate's drawing on its confirmed read, as the host
    does (`test_confirmed_drawing_read.merged`), so the read moves what the package holds."""
    read = confirmed.merged(folder, PLATE_ID, drafting_standard=DRIFTED_STANDARD)
    bridge._results["drawing_read"] = deque([lambda arguments: read()])


def worked_review(
    app: Any, client: TestClient, folder: Path, *, reject: bool = True
) -> waiting_answers.Waiting:
    """The US4 independent test's earlier record: a part-roles answer, a drawing answer whose
    read merged its drawing and moved the finding numbers, and a Reject of a finding whose
    number moves, all made while the review waited."""
    fixture = build_questions_package(folder)
    merging_seat(fixture.bridge, folder)
    app.state.server.bridge_factory = lambda pipe, secret: fixture.bridge
    response = client.post(
        "/sessions",
        json=chat.session_body(
            folder,
            standards_profile=str(fixture.profile),
            bridge={"pipe": "FICT-pipe", "secret": "FICT-secret"},
            send_when_checked=False,
        ),
    )
    assert response.status_code == 201, response.text
    chat_id = str(response.json()["chat_id"])
    waiting = waiting_answers.Waiting(fixture, chat_id, app.state.server.chats[UUID(chat_id)])
    role = waiting_answers.question(waiting)
    drawing = waiting_answers.question(waiting, drawing=True)
    applied = waiting_answers.apply(
        client, waiting, (role.id, "All bought"), (drawing.id, CANDIDATE_CONFIRM)
    )
    assert applied.status_code == 202, applied.text
    assert chat.settle(client, chat_id) == "awaiting_send"
    assert waiting.run.session.drawing_outcomes
    if reject:
        finding = next(f for f in waiting.run.session.findings if f.check == REJECTED_CHECK)
        decided = client.post(
            f"/sessions/{chat_id}/findings/{finding.id}/disposition",
            json={"decision": "rejected", "note": "FICT engineer decision"},
        )
        assert decided.status_code == 200, decided.text
    return waiting


def rerun_of(fresh: TestClient, folder: Path, **overrides: Any) -> runner.ReviewRun:
    response = recheck(fresh, folder, **overrides)
    assert response.status_code == 201, response.text
    held = fresh.app.state.server.chats[UUID(response.json()["chat_id"])]
    return held.run


def decided(session: ReviewSession) -> dict[Any, Any]:
    return {
        finding_subject_key(finding): finding.disposition
        for finding in session.findings
        if finding.disposition is not None
    }


def recheck_row(session: ReviewSession) -> list[str]:
    return [item.reason for item in session.coverage.unresolved if item.check == "coverage.recheck"]


def test_the_independent_test_carries_every_answer_decision_and_outcome_by_identity(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = worked_review(app, client, run_root / "FICT-recheck-worked")
    folder = waiting.fixture.folder
    earlier = load_session(folder / "session.json")
    package = (folder / "package.json").read_bytes()
    on_disk = {name: (folder / name).read_bytes() for name in ("session.json", "report.md")}
    seen: list[dict[str, bytes]] = []
    close_waiting = runner.ReviewRun.close_waiting

    def finalized(run: runner.ReviewRun) -> ReviewSession:
        seen.append({name: (folder / name).read_bytes() for name in on_disk})
        return close_waiting(run)

    monkeypatch.setattr(runner.ReviewRun, "close_waiting", finalized)
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        rerun = rerun_of(fresh, folder)

    session = rerun.session
    assert silent.calls == []
    assert (folder / "package.json").read_bytes() == package
    assert seen == [on_disk]
    earlier_answers = {
        (q.question, tuple(q.options), tuple(q.entity_ids)): (q.answer, q.answered_at)
        for q in earlier.evidence_requests if q.status == "answered"
    }
    carried_answers = {
        (q.question, tuple(q.options), tuple(q.entity_ids)): (q.answer, q.answered_at)
        for q in session.evidence_requests if q.status == "answered"
    }
    assert carried_answers
    assert set(carried_answers.items()) <= set(earlier_answers.items())
    assert not [q for q in session.evidence_requests if CANDIDATE_CONFIRM in q.options]
    assert decided(session) == decided(earlier) != {}
    # The numbers moved (owner decision 87A): the drawing's conformance finding took the
    # rejected finding's earlier number, so a carry by number would Reject the wrong finding.
    numbers_before = {finding_subject_key(f): f.id for f in earlier.findings}
    numbers_after = {finding_subject_key(f): f.id for f in session.findings}
    assert numbers_before.keys() == numbers_after.keys()
    assert [key for key in numbers_before if numbers_before[key] != numbers_after[key]]
    (rejected_before,) = [f for f in earlier.findings if f.disposition is not None]
    (rejected_after,) = [f for f in session.findings if f.disposition is not None]
    assert rejected_before.check == rejected_after.check == REJECTED_CHECK
    assert rejected_after.id != rejected_before.id
    assert rejected_after.disposition == rejected_before.disposition
    (holder,) = [f for f in session.findings if f.id == rejected_before.id]
    assert holder.check == "drawing_profile.conformance"
    assert holder.disposition is None
    role = next(q for q in earlier.evidence_requests if q.answer == "All bought")
    (carried_role,) = [
        q for q in session.evidence_requests
        if (q.question, q.entity_ids) == (role.question, role.entity_ids)
    ]
    assert (carried_role.status, carried_role.answer) == ("answered", "All bought")
    assert session.drawing_outcomes == earlier.drawing_outcomes
    assert recheck_row(session) == []
    assert session.model_status is not None
    assert str(session.model_status.rechecked_from) == str(earlier.session_id)
    assert provider_control.built == []


def test_the_opening_after_a_carried_answer_names_no_finding_it_withdrew(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
) -> None:
    waiting = worked_review(app, client, run_root / "FICT-recheck-opening", reject=False)
    folder = waiting.fixture.folder
    role = waiting_answers.question(waiting)
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        rerun = rerun_of(fresh, folder)
        withdrawn = {
            event["body"]["finding_id"]
            for event in chat.events_of(folder)
            if event["type"] == "finding.withdrawn"
        }
        provider = RecordingProvider([chat.turn("FICT sent")])
        fresh.app.state.server.provider_factory = lambda settings: provider
        chat_id = next(iter(fresh.app.state.server.chats))
        assert fresh.post(f"/sessions/{chat_id}/send", json={}).status_code == 202
        chat.settle(fresh, str(chat_id))

    opening = provider.log[0].first_message["content"]
    standing = {finding.id for finding in rerun.session.findings}
    named = set(rerun._prerun.named_finding_ids())
    assert withdrawn
    assert not withdrawn & named
    assert named <= standing
    assert all(f" {finding_id}" not in opening for finding_id in withdrawn - standing)
    assert opening == rerun._send_cache.opening == rerun.opening_at_send()
    carried_role = next(q for q in rerun.session.evidence_requests if q.question == role.question)
    assert opening.count(waiting_answers.wait_line(carried_role)) == 1
    for outcome in rerun.session.drawing_outcomes:
        assert f"Drawing {outcome.file}: {outcome.outcome}" in opening
    assert not [q for q in rerun.session.evidence_requests if CANDIDATE_CONFIRM in q.options]


# --- matching cases, on the runner's carry directly ------------------------------------------


def coaxial(finding_id: str, hole: str, decision: str | None = None) -> Finding:
    """A `hole.coaxiality` finding on one pair of components, told apart by its hole input."""
    finding = template_finding().model_copy(
        update={
            "id": finding_id,
            "check": "hole.coaxiality",
            "component_ids": ["cmp:0002", "cmp:0003"],
            "inputs": [hole],
            "configuration": "Default",
        }
    )
    if decision is not None:
        finding = finding.model_copy(
            update={
                "disposition": Disposition(
                    decision=decision, note="FICT note", by="FICT engineer", at=FIRST_DECIDED
                )
            }
        )
    return finding


FIRST_DECIDED = datetime(2026, 10, 9, 8, 30, tzinfo=UTC)


@pytest.fixture
def bare(tmp_path: Path) -> Any:
    """A re-run's run with findings and questions set by hand, and its earlier record."""
    folder = package_folder(tmp_path, live_prerun_package())
    run = checks_only(folder, None)
    earlier = run.session.model_copy(deep=True)
    run.session.findings[:] = []
    run.session.evidence_requests[:] = []
    earlier.findings[:] = []
    earlier.evidence_requests[:] = []
    events: list[tuple[str, dict[str, Any]]] = []
    run.sink.add_listener(lambda event: events.append((event.type, dict(event.body))))
    yield run, earlier, events
    run.close()


def test_two_coaxial_findings_on_one_pair_carry_the_reject_onto_its_own(bare: Any) -> None:
    run, earlier, events = bare
    run.session.findings[:] = [coaxial("F-001", "hol:0001"), coaxial("F-002", "hol:0002")]
    earlier.findings[:] = [
        coaxial("F-007", "hol:0001"), coaxial("F-008", "hol:0002", "rejected"),
    ]

    run.carry_from(earlier)

    assert run.session.findings[0].disposition is None
    carried = run.session.findings[1].disposition
    assert carried is not None and carried.decision == "rejected"
    assert carried.at == FIRST_DECIDED and carried.note == "FICT note"
    assert [body for kind, body in events if kind == "disposition"] == [
        {"finding_id": "F-002", "disposition": carried.model_dump(mode="json")}
    ]
    assert recheck_row(run.session) == []


def test_two_earlier_decisions_meeting_one_finding_carry_neither_and_name_each(
    bare: Any,
) -> None:
    run, earlier, events = bare
    run.session.findings[:] = [coaxial("F-001", "hol:0001")]
    earlier.findings[:] = [
        coaxial("F-007", "hol:0001", "rejected"), coaxial("F-008", "hol:0001", "accepted"),
    ]

    run.carry_from(earlier)

    assert run.session.findings[0].disposition is None
    assert not [kind for kind, _ in events if kind == "disposition"]
    assert recheck_row(run.session) == [
        runner.NOT_CARRIED.format(
            items="; ".join([
                "the Reject of F-007 (another decision matches the same finding)",
                "the Accept of F-008 (another decision matches the same finding)",
            ])
        )
    ]


def _request(request_id: str, question: str, *, answer: str | None = None) -> EvidenceRequest:
    return EvidenceRequest(
        id=request_id,
        what=f"FICT {question}",
        why="FICT reason",
        entity_ids=["cmp:0002"],
        question=question,
        options=["FICT yes", "FICT no"],
        source="code",
        status="answered" if answer is not None else "open",
        answer=answer,
        answered_at=FIRST_DECIDED if answer is not None else None,
    )


def test_an_answer_is_carried_onto_the_question_that_asks_the_same_under_a_new_number(
    bare: Any,
) -> None:
    """Owner decision 87A: the earlier ER-005 is the re-run's ER-001, and the earlier ER-001 asks
    something else, so a carry by number would answer the wrong question."""
    run, earlier, _ = bare
    run.session.evidence_requests[:] = [
        _request("ER-001", "FICT asked first now?"), _request("ER-002", "FICT asked first then?"),
    ]
    earlier.evidence_requests[:] = [
        _request("ER-001", "FICT asked first then?"),
        _request("ER-005", "FICT asked first now?", answer="FICT no"),
    ]

    run.carry_from(earlier)

    moved, other = run.session.evidence_requests
    assert (moved.id, moved.status, moved.answer) == ("ER-001", "answered", "FICT no")
    assert moved.answered_at == FIRST_DECIDED
    assert (other.id, other.status, other.answer) == ("ER-002", "open", None)
    assert recheck_row(run.session) == []


def test_two_earlier_answers_meeting_one_question_carry_neither_and_name_each(
    bare: Any,
) -> None:
    """Owner decision 89A, 72A's rule for answers: neither answer is carried, each is named, and
    the question stays open for the engineer to answer after Send."""
    run, earlier, _ = bare
    run.session.evidence_requests[:] = [_request("ER-001", "FICT asked once now?")]
    earlier.evidence_requests[:] = [
        _request("ER-004", "FICT asked once now?", answer="FICT yes"),
        _request("ER-006", "FICT asked once now?", answer="FICT no"),
    ]

    run.carry_from(earlier)

    (question,) = run.session.evidence_requests
    assert (question.status, question.answer, question.answered_at) == ("open", None, None)
    assert recheck_row(run.session) == [
        runner.NOT_CARRIED.format(
            items="; ".join([
                "the answer to ER-004 (another answer matches the same question)",
                "the answer to ER-006 (another answer matches the same question)",
            ])
        )
    ]
    assert run._opening_changed is False


def test_each_unmatched_or_ambiguous_item_is_named_once_in_one_row(bare: Any) -> None:
    run, earlier, _ = bare
    run.session.findings[:] = [coaxial("F-001", "hol:0001"), coaxial("F-002", "hol:0001")]
    run.session.evidence_requests[:] = [
        _request("ER-001", "FICT asked twice?"), _request("ER-002", "FICT asked twice?"),
    ]
    earlier.findings[:] = [
        coaxial("F-007", "hol:0009", "rejected"), coaxial("F-008", "hol:0001", "deferred"),
    ]
    earlier.evidence_requests[:] = [
        _request("ER-005", "FICT no longer asked?", answer="FICT yes"),
        _request("ER-006", "FICT asked twice?", answer="FICT no"),
    ]

    run.carry_from(earlier)

    assert recheck_row(run.session) == [
        runner.NOT_CARRIED.format(
            items="; ".join([
                "the answer to ER-005 (its question is no longer asked)",
                "the answer to ER-006 (it matches more than one question)",
                "the Reject of F-007 (its finding is no longer raised)",
                "the Defer of F-008 (it matches more than one finding)",
            ])
        )
    ]
    assert all(q.status == "open" for q in run.session.evidence_requests)
    assert all(f.disposition is None for f in run.session.findings)


def test_the_timing_inputs_and_a_failed_sends_status_are_carried(bare: Any) -> None:
    run, earlier, _ = bare
    earlier.timing = earlier.timing.replace(
        baseline_minutes=45.0,
        assisted_supervision_minutes=6.0,
        assisted_verification_minutes=9.0,
        false_alarm_handling_minutes=2.0,
    )
    assert earlier.model_status is not None
    failure = SendFailure(at=FIRST_DECIDED, error_class="FictFailure", reason="FICT refused")
    earlier.model_status = earlier.model_status.model_copy(
        update={"state": "send_failed", "failures": [failure]}
    )
    checked = run.session.model_status.checked_at

    run.carry_from(earlier)

    timing = run.session.timing
    assert (
        timing.baseline_minutes, timing.assisted_supervision_minutes,
        timing.assisted_verification_minutes, timing.false_alarm_handling_minutes,
    ) == (45.0, 6.0, 9.0, 2.0)
    status = run.session.model_status
    assert status.state == "send_failed" and status.failures == [failure]
    assert status.rechecked_from == earlier.session_id
    assert status.checked_at == checked
    assert status.document == earlier.model_status.document


def test_a_failed_sends_re_run_keeps_its_failure_and_a_later_send_counts_it(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = waiting_answers.waiting_review(app, client, run_root / "FICT-recheck-failed")
    refused = RecordingProvider([chat.turn("unused")])

    def refusal(**kwargs: Any) -> Any:
        raise RuntimeError("FICT first request refused")

    monkeypatch.setattr(refused._inner, "run", refusal)
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: refused)
    assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    folder = waiting.fixture.folder
    assert load_session(folder / "session.json").model_status.state == "send_failed"
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        rerun = rerun_of(fresh, folder)
        assert rerun.session.model_status.state == "send_failed"
        assert len(rerun.session.model_status.failures) == 1
        provider = RecordingProvider([chat.turn("FICT sent")])
        fresh.app.state.server.provider_factory = lambda settings: provider
        chat_id = next(iter(fresh.app.state.server.chats))
        assert fresh.post(f"/sessions/{chat_id}/send", json={}).status_code == 202
        chat.settle(fresh, str(chat_id))

    report = (folder / "report.md").read_text(encoding="utf-8")
    assert "- Earlier attempts that failed: 1" in report
    assert f"- Checked again from session: {waiting.run.session.session_id}" in report


# --- the Standards profile -------------------------------------------------------------------


PROFILE_CASES = ("unchanged", "another-file", "edited", "added", "removed")


def earlier_with_profile(
    app: Any, client: TestClient, folder: Path, *, profile: bool
) -> waiting_answers.Waiting:
    fixture = build_questions_package(folder)
    app.state.server.bridge_factory = lambda pipe, secret: fixture.bridge
    response = client.post(
        "/sessions",
        json=chat.session_body(
            folder,
            standards_profile=str(fixture.profile) if profile else None,
            bridge={"pipe": "FICT-pipe", "secret": "FICT-secret"},
            send_when_checked=False,
        ),
    )
    assert response.status_code == 201, response.text
    chat_id = str(response.json()["chat_id"])
    return waiting_answers.Waiting(fixture, chat_id, app.state.server.chats[UUID(chat_id)])


def without_data_card_properties(text: str) -> str:
    """The profile with a data card that asks for no property, so the new profile no longer
    raises the data-card finding."""
    document = yaml.safe_load(text)
    document["data_card"]["properties"] = []
    return yaml.safe_dump(document, sort_keys=False)


@pytest.mark.parametrize("case", PROFILE_CASES)
def test_a_changed_profile_grades_with_the_new_one_and_is_named(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
    case: str,
) -> None:
    folder = run_root / f"FICT-recheck-profile-{case}"
    waiting = earlier_with_profile(app, client, folder, profile=case != "added")
    profile = waiting.fixture.profile
    rejected: str | None = None
    if case in {"another-file", "edited"}:
        # Owner decision 87A: a decided finding the new profile no longer raises is named.
        finding = next(f for f in waiting.run.session.findings if f.check == REJECTED_CHECK)
        decided_now = client.post(
            f"/sessions/{waiting.chat_id}/findings/{finding.id}/disposition",
            json={"decision": "rejected", "note": "FICT engineer decision"},
        )
        assert decided_now.status_code == 200, decided_now.text
        rejected = finding.id
    now: Path | None = profile
    if case == "another-file":
        now = folder / "FICT-profile-b.yaml"
        now.write_text(without_data_card_properties(profile.read_text("utf-8")), "utf-8")
    elif case == "edited":
        edited = without_data_card_properties(profile.read_text("utf-8")) + "# FICT edit\n"
        profile.write_text(edited, "utf-8")
    elif case == "removed":
        now = None
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        rerun = rerun_of(fresh, folder, standards_profile=str(now) if now else None)

    status = rerun.session.model_status
    if now is None:
        assert status.profile is None
        assert "profile" not in status.model_dump(mode="json")
    else:
        assert status.profile == {
            "path": str(now), "sha256": hashlib.sha256(now.read_bytes()).hexdigest(),
        }
    rows = recheck_row(rerun.session)
    if case == "unchanged":
        assert rows == []
    elif rejected is not None:
        assert rows == [
            runner.NOT_CARRIED.format(
                items="; ".join([
                    f"the Reject of {rejected} (its finding is no longer raised)",
                    runner.NOT_CARRIED_PROFILE,
                ])
            )
        ]
        assert not [f for f in rerun.session.findings if f.check == REJECTED_CHECK]
        assert not [f for f in rerun.session.findings if f.disposition is not None]
    else:
        assert rows == [runner.NOT_CARRIED.format(items=runner.NOT_CARRIED_PROFILE)]


@pytest.mark.parametrize("digest", ["same", "other"])
def test_a_profile_path_spelled_with_other_capitals_is_the_same_profile(
    bare: Any, digest: str
) -> None:
    """Owner decision 90A: the path compares as `file_key` compares a Windows path, case and
    separator ignored; the digest compares exactly."""
    run, earlier, _ = bare
    assert earlier.model_status is not None and run.session.model_status is not None
    earlier.model_status = earlier.model_status.model_copy(
        update={"profile": {"path": "C:\\FICT\\Standards\\Profile-V3.yaml", "sha256": "a" * 64}}
    )
    run.session.model_status = run.session.model_status.model_copy(
        update={
            "profile": {
                "path": "c:/fict/standards/PROFILE-v3.YAML",
                "sha256": "a" * 64 if digest == "same" else "b" * 64,
            }
        }
    )

    run.carry_from(earlier)

    assert recheck_row(run.session) == (
        [] if digest == "same" else [runner.NOT_CARRIED.format(items=runner.NOT_CARRIED_PROFILE)]
    )


# --- what T087's failures leave --------------------------------------------------------------


def test_an_open_drawing_question_an_unfinished_read_merged_is_named_once(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
) -> None:
    waiting = waiting_answers.waiting_review(app, client, run_root / "FICT-recheck-lost")
    folder = waiting.fixture.folder
    drawing = waiting_answers.question(waiting, drawing=True)
    confirmed.merged(folder, PLATE_ID)()
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        rerun = rerun_of(fresh, folder)

    assert not [q for q in rerun.session.evidence_requests if CANDIDATE_CONFIRM in q.options]
    assert rerun.session.drawing_outcomes == []
    assert recheck_row(rerun.session) == [
        runner.NOT_CARRIED.format(items=runner.NOT_CARRIED_DRAWING.format(id=drawing.id))
    ]


def _candidate(
    request_id: str, entity_ids: list[str], *, answer: str | None = None
) -> EvidenceRequest:
    """A drawing candidate question over `entity_ids`, as `candidate_question` asks it."""
    return EvidenceRequest(
        id=request_id,
        what="FICT same-name drawings",
        why="FICT reason",
        entity_ids=entity_ids,
        question=f"A drawing with the same name sits beside {len(entity_ids)} reviewed file(s)",
        options=list(CANDIDATE_OPTIONS),
        source="code",
        status="answered" if answer is not None else "open",
        answer=answer,
        answered_at=FIRST_DECIDED if answer is not None else None,
    )


def merged_rerun(
    tmp_path: Path, package: EvidencePackage, read: str
) -> tuple[runner.ReviewRun, ReviewSession]:
    """A re-run over `package` once the earlier read merged `read`'s drawing, with its earlier
    record; findings and questions are set by each case."""
    folder = package_folder(tmp_path, package)
    confirmed.merged(folder, read)()
    run = checks_only(folder, None)
    earlier = run.session.model_copy(deep=True)
    for session in (run.session, earlier):
        session.findings[:] = []
        session.evidence_requests[:] = []
    return run, earlier


@pytest.fixture
def two_candidates(tmp_path: Path) -> Any:
    """A re-run over two candidate drawings, the first merged by the earlier read and the second
    refused, with its earlier record; findings and questions are set by each case."""
    package = confirmed.candidates_package(2)
    read, refused = (candidate.document_id for candidate in package.drawing_candidates)
    run, earlier = merged_rerun(tmp_path, package, read)
    yield run, earlier, read, refused
    run.close()


@pytest.mark.parametrize("status", ["answered", "open"])
def test_a_read_that_merged_some_drawings_and_was_refused_for_the_rest_is_named(
    two_candidates: Any, status: str
) -> None:
    """Owner decision 90A, FR-029's rule for a refused or failed read: the question is asked again
    over the refused file, a narrower question no earlier answer asks the same as. An answered
    question's answer is named so; an open one's merged file has no outcome line in the
    record, so the lost outcome is named as R2.13 names it."""
    run, earlier, read, refused = two_candidates
    run.session.evidence_requests[:] = [_candidate("ER-001", [refused])]
    answered = status == "answered"
    earlier.evidence_requests[:] = [
        _candidate("ER-002", [read, refused], answer=CANDIDATE_CONFIRM if answered else None)
    ]
    if answered:
        earlier.drawing_outcomes = [
            DrawingOutcome(file="FICT-KALO-8001.SLDDRW", outcome="opened read-only and read"),
            DrawingOutcome(file="FICT-KALO-8002.SLDDRW", outcome="FICT the host refused it"),
        ]

    run.carry_from(earlier)

    item = (
        "the answer to ER-002 (part of its drawing read was refused or failed, so its question "
        "is asked again)"
        if answered else runner.NOT_CARRIED_DRAWING.format(id="ER-002")
    )
    assert recheck_row(run.session) == [runner.NOT_CARRIED.format(items=item)]
    (asked,) = run.session.evidence_requests
    assert (asked.id, asked.status, asked.answer) == ("ER-001", "open", None)
    assert run.session.drawing_outcomes == earlier.drawing_outcomes


@pytest.mark.parametrize("status", ["answered", "open"])
def test_one_drawing_file_beside_two_documents_read_whole_is_not_a_partial_read(
    tmp_path: Path, status: str
) -> None:
    """013 T083: a part and an assembly of one stem share one candidate file, so a read that
    merged it covers both, though only the first shows in the drawing's views. Nothing is asked
    again. An answered question is carried as its outcome line and not named; an open one's
    merged file has no outcome line, so the lost outcome is named as R2.13 names it."""
    run, earlier = merged_rerun(tmp_path, confirmed.shared_stem_package(), "doc:0001")
    try:
        assert run.context.ir.drawing_candidates == [], "the merge removed both rows"
        answered = status == "answered"
        earlier.evidence_requests[:] = [
            _candidate(
                "ER-001", ["doc:0001", "doc:0002"],
                answer=CANDIDATE_CONFIRM if answered else None,
            )
        ]
        if answered:
            earlier.drawing_outcomes = [
                DrawingOutcome(
                    file=f"{confirmed.SHARED}.SLDDRW", outcome="opened read-only and read"
                )
            ]

        run.carry_from(earlier)

        assert run.session.evidence_requests == [], "nothing is asked again"
        assert recheck_row(run.session) == (
            [] if answered
            else [runner.NOT_CARRIED.format(items=runner.NOT_CARRIED_DRAWING.format(id="ER-001"))]
        )
        assert run.session.drawing_outcomes == earlier.drawing_outcomes
    finally:
        run.close()


def test_a_carry_builds_the_drawing_index_once(
    two_candidates: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner decision 90A: one index per carry, however many earlier drawing questions."""
    run, earlier, read, refused = two_candidates
    earlier.evidence_requests[:] = [
        _candidate("ER-002", [read, refused], answer="FICT no"),
        _candidate("ER-003", [read], answer="FICT no"),
        _candidate("ER-004", [refused]),
        _candidate("ER-005", [read]),
    ]
    built: list[Any] = []
    building = runner.DrawingIndex.for_package

    def counted(package: Any) -> Any:
        built.append(package)
        return building(package)

    monkeypatch.setattr(runner.DrawingIndex, "for_package", counted)

    run.carry_from(earlier)

    assert len(built) == 1


# --- SC-008 and the size sent ----------------------------------------------------------------


def sent_live_and_after_a_re_run(
    app: Any,
    client: TestClient,
    run_root: Path,
    saved: Path,
    waiting: waiting_answers.Waiting,
    settings: dict[str, Any],
) -> tuple[list[RecordedRequest], list[RecordedRequest], runner.ReviewRun]:
    """Press Send on the live waiting review; put its folder back as it was before that Send;
    re-run it from a restarted app and press Send again. Returns each Send's provider log -
    every request of its first turn, the explanation pass's included - and the re-run.

    The same provider, model and folder both times, so SC-008 compares what was sent, not a
    cache built for it (owner decision 87A).
    """
    folder = waiting.fixture.folder
    shutil.copytree(folder, saved)
    live = RecordingProvider([chat.turn("FICT sent")])
    app.state.server.provider_factory = lambda chosen: live
    assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
    chat.settle(client, waiting.chat_id)
    shutil.rmtree(folder)
    shutil.copytree(saved, folder)
    after = RecordingProvider([chat.turn("FICT sent")])
    with restarted_app(run_root, settings) as fresh:
        rerun = rerun_of(fresh, folder)
        fresh.app.state.server.provider_factory = lambda chosen: after
        chat_id = str(next(iter(fresh.app.state.server.chats)))
        assert fresh.post(f"/sessions/{chat_id}/send", json={}).status_code == 202
        chat.settle(fresh, chat_id)
    return live.log, after.log, rerun


def assert_sent_alike(live: list[RecordedRequest], after: list[RecordedRequest]) -> None:
    """Entry by entry: the system prompt, the encoded tools and history, the raw tool specs
    and first message, and whether it was the explanation pass."""
    assert live and len(after) == len(live)
    for index, (expected, actual) in enumerate(zip(live, after, strict=True)):
        assert actual == expected, f"request {index} of Send's first turn differs"


@pytest.mark.usefixtures("vocabulary")
def test_with_nothing_answered_the_first_request_is_the_live_waiting_reviews(
    app: Any,
    client: TestClient,
    run_root: Path,
    tmp_path: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
) -> None:
    waiting = waiting_answers.waiting_review(app, client, run_root / "FICT-recheck-sc008")
    live = waiting.run
    settings = server_settings(provider_control, models, silent)

    sent, resent, rerun = sent_live_and_after_a_re_run(
        app, client, run_root, tmp_path / "saved", waiting, settings
    )

    assert silent.calls == []
    assert rerun.system == live.system
    assert rerun._send_cache.opening == live._send_cache.opening
    assert request_prefix(rerun.system, rerun.tools, rerun._send_cache.opening) == (
        request_prefix(live.system, live.tools, live._send_cache.opening)
    )
    assert rerun._send_cache.estimate == live._send_cache.estimate
    assert_sent_alike(sent, resent)


@pytest.mark.usefixtures("vocabulary")
def test_a_carried_reject_alone_leaves_the_first_request_the_live_waiting_reviews(
    app: Any,
    client: TestClient,
    run_root: Path,
    tmp_path: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
) -> None:
    """Owner decision 88A: a carry of decisions alone does not settle the waiting opening, as a
    decision made while a live review waits does not: `_opening_changed` stays false. Send's
    requests are then the live waiting review's. That comparison alone does not pin the rule:
    the opening reads no disposition, so an opening settled anyway rebuilds the same bytes
    here; the flag is what pins it."""
    waiting = waiting_answers.waiting_review(app, client, run_root / "FICT-recheck-reject")
    finding = next(f for f in waiting.run.session.findings if f.check == REJECTED_CHECK)
    decided_now = client.post(
        f"/sessions/{waiting.chat_id}/findings/{finding.id}/disposition",
        json={"decision": "rejected", "note": "FICT engineer decision"},
    )
    assert decided_now.status_code == 200, decided_now.text
    settings = server_settings(provider_control, models, silent)

    sent, resent, rerun = sent_live_and_after_a_re_run(
        app, client, run_root, tmp_path / "saved", waiting, settings
    )

    (carried,) = [f for f in rerun.session.findings if f.disposition is not None]
    assert carried.check == REJECTED_CHECK
    assert carried.disposition is not None and carried.disposition.decision == "rejected"
    assert not [q for q in rerun.session.evidence_requests if q.status == "answered"]
    assert rerun.session.drawing_outcomes == []
    assert recheck_row(rerun.session) == []
    assert rerun._opening_changed is False, "a decision-only carry does not settle (88A)"
    assert_sent_alike(sent, resent)


@pytest.mark.usefixtures("vocabulary")
def test_the_size_shown_after_a_re_run_is_the_size_sent(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    silent: ScriptedReviewBridge,
) -> None:
    waiting = worked_review(app, client, run_root / "FICT-recheck-size")
    folder = waiting.fixture.folder
    with restarted_app(run_root, server_settings(provider_control, models, silent)) as fresh:
        rerun = rerun_of(fresh, folder)
        chat_id = str(next(iter(fresh.app.state.server.chats)))
        summary = fresh.get(f"/sessions/{chat_id}/snapshot").json()["ranking"]["summary"]
        shown = summary["send"]["input_tokens"]
        provider = RecordingProvider([chat.turn("FICT sent")])
        fresh.app.state.server.provider_factory = lambda settings: provider
        marker = rerun.sink.seq
        assert fresh.post(f"/sessions/{chat_id}/send", json={}).status_code == 202
        chat.settle(fresh, chat_id)

    recorded = provider.log[0]
    specs = [
        SimpleNamespace(name=row["name"], description=row["description"], schema=row["parameters"])
        for row in recorded.tool_specs
    ]
    prefix = request_prefix(recorded.system, specs, recorded.first_message["content"])
    estimate = next(
        event["body"]["estimate"]["input_tokens"]
        for event in chat.events_of(folder)
        if event["type"] == "session.sent" and event["seq"] > marker
    )
    assert tokens.count_tokens(prefix) == shown == estimate
    assert load_session(folder / "session.json").model_status.estimate.input_tokens == shown
