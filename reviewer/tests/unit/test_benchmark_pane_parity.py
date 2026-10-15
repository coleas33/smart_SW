"""A `--pane-defaults` benchmark attempt starts its review as the pane does (T049).

SC-003, the parity slice's gate (`specs/014-design-review-eval/contracts/benchmark-run.md` 5.1
and 15; RUN-15; FR-012; US2-1). Two spies capture what `start_review` receives, each patched where
its caller looks the name up:

- `swreview.chat.server.start_review`, the name the chat server binds at import, under its
  `_start_review` (as `test_chat_server.py` patches it);
- `swreview.cli.start_review`, the name `_review_fn` looks up, which a `benchmark run --provider
  fake --pane-defaults --standards-profile <a copy of the example profile>` review calls before
  playing it through `drive_review` (retargeted from `swreview.agent.runner.start_review`, which
  the review reached through `run_review` in the parity slice, by T101).

Over the same package, with the same `--model` and `--effort`, the two calls differ only in section
5.1's transport rows; every other `start_review` argument is classified as compared, so one added
later fails the test until it is classified. The two sessions' levers, model view, explanations
and provider facts less the key's source are equal. The benchmark reviews through `_review_fn`,
which starts the review with `start_review` and plays it through `drive_review` (T101). The pane
and benchmark share the stoppable tool wrapper and the replay's stopped close-out (T189).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

import swreview.chat.server as chat_server
from swreview import cli
from swreview.agent import runner as agent_runner
from swreview.agent.events import event_stream, replay_events
from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import ScriptedToolCall
from swreview.agent.runner import ReviewRun, start_review
from swreview.agent.settings import pane_defaults
from swreview.benchmark.replay import TurnPlan, play_review
from swreview.ir.loader import save_package
from swreview.report.session import ReviewSession, load_session
from tests.support.packages import build_package
from tests.unit.test_chat_server import MODEL, ORIGIN, TOKEN, ProviderControl, settle, start_session
from tests.unit.test_run_provenance import example_profile_copy

EFFORT = "high"

TRANSPORT = frozenset(
    {
        "provider",
        "package_dir",
        "out_dir",
        "key_source",
        "retry_of",
        "bridge",
        "pipe_name",
        "bridge_secret",
        "bridge_factory",
        "callbacks",
        "redact",
    }
)
"""Section 5.1's transport rows: how a review reaches its adapter, its folders, its bridge and its
listeners, never what it reviews with."""

COMPARED = frozenset(
    {
        "send_when_checked",
        "earlier",
        "model",
        "effort",
        "efficiency",
        "model_view",
        "explain_findings",
        "standards_profile",
        "engineering_context",
        "max_steps",
        "previous_session",
        "fail_tool",
    }
)
"""Every other `start_review` argument: what the review runs with, equal on both surfaces when the
same values are typed (`previous_session` and `fail_tool` at their defaults on both)."""

SIGNATURE = inspect.signature(start_review)


def recorder(calls: list[dict[str, Any]]) -> Any:
    """A stand-in for `start_review` that records every argument, defaults applied, by name."""

    def recording_start_review(*args: Any, **kwargs: Any) -> Any:
        bound = SIGNATURE.bind(*args, **kwargs)
        bound.apply_defaults()
        calls.append(dict(bound.arguments))
        return start_review(*args, **kwargs)

    return recording_start_review


def what_it_reviews_with(call: dict[str, Any]) -> dict[str, Any]:
    """A call's compared arguments; the profile as a path, which the pane relays as text."""
    compared = {name: value for name, value in call.items() if name in COMPARED}
    if compared["standards_profile"] is not None:
        compared["standards_profile"] = Path(compared["standards_profile"])
    return compared


def settings_of(session: ReviewSession) -> dict[str, Any]:
    """What the two sessions must agree on: the levers, the model view, the explanations, and the
    provider facts less the key's source."""
    assert session.provider_info is not None
    return {
        "efficiency": session.efficiency,
        "model_view": session.model_view,
        "explanations_enabled": session.explanations_enabled,
        "provider_info": session.provider_info.model_dump(exclude={"key_source"}),
    }


def test_a_pane_defaults_attempt_starts_reviews_as_the_pane_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert set(SIGNATURE.parameters) == TRANSPORT | COMPARED, (
        "classify every start_review argument as transport or compared"
    )
    assert not TRANSPORT & COMPARED
    profile = example_profile_copy(tmp_path / "profiles")
    pane_calls: list[dict[str, Any]] = []
    benchmark_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(chat_server, "start_review", recorder(pane_calls))
    monkeypatch.setattr(cli, "start_review", recorder(benchmark_calls))

    run_root = tmp_path / "pane-runs"
    pane_run = run_root / "20261007-120000-cover"
    save_package(build_package(), pane_run)
    app = chat_server.create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=ProviderControl().factory,
        list_models=lambda _: [],
    )
    headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    with TestClient(app, headers=headers) as client:
        chat = start_session(
            client, pane_run, model=MODEL, effort=EFFORT, standards_profile=str(profile)
        )
        settle(client, chat["chat_id"])

    package_dir = tmp_path / "benchmark-package"
    save_package(build_package(), package_dir)
    set_path = tmp_path / "sets" / "parity.json"
    set_path.parent.mkdir()
    set_path.write_text(
        json.dumps(
            {
                "name": "parity",
                "packages": [{"package_id": "cover", "path": str(package_dir), "held_out": True}],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "benchmark-run"
    result = CliRunner().invoke(
        cli.app,
        [
            "benchmark",
            "run",
            "--set",
            str(set_path),
            "--out",
            str(out),
            "--provider",
            "fake",
            "--model",
            MODEL,
            "--effort",
            EFFORT,
            "--pane-defaults",
            "--standards-profile",
            str(profile),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    [pane_call] = pane_calls
    [benchmark_call] = benchmark_calls
    assert what_it_reviews_with(benchmark_call) == what_it_reviews_with(pane_call)
    assert pane_call["send_when_checked"] is True and benchmark_call["send_when_checked"] is True
    assert pane_call["earlier"] is None and benchmark_call["earlier"] is None

    pane_session = load_session(pane_run / "session.json")
    benchmark_session = load_session(out / "cover" / "session.json")
    assert settings_of(benchmark_session) == settings_of(pane_session)
    assert benchmark_session.efficiency == pane_defaults(ProviderName.FAKE).efficiency
    assert benchmark_session.explanations_enabled is True


def test_benchmark_and_pane_attempts_wrap_tools_in_the_one_stoppable_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T189, RF-3 and RF-33: both surfaces wrap, and replay uses the shared close-out."""
    pane_runs: list[ReviewRun] = []
    benchmark_runs: list[ReviewRun] = []

    def capture(runs: list[ReviewRun]) -> Any:
        def capturing_start_review(*args: Any, **kwargs: Any) -> ReviewRun:
            run = start_review(*args, **kwargs)
            runs.append(run)
            return run

        return capturing_start_review

    monkeypatch.setattr(chat_server, "start_review", capture(pane_runs))
    monkeypatch.setattr(cli, "start_review", capture(benchmark_runs))
    run_root = tmp_path / "pane-runs"
    pane_folder = run_root / "20261015-120000-cover"
    save_package(build_package(), pane_folder)
    app = chat_server.create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=ProviderControl().factory,
        list_models=lambda _: [],
    )
    headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    with TestClient(app, headers=headers) as client:
        chat = start_session(client, pane_folder)
        settle(client, chat["chat_id"])
    [pane_run] = pane_runs
    assert isinstance(pane_run.tools, agent_runner.StoppableTools)

    stopped: list[ReviewRun] = []
    close_out: list[tuple[ReviewRun, str]] = []
    end_stopped = ReviewRun.end_stopped
    cancel_presentation = ReviewRun.cancel_presentation
    finalize = ReviewRun.finalize

    def ending(run: ReviewRun) -> Any:
        stopped.append(run)
        return end_stopped(run)

    def cancelling(run: ReviewRun) -> None:
        close_out.append((run, "cancel_presentation"))
        cancel_presentation(run)

    def finalizing(run: ReviewRun) -> Any:
        close_out.append((run, "finalize"))
        return finalize(run)

    monkeypatch.setattr(ReviewRun, "end_stopped", ending)
    monkeypatch.setattr(ReviewRun, "cancel_presentation", cancelling)
    monkeypatch.setattr(ReviewRun, "finalize", finalizing)
    package_dir = tmp_path / "package"
    save_package(build_package(), package_dir)
    replay_folder = tmp_path / "replay"
    play_review(
        package_dir,
        replay_folder,
        [
            TurnPlan(
                rounds=((ScriptedToolCall("get_package_summary"),),),
                end_reason="stopped",
                stop_at_last_call=True,
            )
        ],
    )
    [replayed_run] = stopped
    assert [action for run, action in close_out if run is replayed_run] == [
        "cancel_presentation",
        "finalize",
    ]
    assert [
        event.body
        for event in replay_events(event_stream(replay_folder))
        if event.type == "turn.ended"
    ] == [{"reason": "stopped"}]

    set_path = tmp_path / "set.json"
    set_path.write_text(
        json.dumps(
            {
                "name": "stop-parity",
                "packages": [{"package_id": "cover", "path": str(package_dir)}],
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli.app,
        [
            "benchmark",
            "run",
            "--set",
            str(set_path),
            "--out",
            str(tmp_path / "benchmark"),
            "--provider",
            "fake",
            "--model",
            MODEL,
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    [benchmark_run] = benchmark_runs
    assert isinstance(benchmark_run.tools, agent_runner.StoppableTools)
