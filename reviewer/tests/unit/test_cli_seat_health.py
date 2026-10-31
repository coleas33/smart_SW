"""`swreview seat health`: the runbook's health checks a file can prove (004 T350; decision 166A).

`docs/workstation-runbook.md` section 6 lists seven checks after every start. The engineer runs this
command at the seat once SOLIDWORKS is up, and it settles every item a file can prove: `addin.log`
shows the four load checkpoints in order for the latest start, with no tool-service refusal and no
`.SLDDRW` line after it; a backend log newer than that start says the backend is healthy; the
standards profile is present with its version; `uv` is on PATH; `swreview-extract` is built; and
the checkout is clean on `main`. The pane's own checks stay manual, and the output says so.

Every log here is fictional (`tests/fixtures/seat/health/`, one folder per case); each checkout is
a throwaway git repository made in the test's temp folder, so no case reads this machine's
`%LOCALAPPDATA%\\SwReview` or this checkout's own state. The clock is set: five minutes after the
fixtures' latest start, as the runbook has the command run; and one SOLIDWORKS is running, begun
just before that start, unless a case says otherwise.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from swreview.seat import health as seat_health
from tests.unit.test_cli import invoke
from tests.unit.test_cli_profile_upgrade import PROFILE_A, as_version, write

LOGS = Path(__file__).resolve().parents[1] / "fixtures" / "seat" / "health"
EXTRACTOR = Path("extractor/SwReview.Extractor.Console/bin/x64/Release/net48/swreview-extract.exe")
EXAMPLE = Path("config/standards.example.yaml")
FICTIONAL_DRAWING = "made-up-bracket"
FICTIONAL_FOLDER = "fict-seat"
FICTIONAL_NAME = "Jane Fict"

CHECKS = ["add-in load", "tool service", "backend", "profile", "uv", "extractor", "checkout"]
LOG_CHECKS = {"add-in load", "tool service", "backend"}

LATEST_START = datetime(2026, 10, 31, 9, 15, 2, 123456, tzinfo=UTC)
"""The all-good log's latest `AssemblyRedirect installed.` (its last digit of 100 ns dropped)."""
LATEST_LOAD = datetime(2026, 10, 31, 9, 15, 4, tzinfo=UTC)
"""The all-good log's latest `Attached to SOLIDWORKS.`, two seconds after its latest start."""
SOLIDWORKS_BEGAN = datetime(2026, 10, 31, 9, 14, 50, tzinfo=UTC)
"""When the one SOLIDWORKS running began, twelve seconds before the add-in's start line."""


def at(monkeypatch: pytest.MonkeyPatch, when: datetime) -> None:
    monkeypatch.setattr(seat_health, "now", lambda: when)


def running(monkeypatch: pytest.MonkeyPatch, starts: list[datetime] | None) -> None:
    """The SOLIDWORKS processes running, by when each began; None when that cannot be read."""
    monkeypatch.setattr(seat_health, "solidworks_starts", lambda: starts)


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Five minutes after the latest load; a case that wants another time sets its own."""
    at(monkeypatch, LATEST_LOAD + timedelta(minutes=5))


@pytest.fixture(autouse=True)
def one_solidworks(monkeypatch: pytest.MonkeyPatch) -> None:
    """One SOLIDWORKS, begun just before the latest start; a case that wants another says so."""
    running(monkeypatch, [SOLIDWORKS_BEGAN])


@pytest.fixture(autouse=True)
def uv_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """`uv` is found, whatever this machine's PATH says; a case that wants it missing says so."""
    real = shutil.which

    def which(name: str, *args: Any, **kwargs: Any) -> str | None:
        return "fict-uv" if name == "uv" else real(name, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", which)


def logs_with(tmp_path: Path, *lines: str, case: str = "all-good") -> Path:
    """A copy of `case`'s logs with `lines` appended to its `addin.log`."""
    logs = tmp_path / "logs"
    shutil.copytree(LOGS / case, logs)
    with (logs / "addin.log").open("a", encoding="utf-8") as log:
        log.write("".join(f"{line}\n" for line in lines))
    return logs


def checkout(
    tmp_path: Path, *, branch: str = "main", built: bool = True, dirty: bool = False
) -> Path:
    """A throwaway git checkout with no commit: what is ignored is listed in `.git/info/exclude`,
    so the tree is clean until a case adds something to it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", branch, str(repo)], check=True)
    (repo / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (repo / ".git" / "info" / "exclude").write_text(
        "extractor/**/bin/\nconfig/\n", encoding="utf-8"
    )
    if built:
        (repo / EXTRACTOR).parent.mkdir(parents=True)
        (repo / EXTRACTOR).write_bytes(b"")
    if dirty:
        (repo / "stray.txt").write_text("a fictional stray file\n", encoding="utf-8")
    return repo


def health(
    case: str, repo: Path, *extra: str, profile: Path | None = PROFILE_A, logs: Path | None = None
) -> Any:
    args = ["seat", "health", "--logs", str(logs or LOGS / case), "--repo", str(repo)]
    if profile is not None:
        args += ["--profile", str(profile)]
    return invoke(*args, *extra)


def statuses(result: Any) -> dict[str, str]:
    report = json.loads(result.stdout)
    return {row["check"]: row["status"] for row in report["checks"]}


def reason(result: Any, check: str) -> str:
    report = json.loads(result.stdout)
    return next(row["reason"] for row in report["checks"] if row["check"] == check)


def failing(result: Any) -> set[str]:
    return {check for check, status in statuses(result).items() if status == "FAIL"}


# --- the all-good case ----------------------------------------------------------------------


def test_the_all_good_seat_passes_every_check_and_exits_0(tmp_path: Path) -> None:
    result = health("all-good", checkout(tmp_path), "--json")

    assert result.exit_code == 0, result.stdout
    assert list(statuses(result)) == CHECKS
    assert failing(result) == set()


def test_the_text_output_is_one_pass_or_fail_line_per_check_with_its_reason(
    tmp_path: Path,
) -> None:
    result = health("all-good", checkout(tmp_path))

    assert result.exit_code == 0, result.stdout
    lines = [line for line in result.stdout.splitlines() if line.startswith(("PASS ", "FAIL "))]
    assert [line.split(":")[0] for line in lines] == [f"PASS {check}" for check in CHECKS]
    assert all(line.split(":", 1)[1].strip() for line in lines)


def test_the_pane_checks_are_named_as_manual_in_both_outputs(tmp_path: Path) -> None:
    repo = checkout(tmp_path)
    text = health("all-good", repo).stdout
    manual = json.loads(health("all-good", repo, "--json").stdout)["manual"]

    assert "MANUAL" in text
    assert any("Tools > Add-ins" in item for item in manual)
    assert any("Backend ready" in item for item in manual)
    assert any("Ask tab" in item for item in manual)
    for item in manual:
        assert item in text


def test_the_pass_reason_names_the_latest_start_not_an_earlier_one(tmp_path: Path) -> None:
    result = health("all-good", checkout(tmp_path), "--json")

    assert "2026-10-31T09:15:02" in reason(result, "add-in load")
    assert "backend-20261031-091506.log" in reason(result, "backend")


def test_a_tool_service_line_before_the_latest_start_is_not_held_against_it(
    tmp_path: Path,
) -> None:
    """The all-good log carries a tool-service failure from the session before."""
    result = health("all-good", checkout(tmp_path), "--json")

    assert statuses(result)["tool service"] == "PASS"


# --- one fixture per failure ------------------------------------------------------------------


def test_out_of_order_checkpoints_fail_the_load_check(tmp_path: Path) -> None:
    result = health("out-of-order", checkout(tmp_path), "--json")

    assert result.exit_code == 1
    assert failing(result) == {"add-in load"}
    assert "order" in reason(result, "add-in load")


def test_a_tool_service_refusal_after_the_start_fails_and_names_the_drawing_not_its_path(
    tmp_path: Path,
) -> None:
    result = health("refusal-after-start", checkout(tmp_path), "--json")

    assert result.exit_code == 1
    assert failing(result) == {"tool service"}
    assert ".SLDDRW" in reason(result, "tool service")
    assert FICTIONAL_DRAWING not in result.stdout


def test_a_stale_backend_log_fails_the_backend_check(tmp_path: Path) -> None:
    result = health("stale-backend", checkout(tmp_path), "--json")

    assert result.exit_code == 1
    assert failing(result) == {"backend"}
    assert "since the latest load" in reason(result, "backend")


def test_a_missing_profile_fails_the_profile_check(tmp_path: Path) -> None:
    result = health("all-good", checkout(tmp_path), "--json", profile=tmp_path / "absent.yaml")

    assert result.exit_code == 1
    assert failing(result) == {"profile"}
    assert "--profile" in reason(result, "profile")


def test_a_dirty_tree_fails_the_checkout_check(tmp_path: Path) -> None:
    result = health("all-good", checkout(tmp_path, dirty=True), "--json")

    assert result.exit_code == 1
    assert failing(result) == {"checkout"}
    assert "1 changed or untracked" in reason(result, "checkout")
    assert "stray.txt" not in result.stdout


# --- the other ways each check fails ----------------------------------------------------------


def test_a_tool_service_line_with_no_drawing_also_fails(tmp_path: Path) -> None:
    logs = logs_with(
        tmp_path, "[2026-10-31T09:16:00.0000000+00:00] The SwReview tool service did not start."
    )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == {"tool service"}
    assert "2026-10-31T09:16:00" in reason(result, "tool service")


def test_a_line_naming_a_drawing_fails_even_when_it_is_not_the_tool_services(
    tmp_path: Path,
) -> None:
    logs = logs_with(
        tmp_path,
        "[2026-10-31T09:16:00.0000000+00:00] A fictional failure.",
        "   at a frame reading D:\\fict-seat\\made-up-bracket.slddrw",
    )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == {"tool service"}
    assert FICTIONAL_DRAWING not in result.stdout


# --- a line is one AddInLog wrote only when it begins with a time and its offset ----------------


@pytest.mark.parametrize("as_json", [False, True])
def test_a_continuation_line_that_begins_with_a_bracket_is_not_a_line_of_its_own(
    tmp_path: Path, as_json: bool
) -> None:
    """An exception's text in `addin.log` can begin a line with a bracket; it continues the line
    before it, and its bracketed text is never quoted as that line's time."""
    logs = logs_with(
        tmp_path, '["C:\\Users\\Jane Fict\\x.sldprt"] The SwReview tool service is fictional'
    )

    result = health("", checkout(tmp_path), *(["--json"] if as_json else []), logs=logs)

    assert result.exit_code == 0, result.stdout
    assert FICTIONAL_NAME not in result.stdout
    assert "x.sldprt" not in result.stdout


def test_a_drawing_on_a_continuation_line_that_begins_with_a_bracket_fails(tmp_path: Path) -> None:
    logs = logs_with(
        tmp_path, "[D:\\Users\\Jane Fict\\made-up-bracket.SLDDRW] was the active document"
    )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == {"tool service"}
    assert FICTIONAL_NAME not in result.stdout
    assert FICTIONAL_DRAWING not in result.stdout


def test_a_time_with_no_offset_is_not_a_line_the_add_in_wrote(tmp_path: Path) -> None:
    """`AddInLog` stamps every line `{0:O}`, which always carries the offset: a time without one
    cannot be ordered against the backend log's, and is not that file's."""
    logs = tmp_path / "logs"
    shutil.copytree(LOGS / "all-good", logs)
    text = (logs / "addin.log").read_text(encoding="utf-8")
    (logs / "addin.log").write_text(text.replace("+00:00]", "]"), encoding="utf-8")

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == LOG_CHECKS
    assert "AssemblyRedirect installed." in reason(result, "add-in load")


# --- the latest load is this start's, or the command says it is not ----------------------------


def test_a_start_that_wrote_no_lines_fails_the_three_log_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/addin-load-fix.md: a reverted check box, or a broken registration, loads nothing, so
    the start just made adds no line and yesterday's session is the latest the log holds."""
    at(monkeypatch, datetime(2026, 11, 1, 8, 30, tzinfo=UTC))

    result = health("all-good", checkout(tmp_path), "--json")

    assert result.exit_code == 1
    assert failing(result) == LOG_CHECKS
    for check in LOG_CHECKS:
        assert "23 h 14 min" in reason(result, check)
    assert "Tools > Add-ins" in reason(result, "add-in load")


@pytest.mark.parametrize(
    ("after", "status"),
    [(timedelta(hours=1, minutes=59), "PASS"), (timedelta(hours=2, minutes=1), "FAIL")],
    ids=["within two hours", "beyond two hours"],
)
def test_the_latest_load_may_be_at_most_two_hours_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after: timedelta, status: str
) -> None:
    at(monkeypatch, LATEST_LOAD + after)

    result = health("all-good", checkout(tmp_path), "--json")

    assert {check: statuses(result)[check] for check in LOG_CHECKS} == dict.fromkeys(
        LOG_CHECKS, status
    )


def test_a_restart_that_wrote_nothing_after_a_good_load_fails_the_three_log_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 2, F1: a good load at 09:15, then SOLIDWORKS closed and started again at
    09:20 with the add-in not loading (docs/addin-load-fix.md), which writes no line. The log's
    latest load is five minutes old, but it is the closed process's, not this one's."""
    restarted = datetime(2026, 10, 31, 9, 20, tzinfo=UTC)
    running(monkeypatch, [restarted])
    at(monkeypatch, restarted + timedelta(minutes=5))

    result = health("all-good", checkout(tmp_path), "--json")

    assert result.exit_code == 1
    assert failing(result) == LOG_CHECKS
    for check in LOG_CHECKS:
        assert "2026-10-31T09:20:00" in reason(result, check)
    assert "Tools > Add-ins" in reason(result, "add-in load")


@pytest.mark.parametrize(
    ("began", "status"),
    [
        (LATEST_START, "PASS"),
        (LATEST_START + timedelta(microseconds=1), "FAIL"),
    ],
    ids=["at the start line", "just after it"],
)
def test_the_latest_start_line_must_be_no_older_than_the_solidworks_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, began: datetime, status: str
) -> None:
    """The type initializer writes the start line inside the process, so this process's own start
    line is never older than the process."""
    running(monkeypatch, [began])

    result = health("all-good", checkout(tmp_path), "--json")

    assert {check: statuses(result)[check] for check in LOG_CHECKS} == dict.fromkeys(
        LOG_CHECKS, status
    )


def test_the_restart_time_is_given_in_the_logs_own_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`AddInLog` stamps local time with its offset; the process time is read in UTC. The reason
    gives it as the log does, so the engineer can set the two side by side."""
    logs = tmp_path / "logs"
    shutil.copytree(LOGS / "all-good", logs)
    text = (logs / "addin.log").read_text(encoding="utf-8")
    (logs / "addin.log").write_text(text.replace("+00:00]", "+01:00]"), encoding="utf-8")
    running(monkeypatch, [datetime(2026, 10, 31, 9, 20, tzinfo=UTC)])
    at(monkeypatch, datetime(2026, 10, 31, 9, 25, tzinfo=UTC))

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == LOG_CHECKS
    assert "2026-10-31T10:20:00+01:00" in reason(result, "add-in load")


@pytest.mark.parametrize(
    ("starts", "said"),
    [
        ([], "not running"),
        ([SOLIDWORKS_BEGAN, SOLIDWORKS_BEGAN + timedelta(seconds=30)], "2 SOLIDWORKS"),
        (None, "cannot be read"),
    ],
    ids=["none running", "two running", "unreadable"],
)
def test_the_three_log_checks_fail_closed_unless_one_solidworks_start_can_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, starts: list[datetime] | None, said: str
) -> None:
    """With no SOLIDWORKS, or two writing to one log, or a start time that cannot be read, nothing
    ties the log's latest start to the start just made: the three checks fail and say why."""
    running(monkeypatch, starts)

    result = health("all-good", checkout(tmp_path), "--json")

    assert result.exit_code == 1
    assert failing(result) == LOG_CHECKS
    for check in LOG_CHECKS:
        assert said in reason(result, check)


@pytest.mark.skipif(sys.platform != "win32", reason="reads Windows' process list")
def test_the_process_reader_finds_this_python_and_nothing_for_a_made_up_image() -> None:
    """The reader behind `solidworks_starts`, against this machine's processes: this test's own
    interpreter has begun, and an image no process has is absent. It opens each process for the
    limited query alone, and starts nothing."""
    ours = seat_health.process_starts(Path(sys.executable).name)
    later = datetime.now(UTC) + timedelta(seconds=1)

    assert ours, "this test's own interpreter is running"
    assert all(datetime(2020, 1, 1, tzinfo=UTC) < began < later for began in ours)
    assert seat_health.process_starts("fict-no-such-image.exe") == []


def test_the_process_reader_answers_none_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    assert seat_health.process_starts("SLDWORKS.exe") is None


def test_a_reload_that_attached_again_passes_on_its_own_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unticking and ticking the add-in calls `ConnectToSW` again in the same process, which writes
    no new start line: the latest load is its own `Attached to SOLIDWORKS.`, the start three hours
    old, and the backend log is the one begun since that load."""
    logs = logs_with(
        tmp_path,
        "[2026-10-31T12:10:00.0000000+00:00] Attached to SOLIDWORKS.",
        "[2026-10-31T12:10:01.0000000+00:00] Task Pane created.",
        "[2026-10-31T12:10:02.0000000+00:00] Review host started.",
    )
    (logs / "backend-20261031-121005.log").write_text(
        "[2026-10-31T12:10:05.0000000+00:00] starting uv run swreview chat serve\n"
        "[2026-10-31T12:10:09.0000000+00:00] backend healthy on http://127.0.0.1:52012 "
        "(pid 4343)\n",
        encoding="utf-8",
    )
    at(monkeypatch, datetime(2026, 10, 31, 12, 15, tzinfo=UTC))

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == set(), result.stdout
    assert "2026-10-31T12:10:00" in reason(result, "add-in load")
    assert "backend-20261031-121005.log" in reason(result, "backend")


def test_a_reload_needs_a_backend_log_begun_since_it(tmp_path: Path) -> None:
    logs = logs_with(
        tmp_path,
        "[2026-10-31T09:17:00.0000000+00:00] Attached to SOLIDWORKS.",
        "[2026-10-31T09:17:01.0000000+00:00] Task Pane created.",
        "[2026-10-31T09:17:02.0000000+00:00] Review host started.",
    )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == {"backend"}


def test_a_reload_whose_pane_failed_fails_though_the_first_load_was_good(tmp_path: Path) -> None:
    logs = logs_with(
        tmp_path,
        "[2026-10-31T09:17:00.0000000+00:00] Attached to SOLIDWORKS.",
        "[2026-10-31T09:17:01.0000000+00:00] The SwReview Task Pane could not be created. "
        "System.InvalidOperationException: a fictional failure",
        "   at Fict.Stack.Frame()",
        "[2026-10-31T09:17:02.0000000+00:00] Review host started.",
    )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert "add-in load" in failing(result)
    assert "Task Pane created." in reason(result, "add-in load")


def test_a_reload_that_could_not_attach_fails(tmp_path: Path) -> None:
    logs = logs_with(
        tmp_path,
        "[2026-10-31T09:17:00.0000000+00:00] The SwReview add-in could not attach to SOLIDWORKS. "
        "System.Runtime.InteropServices.COMException: a fictional failure",
    )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert "add-in load" in failing(result)
    assert "could not attach" in reason(result, "add-in load")


def test_a_missing_checkpoint_is_named(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    shutil.copytree(LOGS / "all-good", logs)
    text = (logs / "addin.log").read_text(encoding="utf-8")
    cut = text.rsplit("[2026-10-31T09:15:05.0000000+00:00] Task Pane created.\n", 1)
    (logs / "addin.log").write_text("".join(cut), encoding="utf-8")

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == {"add-in load"}
    assert "Task Pane created." in reason(result, "add-in load")


def test_no_addin_log_fails_the_three_checks_that_read_it(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert result.exit_code == 1
    assert failing(result) == {"add-in load", "tool service", "backend"}


def test_a_log_with_no_start_fails_the_three_checks_that_read_it(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "addin.log").write_text(
        "[2026-10-31T09:15:04.0000000+00:00] Attached to SOLIDWORKS.\n", encoding="utf-8"
    )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == {"add-in load", "tool service", "backend"}


def test_a_newest_backend_log_that_never_became_healthy_fails(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    shutil.copytree(LOGS / "all-good", logs)
    (logs / "backend-20261031-092000.log").write_text(
        "[2026-10-31T09:20:00.0000000+00:00] starting uv run swreview chat serve\n"
        "[2026-10-31T09:20:30.0000000+00:00] the backend did not answer /health within 30 "
        "seconds\n",
        encoding="utf-8",
    )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == {"backend"}
    assert "backend-20261031-092000.log" in reason(result, "backend")


def backend_with(tmp_path: Path, *lines: str) -> Path:
    """A copy of the all-good logs with `lines` appended to the newest backend log."""
    logs = tmp_path / "logs"
    shutil.copytree(LOGS / "all-good", logs)
    with (logs / "backend-20261031-091506.log").open("a", encoding="utf-8") as log:
        log.write("".join(f"{line}\n" for line in lines))
    return logs


@pytest.mark.parametrize(
    "line",
    [
        "backend stopped",
        "asked the backend to shut down (Ctrl+Break)",
        "asking the backend to shut down failed: a fictional failure",
        "a process of the backend had not exited 5 seconds after it was ended",
    ],
)
def test_a_backend_that_stopped_after_it_was_healthy_fails(tmp_path: Path, line: str) -> None:
    """Review round 2, F2: `BackendProcess.Stop` writes these on its way down, after the healthy
    line, into the same log. A backend that stopped, or is stopping, is not healthy."""
    logs = backend_with(tmp_path, f"[2026-10-31T09:18:00.0000000+00:00] {line}")

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert result.exit_code == 1
    assert failing(result) == {"backend"}
    assert "stopped" in reason(result, "backend")
    assert "2026-10-31T09:18:00" in reason(result, "backend")


def test_a_second_start_in_the_same_log_needs_its_own_healthy_line(tmp_path: Path) -> None:
    """`OpenLog` appends: a restart within the same second as the last writes into the same
    file, and only a healthy line after its own `starting` line speaks for it."""
    restarted = (
        "[2026-10-31T09:18:00.0000000+00:00] backend stopped",
        "[2026-10-31T09:18:00.5000000+00:00] starting uv run swreview chat serve",
    )
    healthy = (
        "[2026-10-31T09:18:04.0000000+00:00] backend healthy on http://127.0.0.1:52013 (pid 9)"
    )
    repo = checkout(tmp_path)

    starting = health("", repo, "--json", logs=backend_with(tmp_path, *restarted))
    shutil.rmtree(tmp_path / "logs")
    again = health("", repo, "--json", logs=backend_with(tmp_path, *restarted, healthy))

    assert failing(starting) == {"backend"}
    assert "does not say the backend is healthy" in reason(starting, "backend")
    assert failing(again) == set(), again.stdout


def test_a_server_line_after_the_healthy_line_does_not_unsay_it(tmp_path: Path) -> None:
    """The server's own output reaches the same log; only the lines `BackendProcess` writes on a
    start or a stop change what it says."""
    logs = backend_with(
        tmp_path, "[2026-10-31T09:16:00.0000000+00:00] INFO: a fictional request line"
    )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == set(), result.stdout


def test_a_backend_log_is_ordered_by_its_own_clock_whatever_its_offset(tmp_path: Path) -> None:
    """09:30 at +01:00 is 08:30 UTC, before the 09:15 UTC start: stale, though it reads later."""
    logs = tmp_path / "logs"
    logs.mkdir()
    shutil.copy(LOGS / "all-good" / "addin.log", logs)
    (logs / "backend-20261031-093000.log").write_text(
        "[2026-10-31T09:30:00.0000000+01:00] starting uv run swreview chat serve\n"
        "[2026-10-31T09:30:04.0000000+01:00] backend healthy on http://127.0.0.1:52011 (pid 7)\n",
        encoding="utf-8",
    )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == {"backend"}


def test_the_newest_backend_log_is_the_one_that_began_last_by_its_own_clock(
    tmp_path: Path,
) -> None:
    """Its name sorts first, but its first line is the latest: that is the one read."""
    logs = tmp_path / "logs"
    shutil.copytree(LOGS / "all-good", logs)
    (logs / "backend-20261031-090000.log").write_text(
        "[2026-10-31T09:17:00.0000000+00:00] starting uv run swreview chat serve\n",
        encoding="utf-8",
    )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == {"backend"}
    assert "backend-20261031-090000.log" in reason(result, "backend")


def test_a_backend_log_that_cannot_be_read_fails_naming_only_its_file(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    shutil.copytree(LOGS / "all-good", logs)
    (logs / "backend-20261031-092000.log").mkdir()

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert result.exit_code == 1, result.output
    assert failing(result) == {"backend"}
    assert "backend-20261031-092000.log" in reason(result, "backend")
    assert str(tmp_path) not in result.stdout


def test_a_profile_below_version_3_fails(tmp_path: Path) -> None:
    profile = write(tmp_path / "standards.yaml", as_version(2))

    result = health("all-good", checkout(tmp_path), "--json", profile=profile)

    assert failing(result) == {"profile"}
    assert "version 2" in reason(result, "profile")


def test_a_profile_that_does_not_validate_fails_without_quoting_it(tmp_path: Path) -> None:
    """The loader's reason for this file quotes its version, a folder; neither it nor the
    profile's path reaches the output."""
    profile = tmp_path / "standards.yaml"
    profile.write_text("version: D:/fict-seat/vault\n", encoding="utf-8")

    result = health("all-good", checkout(tmp_path), "--json", profile=profile)

    assert failing(result) == {"profile"}
    assert FICTIONAL_FOLDER not in result.stdout
    assert str(tmp_path) not in result.stdout


def test_the_example_profile_copied_into_place_fails(tmp_path: Path) -> None:
    repo = checkout(tmp_path)
    (repo / EXAMPLE).parent.mkdir(parents=True)
    shutil.copy(PROFILE_A, repo / EXAMPLE)

    result = health("all-good", repo, "--json")

    assert failing(result) == {"profile"}
    assert "example" in reason(result, "profile")


def test_the_example_profile_copied_with_other_line_endings_fails(tmp_path: Path) -> None:
    """Downloaded or checked out with LF, saved with CRLF: other bytes, the same profile."""
    text = PROFILE_A.read_text(encoding="utf-8").replace("\r\n", "\n")
    repo = checkout(tmp_path)
    (repo / EXAMPLE).parent.mkdir(parents=True)
    (repo / EXAMPLE).write_bytes(text.encode("utf-8"))
    profile = tmp_path / "standards.yaml"
    profile.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))

    result = health("all-good", repo, "--json", profile=profile)

    assert failing(result) == {"profile"}
    assert "example" in reason(result, "profile")


def test_the_passing_profile_reason_gives_its_version(tmp_path: Path) -> None:
    result = health("all-good", checkout(tmp_path), "--json")

    assert reason(result, "profile").endswith("version 4")


def test_uv_missing_from_path_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name, *args, **kwargs: None)

    result = health("all-good", checkout(tmp_path), "--json")

    assert failing(result) == {"uv"}


def test_the_uv_check_claims_only_this_shells_path(tmp_path: Path) -> None:
    """SOLIDWORKS started from the Start menu inherits Explorer's PATH from the login, not this
    shell's (runbook section 2): the backend check is what proves SOLIDWORKS found `uv`."""
    said = reason(health("all-good", checkout(tmp_path), "--json"), "uv")

    assert "this shell" in said
    assert "backend" in said
    assert "SOLIDWORKS inherits" not in said


def test_an_unbuilt_extractor_fails(tmp_path: Path) -> None:
    result = health("all-good", checkout(tmp_path, built=False), "--json")

    assert failing(result) == {"extractor"}


def test_untracked_files_git_is_configured_to_hide_still_fail_the_checkout(
    tmp_path: Path,
) -> None:
    """Review round 2, F3: `status.showUntrackedFiles=no` drops untracked files from a plain
    `git status --porcelain`; a handover file left in the checkout must still fail it."""
    repo = checkout(tmp_path, dirty=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "status.showUntrackedFiles", "no"], check=True
    )

    result = health("all-good", repo, "--json")

    assert failing(result) == {"checkout"}
    assert "1 changed or untracked" in reason(result, "checkout")


def test_a_branch_other_than_main_fails_the_checkout_check_without_naming_it(
    tmp_path: Path,
) -> None:
    """Review round 2, F5: a branch name is the workstation's, not something the engineer typed,
    and can name a customer or a design; neither output gives it. (T350's case asserted the name
    was printed; that was the leak.)"""
    repo = checkout(tmp_path, branch="fict-customer/made-up-bracket")
    result = health("all-good", repo, "--json")
    text = health("all-good", repo)

    assert failing(result) == {"checkout"}
    assert "not on main" in reason(result, "checkout")
    assert text.exit_code == 1
    for printed in (result.stdout, text.stdout):
        assert "fict-customer" not in printed
        assert "made-up-bracket" not in printed


def test_a_folder_that_is_not_a_checkout_fails_the_two_checks_that_need_one(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "not-a-checkout"
    folder.mkdir()

    result = health("all-good", folder, "--json")

    assert failing(result) == {"extractor", "checkout"}


def test_the_checkout_check_leaves_the_index_alone(tmp_path: Path) -> None:
    """A plain `git status` refreshes stale stat data and rewrites `.git/index` under
    `index.lock`, which can make a git command running beside it, `update-workstation.ps1`'s,
    fail. The check takes no optional lock, so it writes nothing."""
    repo = checkout(tmp_path)
    tracked = repo / "tracked.txt"
    tracked.write_text("a fictional tracked file\n", encoding="utf-8")
    git = ["git", "-C", str(repo), "-c", "user.name=Fict", "-c", "user.email=fict@example.invalid"]
    subprocess.run([*git, "add", "tracked.txt"], check=True)
    subprocess.run([*git, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "fict"], check=True)
    os.utime(tracked, (1_600_000_000, 1_600_000_000))
    index = (repo / ".git" / "index").read_bytes()

    result = health("all-good", repo, "--json")

    assert statuses(result)["checkout"] == "PASS", reason(result, "checkout")
    assert (repo / ".git" / "index").read_bytes() == index


# --- what it prints, and what it never prints ------------------------------------------------


@pytest.mark.parametrize(
    "case", ["all-good", "refusal-after-start", "tool-service-after-start", "stale-backend"]
)
@pytest.mark.parametrize("as_json", [False, True])
def test_no_path_is_printed_from_the_logs_or_the_options(
    tmp_path: Path, case: str, as_json: bool
) -> None:
    """Nothing the engineer did not type, and not even that: no path reaches the output."""
    repo = checkout(tmp_path)
    result = health(case, repo, *(["--json"] if as_json else []))

    assert result.exit_code in (0, 1), result.output
    assert all(check in result.stdout for check in CHECKS)
    for path in (str(tmp_path), str(LOGS), str(PROFILE_A.parent), FICTIONAL_FOLDER):
        assert path not in result.stdout


def test_the_defaults_are_the_documented_folders_under_localappdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`%LOCALAPPDATA%\\SwReview\\logs` and `...\\standards.yaml` (runbook section 1), read from
    the environment at run time; the checkout default is this one, which is only read."""
    local = tmp_path / "local"
    shutil.copytree(LOGS / "all-good", local / "SwReview" / "logs")
    shutil.copy(PROFILE_A, local / "SwReview" / "standards.yaml")
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    result = invoke("seat", "health", "--json")

    assert statuses(result)["add-in load"] == "PASS"
    assert statuses(result)["backend"] == "PASS"
    assert statuses(result)["profile"] == "PASS"
    assert str(local) not in result.stdout
