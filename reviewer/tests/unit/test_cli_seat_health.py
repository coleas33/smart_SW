"""`swreview seat health`: the runbook's health checks a file can prove (004 T350; decision 166A).

`docs/workstation-runbook.md` section 6 lists seven checks after every start. The engineer runs this
command at the seat once SOLIDWORKS is up, and it settles every item a file can prove: `addin.log`
shows the four load checkpoints in order for the latest start, with no tool-service refusal and no
`.SLDDRW` line after it; a backend log newer than that start says the backend is healthy; the
standards profile is present with its version; `uv` is on PATH; `swreview-extract` is built; and
the checkout is clean on `main`. The pane's own checks stay manual, and the output says so.

Every log here is fictional (`tests/fixtures/seat/health/`, one folder per case); each checkout is
a throwaway git repository made in the test's temp folder, so no case reads this machine's
`%LOCALAPPDATA%\\SwReview` or this checkout's own state.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_cli import invoke
from tests.unit.test_cli_profile_upgrade import PROFILE_A, as_version, write

LOGS = Path(__file__).resolve().parents[1] / "fixtures" / "seat" / "health"
EXTRACTOR = Path("extractor/SwReview.Extractor.Console/bin/x64/Release/net48/swreview-extract.exe")
EXAMPLE = Path("config/standards.example.yaml")
FICTIONAL_DRAWING = "made-up-bracket"
FICTIONAL_FOLDER = "fict-seat"

CHECKS = ["add-in load", "tool service", "backend", "profile", "uv", "extractor", "checkout"]


@pytest.fixture(autouse=True)
def uv_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """`uv` is found, whatever this machine's PATH says; a case that wants it missing says so."""
    real = shutil.which

    def which(name: str, *args: Any, **kwargs: Any) -> str | None:
        return "fict-uv" if name == "uv" else real(name, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", which)


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
    assert "since the latest start" in reason(result, "backend")


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
    logs = tmp_path / "logs"
    shutil.copytree(LOGS / "all-good", logs)
    with (logs / "addin.log").open("a", encoding="utf-8") as log:
        log.write("[2026-10-31T09:16:00.0000000+00:00] The SwReview tool service did not start.\n")

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == {"tool service"}
    assert "2026-10-31T09:16:00" in reason(result, "tool service")


def test_a_line_naming_a_drawing_fails_even_when_it_is_not_the_tool_services(
    tmp_path: Path,
) -> None:
    logs = tmp_path / "logs"
    shutil.copytree(LOGS / "all-good", logs)
    with (logs / "addin.log").open("a", encoding="utf-8") as log:
        log.write(
            "[2026-10-31T09:16:00.0000000+00:00] A fictional failure.\n"
            "   at a frame reading D:\\fict-seat\\made-up-bracket.slddrw\n"
        )

    result = health("", checkout(tmp_path), "--json", logs=logs)

    assert failing(result) == {"tool service"}
    assert FICTIONAL_DRAWING not in result.stdout


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


def test_a_profile_below_version_3_fails(tmp_path: Path) -> None:
    profile = write(tmp_path / "standards.yaml", as_version(2))

    result = health("all-good", checkout(tmp_path), "--json", profile=profile)

    assert failing(result) == {"profile"}
    assert "version 2" in reason(result, "profile")


def test_a_profile_that_does_not_validate_fails_without_quoting_it(tmp_path: Path) -> None:
    profile = tmp_path / "standards.yaml"
    profile.write_text("version: 4\nvault_root: D:/fict-seat/vault\n", encoding="utf-8")

    result = health("all-good", checkout(tmp_path), "--json", profile=profile)

    assert failing(result) == {"profile"}
    assert FICTIONAL_FOLDER not in result.stdout


def test_the_example_profile_copied_into_place_fails(tmp_path: Path) -> None:
    repo = checkout(tmp_path)
    (repo / EXAMPLE).parent.mkdir(parents=True)
    shutil.copy(PROFILE_A, repo / EXAMPLE)

    result = health("all-good", repo, "--json")

    assert failing(result) == {"profile"}
    assert "example" in reason(result, "profile")


def test_the_passing_profile_reason_gives_its_version(tmp_path: Path) -> None:
    result = health("all-good", checkout(tmp_path), "--json")

    assert reason(result, "profile").endswith("version 4")


def test_uv_missing_from_path_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name, *args, **kwargs: None)

    result = health("all-good", checkout(tmp_path), "--json")

    assert failing(result) == {"uv"}


def test_an_unbuilt_extractor_fails(tmp_path: Path) -> None:
    result = health("all-good", checkout(tmp_path, built=False), "--json")

    assert failing(result) == {"extractor"}


def test_a_branch_other_than_main_fails_the_checkout_check(tmp_path: Path) -> None:
    result = health("all-good", checkout(tmp_path, branch="workstation/2026-10-31"), "--json")

    assert failing(result) == {"checkout"}
    assert "workstation/2026-10-31" in reason(result, "checkout")


def test_a_folder_that_is_not_a_checkout_fails_the_two_checks_that_need_one(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "not-a-checkout"
    folder.mkdir()

    result = health("all-good", folder, "--json")

    assert failing(result) == {"extractor", "checkout"}


# --- what it prints, and what it never prints ------------------------------------------------


@pytest.mark.parametrize("case", ["all-good", "refusal-after-start", "stale-backend"])
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
