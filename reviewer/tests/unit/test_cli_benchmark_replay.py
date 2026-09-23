"""`swreview benchmark replay` (008 T024, `contracts/replay.md` §1 and §7, `contracts/cli.md`).

A thin shell over `benchmark/replay.replay`: the human output prints the round table, the
three totals, the difference, the estimated-round count and the tokenizer; `--json` prints the
`ReplayReport` and nothing else; a folder that is not a review is one line on stderr and exit
1; an unknown lever is a usage error, exit 2. It needs no key and no network: with every route
to the network and the provider factory patched to raise, it still prices the recording.
"""

from __future__ import annotations

import json
import re
import socket
from pathlib import Path
from typing import Any

import pytest

from swreview import cli
from swreview.agent.providers.fake import ScriptedToolCall
from swreview.benchmark.replay import ReplayReport, TurnPlan
from swreview.ir.loader import save_package
from tests.support.prerun import prerun_package, standards_prerun_package
from tests.support.replay import record_scripted_review
from tests.unit.test_cli import invoke, payload

pytestmark = pytest.mark.usefixtures("vocabulary")

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PROFILE = REPO_ROOT / "config" / "standards.example.yaml"
SUMMARY = ScriptedToolCall("get_package_summary")
COMPONENTS = ScriptedToolCall("list_components", {"parent_id": None, "include_suppressed": True})
STANDARDS = ScriptedToolCall("check_standards")
ROUND_LINE = re.compile(r"^\s*\d+\s+\d+\s+[\d,]+\s+[\d,]+\s+[\d,]+")


@pytest.fixture
def run(tmp_path: Path) -> Path:
    package_dir = tmp_path / "package"
    save_package(prerun_package(), package_dir)
    return record_scripted_review(
        tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,), (COMPONENTS,)), text="Ok.")]
    )


def test_the_human_output_has_the_table_the_totals_and_the_tokenizer(run: Path) -> None:
    result = invoke("benchmark", "replay", str(run))

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert any("tokens counted with o200k_base" in line for line in lines)
    assert sum(1 for line in lines if ROUND_LINE.match(line)) == 3
    totals = next(line for line in lines if line.startswith("totals:"))
    for word in ("recorded", "as recorded", "requested", "difference"):
        assert word in totals
    assert any(line.startswith("rounds:") and "estimated" in line for line in lines)
    assert any(line.startswith("findings:") for line in lines)


def test_json_validates_against_the_report_and_prints_nothing_else(run: Path) -> None:
    result = invoke("benchmark", "replay", str(run), "--json")

    parsed = payload(result)
    report = ReplayReport.model_validate(parsed)
    assert report.tokenizer == "o200k_base"
    assert len(report.rounds) == 3
    assert parsed["rounds"][0]["calls"][0]["class"] == "reproduced"


def test_a_refusal_is_one_stderr_line_and_exit_1(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    result = invoke("benchmark", "replay", str(empty))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert len(result.stderr.strip().splitlines()) == 1


def test_a_check_folder_is_refused_naming_the_event_log(tmp_path: Path, run: Path) -> None:
    (run / "events.jsonl").unlink()

    result = invoke("benchmark", "replay", str(run))

    assert result.exit_code == 1
    assert "events.jsonl" in result.stderr


def test_no_network_and_no_provider_are_needed(run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the replay reached for the network or a provider")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(cli, "provider_factory", refuse)

    result = invoke("benchmark", "replay", str(run), "--json")

    assert result.exit_code == 0, result.output
    assert ReplayReport.model_validate(json.loads(result.stdout))


def test_a_lever_resolves_into_the_requested_settings(run: Path) -> None:
    result = invoke("benchmark", "replay", str(run), "--lever", "trim_tool_descriptions", "--json")

    report = ReplayReport.model_validate(payload(result))
    assert report.settings.requested.efficiency.trim_tool_descriptions is True
    assert report.settings.as_recorded.efficiency.trim_tool_descriptions is False


def test_an_unknown_lever_is_a_usage_error(run: Path) -> None:
    result = invoke("benchmark", "replay", str(run), "--lever", "no_such_lever")

    assert result.exit_code == 2


def test_the_standards_profile_reaches_both_passes(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    save_package(standards_prerun_package(), package_dir)
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((STANDARDS,),))],
        standards_profile=EXAMPLE_PROFILE,
    )

    graded = ReplayReport.model_validate(
        payload(
            invoke(
                "benchmark",
                "replay",
                str(run),
                "--standards-profile",
                str(EXAMPLE_PROFILE),
                "--json",
            )
        )
    )

    assert graded.rounds[0].calls[0].class_ == "reproduced"


def test_benchmark_lists_replay_in_its_help() -> None:
    result = invoke("benchmark", "--help")

    assert result.exit_code == 0
    assert "replay" in result.stdout
