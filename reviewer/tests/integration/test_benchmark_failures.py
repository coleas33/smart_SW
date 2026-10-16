"""Run, score and resume the fictional forced-failure set (T208; SC-007).

The scripted provider exercises the real CLI, tools, retry loop and attempt driver.
RF-26: this needs no native evidence package and has no integration marker.
94A: returned SAFETY stops run on the scripted provider; Gemini is deferred.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.providers import retry
from swreview.agent.providers.fake import (
    SYNTHETIC_USAGE,
    ScriptedRound,
    ScriptedToolCall,
    ScriptedTurn,
)
from swreview.benchmark.scorecard import read_scorecard
from swreview.ir.loader import save_package
from tests.support.answer_keys import write_key
from tests.support.scripted_answers import FIT, ask, turn
from tests.unit.test_benchmark_attempts import (
    DriverClock,
    TransientError,
    driver_events,
    driver_row,
    driver_status,
    install_driver_providers,
)
from tests.unit.test_benchmark_attempts import driver_clock as driver_clock
from tests.unit.test_benchmark_questions import PACKAGE, PIN_1, PLATE_1, PLATE_DOC, PLATE_HOLE

IDS = ("fict-error", "fict-silent", "fict-stopped")
FIT_QUESTION = ask(PIN_1, PLATE_HOLE, item=FIT)
RE_ASK = ask(PLATE_HOLE, item=FIT)
FORBIDDEN_HIT = ScriptedToolCall(
    "record_drawing_finding",
    {
        "document_id": PLATE_DOC,
        "sheet": "Sheet1",
        "observed": "The tapped hole is called out without a thread depth",
        "requirement": "A tapped hole callout states the usable thread depth",
        "source_refs": [{"document_id": PLATE_DOC, "sheet": "Sheet1"}],
        "status": "suspected",
        "recommended_action": "Add the tapped depth to the hole callout",
    },
)


def fictional_set(folder: Path) -> tuple[Path, Path]:
    """Each package has one defect, forbidden entry, question rule and scripted answer."""
    entries = []
    keys = folder / "keys"
    cases = folder / "cases"
    cases.mkdir()
    for package_id in IDS:
        package_dir = folder / "packages" / package_id
        save_package(PACKAGE, package_dir)
        case = cases / f"{package_id}.json"
        case.write_text(
            json.dumps({
                "case_file_version": 1,
                "package_id": package_id,
                "answers": [{
                    "id": "A-1", "item": FIT, "ids": [PLATE_1, PIN_1],
                    "answer": "press fit",
                }],
            }),
            encoding="utf-8",
        )
        write_key(
            keys,
            package_id,
            known_defects=[{"check": "rms.sketches.fully_defined", "component_ids": [PIN_1]}],
            forbidden=[{"checks": ["drawing.manufacturing_inputs"], "document_ids": [PLATE_DOC]}],
            question_counts=[{"item": FIT, "ids": [PLATE_1, PIN_1], "min": 1, "max": 1}],
        )
        entries.append({"package_id": package_id, "path": str(package_dir), "case_file": str(case)})
    path = folder / "set.json"
    path.write_text(json.dumps({"name": "fict-failures", "packages": entries}), encoding="utf-8")
    return path, keys


def snapshot(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in folder.rglob("*") if path.is_file()}


def test_failures_are_unscored_a_safety_stop_is_scored_and_only_failures_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_clock: DriverClock,
) -> None:
    set_file, keys = fictional_set(tmp_path)
    out = tmp_path / "run"
    sleeps: list[float] = []
    monkeypatch.setattr(retry, "sleep", sleeps.append)
    monkeypatch.setattr(retry, "uniform", lambda low, high: high / 2)
    monkeypatch.setattr(cli, "STREAM_ACTIVITY_WINDOW_S", 2)
    monkeypatch.setattr(cli, "STOP_GRACE_S", 2)
    real_run, real_resume = cli.run_benchmark, cli.resume_benchmark

    def run(*args: Any, **options: Any) -> Any:
        return real_run(
            *args, **options, clock=driver_clock, stream_activity_window_s=2, stop_grace_s=2,
        )

    def resume(*args: Any, **options: Any) -> Any:
        return real_resume(*args, **options, clock=driver_clock)

    monkeypatch.setattr(cli, "run_benchmark", run)
    monkeypatch.setattr(cli, "resume_benchmark", resume)

    class SilentHang(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            driver_clock.sleep(1000)
            return True

    built = install_driver_providers(
        monkeypatch,
        [
            [ScriptedTurn(text="", fails=TransientError("fict exhausted request"))],
            [ScriptedTurn(text="Unreached.", hang=SilentHang())],
            [
                turn(FIT_QUESTION, text="Which fit holds the pin?"),
                ScriptedTurn(
                    text="", rounds=(ScriptedRound((RE_ASK, FORBIDDEN_HIT), SYNTHETIC_USAGE),),
                    usage=None, stop_reason="SAFETY", end_reason="error",
                ),
            ],
        ],
        clock=driver_clock,
        sleep=driver_clock.sleep,
    )
    command = CliRunner()
    ran = command.invoke(cli.app, [
        "benchmark", "run", "--set", str(set_file), "--out", str(out),
        "--provider", "fake", "--package-time-limit", "1",
    ])
    assert ran.exit_code == 1, ran.stdout + ran.stderr
    assert len(built) == 3, ran.stdout + ran.stderr
    assert "fict-error: infrastructure provider_error" in ran.stdout
    assert "fict-silent: infrastructure abandoned" in ran.stdout
    assert "fict-stopped: behavioural provider_stop (SAFETY)" in ran.stdout
    assert f"swreview benchmark resume {out}" in ran.stdout + ran.stderr
    assert len(sleeps) == retry.BENCHMARK_RETRY.retries == 5

    scored = command.invoke(cli.app, ["benchmark", "score", str(out), "--answer-keys", str(keys)])
    assert scored.exit_code == 0, scored.stdout + scored.stderr
    scorecard = read_scorecard(out)
    payload = scorecard.model_dump(mode="json", by_alias=True)
    assert [(row["package_id"], row["kind"], row["class"], row["attempts"])
            for row in payload["unscored_packages"]] == [
        ("fict-error", "infrastructure", "provider_error", 1),
        ("fict-silent", "infrastructure", "abandoned", 1),
    ]
    assert [(row["package_id"], row["class"], row["retries"])
            for row in payload["failed_attempts"]] == [
        ("fict-error", "provider_error", 5), ("fict-silent", "abandoned", 0),
    ]
    for row in payload["unscored_packages"] + payload["failed_attempts"]:
        assert row["folder"] == f"attempts/{row['package_id']}/1"
        assert (out / row["folder"]).is_dir()
    [kept] = scorecard.per_package
    assert kept.package_id == "fict-stopped"
    assert payload["per_package"][0]["run_status"] == {
        "kind": "behavioural", "class": "provider_stop", "stop_reason": "SAFETY",
    }
    assert len(kept.re_asks) == 1 and kept.re_asks[0].outcome == "already_answered"
    assert kept.forbidden_hit_finding_ids == ["F-001"]
    assert kept.question_counts[0].count == 2
    aggregate = scorecard.aggregate
    assert (aggregate.packages, aggregate.missed_known_defects, aggregate.false_alarms) == (1, 1, 1)
    assert (aggregate.re_asks, aggregate.forbidden_hits) == (1, 1)
    assert aggregate.question_count_misses == 1
    assert aggregate.round_trips == kept.round_trips == 2
    for field in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"):
        assert getattr(aggregate, field) == getattr(kept.usage, field)
    assert scorecard.distribution == [kept.net_saved_minutes]

    original_status = driver_status(out)
    original_attempts = {package_id: snapshot(out / "attempts" / package_id / "1")
                         for package_id in IDS[:2]}
    stopped_files = snapshot(out / "fict-stopped")
    started: list[Path] = []
    real_start = cli.start_review

    def start(package_dir: Path, session_out_dir: Path, **options: Any) -> Any:
        started.append(Path(session_out_dir))
        assert Path(session_out_dir).is_dir()
        return real_start(package_dir, session_out_dir, **options)

    monkeypatch.setattr(cli, "start_review", start)
    resumed_providers = install_driver_providers(
        monkeypatch,
        [[turn(FIT_QUESTION), turn(text="Completed from the beginning.")] for _ in IDS[:2]],
        clock=driver_clock,
        sleep=driver_clock.sleep,
    )
    resumed = command.invoke(cli.app, ["benchmark", "resume", str(out)])
    assert resumed.exit_code == 0, resumed.stdout + resumed.stderr
    assert resumed.stdout.splitlines() == ["fict-error: completed", "fict-silent: completed"]
    assert len(resumed_providers) == 2
    assert [folder.relative_to(out).as_posix() for folder in started] == [
        "attempts/fict-error/2", "attempts/fict-silent/2",
    ]
    assert [provider._turn_index for provider in resumed_providers] == [2, 2]
    status = driver_status(out)
    for package_id in IDS[:2]:
        rows = status["packages"][package_id]["attempts"]
        assert len(rows) == 2 and rows[0] == original_status["packages"][package_id]["attempts"][0]
        assert snapshot(out / "attempts" / package_id / "1") == original_attempts[package_id]
        assert (rows[1]["attempt"], rows[1]["resumed"], rows[1]["folder"]) == (2, True, package_id)
        assert status["packages"][package_id]["kept_attempt"] == 2
        fresh = driver_events(out / package_id)
        previous = driver_events(out / "attempts" / package_id / "1")
        assert fresh[0].seq == 1
        assert fresh[0].body["session_id"] != previous[0].body["session_id"]
        assert driver_row(out, package_id)["kind"] == "completed"
    assert status["packages"]["fict-stopped"] == original_status["packages"]["fict-stopped"]
    assert snapshot(out / "fict-stopped") == stopped_files
