"""One whole re-model through the real backend, in the pipeline's own order (T134a to T134g).

`tests/unit/test_chat_remodel_routes.py` asks of each of the nine routes what
`contracts/backend-remodel.md` says of that route. This file asks the other question the
wiring brief's division of labour raises: do the nine routes, `remodel/runner.py`, the apply
loop, the grader and the event stream **compose** into the run
`AddIn/Remodel/BackendRemodelPipeline.cs` drives - when they are driven in the pipeline's
order, over one run folder, with the add-in's two in-process dumps arriving from outside?

The order is the pipeline's and not a convenience: probe, open, the ModelCheck dump the
add-in writes into the run folder as `package-before.json`, plan, start, poll, the
package-after rendezvous the add-in answers, poll to a terminal state. Every seam between
those steps is the run folder, which is the property that lets the pane be restarted
mid-run, and the only way to test that the folder really is the state is to cross those
seams for real rather than to hand one function the other's return value.

Three flows, because three are what the tab can end in:

1. **to completion.** The run reaches a terminal `plan.json` state with `changes.jsonl`,
   `grades.json` and `events.jsonl` beside it, and the events route replays exactly what
   the run wrote to disk - which is what the pipeline's poll loop relays to the page.
2. **the engineer stopped it.** Stop posted while a change is in flight ends the run
   `truncated`, with what landed readable from `changes.jsonl` and what was planned still
   on the plan (`pane-remodel-messages.md`, `remodel.stop`).
3. **the part already had rebuild errors.** `remodel.open` refuses with
   `preexisting_rebuild_errors`, the reply carries `copy_present: false` and the count, and
   nothing downstream can start - because the bridge has already deleted the copy.

Nothing here is stubbed but the seat and the clockless parts of a race: the application is
the real `create_app`, the bridge is `tests/support/remodel_bridge.py::FakeRemodelBridge`
(through the unit suite's `ProbingBridge`, which adds the one command the executor never
sends), and the part is the one `tests/support/remodel.py` builds. No SOLIDWORKS is
launched, no provider is reached and no key is read: the application is built with a
scripted provider factory, and the assertion below is that a remodel run never asks it for
anything, because `POST /remodel/runs` reaches a model only through
`remodel/runner.py::build_provider` (FR-045, SC-009).

**Why so much is imported from the unit suite.** The probing seat, the part, the nine
request helpers and the calibration seam are that file's and are imported rather than
copied, the way `tests/integration/test_coverage_stop.py` imports the provider suites'
builders: a second copy of `ProbingBridge` would be a second fake seat to keep in step with
`contracts/bridge-remodel.md`. What this file defines for itself is the application (a
different provider factory) and the seat that can hold a write open, which is what makes the
stop deterministic rather than a sleep.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview.agent.events import EVENTS_FILE_NAME
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.bridge.remodel_client import RemodelPreflightError
from swreview.chat.server import create_app
from swreview.chat.sessions import replay_events
from swreview.remodel.apply_log import CHANGES_FILE_NAME, read_changes
from swreview.remodel.artifacts import GRADES_FILE_NAME, PACKAGE_AFTER
from swreview.remodel.attestation import ATTESTATION_FILE_NAME
from swreview.remodel.plan import PACKAGE_BEFORE, RemodelPlan, plan_path
from swreview.remodel.runner import JUDGEMENT_ITEM
from tests.unit.test_chat_remodel_routes import (
    ORIGIN,
    PACKAGE,
    PROBE_ID,
    RUN_ID,
    SECRET,
    SOURCE_CONTENT,
    TOKEN,
    WAIT_S,
    ProbingBridge,
    calibrated,
    close,
    copy_path_of,
    deliver_package_after,
    dumped,
    open_copy,
    plan,
    planned,
    probe,
    seat,
    start,
    status_of,
    wait_for,
)

OPEN_FILE_NAME = "open.json"
MODEL = "fake-scripted"

TERMINAL_JOB_STATES = {"finished", "failed"}


# --- the seat that can hold one write open ------------------------------------------------


class PausingBridge(ProbingBridge):
    """`ProbingBridge` that can hold the run inside its first write until the test lets go.

    A stop posted "mid-run" is otherwise a race: the worker thread applies a small plan in
    microseconds and a test that posted the stop after `POST /remodel/runs` returned would
    be asserting about whichever change the scheduler happened to be on. So the seat is the
    clock. The run blocks inside the first mutating call, the test posts the stop while that
    change is genuinely in flight, and the run then does exactly what
    `pane-remodel-messages.md` says `remodel.stop` does: finishes the change in flight,
    records it, and reads the flag **between** changes.

    Off by default, so the same fake serves the run that goes to completion.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.writing = threading.Event()
        """Set by the worker thread when the first write is in flight."""

        self.release = threading.Event()
        """Cleared only by `hold_the_first_write`; the seat answers at once otherwise."""

        self.release.set()

    def hold_the_first_write(self) -> None:
        self.release.clear()

    def _begin(self, command: str, params: dict[str, Any]) -> Any:
        outcome = super()._begin(command, params)
        if self.mutations == 1:
            self.writing.set()
            assert self.release.wait(WAIT_S), (
                "the first write was never released; the test that held it open did not "
                "let go and the run would have blocked forever"
            )
        return outcome


# --- the application, with a model nothing in a run may reach ------------------------------


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def run_dir(run_root: Path) -> Path:
    """The run folder the host created before it asked the backend for anything."""
    directory = run_root / RUN_ID
    directory.mkdir()
    return directory


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """The engineer's file, which phase D re-reads to re-check the attestation."""
    path = tmp_path / "work" / "bracket.SLDPRT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(SOURCE_CONTENT)
    return path


@pytest.fixture
def bridge(source: Path, run_dir: Path) -> PausingBridge:
    return PausingBridge(seat(PACKAGE), source=source, copy_path=copy_path_of(run_dir))


@pytest.fixture
def scripted(bridge: PausingBridge) -> list[Any]:
    """Every settings object the application's provider factory was asked to build from."""
    return []


@pytest.fixture
def app(run_root: Path, bridge: PausingBridge, scripted: list[Any]) -> Any:
    """The real backend: a scripted provider for sessions, the fake seat for `remodel.*`.

    The provider factory is the one `create_app` hands **chat sessions**; a remodel run
    reaches a model only through `remodel/runner.py::build_provider`, so `scripted` staying
    empty through a whole run is the assertion that the two paths are not the same one.
    """

    def provider_factory(settings: Any) -> FakeProvider:
        scripted.append(settings)
        return FakeProvider(script=[ScriptedTurn(text="Nothing to propose.")], model=MODEL)

    return create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=provider_factory,
        list_models=lambda _provider: [],
        remodel_bridge_factory=lambda _pipe, _secret: bridge,
    )


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as test_client:
        yield test_client


# --- reading the folder back ---------------------------------------------------------------


def plan_on_disk(run_dir: Path) -> RemodelPlan:
    return RemodelPlan.model_validate_json(plan_path(run_dir).read_text(encoding="utf-8"))


def events_of(client: TestClient, job_id: str, after: int = 0) -> dict[str, Any]:
    response = client.get(f"/remodel/runs/{job_id}/events", params={"after": after})
    assert response.status_code == 200, response.text
    return dict(response.json())


def started(client: TestClient, run_dir: Path) -> str:
    response = start(client, run_dir)
    assert response.status_code == 201, response.text
    return str(response.json()["job_id"])


def answer_the_rendezvous(client: TestClient, job_id: str, run_dir: Path) -> dict[str, Any]:
    """What the pipeline does at `awaiting: "package_after"`: dump, post, keep polling."""
    wait_for(client, job_id, lambda state: state["awaiting"] == "package_after")
    assert deliver_package_after(client, job_id, run_dir).status_code == 200
    return wait_for(client, job_id, lambda state: state["state"] in TERMINAL_JOB_STATES)


# --- 1. the run that goes to completion -----------------------------------------------------


class TestARunThroughTheWholePipeline:
    def test_the_folder_carries_the_run_from_one_route_to_the_next(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        """Probe, open, dump, plan: each step reads what the one before it wrote down.

        `POST /remodel/plan` is handed nothing but a `run_dir`, so if `open.json` and
        `source-attestation.json` were not on disk it could not name the copy, the scope or
        the source - which is the whole reason the pipeline can be stateless.
        """
        assert probe(client, source).json()["refusals"] == []
        assert open_copy(client, run_dir, source).json()["copy_present"] is True
        assert (run_dir / OPEN_FILE_NAME).is_file()
        assert (run_dir / ATTESTATION_FILE_NAME).is_file()

        dumped(run_dir, PACKAGE_BEFORE)
        summary = plan(client, run_dir).json()["plan_summary"]

        assert summary["state"] == "planned"
        written = plan_on_disk(run_dir)
        assert written.run_id == RUN_ID
        assert written.copy_path == copy_path_of(run_dir)
        assert written.scope.probe_id == PROBE_ID
        assert written.source is not None and written.source.path == str(source)

    def test_the_run_ends_saved_with_every_artifact_the_pane_reads(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The whole of tab 5's happy path, and what it leaves on disk afterwards.

        A terminal state, the change log, both grades and the report are what the pane's
        result view and `remodel.finished` are built from; a run that reached `finished`
        without them would be a run nobody could show.
        """
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        job_id = started(client, run_dir)

        state = answer_the_rendezvous(client, job_id, run_dir)

        assert state["state"] == "finished", state
        assert state["error"] is None
        assert plan_on_disk(run_dir).state == "saved"
        assert state["plan_state"] == "saved"
        assert state["changes_applied"] == state["changes_total"] >= 1
        assert (run_dir / CHANGES_FILE_NAME).is_file()
        assert (run_dir / GRADES_FILE_NAME).is_file()
        assert (run_dir / "report.md").is_file()

    def test_the_change_log_is_the_run_the_pipeline_relayed(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        bridge: PausingBridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Every planned change is opened and then closed out, and the seat did the writes.

        The pipeline tails this file and hands each new line to the page verbatim, so the
        lines have to be complete records of what the seat was asked for - not a summary
        written after the fact. Two lines per change: `attempting` is written **before** the
        bridge call, so a run whose process died mid-change says which change it was in.
        """
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        job_id = started(client, run_dir)
        answer_the_rendezvous(client, job_id, run_dir)

        records = read_changes(run_dir / CHANGES_FILE_NAME)
        planned_changes = plan_on_disk(run_dir).changes
        opened = [row for row in records if row.status == "attempting"]
        closed = [row for row in records if row.status != "attempting"]
        assert [row.seq for row in opened] == list(range(1, len(planned_changes) + 2))
        assert [row.seq for row in closed] == [row.seq for row in opened]
        assert {row.status for row in closed} == {"applied"}
        assert closed[-1].kind == "save", "the gate's save is the last record of a saved run"
        assert [row.kind for row in closed[:-1]] == [row.kind for row in planned_changes]
        assert bridge.mutations == len(planned_changes)
        assert bridge.saves == 1

    def test_both_grades_are_measured_and_written_down(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`grades.json` holds the reading before and the reading after the same waivers.

        The after-grade is taken from the dump the add-in posted through the rendezvous, so
        this is also the assertion that the rendezvous handed the run the right file.
        """
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        job_id = started(client, run_dir)
        answer_the_rendezvous(client, job_id, run_dir)

        grades = json.loads((run_dir / GRADES_FILE_NAME).read_text(encoding="utf-8"))
        assert set(grades) == {"before", "after", "per_rule"}
        assert grades["before"] and grades["after"]
        assert (run_dir / "rms-after.json").is_file()

    def test_the_events_route_replays_exactly_what_the_run_wrote(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The poll loop's second half: the same `events.jsonl` the review stream replays.

        Asserted against the file rather than against itself, because the route's job is to
        hand back the run's own stream and `after=N` is how the pipeline resumes a poll it
        was interrupted in the middle of.
        """
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        job_id = started(client, run_dir)
        answer_the_rendezvous(client, job_id, run_dir)

        whole = events_of(client, job_id)
        on_disk = list(replay_events(run_dir / EVENTS_FILE_NAME))

        assert [event["seq"] for event in whole["events"]] == [row.seq for row in on_disk]
        assert whole["events"], "a run that judged, applied and verified writes events"
        assert whole["next"] == whole["events"][-1]["seq"]
        halfway = whole["events"][len(whole["events"]) // 2]["seq"]
        rest = events_of(client, job_id, after=halfway)
        assert [event["seq"] for event in rest["events"]] == [
            event["seq"] for event in whole["events"] if event["seq"] > halfway
        ]

    def test_the_run_reaches_a_model_only_through_the_runner(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        scripted: list[Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FR-045 and SC-009 over a whole run rather than over one route.

        The application was built with a provider factory, and a remodel run never asks it
        for anything: `build_provider` is the one entry point, it refuses the scripted
        provider this run names, and the absence is recorded on the plan while phases C and
        D run unaffected. A deterministic re-model works on a workstation with no key.
        """
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        job_id = started(client, run_dir)
        state = answer_the_rendezvous(client, job_id, run_dir)

        assert scripted == [], "the sessions' provider factory is not the run's"
        assert state["state"] == "finished"
        absence = [row for row in plan_on_disk(run_dir).coverage if row.item == JUDGEMENT_ITEM]
        assert absence, "a run that built no model says so on the plan"
        assert "no model saw this part" in absence[0].reason

    def test_closing_the_copy_keeps_it_for_the_host_to_delete(
        self, client: TestClient, run_dir: Path, source: Path, bridge: PausingBridge
    ) -> None:
        """The last call of the pipeline: the host is the one deleter of `copy/`."""
        planned(client, run_dir, source)

        assert close(client, run_dir).json() == {"closed": True}

        assert bridge.closed is True
        assert bridge.discards == 0
        assert bridge.copy_exists is True

    def test_no_reply_and_no_artifact_of_the_whole_run_carries_the_secret(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The bridge secret reaches the client and stops there, over a whole run."""
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        job_id = started(client, run_dir)
        answer_the_rendezvous(client, job_id, run_dir)

        written = [
            path.read_text(encoding="utf-8", errors="ignore")
            for path in sorted(run_dir.rglob("*"))
            if path.is_file()
        ]
        assert all(SECRET not in text for text in written)
        assert SECRET not in json.dumps(status_of(client, job_id))
        assert SECRET not in json.dumps(events_of(client, job_id))


# --- 2. the engineer stops the run --------------------------------------------------------


class TestTheEngineerStopsTheRun:
    def test_a_stop_mid_change_truncates_the_run_with_its_changes_readable(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        bridge: PausingBridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`remodel.stop`: the change in flight finishes and the run reports `truncated`.

        The run still reaches the package-after rendezvous, because a truncated run is
        graded and reported like any other: the engineer asked for the run to end, not for
        the evidence of what it did to be thrown away.
        """
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        total = len(plan_on_disk(run_dir).changes)
        assert total >= 2, "a plan of one change has no 'between changes' to stop at"
        bridge.hold_the_first_write()
        job_id = started(client, run_dir)
        assert bridge.writing.wait(WAIT_S), "the run never reached its first write"

        assert client.post(f"/remodel/runs/{job_id}/stop", json={}).json() == {
            "stopping": True
        }
        bridge.release.set()
        state = answer_the_rendezvous(client, job_id, run_dir)

        assert state["state"] == "finished", state
        assert plan_on_disk(run_dir).state == "truncated"
        assert state["plan_state"] == "truncated"
        records = read_changes(run_dir / CHANGES_FILE_NAME)
        applied = [row for row in records if row.status == "applied" and row.kind != "save"]
        assert [row.seq for row in applied] == [1], [row.seq for row in records]
        assert applied[0].kind == "reorder"
        assert state["changes_total"] == total
        # `changes_applied` is what the page shows as `remodel.stopped {changes_applied}`,
        # so it counts what landed. A truncated run that passed the gate still writes the
        # `save` line, and reading that line as "all of them" would report a run the
        # engineer stopped after one change as a completed one.
        assert len(applied) == 1 < total
        assert state["changes_applied"] == 1
        assert state["current"] is None

    def test_the_changes_that_were_never_attempted_are_written_down_as_such(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        bridge: PausingBridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A stopped run is still a readable one (Principle VI): the plan says which
        changes landed and which were never tried, and the seat was asked for no more.

        The copy is still saved, because the gate passed: stopping ends the *work*, and the
        engineer keeps what the run had already done under a verdict that was measured. A
        run that threw the applied changes away would make Stop the expensive button.
        """
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        total = len(plan_on_disk(run_dir).changes)
        bridge.hold_the_first_write()
        job_id = started(client, run_dir)
        assert bridge.writing.wait(WAIT_S)
        client.post(f"/remodel/runs/{job_id}/stop", json={})
        bridge.release.set()
        answer_the_rendezvous(client, job_id, run_dir)

        written = plan_on_disk(run_dir)
        assert written.state == "truncated"
        assert bridge.mutations == 1, "nothing after the change in flight was attempted"
        assert bridge.saves == 1, "what did land is saved under the verdict that was measured"
        assert (run_dir / GRADES_FILE_NAME).is_file()
        assert (run_dir / "report.md").is_file()
        assert len(written.changes) == total, "the plan is not rewritten by the stop"

    def test_the_report_names_the_stop_and_not_a_limit(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        bridge: PausingBridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The report is the product (Principle VI), and a stopped run reads as stopped.

        `stopped` finalizes `truncated` the same way the three bounds do, so the state
        alone cannot say why the run ended short; the headline is where the difference has
        to be visible, and a limit nobody reached is a cause the evidence does not support.
        """
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        bridge.hold_the_first_write()
        job_id = started(client, run_dir)
        assert bridge.writing.wait(WAIT_S)
        client.post(f"/remodel/runs/{job_id}/stop", json={})
        bridge.release.set()
        answer_the_rendezvous(client, job_id, run_dir)

        headline = (run_dir / "report.md").read_text(encoding="utf-8").splitlines()[0]

        assert plan_on_disk(run_dir).state == "truncated"
        assert "the engineer stopped this run" in headline
        assert "limit" not in headline

    def test_a_second_stop_changes_nothing(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        bridge: PausingBridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Idempotent, for the same reason `POST /sessions/{chat_id}/stop` is: the pane may
        send it again, and a run that has already ended is not turned into a failure."""
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        bridge.hold_the_first_write()
        job_id = started(client, run_dir)
        assert bridge.writing.wait(WAIT_S)
        client.post(f"/remodel/runs/{job_id}/stop", json={})
        bridge.release.set()
        answer_the_rendezvous(client, job_id, run_dir)

        again = client.post(f"/remodel/runs/{job_id}/stop", json={})

        assert again.status_code == 200
        assert again.json() == {"stopping": True}
        assert status_of(client, job_id)["plan_state"] == "truncated"


# --- 3. the part that already had rebuild errors --------------------------------------------


class TestAPartThatAlreadyHadRebuildErrors:
    def test_the_open_answers_the_count_and_no_copy(
        self, client: TestClient, run_dir: Path, source: Path, bridge: PausingBridge
    ) -> None:
        """The refusal the host handles itself, reached from a `200` and not an error body.

        `remodel.open` rolls to the end and rebuilds before it answers, so a non-zero count
        is the source's own; the bridge has already deleted the copy and closed the
        document, and `copy_present: false` is how the host knows not to offer Show or
        Discard for a copy that is not there.
        """
        bridge.open_raises = RemodelPreflightError(
            "the part already has 3 rebuild errors",
            "preexisting_rebuild_errors",
            {"rebuild_error_count": 3},
        )
        assert probe(client, source).json()["refusals"] == []

        response = open_copy(client, run_dir, source)

        assert response.status_code == 200
        assert response.json() == {
            "copy_path": copy_path_of(run_dir),
            "rebuild_error_count": 3,
            "copy_present": False,
        }

    def test_nothing_downstream_can_start_from_that_folder(
        self, client: TestClient, run_dir: Path, source: Path, bridge: PausingBridge
    ) -> None:
        """No baseline was written, so the folder is not a run: the plan has nothing to
        read and the start route has no plan. The engineer fixes the part and probes
        again, which is the recovery `quickstart.md` documents."""
        bridge.open_raises = RemodelPreflightError(
            "the part already has 3 rebuild errors",
            "preexisting_rebuild_errors",
            {"rebuild_error_count": 3},
        )
        assert open_copy(client, run_dir, source).status_code == 200

        assert not (run_dir / OPEN_FILE_NAME).exists()
        assert not (run_dir / ATTESTATION_FILE_NAME).exists()
        dumped(run_dir, PACKAGE_BEFORE)
        refused = plan(client, run_dir)
        assert refused.status_code == 400
        assert refused.json()["error_class"] == "RunFolderFailed"
        assert start(client, run_dir).json()["error_class"] == "RunNotPlanned"

    def test_a_count_the_refusal_did_not_carry_stays_unknown_through_the_flow(
        self, client: TestClient, run_dir: Path, source: Path, bridge: PausingBridge
    ) -> None:
        """Unknown is not zero: a part whose count could not be read has no baseline, and
        the reply says so rather than reporting a clean part."""
        bridge.open_raises = RemodelPreflightError(
            "the copy would not rebuild cleanly", "preexisting_rebuild_errors", {}
        )

        body = open_copy(client, run_dir, source).json()

        assert body["rebuild_error_count"] is None
        assert body["copy_present"] is False


# --- what the flow must never do ------------------------------------------------------------


def test_the_source_is_named_in_no_bridge_call_after_the_open(
    client: TestClient,
    run_dir: Path,
    source: Path,
    bridge: PausingBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`RemodelScope` holds the only document a run can reach once the copy is open, and
    this is that property asserted over a whole run's call log rather than command by
    command. The copy is worked on and the engineer's file is unreachable, not merely
    un-targeted (owner decision: copy only, never the source)."""
    calibrated(monkeypatch)
    planned(client, run_dir, source)
    job_id = started(client, run_dir)
    answer_the_rendezvous(client, job_id, run_dir)

    opened = [index for index, call in enumerate(bridge.calls) if call[0] == "remodel.open"]
    after = bridge.calls[opened[-1] + 1 :]
    assert after, "a run that applied changes sent something after the open"
    assert str(source) not in json.dumps(after)
    assert PACKAGE_AFTER not in json.dumps(after), "the dumps are the add-in's, not the bridge's"


def test_the_run_polls_the_same_folder_the_routes_wrote(
    client: TestClient, run_dir: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One run folder end to end: every artifact of this flow is inside it and the poll
    reads its numbers off the same files, which is what makes a run readable after a
    restart and a crashed run readable at all."""
    calibrated(monkeypatch)
    planned(client, run_dir, source)
    job_id = started(client, run_dir)
    answer_the_rendezvous(client, job_id, run_dir)

    names = {path.name for path in run_dir.iterdir() if path.is_file()}

    assert {
        OPEN_FILE_NAME,
        ATTESTATION_FILE_NAME,
        PACKAGE_BEFORE,
        PACKAGE_AFTER,
        "plan.json",
        CHANGES_FILE_NAME,
        EVENTS_FILE_NAME,
        GRADES_FILE_NAME,
        "report.md",
    } <= names, sorted(names)
    state = status_of(client, job_id)
    records = read_changes(run_dir / CHANGES_FILE_NAME)
    assert state["changes_total"] == len(plan_on_disk(run_dir).changes)
    assert state["changes_applied"] == len(
        [row for row in records if row.status == "applied" and row.kind != "save"]
    )
    assert records[-1].kind == "save"
    assert state["current"] is None, "the save is not one of the planned changes"
