"""Regeneration seeds runtime inputs and rejects structural drift without rewriting output."""

from __future__ import annotations

import importlib
import json
import subprocess
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import events, runner
from swreview.benchmark.replay import TurnPlan
from swreview.tools import context, registry
from tests.support import replay
from tests.support.mechanical import load_generator
from tests.unit.test_chat_server import call

START = "2026-10-12T12:00:00+00:00"
END = "2026-10-12T12:00:03+00:00"
IDENTITY = "e5b72d6b-c68c-44d3-9fde-86c1598f7f2e"


def module() -> Any:
    return importlib.import_module("tests.support.replay_inputs")


def baseline_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "FICT-baseline"
    folder.mkdir(parents=True)
    session = {"session_id": IDENTITY, "started_at": START, "steps": [{"elapsed_s": 0.125}]}
    rows = [
        {"at": f"2026-10-12T12:00:0{index}+00:00", "type": kind, "body": body}
        for index, (kind, body) in enumerate(
            [
                ("session.started", {}),
                ("text.done", {}),
                ("usage", {}),
                ("session.ended", {"ended_at": END}),
            ]
        )
    ]
    (folder / "session.json").write_bytes(json.dumps(session).encode())
    (folder / "events.jsonl").write_bytes(
        b"\r\n".join(json.dumps(row).encode() for row in rows) + b"\r\n"
    )
    return folder


def consume(*args: Any, change: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """A controlled generator pass consumes the actual patched producer seams."""
    counts = {
        "uuid": 1,
        "start": 1,
        "event": 4 if kwargs.get("usages") is not None else 3,
        "end": 1,
        "perf": 2,
    }
    if change is not None:
        kind, delta = change.split(":")
        counts[kind] += int(delta)
    return {
        "uuid": [str(context.uuid4()) for _ in range(counts["uuid"])],
        "start": [context.datetime.now(UTC).isoformat() for _ in range(counts["start"])],
        "events": [events.utc_now().isoformat() for _ in range(counts["event"])],
        "ends": [runner.datetime.now(UTC).isoformat() for _ in range(counts["end"])],
        "perf": [registry.perf_counter() for _ in range(counts["perf"])],
    }


def test_each_generator_pass_resets_and_writing_uses_every_recorded_event_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    support = module()
    folder = baseline_folder(tmp_path)
    before = replay.folder_hashes(folder)
    monkeypatch.setattr(replay, "play_review", consume)
    inputs = support.ReplayBaseline.from_folder(folder)
    for _ in range(2):
        with support.seed_replay_inputs(inputs):
            first = replay.play_review(None, None, [TurnPlan()])
            second = replay.play_review(None, None, [TurnPlan()], usages={(0, 0): object()})
        assert first["events"] == [START] * 3
        assert second["events"] == [f"2026-10-12T12:00:0{index}+00:00" for index in range(4)]
        for result in (first, second):
            assert result["uuid"] == [IDENTITY]
            assert result["start"] == [START]
            assert result["ends"] == [END]
            assert result["perf"] == [0.0, 0.125]
    assert replay.folder_hashes(folder) == before


def test_a_supplied_empty_usage_mapping_is_a_writing_pass_not_a_learning_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    support = module()
    inputs = support.ReplayBaseline.from_folder(baseline_folder(tmp_path))
    monkeypatch.setattr(replay, "play_review", consume)
    with support.seed_replay_inputs(inputs):
        replay.play_review(None, None, [TurnPlan()])
        written = replay.play_review(None, None, [TurnPlan()], usages={})
    assert written["events"] == [f"2026-10-12T12:00:0{n}+00:00" for n in range(4)]


@pytest.mark.parametrize("kind", ["uuid", "start", "event", "end", "perf"])
@pytest.mark.parametrize("delta", [-1, 1])
@pytest.mark.parametrize("writing", [False, True])
def test_extra_or_missing_runtime_consumption_is_refused_and_seams_are_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, delta: int, writing: bool
) -> None:
    support = module()
    inputs = support.ReplayBaseline.from_folder(baseline_folder(tmp_path))
    before = (
        context.uuid4,
        context.datetime,
        runner.datetime,
        events.utc_now,
        registry.perf_counter,
    )
    monkeypatch.setattr(
        replay, "play_review", lambda *a, **k: consume(*a, change=f"{kind}:{delta}", **k)
    )
    with pytest.raises(AssertionError, match=kind):
        with support.seed_replay_inputs(inputs):
            replay.play_review(
                None, None, [TurnPlan()], **({"usages": {0: object()}} if writing else {})
            )
    assert (
        context.uuid4,
        context.datetime,
        runner.datetime,
        events.utc_now,
        registry.perf_counter,
    ) == before


def test_original_failure_is_not_replaced_by_an_underconsumption_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    support = module()
    inputs = support.ReplayBaseline.from_folder(baseline_folder(tmp_path))

    def refused(*args: Any, **kwargs: Any) -> Any:
        raise OSError("FICT-original-generator-failure")

    monkeypatch.setattr(replay, "play_review", refused)
    with pytest.raises(OSError, match="FICT-original-generator-failure"):
        with support.seed_replay_inputs(inputs):
            replay.play_review(None, None, [TurnPlan()])
    assert replay.play_review is refused


@pytest.mark.parametrize("kind", ["uuid", "start", "event", "end", "perf"])
def test_a_producer_catching_an_overflow_cannot_hide_it_from_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    support = module()
    inputs = support.ReplayBaseline.from_folder(baseline_folder(tmp_path))

    def caught(*args: Any, **kwargs: Any) -> Any:
        result = consume(*args, **kwargs)
        calls = {
            "uuid": context.uuid4,
            "start": context.datetime.now,
            "event": events.utc_now,
            "end": runner.datetime.now,
            "perf": registry.perf_counter,
        }
        try:
            calls[kind]()
        except AssertionError:
            pass
        return result

    monkeypatch.setattr(replay, "play_review", caught)
    with pytest.raises(AssertionError, match=kind):
        with support.seed_replay_inputs(inputs):
            replay.play_review(None, None, [TurnPlan()])
            replay.play_review(None, None, [TurnPlan()], usages={0: object()})


@pytest.mark.usefixtures("vocabulary")
def test_real_two_pass_recording_reproduces_raw_bytes_and_keeps_changed_stable_content(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    support = module()
    turns = [TurnPlan(rounds=((call("get_package_summary"),),), text="FICT-stable-answer")]
    baseline = replay.record_scripted_review(tmp_path / "FICT-original", tmp_package_dir, turns)
    inputs = support.ReplayBaseline.from_folder(baseline)
    expected = replay.folder_hashes(baseline)
    for name in ("FICT-first", "FICT-second"):
        with support.seed_replay_inputs(inputs):
            output = replay.record_scripted_review(tmp_path / name, tmp_package_dir, turns)
        assert replay.folder_hashes(output) == expected
    changed = [TurnPlan(rounds=turns[0].rounds, text="FICT-changed-answer")]
    with support.seed_replay_inputs(inputs):
        output = replay.record_scripted_review(tmp_path / "FICT-changed", tmp_package_dir, changed)
    assert replay.folder_hashes(output) != expected
    assert b"FICT-changed-answer" in (output / "events.jsonl").read_bytes()
    assert b"FICT-stable-answer" in (baseline / "events.jsonl").read_bytes()
    difference = subprocess.run(
        [
            "git",
            "diff",
            "--no-index",
            "--quiet",
            str(baseline / "events.jsonl"),
            str(output / "events.jsonl"),
        ],
        check=False,
        capture_output=True,
    )
    assert difference.returncode == 1, difference.stderr.decode(errors="replace")


def verifier() -> Any:
    return load_generator(Path(__file__).parents[1] / "fixtures/replay/verify_regeneration.py")


@pytest.mark.parametrize(
    "passes", [[], [False], [False, True, True], [True, False], [False, False], [True, True]]
)
def test_a_missing_extra_or_reordered_generator_pass_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, passes: list[bool]
) -> None:
    support = module()
    inputs = support.ReplayBaseline.from_folder(baseline_folder(tmp_path))
    monkeypatch.setattr(replay, "play_review", consume)
    with pytest.raises(AssertionError, match="passes"):
        with support.seed_replay_inputs(inputs):
            for writing in passes:
                replay.play_review(
                    None, None, [TurnPlan()], **({"usages": {0: object()}} if writing else {})
                )


def test_verification_skips_before_generating_when_the_owner_mapping_is_absent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    driver = verifier()

    def absent(name: str) -> Path:
        pytest.skip("FICT-private-mapping-path")

    monkeypatch.setattr(driver, "recording_folder", absent)
    monkeypatch.setattr(driver, "load_generator", lambda p: pytest.fail("generator must not load"))
    assert driver.main([]) == 0
    output = capsys.readouterr()
    assert "skip" in output.out.lower()
    assert "FICT-private" not in output.out + output.err


def test_verification_runs_the_unchanged_generator_arguments_and_keeps_logs_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    driver = verifier()
    root = tmp_path / "reviewer"
    fixture_root = root / "tests/fixtures/replay"
    for name in driver.RECORDING_NAMES:
        folder = fixture_root / name
        folder.mkdir(parents=True)
        fixture = baseline_folder(tmp_path / f"FICT-{name}")
        for path in fixture.iterdir():
            (folder / path.name).write_bytes(path.read_bytes())
    monkeypatch.setattr(driver, "REVIEWER", root)
    monkeypatch.setattr(driver, "recording_folder", lambda n: tmp_path / f"FICT-owner-{n}")
    captured: list[list[str]] = []

    class Generator:
        def main(self, argv: list[str]) -> int:
            captured.append(argv)
            print("FICT-private-generator-output")
            replay.play_review(None, None, [TurnPlan()])
            replay.play_review(None, None, [TurnPlan()], usages={0: object()})
            return 0

    monkeypatch.setattr(driver, "load_generator", lambda p: Generator())
    monkeypatch.setattr(replay, "play_review", consume)
    assert driver.main([]) == 0
    assert captured == [
        ["--recorded", str(tmp_path / f"FICT-owner-{n}"), "--name", n]
        + (["--groups", "113"] if n == "big-assembly" else [])
        for n in driver.RECORDING_NAMES
    ]
    printed = capsys.readouterr()
    assert "FICT-private" not in printed.out + printed.err


def test_verification_refuses_a_seed_failure_after_the_generator_returned_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    driver = verifier()
    monkeypatch.setattr(driver, "RECORDING_NAMES", ("big-assembly",))
    monkeypatch.setattr(driver, "recording_folder", lambda n: tmp_path / "FICT-owner")
    monkeypatch.setattr(driver.ReplayBaseline, "from_folder", lambda p: object())

    class Generator:
        def main(self, args: list[str]) -> int:
            return 0

    @contextmanager
    def missing_inputs(baseline: Any) -> Any:
        yield
        raise AssertionError("FICT-private-missing-clock")

    monkeypatch.setattr(driver, "load_generator", lambda p: Generator())
    monkeypatch.setattr(driver, "seed_replay_inputs", missing_inputs)
    assert driver.main([]) == 1
    printed = capsys.readouterr()
    assert "refused" in printed.out
    assert "FICT-private" not in printed.out + printed.err


def test_a_generator_system_exit_is_private_and_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    driver = verifier()
    monkeypatch.setattr(driver, "RECORDING_NAMES", ("big-assembly",))
    monkeypatch.setattr(driver, "recording_folder", lambda n: tmp_path / "FICT-owner")
    monkeypatch.setattr(driver.ReplayBaseline, "from_folder", lambda p: object())

    class Generator:
        def main(self, args: list[str]) -> int:
            raise SystemExit("FICT-private-owner-folder")

    @contextmanager
    def unchanged(baseline: Any) -> Any:
        yield

    monkeypatch.setattr(driver, "load_generator", lambda p: Generator())
    monkeypatch.setattr(driver, "seed_replay_inputs", unchanged)
    assert driver.main([]) == 1
    printed = capsys.readouterr()
    assert "FICT-private" not in printed.out + printed.err
