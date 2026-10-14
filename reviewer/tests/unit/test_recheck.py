"""US4: a waiting review survives a restart (feature 015, `contracts/recheck.md`).

The carried live step (T092): a re-run of a not-sent review's checks carries the first run's
live interference outcome instead of asking SOLIDWORKS again, records one carried step where
the first run recorded its call, and carries the drawing-read capability onto its own record
(FR-028; SC-008; research R2.17). The claim and the rotation (T094): `POST /sessions` with
`recheck: true` copies the earlier record, moves its stream, adopts a re-run the backend
finished, and leaves the earlier record whole whenever a re-run fails or is cut off (FR-041;
RK-4; owner decision 76A). Every package, path and seat here is fictional.
"""

from __future__ import annotations

import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview import atomic
from swreview.agent import runner
from swreview.agent.providers import ProviderName
from swreview.agent.providers.deferred import DeferredProvider
from swreview.agent.settings import ProviderSettings, pane_defaults
from swreview.chat import server
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
from swreview.report.session import ReviewSession, load_session, save_session
from tests.support.prerun import LIVE_ROWS, live_prerun_package, prerun_package
from tests.support.questions_package import build_questions_package
from tests.support.restart import BEFORE_REPLACE, disk_at, restarted_app
from tests.support.review_bridge import VOLUME_UNIT_GAP, ScriptedReviewBridge
from tests.unit import test_chat_server as chat
from tests.unit import test_waiting_answers as waiting_answers

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
    assert provider_control.built == []


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

    Returns the indexes the successful re-run left.
    """
    assert (folder / "session.json").read_bytes() == earlier.files["session.json"]
    with restarted_app(root, settings) as fresh:
        restored = fresh.get(f"/reviews/{folder.name}")
        assert restored.status_code == 200, restored.text
        assert restored.json()["read_only"] is True
        assert [finding["id"] for finding in restored.json()["findings"]] == [
            finding.id for finding in earlier.record.findings
        ]
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
