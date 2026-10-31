"""`swreview seat health`: the runbook's health checks a file can prove (004 R28, decision 166A).

`docs/workstation-runbook.md` section 6 lists what to check after every start. Seven checks here
settle the part a file can prove, each PASS or FAIL with a one-line reason: the add-in's four load
checkpoints in order for the latest start (`AddInLog`, `SwReviewAddIn.ConnectToSW`), no
tool-service refusal or `.SLDDRW` line after it (`ToolServiceGate`), a backend log begun since that
start that says the backend is healthy (`BackendProcess.WaitForHealth`), the standards profile with
its version, `uv` on PATH, `swreview-extract` built, and the checkout clean on `main`. What only the
pane shows stays manual (`MANUAL`).

It reads files and runs two read-only `git` commands; it starts nothing else, reads no key (the
settings file, which holds one, is never opened), and prints no path - a reason names a log by its
file name and a line by its time, never by its text, which can name a document.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from swreview.checks.standards.profile import ProfileInvalid, ProfileUnreadable, load_profile

CHECKPOINTS = (
    "AssemblyRedirect installed.",
    "Attached to SOLIDWORKS.",
    "Task Pane created.",
    "Review host started.",
)
"""The four lines `addin.log` gains on every load, in order (docs/addin-load-fix.md); the first
is the type initializer's, so its last occurrence is the latest start."""

TOOL_SERVICE = "The SwReview tool service"
"""The tool service logs only refusals and failures: a line beginning so means it did not
attach."""

DRAWING = ".slddrw"
HEALTHY = "backend healthy on "
EXTRACTOR = Path("extractor/SwReview.Extractor.Console/bin/x64/Release/net48/swreview-extract.exe")
EXAMPLE = Path("config/standards.example.yaml")
LOWEST_CURRENT_VERSION = 3
"""Runbook section 5: the profile prints `version: 3`, or `version: 4` after feature 013's
upgrade."""

DEFAULT_REPO = Path(__file__).resolve().parents[4]
"""The checkout this command runs from, as `update-workstation.ps1` builds its own."""

MANUAL = (
    "Tools > Add-ins shows SwReview ticked (runbook 6, item 1)",
    "the Review tab's badge reads Backend ready (item 2)",
    "Model check on a part gives a grade and a -check run folder (item 3)",
    "Standards on the same part gives a verdict with every check accounted for (item 4)",
    "with a key, a Review of a small assembly ends on screen (item 5)",
    "five tabs, and no Ask tab (item 6)",
)

_ENTRY = re.compile(r"\[(?P<stamp>[^\]]*)\] ?(?P<text>.*)")


@dataclass(frozen=True)
class Check:
    check: str
    status: str
    reason: str


def passed(check: str, reason: str) -> Check:
    return Check(check, "PASS", reason)


def failed(check: str, reason: str) -> Check:
    return Check(check, "FAIL", reason)


@dataclass(frozen=True)
class _Entry:
    """One timestamped line and the untimed lines after it (a stack trace `Report` wrote)."""

    stamp: str
    text: str
    whole: str

    @property
    def time(self) -> datetime | None:
        try:
            value = datetime.fromisoformat(self.stamp)
        except ValueError:
            return None
        return value if value.tzinfo is not None else None


def _entries(path: Path) -> list[_Entry]:
    entries: list[_Entry] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _ENTRY.match(line)
        if match:
            entries.append(_Entry(match["stamp"], match["text"].strip(), match["text"]))
        elif entries:
            last = entries[-1]
            entries[-1] = _Entry(last.stamp, last.text, f"{last.whole}\n{line}")
    return entries


def _swreview_local() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home() / "AppData" / "Local") / "SwReview"


def default_logs() -> Path:
    return _swreview_local() / "logs"


def default_profile() -> Path:
    return _swreview_local() / "standards.yaml"


def run(logs: Path, repo: Path, profile: Path) -> list[Check]:
    """Every check, in the order the runbook reads them."""
    log = logs / "addin.log"
    entries = _entries(log) if log.is_file() else None
    start = _latest_start(entries)
    return [
        _load(entries, start),
        _tool_service(entries, start),
        _backend(logs, entries, start),
        _profile(profile, repo),
        _uv(),
        _extractor(repo),
        _checkout(repo),
    ]


def _latest_start(entries: list[_Entry] | None) -> int | None:
    starts = [i for i, entry in enumerate(entries or []) if entry.text == CHECKPOINTS[0]]
    return starts[-1] if starts else None


def _no_start(check: str, entries: list[_Entry] | None) -> Check:
    if entries is None:
        return failed(check, "there is no addin.log in the log folder: the add-in has never loaded")
    return failed(
        check,
        f"addin.log has no '{CHECKPOINTS[0]}' line: the add-in has not loaded since the log began "
        "(runbook section 7)",
    )


def _load(entries: list[_Entry] | None, start: int | None) -> Check:
    check = "add-in load"
    if entries is None or start is None:
        return _no_start(check, entries)
    stamp = entries[start].stamp
    after = [entry.text for entry in entries[start + 1 :]]
    positions = []
    for line in CHECKPOINTS[1:]:
        if line not in after:
            return failed(
                check,
                f"'{line}' is missing after the latest start at {stamp}; the line after the last "
                "checkpoint names the step that failed (runbook section 7)",
            )
        positions.append(after.index(line))
    if positions != sorted(positions):
        return failed(
            check, f"the four checkpoint lines after the latest start at {stamp} are out of order"
        )
    return passed(check, f"the four checkpoint lines in order after the latest start at {stamp}")


def _tool_service(entries: list[_Entry] | None, start: int | None) -> Check:
    check = "tool service"
    if entries is None or start is None:
        return _no_start(check, entries)
    for entry in entries[start + 1 :]:
        if DRAWING in entry.whole.lower():
            return failed(
                check,
                f"the line at {entry.stamp} names a drawing (.SLDDRW): the active document was a "
                "drawing; start with a part or assembly active (runbook section 6)",
            )
        if entry.text.startswith(TOOL_SERVICE):
            return failed(
                check,
                f"a tool-service line at {entry.stamp}: the tool service logs only refusals and "
                "failures, so it did not attach; read that line of addin.log",
            )
    return passed(check, f"no tool-service line and no drawing named since {entries[start].stamp}")


def _backend(logs: Path, entries: list[_Entry] | None, start: int | None) -> Check:
    check = "backend"
    if entries is None or start is None:
        return _no_start(check, entries)
    began = entries[start].time
    if began is None:
        return failed(check, f"the latest start's time '{entries[start].stamp}' cannot be read")
    since: list[tuple[datetime, Path, list[_Entry]]] = []
    for path in logs.glob("backend-*.log"):
        lines = _entries(path)
        first = lines[0].time if lines else None
        if first is not None and first >= began:
            since.append((first, path, lines))
    if not since:
        return failed(
            check,
            f"no backend log has begun since the latest start at {entries[start].stamp}: open the "
            "Review tab, wait for Backend ready and run this again (runbook section 6, item 2)",
        )
    _, newest, lines = max(since, key=lambda row: row[0])
    if any(entry.text.startswith(HEALTHY) for entry in lines):
        return passed(
            check, f"{newest.name}, the newest since the start, says the backend is healthy"
        )
    return failed(
        check,
        f"{newest.name}, the newest since the start, does not say the backend is healthy; read it "
        "(a backend that cannot be located means uv is not on the PATH SOLIDWORKS sees)",
    )


def _profile(profile: Path, repo: Path) -> Check:
    check = "profile"
    try:
        loaded = load_profile(profile)
    except ProfileUnreadable as refusal:
        return failed(
            check,
            f"{refusal.reason}; the default is %LOCALAPPDATA%\\SwReview\\standards.yaml, and when "
            "the settings file names another, pass it with --profile (runbook section 5)",
        )
    except ProfileInvalid:
        # Its reason can quote a value from the file, which never leaves the machine.
        return failed(
            check,
            "the profile does not validate: run the validation in runbook section 5 to see which "
            "fields",
        )
    example = repo / EXAMPLE
    if example.is_file() and example.read_bytes() == profile.read_bytes():
        return failed(
            check,
            "the profile is the repository's fictional example copied into place; place the "
            "owner's file (runbook section 5)",
        )
    if loaded.version < LOWEST_CURRENT_VERSION:
        return failed(
            check,
            f"version {loaded.version}: a version below {LOWEST_CURRENT_VERSION} still loads, but "
            "the sections it predates come back skipped; rewriting it is the owner's (runbook "
            "section 5)",
        )
    return passed(check, f"present, version {loaded.version}")


def _uv() -> Check:
    if shutil.which("uv"):
        return passed("uv", "uv is on this session's PATH, which SOLIDWORKS inherits")
    return failed(
        "uv",
        "uv is not on PATH: the Review tab cannot start its backend (runbook section 2)",
    )


def _extractor(repo: Path) -> Check:
    if (repo / EXTRACTOR).is_file():
        return passed(
            "extractor", "swreview-extract.exe is built (alias it as runbook section 1 says)"
        )
    return failed(
        "extractor",
        "swreview-extract.exe is not built: run extractor\\tools\\update-workstation.ps1 "
        "(runbook section 4)",
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _checkout(repo: Path) -> Check:
    check = "checkout"
    status = _git(repo, "status", "--porcelain")
    if status is None:
        return failed(check, "git could not be run: is it installed and on PATH?")
    if status.returncode != 0:
        # git's own words would name the folder; the engineer can run it there to read them.
        return failed(check, "git cannot read the checkout (pass --repo, or run git status there)")
    problems = []
    branch = _git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    if branch is None or branch.returncode != 0:
        problems.append("HEAD is not on a branch, so not on main")
    elif branch.stdout.strip() != "main":
        problems.append(f"on {branch.stdout.strip()}, not main")
    changed = status.stdout.splitlines()
    if changed:
        problems.append(f"{len(changed)} changed or untracked path(s): run git status there")
    if problems:
        return failed(check, "; ".join(problems))
    return passed(check, "on main, with nothing changed or untracked")
