"""The workstation update script runs the development machine's gate and says where things are.

`extractor/tools/update-workstation.ps1` cannot run here (it builds against a SOLIDWORKS seat and
registers a COM add-in), so what the seat-readiness review of 2026-09-23 found is held in its
source, the way the page scans hold the pages (feature 008 T123):

- the gate's pytest deselects the `live` tests, as CI does (`.github/workflows/reviewer.yml`), so a
  provider key in the seat's environment does not make the gate call a paid API or fail on a
  filtered network;
- a dirty checkout is moved aside with `git stash push --include-untracked`, since a plain
  `git stash push` leaves the untracked findings document that made the tree dirty;
- `-SolidWorksRoot` reaches both the build (`-p:SwRedist=`) and the registration, for a seat
  installed somewhere else, and `-TokenizerFrom` reaches `swreview tokenizer fetch --from` for a
  seat whose web filter blocks the vocabulary's host;
- the health step prints where `swreview-extract.exe` was built, which every probe task calls by
  its bare name.

When Windows PowerShell is on the PATH, the script is also parsed, so a syntax error fails here.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "extractor" / "tools" / "update-workstation.ps1"
CONSOLE = REPO / "extractor" / "SwReview.Extractor.Console"
CONSOLE_PROJECT = CONSOLE / "SwReview.Extractor.Console.csproj"
BUILD_PROPS = REPO / "extractor" / "Directory.Build.props"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def parameters(script: str) -> set[str]:
    block = script[script.index("param(") : script.index("\n)\n", script.index("param("))]
    return set(re.findall(r"\$([A-Za-z]+)", block))


def test_the_gates_pytest_deselects_the_live_tests_as_ci_does(script: str) -> None:
    [pytest_line] = [line for line in script.splitlines() if "uv run pytest" in line
                     and "Invoke-Step" not in line]

    assert '-m "not live"' in pytest_line
    assert 'SWREVIEW_REQUIRE_TOKENIZER = "1"' in script
    workflow = (REPO / ".github" / "workflows" / "reviewer.yml").read_text(encoding="utf-8")
    assert 'pytest -m "not live"' in workflow


def test_a_dirty_checkout_is_moved_aside_with_its_untracked_files(script: str) -> None:
    advice = script[script.index("if ($dirty)") : script.index("$before = git rev-parse")]

    assert "git stash push --include-untracked" in advice
    assert "handover" in advice


def test_the_solidworks_root_reaches_the_build_and_the_registration(script: str) -> None:
    assert {"SolidWorksRoot", "TokenizerFrom"} <= parameters(script)
    [build] = [
        line for line in script.splitlines() if "dotnet build" in line and "Invoke-Step" in line
    ]
    assert "-p:SwRedist=$swRedist" in build
    assert re.search(r'\$swRedist = Join-Path \$SolidWorksRoot "api\\redist"', script)
    assert "-SolidWorksRoot $SolidWorksRoot" in script[script.index('"register-addin.ps1"'):]
    default = re.search(r'\[string\] \$SolidWorksRoot = "([^"]+)"', script)
    props = BUILD_PROPS.read_text(encoding="utf-8")
    assert default is not None and default.group(1) + "\\api\\redist" in props


def test_a_vocabulary_carried_by_hand_is_fetched_from_its_file(script: str) -> None:
    reviewer = script[script.index("# 4. The reviewer.") :]
    fetch = reviewer[: reviewer.index("if (-not $SkipTests)")]

    assert "{ uv run swreview tokenizer fetch --from $TokenizerFrom }" in fetch
    assert "{ uv run swreview tokenizer fetch }" in fetch


def test_the_health_step_prints_where_swreview_extract_was_built(script: str) -> None:
    health = script[script.index("# 7."):]
    assembly = ET.parse(CONSOLE_PROJECT).getroot().findtext(".//AssemblyName")
    platform = ET.parse(BUILD_PROPS).getroot().findtext(".//Platforms")

    assert assembly == "swreview-extract" and platform == "x64"
    assert (
        rf"SwReview.Extractor.Console\bin\{platform}\$Configuration\net48\{assembly}.exe" in health
    )
    assert "Set-Alias swreview-extract" in health


def test_an_elevated_run_is_warned_about_whose_profile_it_fills(script: str) -> None:
    assert "WindowsBuiltInRole]::Administrator" in script
    assert "Write-Warning" in script


def test_the_runbooks_manual_steps_are_the_scripts(script: str) -> None:
    """`docs/workstation-runbook.md` gives the script's steps by hand (sections 3, 4 and 9); a
    manual install that skipped the vocabulary went green with the vocabulary tests skipped, and
    a manual gate that ran the live tests called a paid API. Each of the script's choices is in
    the runbook too, and the runbook says where the console and a findings document go."""
    runbook = (REPO / "docs" / "workstation-runbook.md").read_text(encoding="utf-8")

    for step in (
        "uv run swreview tokenizer fetch",
        'tokenizer fetch --from "<file>"',
        '$env:SWREVIEW_REQUIRE_TOKENIZER = "1"',
        'uv run pytest -q -m "not live"',
        "git stash push --include-untracked",
        "-SolidWorksRoot",
        "-TokenizerFrom",
    ):
        assert step in runbook, step
    assert runbook.count('uv run pytest -q -m "not live"') >= 3
    assert "uv run pytest -q\n" not in runbook and "uv run pytest -q " not in runbook.replace(
        'uv run pytest -q -m "not live"', ""
    )
    assert r"SwReview.Extractor.Console\bin\x64\Release\net48\swreview-extract.exe" in runbook
    assert r"%LOCALAPPDATA%\SwReview\handover\<date>" in runbook
    assert "version: 3" in runbook


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_the_script_parses() -> None:
    command = (
        "$errors = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', "
        "[ref]$null, [ref]$errors); "
        "$errors | ForEach-Object { $_.Message }"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == ""
