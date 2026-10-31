"""`swreview seat health`: the runbook's health checks a file can prove (004 R28, decision 166A).

`docs/workstation-runbook.md` section 6 lists what to check after every start. Seven checks here
settle the part a file can prove, each PASS or FAIL with a one-line reason: the add-in's four load
checkpoints in order for the latest load (`AddInLog`, `SwReviewAddIn.ConnectToSW`), no
tool-service refusal or `.SLDDRW` line after it (`ToolServiceGate`), a backend log begun since it
that says the backend is healthy and has not stopped since (`BackendProcess`), the standards
profile with its version, `uv` on PATH, `swreview-extract` built, and the checkout clean on `main`.
What only the pane shows stays manual (`MANUAL`). A start that loaded nothing writes nothing, and
the session before it must not pass for it: the three log checks fail unless the log's latest
start is no older than the one SOLIDWORKS running, and when the latest load is more than `FRESH`
old.

It reads files and the start time of each running `SLDWORKS.exe` (opened for the limited query
alone), and runs two read-only `git` commands, taking no optional lock; it starts nothing else,
writes nothing, reads no key (the settings file, which holds one, is never opened), and prints no
path or branch - a reason names a log by its file name and a line by its time, never by its text,
which can name a document.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from swreview.checks.standards.profile import (
    DEFAULT_PATH,
    ProfileError,
    ProfileInvalid,
    ProfileUnreadable,
    StandardsProfile,
    load_profile,
)

CHECKPOINTS = (
    "AssemblyRedirect installed.",
    "Attached to SOLIDWORKS.",
    "Task Pane created.",
    "Review host started.",
)
"""The four lines `addin.log` gains on a load, in order (docs/addin-load-fix.md). The first is
the type initializer's, written once per SOLIDWORKS process, so its last occurrence is the latest
start; the other three are `ConnectToSW`'s, written again each time the add-in is ticked."""

NOT_ATTACHED = "The SwReview add-in could not attach to SOLIDWORKS."
"""What `ConnectToSW` writes instead of `Attached to SOLIDWORKS.` when its load fails."""

TOOL_SERVICE = "The SwReview tool service"
"""The tool service logs only refusals and failures: a line beginning so means it did not
attach."""

FRESH = timedelta(hours=2)
"""The oldest the latest load may be. The command is run right after a start (runbook section
6); a start that loaded nothing - a reverted check box, a broken registration
(docs/addin-load-fix.md) - writes no line, and leaves the session before it as the latest."""

LOG_CHECKS = ("add-in load", "tool service", "backend")
"""The checks `addin.log` settles, in order."""

SOLIDWORKS = "SLDWORKS.exe"

DRAWING = ".slddrw"
STARTING = "starting "
HEALTHY = "backend healthy on "
STOPPING = (
    "asked the backend to shut down",
    "asking the backend to shut down failed",
    "a process of the backend had not exited",
    "backend stopped",
)
"""What `BackendProcess.Stop` writes on its way down, after the healthy line, into the same log."""
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

_STAMPED = re.compile(r"\[(?P<stamp>[^\]]*)\] ?(?P<text>.*)")


@dataclass(frozen=True)
class Check:
    check: str
    status: str
    reason: str


def passed(check: str, reason: str) -> Check:
    return Check(check, "PASS", reason)


def failed(check: str, reason: str) -> Check:
    return Check(check, "FAIL", reason)


def now() -> datetime:
    """The clock the latest load is aged by."""
    return datetime.now(UTC)


def solidworks_starts() -> list[datetime] | None:
    """When each running SOLIDWORKS began; None when that cannot be read."""
    return process_starts(SOLIDWORKS)


def process_starts(image: str) -> list[datetime] | None:
    """When each running process of `image` began (its file name, in any case), from Windows'
    process list; None off Windows, or when one of them refuses the query or has gone before it
    is read. Each is opened for `PROCESS_QUERY_LIMITED_INFORMATION` alone."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        )

    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snapshot is None or snapshot == ctypes.c_void_p(-1).value:  # INVALID_HANDLE_VALUE
        return None
    ids = []
    try:
        entry = Entry(dwSize=ctypes.sizeof(Entry))
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.szExeFile.lower() == image.lower():
                ids.append(entry.th32ProcessID)
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    starts = []
    for pid in ids:
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        try:
            if not kernel32.GetProcessTimes(handle, *(ctypes.byref(time) for time in times)):
                return None
        finally:
            kernel32.CloseHandle(handle)
        ticks = times[0].dwHighDateTime << 32 | times[0].dwLowDateTime  # 100 ns since 1601 UTC
        starts.append(datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=ticks // 10))
    return starts


@dataclass(frozen=True)
class _Entry:
    """One line the add-in or the backend wrote, and the lines after it that begin with no time
    (an exception's text, which `Report` writes whole)."""

    time: datetime
    text: str
    whole: str


def _stamped(line: str) -> tuple[datetime, str] | None:
    """The time and text of a line that begins `[<time>]` as `AddInLog` and `BackendProcess`
    write it (`{0:O}`, always with its offset); None for any other line, a bracket included."""
    match = _STAMPED.match(line)
    if match is None:
        return None
    try:
        time = datetime.fromisoformat(match["stamp"])
    except ValueError:
        return None
    return (time, match["text"]) if time.tzinfo is not None else None


def _entries(path: Path) -> list[_Entry]:
    entries: list[_Entry] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stamped = _stamped(line)
        if stamped is not None:
            time, text = stamped
            entries.append(_Entry(time, text.strip(), text))
        elif entries:
            last = entries[-1]
            entries[-1] = _Entry(last.time, last.text, f"{last.whole}\n{line}")
    return entries


def _first_time(path: Path) -> datetime | None:
    with path.open(encoding="utf-8", errors="replace") as log:
        stamped = _stamped(log.readline().rstrip("\n"))
    return stamped[0] if stamped is not None else None


def _when(time: datetime) -> str:
    return time.isoformat(timespec="seconds")


def _unreadable(path: Path, error: OSError) -> str:
    """Why a log cannot be read, by its file name: `str(error)` would name its folder."""
    return f"{path.name} cannot be read: {error.strerror or type(error).__name__}"


def _swreview_local() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home() / "AppData" / "Local") / "SwReview"


def default_logs() -> Path:
    return _swreview_local() / "logs"


def default_profile() -> Path:
    return _swreview_local() / "standards.yaml"


def run(logs: Path, repo: Path, profile: Path) -> list[Check]:
    """Every check, in the order the runbook reads them."""
    return [
        *_log_checks(logs),
        _profile(profile, repo),
        _uv(),
        _extractor(repo),
        _checkout(repo),
    ]


def _log_checks(logs: Path) -> list[Check]:
    """The three checks `addin.log` settles, from its latest load: the last `ConnectToSW` line
    (attached, or not) after the latest start, or that start when none follows it."""

    def all_fail(reason: str) -> list[Check]:
        return [failed(check, reason) for check in LOG_CHECKS]

    log = logs / "addin.log"
    if not log.is_file():
        return all_fail("there is no addin.log in the log folder: the add-in has never loaded")
    try:
        entries = _entries(log)
    except OSError as error:
        return all_fail(_unreadable(log, error))
    starts = [index for index, entry in enumerate(entries) if entry.text == CHECKPOINTS[0]]
    if not starts:
        return all_fail(
            f"addin.log has no '{CHECKPOINTS[0]}' line: the add-in has not loaded since the log "
            "began (runbook section 7)"
        )
    start = starts[-1]
    unproved = _not_this_start(entries[start].time)
    if unproved is not None:
        return all_fail(unproved)
    loads = [
        index
        for index in range(start + 1, len(entries))
        if entries[index].text == CHECKPOINTS[1] or entries[index].text.startswith(NOT_ATTACHED)
    ]
    latest = loads[-1] if loads else start
    age = now() - entries[latest].time
    if age > FRESH:
        minutes = int(age.total_seconds() // 60)
        return all_fail(
            f"the add-in's latest load was at {_when(entries[latest].time)}, {minutes // 60} h "
            f"{minutes % 60} min ago, and this checks the start just made: if SOLIDWORKS has been "
            "started since, the add-in did not load (Tools > Add-ins, runbook section 7); if not, "
            "start it and run this again"
        )
    return [
        _load(entries, start, loads),
        _tool_service(entries, latest),
        _backend(logs, entries[latest].time),
    ]


def _not_this_start(start: datetime) -> str | None:
    """Why the log's latest start cannot be the one SOLIDWORKS running, or None when it can: the
    type initializer writes the start line inside the process, so the running one's own is no
    older than it, and a start that loaded nothing leaves only older ones."""
    started = solidworks_starts()
    if started is None:
        return (
            "when SOLIDWORKS started cannot be read here, so addin.log cannot be tied to the start "
            "just made: run this at the seat, as the user SOLIDWORKS runs as"
        )
    if not started:
        return "SOLIDWORKS is not running: this checks the start just made; start it, then run this"
    if len(started) > 1:
        return (
            f"{len(started)} SOLIDWORKS processes are running and write to one addin.log, which "
            "cannot say whose start is whose: close all but one and run this again"
        )
    began = started[0].astimezone(start.tzinfo)
    if start < began:
        return (
            f"SOLIDWORKS started at {_when(began)} and the add-in has written no start line "
            "since, so it did not load (Tools > Add-ins, runbook section 7)"
        )
    return None


def _load(entries: list[_Entry], start: int, loads: list[int]) -> Check:
    check = "add-in load"
    began = _when(entries[start].time)
    later = CHECKPOINTS[2:]
    if not loads:
        return failed(
            check,
            f"'{CHECKPOINTS[1]}' is missing after the latest start at {began}; the line after the "
            "last checkpoint names the step that failed (runbook section 7)",
        )
    if any(entry.text in later for entry in entries[start + 1 : loads[0]]):
        return failed(
            check, f"the four checkpoint lines after the latest start at {began} are out of order"
        )
    load = entries[loads[-1]]
    loaded = _when(load.time)
    if load.text.startswith(NOT_ATTACHED):
        return failed(
            check,
            f"the add-in could not attach to SOLIDWORKS at {loaded}; that line of addin.log names "
            "why (runbook section 7)",
        )
    after = [entry.text for entry in entries[loads[-1] + 1 :] if entry.text in later]
    for line in later:
        if line not in after:
            return failed(
                check,
                f"'{line}' is missing after the latest load at {loaded}; the line after the last "
                "checkpoint names the step that failed (runbook section 7)",
            )
    if after != list(later):
        return failed(
            check, f"the checkpoint lines after the latest load at {loaded} are out of order"
        )
    again = "" if loads[-1] == loads[0] else f", and again at {loaded}"
    return passed(check, f"the four checkpoint lines in order for the start at {began}{again}")


def _tool_service(entries: list[_Entry], latest: int) -> Check:
    check = "tool service"
    for entry in entries[latest + 1 :]:
        if DRAWING in entry.whole.lower():
            return failed(
                check,
                f"the line at {_when(entry.time)} names a drawing (.SLDDRW): the active document "
                "was a drawing; start with a part or assembly active (runbook section 6)",
            )
        if entry.text.startswith(TOOL_SERVICE):
            return failed(
                check,
                f"a tool-service line at {_when(entry.time)}: the tool service logs only "
                "refusals and failures, so it did not attach; read that line of addin.log",
            )
    return passed(
        check,
        f"no tool-service line and no drawing named since {_when(entries[latest].time)}",
    )


def _backend(logs: Path, since: datetime) -> Check:
    check = "backend"
    began: list[tuple[datetime, str, Path]] = []
    for path in logs.glob("backend-*.log"):
        try:
            first = _first_time(path)
        except OSError as error:
            return failed(check, _unreadable(path, error))
        if first is not None and first >= since:
            began.append((first, path.name, path))
    if not began:
        return failed(
            check,
            f"no backend log has begun since the latest load at {_when(since)}: open the "
            "Review tab, wait for Backend ready and run this again (runbook section 6, item 2)",
        )
    *_, newest = max(began)
    try:
        lines = _entries(newest)
    except OSError as error:
        return failed(check, _unreadable(newest, error))
    # The last line `BackendProcess` writes on a start or a stop says where the backend stands.
    said = [entry for entry in lines if entry.text.startswith((STARTING, HEALTHY, *STOPPING))]
    if said and said[-1].text.startswith(HEALTHY):
        return passed(
            check, f"{newest.name}, the newest since the load, says the backend is healthy"
        )
    if said and said[-1].text.startswith(STOPPING):
        return failed(
            check,
            f"{newest.name}, the newest since the load, says the backend stopped at "
            f"{_when(said[-1].time)}: open the Review tab, wait for Backend ready and run this "
            "again (runbook section 6, item 2)",
        )
    return failed(
        check,
        f"{newest.name}, the newest since the load, does not say the backend is healthy; read it "
        "(a backend that cannot be located means uv is not on the PATH SOLIDWORKS sees)",
    )


def _profile(profile: Path, repo: Path) -> Check:
    check = "profile"
    try:
        loaded = load_profile(profile)
    except ProfileUnreadable as refusal:
        return failed(
            check,
            f"{refusal.reason}; the default is {DEFAULT_PATH}, and when the settings file names "
            "another, pass it with --profile (runbook section 5)",
        )
    except ProfileInvalid:
        # Its reason can quote a value from the file, which never leaves the machine.
        return failed(
            check,
            "the profile does not validate: run the validation in runbook section 5 to see which "
            "fields",
        )
    if _is_example(loaded, repo / EXAMPLE):
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


def _is_example(loaded: StandardsProfile, example: Path) -> bool:
    """The same profile as the example, whatever its line endings or comments."""
    try:
        return load_profile(example).model_dump() == loaded.model_dump()
    except ProfileError:
        return False


def _uv() -> Check:
    if shutil.which("uv"):
        return passed(
            "uv", "uv is on this shell's PATH; the backend check proves SOLIDWORKS found it"
        )
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
            # No optional lock: a plain `status` rewrites a stale index under index.lock.
            ["git", "--no-optional-locks", "-C", str(repo), *args],
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
    # Explicitly: `status.showUntrackedFiles=no` would hide untracked files from a plain status.
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
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
        # Not by name: a branch can name a customer or a design, and the engineer did not type it.
        problems.append("HEAD is not on main")
    changed = status.stdout.splitlines()
    if changed:
        problems.append(f"{len(changed)} changed or untracked path(s): run git status there")
    if problems:
        return failed(check, "; ".join(problems))
    return passed(check, "on main, with nothing changed or untracked")
