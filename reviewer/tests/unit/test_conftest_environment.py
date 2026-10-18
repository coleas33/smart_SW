"""The two environment rules `tests/conftest.py` settles for every test.

1. Colour: GitHub Actions sets `GITHUB_ACTIONS`, which makes Typer's Rich console a colour
   terminal, and every help-text assertion then saw ANSI codes on CI only. The conftest
   removes the colour-forcing variables before Typer loads; these tests pin that both in
   this run and in a child run started with every one of them set.
2. Temporary folder: a `--basetemp` inside the checkout turns the benchmark tests red (their
   fictional sets would lie inside the checkout, which the product treats differently), so the
   conftest refuses such a run with one usage error rather than ~90 path-spelling failures.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import COLOUR_FORCING_ENV, REPO_ROOT, basetemp_inside_checkout

REVIEWER = REPO_ROOT / "reviewer"
THIS_FILE = Path(__file__).resolve().relative_to(REVIEWER).as_posix()


def child_pytest(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """A separate pytest run over this file, from the reviewer folder, as CI starts one."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", *args],
        cwd=REVIEWER,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **env},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


# --- 1. colour ------------------------------------------------------------------------------


def test_no_colour_forcing_variable_survives_into_the_tests() -> None:
    from typer import rich_utils

    assert [name for name in COLOUR_FORCING_ENV if name in os.environ] == []
    assert not rich_utils.FORCE_TERMINAL


def test_help_text_is_plain_so_option_names_are_contiguous() -> None:
    from swreview import cli

    result = CliRunner().invoke(cli.app, ["benchmark", "run", "--help"])
    assert result.exit_code == 0, result.output
    assert "\x1b[" not in result.output
    assert "--jobs" in result.output


def test_a_run_started_with_every_colour_forcing_variable_still_sees_plain_help() -> None:
    forced = dict.fromkeys(COLOUR_FORCING_ENV, "1") | {"GITHUB_ACTIONS": "true"}
    result = child_pytest(
        f"{THIS_FILE}::test_no_colour_forcing_variable_survives_into_the_tests",
        f"{THIS_FILE}::test_help_text_is_plain_so_option_names_are_contiguous",
        env=forced,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


# --- 2. temporary folder --------------------------------------------------------------------


@pytest.mark.parametrize("inside", [".pytest-tmp", "reviewer/.pytest-tmp", "."])
def test_a_basetemp_in_the_checkout_or_the_checkout_itself_is_inside(
    tmp_path: Path, inside: str
) -> None:
    root = tmp_path / "checkout"
    assert basetemp_inside_checkout(root / inside, tmp_path, root) == (root / inside).resolve()


def test_a_relative_basetemp_resolves_against_the_working_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "checkout"
    (root / "reviewer").mkdir(parents=True)
    monkeypatch.chdir(root / "reviewer")
    assert basetemp_inside_checkout(".pytest-tmp", tmp_path, root) == (
        root / "reviewer" / ".pytest-tmp"
    ).resolve()
    assert basetemp_inside_checkout("../../outside", tmp_path, root) is None


@pytest.mark.parametrize("outside", ["elsewhere/pytest", "checkout-ci/pytest", "checkout2"])
def test_a_basetemp_outside_or_in_a_sibling_sharing_the_name_prefix_is_outside(
    tmp_path: Path, outside: str
) -> None:
    assert basetemp_inside_checkout(tmp_path / outside, tmp_path, tmp_path / "checkout") is None


def test_without_basetemp_the_temporary_root_pytest_would_use_is_the_one_tested(
    tmp_path: Path,
) -> None:
    root = tmp_path / "checkout"
    assert basetemp_inside_checkout(None, tmp_path / "temp", root) is None
    assert basetemp_inside_checkout(None, root / "temp", root) == (root / "temp").resolve()


def test_a_run_with_basetemp_inside_the_checkout_is_refused_before_any_folder_is_made() -> None:
    probe = REVIEWER / ".pytest-tmp-refusal-probe"
    assert not probe.exists()
    result = child_pytest("--co", THIS_FILE, f"--basetemp={probe}", env={})
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    assert "lies inside the checkout" in result.stderr
    assert "Pass --basetemp=<a folder outside the checkout>, or omit it." in result.stderr
    assert not probe.exists()


def test_the_current_run_s_temporary_folder_is_outside_the_checkout(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    assert not tmp_path_factory.getbasetemp().resolve().is_relative_to(REPO_ROOT.resolve())
