"""T023: the replay delegates to the runner's one request-prefix renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
from swreview.agent.providers.fake import FakeProvider
from swreview.benchmark import replay


def test_the_runner_names_the_request_prefix() -> None:
    assert callable(runner.request_prefix)


def test_the_replay_passes_the_real_runs_prefix_inputs_to_the_shared_renderer(
    tmp_package_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runner.start_review(
        tmp_package_dir,
        tmp_path / "out",
        provider=FakeProvider(script=(), model="fake-1"),
        effort="high",
    )
    calls: list[tuple[Any, ...]] = []

    def shared(*args: Any) -> str:
        calls.append(args)
        return "FICT-shared-renderer"

    monkeypatch.setattr(runner, "request_prefix", shared)
    try:
        assert replay._prefix(run) == "FICT-shared-renderer"
        assert calls == [(run.system, run.tools, run.opening_message)]
    finally:
        run.close()
