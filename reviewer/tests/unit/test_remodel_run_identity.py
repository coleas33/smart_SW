"""A run's worker that outlived its session cannot change the next run's copy (owner decision 159A).

On Codex's review of the merge (C1; 004 T240): the add-in took a status poll the backend did not
answer for the run's end, closed the run's session on the bridge and was free, and the next plan
opened its copy on the same bridge - while the run's worker, in the backend, went on. Its next
change named no run, so the bridge carried it out on the session it held: the next run's copy,
which passes every check `VerifyTarget` makes because it is that run's own.

The add-in no longer ends a run before its job (T239). This is the defence behind that, end to end
on the Python side: the real `RemodelClient` and the real executor (`remodel/apply.py`), over an
in-memory bridge that keeps one session at a time as the C# dispatcher does and checks the run a
command names against it. Run A applies one change; between two of its commands the add-in closes
A's session and run B's plan opens B's copy; A's next change is refused, A stops with its change
log intact, and B's copy is untouched.

The bridge here carries out a command that names no run, as a host before protocol 1.5 did, so
that a client that sent none would show the defect rather than a refusal; it records every such
command, and the test asserts there were none. The C# dispatcher itself refuses one
(`RemodelRunIdentityTests`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from swreview.bridge.remodel_client import RemodelClient
from swreview.remodel.apply import apply_changes, open_log
from swreview.remodel.apply_log import CHANGES_FILE_NAME, read_changes
from swreview.remodel.plan import ChangeSubject, Limits, PlannedChange
from tests.support.remodel_bridge import StepClock

RUN_A = "20260916-142201-bracket-remodel"
RUN_B = "20260916-142305-bracket-remodel"
START = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)
BOSS, FILLET = "pr:boss1", "pr:fillet1"
TREE = {BOSS: "Boss-Extrude1", FILLET: "Fillet1"}
SOURCE = r"C:\work\bracket.SLDPRT"


def copy_of(run_id: str) -> str:
    """The run's copy, where `remodel.open` would put it; nothing here touches a disk."""
    return rf"C:\runs\{run_id}\copy\bracket-RMS.SLDPRT"


class OneSessionBridge:
    """The bridge's `remodel.*` end, in memory: one session at a time, as the dispatcher keeps it.

    No session is `target_mismatch`; a command naming another run than the session's is
    `session_mismatch`, before anything is read or written. `between` runs once, after the first
    `remodel.rebuild` is answered and before the run that sent it is told: the moment the add-in
    moved on while that run's worker still ran.
    """

    def __init__(self) -> None:
        self.session: str | None = None
        self.copies: dict[str, dict[str, str]] = {}
        self.unnamed: list[str] = []
        self.between: Callable[[], None] | None = None

    def request(self, line: str) -> str:
        request = json.loads(line)
        answer = self._answer(request["command"], request.get("params") or {})
        if request["command"] == "remodel.rebuild" and self.between is not None:
            moved_on, self.between = self.between, None
            moved_on()
        return json.dumps({"id": request["id"], "elapsed_ms": 1, **answer})

    def close(self) -> None:
        pass

    def _answer(self, command: str, params: dict[str, Any]) -> dict[str, Any]:
        if command == "remodel.open":
            if self.session is not None:
                return _refused("run_in_progress", "this bridge already has a remodel run open")
            self.session = params["run_id"]
            self.copies[params["run_id"]] = dict(TREE)
            return _ok({"document_path": params["copy_path"], "tag": params["run_id"]})
        if self.session is None:
            return _refused("target_mismatch", "remodel.open has not returned in this session")
        if "run_id" not in params:
            self.unnamed.append(command)
        elif params["run_id"] != self.session:
            return _refused(
                "session_mismatch",
                f"{command} was sent for run '{params['run_id']}', and the copy open on this "
                f"bridge belongs to run '{self.session}'; nothing was read or written",
            )
        copy = self.copies[self.session]
        if command == "remodel.rename":
            previous = copy[params["persist_ref"]]
            copy[params["persist_ref"]] = params["new_name"]
            return _ok({"previous_name": previous, "new_name": params["new_name"]})
        if command == "remodel.rebuild":
            return _ok(
                {"rebuild_errors": 0, "whats_wrong": [], "elapsed_ms": 5, "feature_errors": []}
            )
        assert command == "remodel.close", command
        self.session = None
        return _ok({"closed": True, "copy_deleted": False})


def _ok(result: Any) -> dict[str, Any]:
    return {"status": "ok", "result": result, "error": None}


def _refused(error_code: str, error: str) -> dict[str, Any]:
    return {"status": "error", "result": {"error_code": error_code, "detail": {}}, "error": error}


def _for_run(bridge: OneSessionBridge, run_id: str) -> RemodelClient:
    """A client acting for one run, bound as the backend's routes bind theirs."""
    client = RemodelClient(transport=bridge)
    client.run_id = run_id
    return client


def _rename(seq: int, persist_ref: str, name: str, new_name: str) -> PlannedChange:
    return PlannedChange(
        seq=seq,
        kind="rename",
        subject_kind="feature",
        subject=ChangeSubject(feature_id=f"feat:000{seq}", name=name, persist_ref=persist_ref),
        params={"persist_ref": persist_ref, "new_name": new_name},
        expect={"rebuild_errors_delta": 0},
    )


def test_a_run_whose_session_was_closed_under_it_cannot_change_the_next_runs_copy(
    tmp_path: Path,
) -> None:
    bridge = OneSessionBridge()
    run_a = _for_run(bridge, RUN_A)
    run_a.open(SOURCE, copy_of(RUN_A), RUN_A, "probe:1")

    def the_add_in_moves_on() -> None:
        _for_run(bridge, RUN_A).close_document(False)
        _for_run(bridge, RUN_B).open(SOURCE, copy_of(RUN_B), RUN_B, "probe:2")

    bridge.between = the_add_in_moves_on
    run_dir = tmp_path / RUN_A

    result = apply_changes(
        client=run_a,
        log=open_log(run_dir),
        changes=(
            _rename(1, BOSS, "Boss-Extrude1", "Boss-Base1"),
            _rename(2, FILLET, "Fillet1", "Fillet-Outer"),
        ),
        target_path=copy_of(RUN_A),
        baseline=0,
        limits=Limits(),
        now=StepClock(START, 0.31),
    )

    # Run B's copy is as B opened it, and B's session is still the bridge's.
    assert bridge.copies[RUN_B] == TREE
    assert bridge.session == RUN_B
    # Run A applied its first change, on its own copy, and stopped at its second.
    assert bridge.copies[RUN_A] == {BOSS: "Boss-Base1", FILLET: "Fillet1"}
    assert result.applied == (1,)
    assert result.failed == (2,)
    assert result.status == "aborted"
    assert result.stop is not None
    assert result.stop.reason == "target_mismatch"
    assert result.stop.seq == 2
    # The change log says why, against the change that was refused.
    refused = read_changes(run_dir / CHANGES_FILE_NAME)[-1]
    assert (refused.seq, refused.status, refused.error_code) == (2, "failed", "session_mismatch")
    # Every command after an open named its run.
    assert bridge.unnamed == []
