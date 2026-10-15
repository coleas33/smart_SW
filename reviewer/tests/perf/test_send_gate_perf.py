"""The seconds a checks-only start and a re-run hold the host's call (feature 015 T098).

Owner decision 70A: the host's one message pump waits for `POST /sessions`, so the bound on
an unticked start and on a re-run of a waiting review is measured, not chosen (research
R2.17, RK-10). On `test_prerun_perf.py`'s thousand-group package this times, through the
backend's own route, a ticked start, an unticked start, and a re-run with a carry from a
restarted backend - a Reject made while the first run waited, carried onto its finding - and
prints the seconds. It asserts that the unticked start's added work - the Send cache, the
finalization and the render - stays a small fraction of the pre-run both starts share.

Not in the default run, for the reason every module here gives: a timing assertion measures
the machine as much as the code (`tests/conftest.py::pytest_ignore_collect`). Run it with:

    uv run pytest -m perf -s tests/perf/test_send_gate_perf.py
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview import prerun
from swreview.agent import runner
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.chat import server
from swreview.chat.server import create_app
from swreview.ir.loader import save_package
from swreview.report.session import load_session
from tests.perf.test_prerun_perf import PERF_GROUPS, thousand_group_package
from tests.support.restart import restarted_app

TOKEN = "FICT-perf-token"
ORIGIN = "https://fictional.example"
ADDED_WORK_SHARE = 0.25
"""The largest share of the shared pre-run the unticked start's added work may take."""

ONE_RULE_S = 30.0
"""The host's one call timeout (`BackendClient.CallTimeout`), which a re-run must fit inside
for one 30 s rule to cover every call (owner decision 70A)."""


class Timer:
    """Seconds spent inside each wrapped callable, summed per name."""

    def __init__(self) -> None:
        self.seconds: dict[str, float] = {}

    def wrap(self, name: str, action: Callable[..., Any]) -> Callable[..., Any]:
        def timed(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return action(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                self.seconds[name] = self.seconds.get(name, 0.0) + elapsed

        return timed


def settings() -> dict[str, Any]:
    return {
        "token": TOKEN,
        "allow_origin": ORIGIN,
        "provider_factory": lambda chosen: FakeProvider(
            script=[ScriptedTurn(text="FICT done")], model=chosen.model
        ),
        "list_models": lambda provider: [],
    }


def body(folder: Path, **changes: Any) -> dict[str, Any]:
    return {
        "run_dir": str(folder),
        "provider": "fake",
        "model": "fake-1",
        "effort": "high",
        "bridge": None,
        "engineer": "FICT engineer",
        "retry_of": None,
        **changes,
    }


def timed_post(client: TestClient, payload: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    started = time.perf_counter()
    response = client.post("/sessions", json=payload)
    elapsed = time.perf_counter() - started
    assert response.status_code == 201, response.text
    return elapsed, response.json()


def settled(client: TestClient, chat_id: str) -> None:
    """Wait for the ticked chat's turn to end, so it does not share the next timing's CPU."""
    deadline = time.monotonic() + 120.0
    while client.get(f"/sessions/{chat_id}").json()["state"] == "running":
        assert time.monotonic() < deadline, "the ticked review never finished its turn"
        time.sleep(0.05)


@pytest.mark.perf
def test_the_checks_only_start_and_the_re_run_fit_their_measured_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "runs"
    for name in ("ticked", "waiting"):
        save_package(thousand_group_package(), root / name)
    timer = Timer()
    monkeypatch.setattr(runner, "prerun_checks", timer.wrap("prerun", prerun.prerun_checks))
    monkeypatch.setattr(
        runner.ReviewRun, "close_waiting", timer.wrap("added", runner.ReviewRun.close_waiting)
    )
    monkeypatch.setattr(
        server.ChatServer, "_render_run", timer.wrap("added", server.ChatServer._render_run)
    )
    headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    with TestClient(create_app(run_root=root, **settings()), headers=headers) as first:
        ticked_s, ticked = timed_post(first, body(root / "ticked"))
        shared = timer.seconds.pop("prerun")
        settled(first, ticked["chat_id"])
        timer.seconds.clear()
        waiting_s, started = timed_post(first, body(root / "waiting", send_when_checked=False))
        unticked_prerun = timer.seconds["prerun"]
        added = timer.seconds["added"]
        session = load_session(root / "waiting" / "session.json")
        finding = session.findings[-1]
        decided = first.post(
            f"/sessions/{started['chat_id']}/findings/{finding.id}/disposition",
            json={"decision": "rejected", "note": "FICT engineer decision"},
        )
        assert decided.status_code == 200, decided.text

    with restarted_app(root, settings()) as fresh:
        rerun_s, _ = timed_post(
            fresh, body(root / "waiting", send_when_checked=False, recheck=True)
        )
    rerun = load_session(root / "waiting" / "session.json")

    print(
        f"\n{PERF_GROUPS} groups: ticked start {ticked_s:.2f} s (pre-run {shared:.2f} s); "
        f"unticked start {waiting_s:.2f} s (pre-run {unticked_prerun:.2f} s, cache, "
        f"finalization and render {added:.2f} s); re-run with a carry {rerun_s:.2f} s"
    )
    carried = next(f for f in rerun.findings if f.disposition is not None)
    assert carried.disposition.decision == "rejected"
    assert rerun.model_status is not None
    assert str(rerun.model_status.rechecked_from) == str(session.session_id)
    assert added < ADDED_WORK_SHARE * unticked_prerun
