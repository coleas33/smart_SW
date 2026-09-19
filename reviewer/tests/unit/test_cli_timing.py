"""`swreview timing <run_dir>` (T011): the four human inputs against any run folder.

`benchmark time` resolves a layout only the benchmark harness produces, so until this
command landed no real run - a pane review, a command-line review, an RMS check, a
standards check - could record a baseline at all, and every report printed "Net saved
minutes: unknown" (spec User Story 1).

What this module is responsible for, from `contracts/timing.md` section 2: the four
options, the derived net that is never an input, the re-render that keeps the package's
component names and a standards folder's verdict header, and the three refusals - each
naming what was wrong, and each leaving the folder exactly as it was.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from swreview.report.session import load_session
from tests.unit.test_cli import invoke, payload

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "attention"
REVIEW_FOLDER = FIXTURES / "review-folder"
CHECK_FOLDER = FIXTURES / "check-folder"

PLACEHOLDER = "_The evidence package was not supplied to the renderer._"
NAMED_COMPONENT = "cmp:0003 (cover-assy-1/housing-1)"

STANDARDS_VERDICT: dict[str, Any] = {
    "state": "ready",
    "counts": {
        "error": 0,
        "warning": 1,
        "checked": 14,
        "skipped": 1,
        "unresolved": 0,
        "out_of_scope": 1,
    },
    "waived": 0,
    "unresolved_check_ids": [],
    "notes": ["no drawing graded"],
}
"""A `verdict_json` block as `check.json` records it, written out rather than computed, so
this module reads the header off the folder the way the command does."""


@pytest.fixture
def review_dir(tmp_path: Path) -> Path:
    target = tmp_path / "20260918-215755-review"
    shutil.copytree(REVIEW_FOLDER, target)
    return target


@pytest.fixture
def standards_dir(tmp_path: Path) -> Path:
    """A check folder whose record names the standards family and carries a verdict."""
    target = tmp_path / "20260918-220300-standards"
    shutil.copytree(CHECK_FOLDER, target)
    record = json.loads((target / "check.json").read_text(encoding="utf-8"))
    record["family"] = "standards"
    record["verdict"] = STANDARDS_VERDICT
    (target / "check.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return target


def record(run_dir: Path, *options: str) -> Any:
    return invoke("timing", str(run_dir), *options)


def four(run_dir: Path, *extra: str) -> Any:
    """The scenario-1 recording: baseline 45, supervision 6, verification 9, false alarms 2."""
    return record(
        run_dir,
        "--baseline",
        "45",
        "--supervision",
        "6",
        "--verification",
        "9",
        "--false-alarms",
        "2",
        *extra,
    )


def files_in(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


# --- 1. the recording --------------------------------------------------------------


def test_the_four_inputs_reach_the_session_and_the_net_is_derived(review_dir: Path) -> None:
    body = payload(four(review_dir, "--json"))

    assert body["run_dir"] == str(review_dir.resolve())
    assert body["session_file"] == str(review_dir.resolve() / "session.json")
    assert body["report_file"] == str(review_dir.resolve() / "report.md")
    assert body["timing"] == {
        "baseline_minutes": 45.0,
        "assisted_supervision_minutes": 6.0,
        "assisted_verification_minutes": 9.0,
        "false_alarm_handling_minutes": 2.0,
        "unattended_runtime_minutes": body["timing"]["unattended_runtime_minutes"],
        "net_saved_minutes": 28.0,
    }
    timing = load_session(review_dir / "session.json").timing
    assert timing.baseline_minutes == 45.0
    assert timing.net_saved_minutes == 28.0


def test_the_lines_name_the_four_values_and_the_net(review_dir: Path) -> None:
    result = four(review_dir)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "net saved: 28.0" in result.stdout
    assert "baseline 45.0" in result.stdout


def test_there_is_no_way_to_supply_the_net(review_dir: Path) -> None:
    """FR-004: the one number the pilot must never type is not an option."""
    before = files_in(review_dir)

    result = record(review_dir, "--net", "999")

    assert result.exit_code == 2
    assert files_in(review_dir) == before


def test_an_omitted_input_keeps_the_value_already_recorded(review_dir: Path) -> None:
    four(review_dir)

    body = payload(record(review_dir, "--supervision", "7", "--json"))

    assert body["timing"]["baseline_minutes"] == 45.0
    assert body["timing"]["assisted_supervision_minutes"] == 7.0
    assert body["timing"]["net_saved_minutes"] == 27.0


def test_recording_twice_replaces_the_earlier_values(review_dir: Path) -> None:
    """Acceptance scenario 5: the new values are not silently merged with the old."""
    four(review_dir)

    body = payload(record(review_dir, "--baseline", "60", "--json"))

    assert body["timing"]["baseline_minutes"] == 60.0
    assert body["timing"]["net_saved_minutes"] == 43.0


# --- 2. the re-render --------------------------------------------------------------


def test_the_report_is_re_rendered_with_the_net_and_the_package(review_dir: Path) -> None:
    four(review_dir)

    report = (review_dir / "report.md").read_text(encoding="utf-8")
    assert "- Net saved minutes: 28.0" in report
    assert NAMED_COMPONENT in report
    assert PLACEHOLDER not in report


def test_a_standards_check_folder_keeps_its_verdict_header(standards_dir: Path) -> None:
    """The defect a second lossy re-render would have doubled (research R2.7)."""
    four(standards_dir)

    report = (standards_dir / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# Standards Check: ")
    assert "- Verdict: ready" in report
    assert "- Notes: no drawing graded" in report
    assert "- Net saved minutes: 28.0" in report


def test_an_rms_check_folder_gets_no_header_and_is_still_timed(tmp_path: Path) -> None:
    run_dir = tmp_path / "20260918-220300-rms"
    shutil.copytree(CHECK_FOLDER, run_dir)

    four(run_dir)

    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# Design Review Report")
    assert "- Net saved minutes: 28.0" in report


# --- 3. the three refusals ---------------------------------------------------------


@pytest.mark.parametrize(
    ("option", "field"),
    [
        ("--baseline", "baseline_minutes"),
        ("--supervision", "assisted_supervision_minutes"),
        ("--verification", "assisted_verification_minutes"),
        ("--false-alarms", "false_alarm_handling_minutes"),
    ],
)
def test_a_negative_input_exits_1_naming_the_field_and_writes_nothing(
    review_dir: Path, option: str, field: str
) -> None:
    four(review_dir)
    before = files_in(review_dir)

    result = record(review_dir, option, "-1")

    assert result.exit_code == 1, result.stdout + result.stderr
    assert field in result.stderr
    assert files_in(review_dir) == before


def test_a_folder_with_no_session_exits_1_naming_the_path(tmp_path: Path) -> None:
    empty = tmp_path / "not-a-run"
    empty.mkdir()

    result = record(empty)

    assert result.exit_code == 1
    assert "session.json" in result.stderr
    assert list(empty.iterdir()) == []


def test_a_benchmark_run_root_names_the_command_for_it(tmp_path: Path) -> None:
    run_root = tmp_path / "20260918-benchmark"
    shutil.copytree(REVIEW_FOLDER, run_root / "pkg-1")
    before = files_in(run_root / "pkg-1")

    result = record(run_root, "--baseline", "45")

    assert result.exit_code == 1
    assert "benchmark time" in result.stderr
    assert files_in(run_root / "pkg-1") == before
