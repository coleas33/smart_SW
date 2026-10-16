"""The report page and the record of what a benchmark attempt sent (feature 014
`contracts/report.md`; `contracts/benchmark-run.md` 12).

## The prompts record (FR-057, D11)

The system prompt is built in memory and no event carries it or any user message, so a benchmark
attempt writes `<package folder>/prompts.json`: `prompts_version` 1, `system` (`ReviewRun.system`)
and `user_messages` (every `role: user` entry of `ReviewRun.messages`, in order; message `k`
opens turn `k`). It is written before the first turn and again when the attempt ends, so an
attempt that raised still records what it sent first. Only the benchmark attempt writes it
(`cli._review_fn`): the pane's folders and the `review` command's gain nothing, and no event
carries it (plan decision INT-1). A folder without it reads "not recorded". The first section is
the record's one format, one writer and one reader.

## The report (FR-034, FR-021, FR-051; RP-1 to RP-7)

`build_report` writes one static page, `index.html`, and transcript pages for kept and failed
attempts of each run folder, from run folders alone: every scored number is the scorecard's
(`read_scorecard`, the one reader), counted from its id lists where it is rendered by the ledger's
rule (`compare.format_count`); the matcher is never run and no key is read. Streams are found
through `event_stream`, plain or packed, and read through `replay_events` (RF-29, RF-83).
Failed attempts' billed usage and served models come from `runner.attempt_facts`, independently
of where their transcript walk stops; each call's full result through `read_stored_result`,
embedded escaped (RF-30). Every recorded string is escaped; the pages hold one inline style
block, no external resource and no build time. Statuses, costs and price sources are rendered from
the scorecard; failed attempts' billed usage and cost stay separate from every score (T216, T217).
"""

from __future__ import annotations

import contextlib
import html
import json
import os
import re
import secrets
import shutil
import stat
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

from swreview import atomic
from swreview.agent.events import event_stream, replay_events
from swreview.agent.providers import AgentEvent, ProviderName, TokenUsage, usage_from_body
from swreview.agent.runner import SESSION_FILE_NAME
from swreview.benchmark import runner
from swreview.benchmark.answers import AnswerLog, AnswerPoint, read_answer_log
from swreview.benchmark.compare import distinct_run_dirs, format_count
from swreview.benchmark.origins import deciding_false_alarm_ids
from swreview.benchmark.prices import Cost
from swreview.benchmark.recording import bracketing_step, round_kind
from swreview.benchmark.runner import SAVED_SET_FILE, RunProvenance, load_provenance
from swreview.benchmark.scorecard import (
    NOT_ASSESSED,
    SCORECARD_FILE,
    UNKNOWN,
    FailedAttempt,
    PackageScore,
    Scorecard,
    UnscoredPackage,
    read_scorecard,
    sum_or_none,
)
from swreview.benchmark.sets import (
    REPO_ROOT,
    BenchmarkPackageRef,
    checkout_relative,
    load_saved_set,
)
from swreview.findings import ReviewModel
from swreview.ir.loader import AnswerKeyAccessError, load_package, reject_answer_key_path
from swreview.report.names import component_names
from swreview.report.session import ReviewSession, SessionUsage, load_session
from swreview.tools.registry import Unstored, UnstoredReason, read_stored_result

if TYPE_CHECKING:
    from swreview.agent.runner import ReviewRun

__all__ = [
    "PROMPTS_FILE",
    "PROMPTS_VERSION",
    "REPORT_GENERATOR",
    "PromptsRecord",
    "ReportBuilt",
    "ReportError",
    "build_report",
    "deciding_false_alarm_ids",
    "read_prompts_record",
    "write_prompts_record",
]

# --- the prompts record ---------------------------------------------------------------------

PROMPTS_FILE = "prompts.json"
PROMPTS_VERSION = 1


class PromptsRecord(ReviewModel):
    """One package folder's `prompts.json` (data-model section 7, **PromptsRecord**)."""

    prompts_version: Literal[1]
    system: str
    """`ReviewRun.system`, byte for byte."""
    user_messages: list[str]
    """Every `role: user` message of `ReviewRun.messages`, in order: the opening message, then
    one per answer turn as sent."""


def write_prompts_record(run: ReviewRun, folder: Path) -> None:
    """Write what `run` has sent so far to `folder / PROMPTS_FILE`, through the one atomic writer.

    Before the first turn no user message is in the history yet (`ReviewRun.start` sends
    `opening_message`, and `_ask` appends it), so the record then holds the opening message the
    first turn will send. UTF-8 bytes with `\\n` line endings and a final newline.
    """
    sent = [message["content"] for message in run.messages if message.get("role") == "user"]
    record = PromptsRecord(
        prompts_version=PROMPTS_VERSION,
        system=run.system,
        user_messages=sent if sent else [run.opening_message],
    )
    atomic.write_atomic(
        Path(folder) / PROMPTS_FILE, (record.model_dump_json(indent=2) + "\n").encode("utf-8")
    )


def read_prompts_record(folder: Path) -> PromptsRecord | None:
    """The record in `folder`, or `None` when it holds none (a folder written before the record).

    A file that is not JSON or does not validate raises its `ValueError` (pydantic's
    `ValidationError` is one) to the caller, which names it.
    """
    try:
        raw = (Path(folder) / PROMPTS_FILE).read_bytes()
    except FileNotFoundError:
        return None
    return PromptsRecord.model_validate_json(raw)


# --- the report (`contracts/report.md`) ------------------------------------------------------

REPORT_GENERATOR = "swreview benchmark report"
GENERATOR_TAG = f'<meta name="generator" content="{REPORT_GENERATOR}">'
"""What marks a folder's `index.html` as a previous report this command may replace."""

INDEX_FILE = "index.html"
TRANSCRIPTS_DIR = "transcripts"

NOT_RECORDED = "not recorded"
PROMPTS_UNREADABLE = "the prompts record is unreadable"
NO_SESSION = "no session was recorded"
SESSION_UNREADABLE = "the session is unreadable"
ANSWER_LOG_UNREADABLE = "the answer log is unreadable"
NO_EVENTS = "no events were recorded"
UNREADABLE_FROM = "the event log is unreadable from line {line}"
MALFORMED_FROM = "{run}/{package}: the event log is unreadable from seq {seq}"
"""A body the walk cannot read, read as an unreadable line is (owner decision 83A)."""
NOT_IN_THE_LOG = "this turn is not in the event log"
NOT_SHOWN = "not shown: the log is unreadable before this turn"
"""A recorded turn past a log that stopped early, at a damaged body or an unreadable line (91A)."""
EXPLANATION_PASS = "explanation pass"
CODE_BEFORE_THE_FIRST_TURN = "Code before the first turn"
UNSTORED: dict[UnstoredReason, str] = {
    "missing": "full result not stored",
    "other_session": "a stale result from another session in this folder",
    "unreadable": "the stored result is unreadable",
    "other_call": "a result recorded for another call",
}
"""Each `Unstored` reason as the transcript names it (`report.md` 5), never guessed."""

NOT_IN_A_FILE_NAME = frozenset('<>:"|?*')
"""The printable characters Windows refuses in a file name; control characters too."""

WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{n}" for n in range(1, 10)),
        *(f"LPT{n}" for n in range(1, 10)),
    }
)
"""The device names Windows reserves, with or without an extension."""

BUILDING = ".building"
"""The suffix of the sibling folder a build is written into before it is put in place (83A)."""

STAGED = (f"{TRANSCRIPTS_DIR}.new", f"{TRANSCRIPTS_DIR}.old", f"{INDEX_FILE}.new")
"""The names an in-place copy stages beside a report before renaming them into place (owner
decision 96A). A copy that was killed may leave them, and so may a user: a folder holding one is
refused, never cleared; this command deletes one only when this same call made it exclusively and
then met an `OSError` or a refusal (97A, 101A)."""

STRANDED_FILE = "STRANDED-by-swreview-benchmark-report.txt"
"""Written into a previous report a build moved aside and could not move back, so that no later
build's sweep takes it for its own and removes it (96A)."""

ORPHAN_MIN_AGE_S = 600
"""A build's sibling changed within this many seconds is never swept: another build may be
writing it. Chosen over detecting a folder held open by another build, which Windows does not
report without trying to remove it (96A)."""

PREVIOUS = ".previous"
"""The suffix a previous report is moved aside under while the build is moved in (83A, 91A)."""

KEY_GUARD_REASON = "a run folder under it is never read by the report"
"""The reason the key guard's refusal names for a run folder under a key path."""

STYLE = """body{font-family:system-ui,sans-serif;margin:1.5rem;color:#1b1b1b;background:#fff}
table{border-collapse:collapse;margin:.5rem 0}
th,td{border:1px solid #ccc;padding:.25rem .5rem;text-align:left;vertical-align:top}
pre{white-space:pre-wrap;word-break:break-word;background:#f6f6f6;padding:.5rem}
.note{color:#555}
details{margin:.25rem 0}
section{margin:1rem 0}"""


class ReportError(ValueError):
    """A run folder or an output folder this command refuses; one line naming it."""


@dataclass(frozen=True)
class ReportBuilt:
    """Where the page was written and how many transcript pages beside it."""

    index: Path
    transcripts: int
    removed: tuple[Path, ...] = ()
    """The siblings an earlier, killed build left, removed before this one (91A)."""
    warnings: tuple[str, ...] = ()
    """What this build left and could not remove, its report being in place (91A)."""


@dataclass(frozen=True)
class _Legend:
    """A package's component names, or the one line saying why there are none."""

    names: dict[str, str] | None
    note: str | None


@dataclass(frozen=True)
class _FailedLog:
    """One failed transcript's events, with its billed facts from the shared attempt reader."""

    events: list[AgentEvent]
    malformed: int | None
    unreadable: tuple[int, ...]
    usage: TokenUsage | None
    served_models: list[str]


@dataclass(frozen=True)
class _Run:
    """One run folder as the report reads it, before any transcript is written."""

    path: Path
    name: str
    """The folder relative to the common parent of the run folders' parents, `/`-separated."""
    scorecard: Scorecard
    provenance: RunProvenance | None
    entries: dict[str, BenchmarkPackageRef]
    """The saved set's entries by package id, in saved order; empty when it does not load."""
    no_legend: str | None
    """Why no package of this run has a legend, when the saved set is absent or fails."""
    streams: dict[str, Path]
    """Each scored package's stream, as `event_stream` found it."""
    failed_logs: dict[str, _FailedLog]
    """Failed attempts keyed by their scorecard rows' exact run-relative folders."""

    @property
    def reasoning_label(self) -> str:
        """Reasoning tokens' name for the run's provider (ab-harness 10.8)."""
        provider = self.provenance.provider if self.provenance is not None else None
        return "thoughts" if provider == ProviderName.GEMINI.value else "reasoning"

    def transcript(self, package_id: str) -> str:
        """The package's transcript page, relative to the output folder, `/`-separated."""
        return f"{TRANSCRIPTS_DIR}/{self.name}/{package_id}.html"

    def failed_transcript(self, attempt: FailedAttempt) -> str:
        """A separate page for each failed row; recorded ids and folders are never filenames."""
        ordinal = self.scorecard.failed_attempts.index(attempt) + 1
        return f"{TRANSCRIPTS_DIR}/{self.name}/failed-attempts/{ordinal}.html"


def build_report(
    run_dirs: Sequence[Path | str], out: Path | str, *, root: Path = REPO_ROOT
) -> ReportBuilt:
    """Build `<out>/index.html` and one transcript page per scored package of each run folder.

    Refuses, before writing anything (`report.md` 7): a folder named twice; a run folder under a
    key path; one with no `scorecard.json`; a scorecard `read_scorecard` refuses; a scored package
    id that cannot name a file, or two that are one file name case-folded; an `out` at or under a
    run folder, or holding anything but a previous report; run folders on two drives, or in the
    home folder with a common parent at or above it (owner decision 84A). A saved set or package
    under a key path is refused with the key guard's message, and a package folder holding both
    stream forms with `event_stream`'s, before anything is written too. Every number is the
    scorecard's; nothing is written into a run folder; no build time is written, so two builds
    are byte-identical.

    The pages are written into a new sibling folder of `out` and put in place once all are
    written, so a build that fails part-way, on an `OSError` such as a path too long included,
    leaves a previous report as it was (owner decision 83A). In place means moved: the previous
    report aside, the build in, the previous one removed. Where `out` is or holds the working
    folder, or is a link, or the move fails, the build is copied into `out` instead, replacing
    its contents (owner decision 91A), staged beside them first (96A). Removing the old report
    is best effort: one that cannot be removed is named in `ReportBuilt.warnings`, the new report
    being in place. Folders a killed build left are swept first, only those that are ours by name,
    contents and age (`_remove_orphans`, 96A), named in `ReportBuilt.removed`, any kept named in
    `ReportBuilt.warnings`. The build needs write access to `out`'s parent.
    """
    out = Path(out)
    paths = distinct_run_dirs(run_dirs)
    for path in paths:
        reject_answer_key_path(path, KEY_GUARD_REASON)
    for path in paths:
        if not (path / SCORECARD_FILE).is_file():
            raise ReportError(
                f"{path}: no {SCORECARD_FILE}; run `swreview benchmark score` on it first"
            )
    scorecards = [read_scorecard(path) for path in paths]
    for path, scorecard in zip(paths, scorecards, strict=True):
        _refuse_package_ids_that_name_no_file(path, scorecard)
    _refuse_an_out_in_a_run_folder(out, paths)
    _refuse_a_foreign_out(out)

    names = _relative_names(paths)
    runs = [
        _read_run(path, name, scorecard, root=root)
        for path, name, scorecard in zip(paths, names, scorecards, strict=True)
    ]
    legends: dict[Path, _Legend] = {}
    for run in runs:
        for score in [*run.scorecard.per_package, *run.scorecard.failed_attempts]:
            entry = run.entries.get(score.package_id)
            if entry is not None and entry.path not in legends:
                legends[entry.path] = _legend(entry, root=root)

    target = out.resolve()
    in_place = _in_place(out, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    removed, stuck = _remove_orphans(target)
    building = _sibling(target, BUILDING)
    building.mkdir()
    try:
        _write_page(building / INDEX_FILE, _index_page(runs))
        written = 0
        for run in runs:
            for score in run.scorecard.per_package:
                page = _transcript_page(run, score, _legend_of(run, score, legends))
                _write_page(building / Path(*run.transcript(score.package_id).split("/")), page)
                written += 1
            for attempt in run.scorecard.failed_attempts:
                page = _transcript_page(run, attempt, _legend_of(run, attempt, legends))
                _write_page(building / Path(*run.failed_transcript(attempt).split("/")), page)
                written += 1
        leftovers = _place(building, target, in_place=in_place)
    except BaseException:
        _remove(building)
        raise
    return ReportBuilt(
        index=target / INDEX_FILE,
        transcripts=written,
        removed=removed,
        warnings=stuck + tuple(_leftover_warning(leftover) for leftover in leftovers),
    )


def _legend_of(
    run: _Run, score: PackageScore | FailedAttempt, legends: dict[Path, _Legend]
) -> _Legend:
    """The package's legend, or why the run shows none."""
    if run.no_legend is not None:
        return _Legend(names=None, note=run.no_legend)
    entry = run.entries.get(score.package_id)
    if entry is None:
        return _Legend(
            names=None,
            note=f"the saved set names no package {score.package_id}, so no component names "
            "are shown",
        )
    return legends[entry.path]


def _sibling(target: Path, suffix: str) -> Path:
    """A new folder name beside `target`: `.<name>.<random>` and the suffix. Made with
    `Path.mkdir`, never `tempfile.mkdtemp`, whose mode 0o700 becomes a Windows ACL closed to
    everyone but the owner from Python 3.12.4 on (owner decision 91A)."""
    return target.with_name(f".{target.name}.{secrets.token_hex(8)}{suffix}")


def _in_place(out: Path, target: Path) -> bool:
    """Whether the build is copied into `out` rather than moved: `out` is a link, whose target
    the copy updates, or is or holds the working folder, which cannot be moved (91A)."""
    if out.is_symlink() or _is_junction(out):
        return True
    return target.exists() and Path.cwd().resolve().is_relative_to(target)


def _place(built: Path, target: Path, *, in_place: bool) -> tuple[Path, ...]:
    """Put the finished build at `target`; the folders this left and could not remove.

    Moved when it can be: a previous report, or an empty folder, aside, the build in, the
    previous one removed. Copied in place when `in_place`, or when the previous report cannot be
    moved aside (owner decision 91A). When the build cannot be moved in, the previous report is
    moved back first, on any exception, an interruption included; then an `OSError` falls back to
    the copy and anything else is raised (owner decision 96A).
    """
    if in_place:
        return _left(_copy_in_place(built, target), _remove(built))
    if not target.exists():
        built.rename(target)
        return ()
    previous = _sibling(target, PREVIOUS)
    try:
        target.rename(previous)
    except OSError:
        return _left(_copy_in_place(built, target), _remove(built))
    strays = _strays(previous)
    if strays:
        refusal = ReportError(
            f"{target} gained {', '.join(strays)} while the report was being built; it is left in "
            "place with the previous report, and nothing was replaced: move it elsewhere and "
            "build again"
        )
        _move_back(previous, target, refusal)
        raise refusal
    try:
        built.rename(target)
    except BaseException as failure:
        _move_back(previous, target, failure)
        if not isinstance(failure, OSError):
            raise
        return _left(_copy_in_place(built, target), _remove(built))
    return _left(_remove(previous))


def _strays(folder: Path) -> list[str]:
    """What a folder just moved aside as the previous report holds that this command did not
    write there, written after `--out` was checked (owner decision 101A): any name but
    `index.html` and `transcripts/`, and either of those when it is not what this command
    writes. Empty when the folder is empty or a report."""
    names = sorted(child.name for child in folder.iterdir())
    strays = [name for name in names if name not in (INDEX_FILE, TRANSCRIPTS_DIR)]
    if strays or _holds_a_report(folder, index_required=False):
        return strays
    return names


def _left(*folders: Path | None) -> tuple[Path, ...]:
    return tuple(folder for folder in folders if folder is not None)


def _move_back(previous: Path, target: Path, failure: BaseException) -> None:
    """Put the previous report back at `target`. When that fails too, mark it so that no later
    build's sweep removes it, and refuse, naming where it is; a mark that cannot be written is
    named on the refusal too, never dropped (owner decisions 96A, 97A)."""
    try:
        previous.rename(target)
    except OSError:
        message = (
            f"the previous report was moved aside to {previous} and could not be moved back to "
            f"{target}; move it back by hand"
        )
        try:
            (previous / STRANDED_FILE).write_bytes(
                (
                    f"swreview benchmark report moved the previous report in this folder aside "
                    f"from {target} and could not move it back. Move it back by hand, then "
                    "delete this file; no build removes this folder while it holds this file.\n"
                ).encode()
            )
        except OSError as unmarked:
            message += (
                f"; it could not be marked against removal ({unmarked}), so move it back before "
                "building again"
            )
        raise ReportError(message) from failure


def _copy_in_place(built: Path, target: Path) -> Path | None:
    """Replace `target`'s report with the build's, keeping the folder itself (owner decision 96A);
    the old transcripts' folder, when it could not be removed afterwards.

    The build is copied beside the report first, as `transcripts.new` and `index.html.new`, each
    made exclusively (a folder made with `mkdir`, a file opened `"xb"`), so a name someone else
    made, before or after the check, is refused and never touched (owner decisions 97A, 101A).
    Then the old `transcripts/` is renamed aside to `transcripts.old`, `transcripts.new` into its
    place, and `index.html.new` over `index.html`; `transcripts.old` is removed, best effort, only
    when this call renamed `transcripts/` to it. On any exception the old `transcripts/` is put
    back; on an `OSError` or a refusal, not a kill, the staging names this call made, and only
    those, are removed too, so the previous report stays whole and the next build is not refused
    for them (101A). A kill can still leave them, and the next build then refuses, naming them.
    """
    staged = _staging_held(target)
    if staged:
        raise ReportError(_staging_refusal(target, staged))
    staged_transcripts, old_transcripts, staged_index = (target / name for name in STAGED)
    transcripts = target / TRANSCRIPTS_DIR
    made: list[Path] = []  # the staging names this call made, exclusively: all it may remove
    aside = False  # whether this call renamed `transcripts/` to `transcripts.old`
    try:
        _make_exclusively(staged_transcripts, target, made)
        if (built / TRANSCRIPTS_DIR).is_dir():
            shutil.copytree(built / TRANSCRIPTS_DIR, staged_transcripts, dirs_exist_ok=True)
        _make_exclusively(staged_index, target, made, copy_of=built / INDEX_FILE)
        if transcripts.exists():
            transcripts.rename(old_transcripts)
            aside = True
        staged_transcripts.rename(transcripts)
        made.remove(staged_transcripts)
        try:
            os.replace(staged_index, target / INDEX_FILE)
        except BaseException:
            transcripts.rename(staged_transcripts)
            made.append(staged_transcripts)
            raise
        made.remove(staged_index)
    except BaseException as failure:
        if aside and not os.path.lexists(transcripts):
            old_transcripts.rename(transcripts)
            aside = False
        if isinstance(failure, (OSError, ReportError)):
            for path in made:
                _remove_made(path)
        raise
    return _remove(old_transcripts) if aside else None


def _make_exclusively(
    path: Path, target: Path, made: list[Path], *, copy_of: Path | None = None
) -> None:
    """Make the staging name `path`, a folder, or a file holding `copy_of`'s bytes, failing if
    anything is already there; refused naming it then, and recorded in `made` once made."""
    try:
        if copy_of is None:
            path.mkdir()
        else:
            handle = path.open("xb")
    except FileExistsError:
        raise ReportError(_staging_refusal(target, [path.name])) from None
    made.append(path)
    if copy_of is not None:
        with handle, copy_of.open("rb") as source:
            shutil.copyfileobj(source, handle)


def _remove_made(path: Path) -> None:
    """Remove a staging name this call made, best effort."""
    if path.is_dir() and not path.is_symlink():
        _remove(path)
    else:
        with contextlib.suppress(OSError):
            path.unlink()


def _is_junction(path: Path) -> bool:
    """Whether `path` is a Windows junction: `Path.is_junction` where it exists (Python 3.12), the
    mount-point reparse tag of `os.lstat` on Windows otherwise, never elsewhere (owner decision
    95A: the reviewer supports Python 3.11)."""
    method = getattr(Path, "is_junction", None)
    if method is not None:
        return bool(method(path))
    if os.name != "nt":
        return False
    try:
        return os.lstat(path).st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    except OSError:
        return False


def _rmtree(folder: Path) -> None:
    """`shutil.rmtree`, retrying a read-only entry with `_writable`: through `onexc` on Python
    3.12, through `onerror`, which hands over `exc_info` instead, on 3.11 (95A)."""
    if sys.version_info >= (3, 12):
        shutil.rmtree(folder, onexc=_writable)
    else:
        shutil.rmtree(folder, onerror=_writable)


def _writable(function: Any, name: str, error: Any) -> None:
    """`shutil.rmtree`'s retry for a read-only entry: on Windows, clear the flag and try once
    more; elsewhere a file's own mode never stops its removal, so the error stands. `error` is the
    exception (`onexc`) or its `exc_info` (`onerror`)."""
    if os.name != "nt":
        raise error if isinstance(error, BaseException) else error[1]
    os.chmod(name, stat.S_IWRITE)
    function(name)


def _remove(folder: Path) -> Path | None:
    """Remove a folder this command wrote, read-only flags cleared; best effort: the folder
    when it is still there afterwards, else `None`, never reporting a removal that did not
    happen (owner decision 96A)."""
    with contextlib.suppress(OSError):
        _rmtree(folder)
    return folder if os.path.lexists(folder) else None


def _build_sibling(name: str) -> re.Pattern[str]:
    """The names this command gives the folders beside an `--out` named `name`: its own random
    part, 16 hexadecimal digits, or an earlier build's `tempfile.mkdtemp` part, 8 of
    `[a-z0-9_]`, then `.building` or `.previous`; nothing else (owner decision 96A)."""
    return re.compile(
        rf"\.{re.escape(name)}\.(?:[0-9a-f]{{16}}|[a-z0-9_]{{8}})"
        rf"(?:{re.escape(BUILDING)}|{re.escape(PREVIOUS)})"
    )


def _remove_orphans(target: Path) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    """The folders a killed build of `target` left beside it, swept, best effort: those removed,
    and a warning for each kept or not removable, both to be named (owner decisions 91A, 96A).

    Only a real folder (no link, no junction) named as `_build_sibling` names them is considered,
    and one is removed only when `_why_kept` finds no reason to keep it.
    """
    if not target.parent.is_dir():
        return (), ()
    pattern = _build_sibling(target.name)
    removed: list[Path] = []
    warnings: list[str] = []
    for child in sorted(target.parent.iterdir()):
        if not pattern.fullmatch(child.name):
            continue
        if child.is_symlink() or _is_junction(child) or not child.is_dir():
            continue
        try:
            reason = _why_kept(child, target)
        except OSError as unread:
            reason = f"could not read it ({unread})"
        if reason is not None:
            warnings.append(f"kept {child}: {reason}")
        elif _remove(child) is None:
            removed.append(child)
        else:
            warnings.append(
                f"could not remove {child}, left by an earlier build; remove it by hand"
            )
    return tuple(removed), tuple(warnings)


def _why_kept(sibling: Path, target: Path) -> str | None:
    """Why a folder named as a build's sibling is not swept, or `None` (owner decision 96A): it
    is a previous report a build could not move back; it holds anything but a report; it changed
    within `ORPHAN_MIN_AGE_S`; or it is a previous report while `target` holds none, so it may be
    the only copy."""
    if (sibling / STRANDED_FILE).exists():
        return (
            "a build moved this previous report aside and could not move it back; move it back "
            "by hand"
        )
    staged = _staging_held(sibling)
    if staged:
        return (
            f"it holds {', '.join(staged)}, a name an in-place copy stages under; delete it by "
            "hand if an interrupted build left it"
        )
    if not _holds_a_report(sibling, index_required=False):
        return "it holds files this command did not write"
    if time.time() - _youngest(sibling) < ORPHAN_MIN_AGE_S:
        return (
            f"it changed within the last {ORPHAN_MIN_AGE_S // 60} minutes, so another build may "
            "be writing it"
        )
    if sibling.name.endswith(PREVIOUS) and not (
        target.is_dir() and _holds_a_report(target, index_required=True)
    ):
        return f"{target} holds no report, so this may be the only copy of the previous one"
    return None


def _youngest(folder: Path) -> float:
    """The latest modification time of `folder` and of everything beneath it, links unfollowed
    and junctions skipped, their own times too (owner decision 97A)."""
    youngest = os.lstat(folder).st_mtime
    pending = [folder]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                if _is_junction(Path(entry.path)):
                    continue
                youngest = max(youngest, entry.stat(follow_symlinks=False).st_mtime)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
    return youngest


def _leftover_warning(leftover: Path) -> str:
    """The one line naming a folder this build could not remove, its report being in place."""
    if leftover.name.endswith(PREVIOUS):
        what = "the previous report"
    elif leftover.name == STAGED[1]:
        what = "the previous report's transcripts; the next build refuses until it is gone"
    else:
        what = "this build's copy"
    return f"could not remove {leftover}, {what}; the new report is in place, so remove it by hand"


def _refuse_package_ids_that_name_no_file(run: Path, scorecard: Scorecard) -> None:
    """Each scored package id names a folder and a transcript file: refuse one that cannot, and
    two that are one file name where case is not told apart (owner decision 84A)."""
    seen: dict[str, str] = {}
    for score in scorecard.per_package:
        package_id = score.package_id
        reason = _why_no_file_name(package_id)
        if reason is not None:
            raise ReportError(
                f"{run}: package id {package_id!r} cannot name a transcript file: {reason}"
            )
        earlier = seen.setdefault(package_id.casefold(), package_id)
        if earlier != package_id:
            raise ReportError(
                f"{run}: package ids {earlier!r} and {package_id!r} are one file name where "
                "case is not told apart"
            )


def _why_no_file_name(name: str) -> str | None:
    """Why `name` cannot be a file name on every platform the reviewer runs on, or `None`."""
    if not name:
        return "it is empty"
    if "/" in name or "\\" in name:
        return "it holds a path separator"
    if name == ".":
        return "it is '.'"
    if ".." in name:
        return "it holds '..'"
    if any(character in NOT_IN_A_FILE_NAME or ord(character) < 32 for character in name):
        return "it holds a character Windows does not allow in a file name"
    if name.endswith((".", " ")):
        return "it ends in a dot or a space"
    if name.split(".", 1)[0].upper() in WINDOWS_RESERVED:
        return "it is a name Windows reserves"
    return None


def _refuse_an_out_in_a_run_folder(out: Path, runs: Sequence[Path]) -> None:
    """The report writes nothing into a run folder, so `--out` lies outside every one (84A)."""
    target = out.resolve()
    for run in runs:
        if target.is_relative_to(run.resolve()):
            raise ReportError(
                f"{out} lies in the run folder {run}; the report writes nothing into a run "
                "folder: choose a folder outside it"
            )


def _refuse_a_foreign_out(out: Path) -> None:
    """`--out` is absent, empty, or a previous report (`_holds_a_report`, its `index.html`
    required). Refused on their own line: a `transcripts/` that is a link (96A), and a staging
    name or the marker of a report a build could not move back, each with what to do (97A)."""
    if not out.exists():
        return
    if out.is_dir():
        transcripts = out / TRANSCRIPTS_DIR
        if transcripts.is_symlink() or _is_junction(transcripts):
            raise ReportError(
                f"{transcripts} is a link; the report replaces that folder and will not write "
                "through a link: remove the link, or choose another folder"
            )
        staged = _staging_held(out)
        if staged:
            raise ReportError(_staging_refusal(out, staged))
        if (out / STRANDED_FILE).exists():
            raise ReportError(
                f"{out / STRANDED_FILE} marks a previous report a build could not move back; if "
                "you have moved it back by hand, delete this file and build again"
            )
        if not any(out.iterdir()) or _holds_a_report(out, index_required=True):
            return
    raise ReportError(f"{out} holds files this command did not write; choose an empty folder")


def _staging_held(folder: Path) -> list[str]:
    """The staging names `folder` holds, file, folder or link (owner decision 97A)."""
    return [name for name in STAGED if os.path.lexists(folder / name)]


def _staging_refusal(folder: Path, names: Sequence[str]) -> str:
    """The one line refusing a folder holding staging names, every one found named (101A)."""
    if len(names) == 1:
        return (
            f"{folder / names[0]} is a name this command stages an in-place copy under, so it may "
            "be what an interrupted build left, or yours; this command never deletes it: delete "
            "it, or move it elsewhere, and build again"
        )
    return (
        f"{folder} holds {', '.join(names)}, names this command stages an in-place copy under, so "
        "they may be what an interrupted build left, or yours; this command never deletes them: "
        "delete them, or move them elsewhere, and build again"
    )


def _holds_a_report(folder: Path, *, index_required: bool) -> bool:
    """Whether `folder` holds only what this command leaves: an `index.html` carrying the
    generator tag (needed only when `index_required`) and a `transcripts/` that is a folder and
    no link (owner decisions 96A, 97A: a staging name is no part of a report)."""
    held = {child.name for child in folder.iterdir()}
    if not held <= {INDEX_FILE, TRANSCRIPTS_DIR}:
        return False
    index = folder / INDEX_FILE
    if INDEX_FILE in held:
        if not index.is_file() or GENERATOR_TAG.encode("utf-8") not in index.read_bytes():
            return False
    elif index_required:
        return False
    transcripts = folder / TRANSCRIPTS_DIR
    return TRANSCRIPTS_DIR not in held or (
        transcripts.is_dir() and not transcripts.is_symlink() and not _is_junction(transcripts)
    )


def _relative_names(paths: Sequence[Path]) -> list[str]:
    """Each run folder relative to the common parent of the folders' parents.

    Refused when there is none (two drives), and when two or more run folders, one in the home
    folder, have the home folder or a folder above it as their common parent: the names would then
    carry the home folder's own folders, `Users/<name>/AppData/...` (owner decision 84A). A lone
    run folder is named by its own name, and is never refused for it; nor is any where the
    platform names no home folder (owner decision 92A).
    """
    resolved = [path.resolve() for path in paths]
    try:
        common = Path(os.path.commonpath([str(path.parent) for path in resolved]))
    except ValueError:
        raise ReportError(
            "the run folders have no common parent (they lie on different drives); "
            "copy them under one folder first"
        ) from None
    home = _home()
    if home is not None and len(resolved) > 1 and home.is_relative_to(common):
        for path, full in zip(paths, resolved, strict=True):
            if full.is_relative_to(home):
                raise ReportError(
                    f"{path} lies in the home folder and the run folders' common parent {common} "
                    "is at or above it, so the report would name the home folder's folders; copy "
                    "the run folders under one study folder first"
                )
    return [path.relative_to(common).as_posix() for path in resolved]


def _home() -> Path | None:
    """The home folder, or `None` where the platform names none: then none is guarded (92A)."""
    try:
        return Path.home().resolve()
    except RuntimeError:
        return None


def _read_run(path: Path, name: str, scorecard: Scorecard, *, root: Path) -> _Run:
    """A run folder's provenance, saved set and streams; a refusal propagates."""
    saved = path / SAVED_SET_FILE
    entries: dict[str, BenchmarkPackageRef] = {}
    no_legend: str | None = None
    if not saved.is_file():
        no_legend = "the run folder holds no saved set, so no component names are shown"
    else:
        try:
            entries = {ref.package_id: ref for ref in load_saved_set(saved, root=root).packages}
        except AnswerKeyAccessError:
            raise
        except (OSError, ValueError):
            no_legend = "the run folder's saved set does not load, so no component names are shown"
    return _Run(
        path=path,
        name=name,
        scorecard=scorecard,
        provenance=load_provenance(path),
        entries=entries,
        no_legend=no_legend,
        streams={
            score.package_id: event_stream(runner.resolve_attempt_folder(path, score.package_id))
            for score in scorecard.per_package
        },
        failed_logs={
            attempt.folder: _read_failed_log(runner.resolve_attempt_folder(path, attempt.folder))
            for attempt in scorecard.failed_attempts
        },
    )


def _read_failed_log(folder: Path) -> _FailedLog:
    facts = runner.attempt_facts(folder)
    unreadable: list[int] = []
    logged, malformed = _readable_prefix(
        list(replay_events(event_stream(folder), on_unreadable=unreadable.append))
    )
    usage = (
        SessionUsage.summed([round_.usage for round_ in facts.rounds], []).totals
        if facts.paid else None
    )
    return _FailedLog(
        events=logged,
        malformed=malformed,
        unreadable=tuple(unreadable),
        usage=usage,
        served_models=facts.served_models,
    )


def _legend(entry: BenchmarkPackageRef, *, root: Path) -> _Legend:
    """The package's component names, loaded once; the key guard's refusal propagates."""
    try:
        package = load_package(entry.path).package
    except AnswerKeyAccessError:
        raise
    except (OSError, ValueError):
        relative = checkout_relative(entry.path, root=root)
        saved = relative.as_posix() if relative is not None else str(entry.path)
        return _Legend(
            names=None,
            note=f"the package at {saved} does not load, so no component names are shown",
        )
    return _Legend(names=component_names(package), note=None)


def _write_page(path: Path, lines: list[str]) -> None:
    """UTF-8 bytes with `\\n` line endings, never `write_text`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _href(relative: str) -> str:
    """A relative link, each `/`-separated segment percent-encoded."""
    return "/".join(quote(segment, safe="") for segment in relative.split("/"))


def _page(title: str) -> list[str]:
    return [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        GENERATOR_TAG,
        f"<title>{_e(title)}</title>",
        f"<style>{STYLE}</style>",
        "</head>",
        "<body>",
    ]


def _cell(value: object) -> str:
    """A recorded value, or `unknown` when there is none (Principle I)."""
    return UNKNOWN if value is None else str(value)


def _recorded(record: RunProvenance | None, name: str) -> str:
    """A field of the run's provenance, or `unknown` when the run folder holds no record."""
    return _cell(getattr(record, name) if record is not None else None)


# --- the index page (`report.md` 4) ----------------------------------------------------------


def _index_page(runs: Sequence[_Run]) -> list[str]:
    lines = [*_page("Benchmark report"), "<h1>Benchmark report</h1>", "<h2>Run folders</h2>"]
    lines += [
        "<table>",
        _row(
            ["run", "study", "arm", "repetition", "provider", "model", "commit", "started"],
            header=True,
        ),
    ]
    for run in runs:
        record = run.provenance
        lines.append(
            _row(
                [
                    run.name,
                    _recorded(record, "lever"),
                    _recorded(record, "arm"),
                    _recorded(record, "rep"),
                    _recorded(record, "provider"),
                    _recorded(record, "model"),
                    _recorded(record, "commit"),
                    _cell(record.started_at.isoformat() if record else None),
                ]
            )
        )
    lines.append("</table>")
    priced = [
        (run, model)
        for run in runs
        if run.scorecard.price_table is not None
        for model in run.scorecard.price_table.models
    ]
    if priced:
        lines += [
            "<h2>Price table</h2>",
            "<table>",
            _row(
                ["run", "provider", "model", "price", "source", "date"],
                header=True,
            ),
        ]
        for run, model in priced:
            for name in ("input", "cached_input", "output"):
                price = getattr(model, name)
                lines.append(
                    _row(
                        [
                            run.name,
                            model.provider,
                            model.model,
                            name,
                            price.source,
                            price.date.isoformat(),
                        ]
                    )
                )
        lines.append("</table>")
    lines += [
        "<h2>Totals</h2>",
        "<table>",
        _row(
            [
                "run",
                "packages scored",
                "completed",
                "bound-reached",
                "stopped by class",
                "failed by kind and class",
                "status unknown",
                "total tokens",
                "cost",
                "wall clock s",
            ],
            header=True,
        ),
    ]
    for run in runs:
        aggregate = run.scorecard.aggregate
        per_package = run.scorecard.per_package
        tokens = format_count(aggregate.total_tokens)
        if aggregate.packages == 0:
            tokens = "no package scored"
        elif aggregate.total_tokens is None:
            tokens += (
                f" ({format_count(aggregate.packages - aggregate.packages_with_usage)} of "
                f"{format_count(aggregate.packages)} packages report no usage)"
            )
        seconds = sum_or_none([score.wall_clock_s for score in per_package])
        wall = format_count(seconds)
        if not per_package:
            wall = "no package scored"
        elif seconds is None:
            missing = sum(1 for score in per_package if score.wall_clock_s is None)
            wall += (
                f" ({format_count(missing)} of {format_count(len(per_package))} packages "
                "report no wall clock)"
            )
        statuses = Counter(_status(score) for score in per_package)
        stopped = Counter(
            {
                name.removeprefix("stopped: "): count
                for name, count in statuses.items()
                if name.startswith("stopped: ")
            }
        )
        failed = Counter(
            f"{row.kind}, {_cell(row.class_)}" for row in run.scorecard.unscored_packages
        )
        lines.append(
            _row(
                [
                    run.name,
                    format_count(len(per_package)),
                    format_count(statuses["completed"]),
                    format_count(statuses["bound-reached"]),
                    _counts(stopped),
                    _counts(failed),
                    format_count(statuses[UNKNOWN]),
                    tokens,
                    _cost(aggregate.cost),
                    wall,
                ]
            )
        )
    lines.append("</table>")
    for run in runs:
        billed = (
            _cost(run.scorecard.aggregate.failed_attempts_cost)
            if run.scorecard.failed_attempts else "none: no attempt failed"
        )
        lines.append(
            "<p>" + _e(
                f"{run.name}: billed by failed attempts, in no score: "
                f"{billed}"
            ) + "</p>"
        )
    for package_id in _case_order(runs):
        lines += _case_section(package_id, runs)
    lines += _failed_attempts(runs)
    lines += ["</body>", "</html>"]
    return lines


def _row(cells: Sequence[str], *, header: bool = False, raw: bool = False) -> str:
    tag = "th" if header else "td"
    return (
        "<tr>" + "".join(f"<{tag}>{cell if raw else _e(cell)}</{tag}>" for cell in cells) + "</tr>"
    )


def _case_order(runs: Sequence[_Run]) -> list[str]:
    """The first run folder's saved-set order, then any package only a later one holds, then any
    kept or failed package no saved set names, in scorecard order."""
    scored = {
        score.package_id
        for run in runs
        for score in (
            *run.scorecard.per_package,
            *run.scorecard.unscored_packages,
            *run.scorecard.failed_attempts,
        )
    }
    ordered: dict[str, None] = {}
    for run in runs:
        for package_id in run.entries:
            if package_id in scored:
                ordered.setdefault(package_id)
    for run in runs:
        for score in (
            *run.scorecard.per_package,
            *run.scorecard.unscored_packages,
            *run.scorecard.failed_attempts,
        ):
            ordered.setdefault(score.package_id)
    return list(ordered)


def _study_order(run: _Run) -> tuple[tuple[bool, str], tuple[bool, str], tuple[bool, int]]:
    """Study (`lever`), arm and repetition, `None` last."""
    record = run.provenance
    lever = record.lever if record is not None else None
    arm = record.arm if record is not None else None
    rep = record.rep if record is not None else None
    return (lever is None, lever or ""), (arm is None, arm or ""), (rep is None, rep or 0)


def _case_section(package_id: str, runs: Sequence[_Run]) -> list[str]:
    rows = sorted(
        (
            (run, score)
            for run in runs
            for score in [_case_score(run, package_id)]
            if score is not None
        ),
        key=lambda pair: _study_order(pair[0]),
    )
    scored = next((score for _, score in rows if isinstance(score, PackageScore)), None)
    tags = _tags(package_id, scored, runs) if scored is not None else "not scored: failed"
    lines = [f"<section><h2>{_e(package_id)}</h2>", f"<p>{_e(tags)}</p>"]
    lines += ["<table>"]
    lines.append(
        _row(
            [
                "run",
                "status",
                "held-out model-produced",
                "code-produced",
                "tuned-on",
                "false alarms",
                "tokens",
                "cost",
                "wall clock s",
                "transcript",
            ],
            header=True,
        )
    )
    for run, score in rows:
        record = run.provenance
        run_cell = (
            f"{run.name}, arm {_recorded(record, 'arm')}, repetition {_recorded(record, 'rep')}"
        )
        if not isinstance(score, PackageScore):
            attempts = [
                row for row in run.scorecard.failed_attempts if row.package_id == package_id
            ]
            last = next((row for row in attempts if row.folder == score.folder), None)
            link = (
                f'<a href="{_e(_href(run.failed_transcript(last)))}">transcript</a>'
                if last is not None
                else UNKNOWN
            )
            cells = [
                _e(run_cell),
                _e(_failed_status(score)),
                *[_e("not scored: failed")] * 4,
                _e(
                    "failed attempts: "
                    + "; ".join(
                        f"attempt {row.attempt}: "
                        f"{_tokens(run.failed_logs[row.folder].usage, run.reasoning_label)}"
                        for row in attempts
                    )
                ),
                _e(
                    "failed attempts: "
                    + "; ".join(f"attempt {row.attempt}: {_cost(row.cost)}" for row in attempts)
                ),
                UNKNOWN,
                link,
            ]
            lines.append(_row(cells, raw=True))
            continue
        link = f'<a href="{_e(_href(run.transcript(package_id)))}">transcript</a>'
        cells = [
            _e(run_cell),
            _e(_status(score)),
            _e(_defects(score, tag="held_out", producer="model", headline=True)),
            _e(_defects(score, tag=None, producer="code")),
            _e(_defects(score, tag="tuned_on", producer="model")),
            _e(_false_alarms(score)),
            _e(_tokens(score.usage, run.reasoning_label)),
            _e(_cost(score.cost)),
            _e(format_count(score.wall_clock_s)),
            link,
        ]
        lines.append(_row(cells, raw=True))
    lines += ["</table>", "</section>"]
    return lines


def _case_score(
    run: _Run, package_id: str
) -> PackageScore | UnscoredPackage | FailedAttempt | None:
    return next(
        (
            score
            for score in (
                *run.scorecard.per_package,
                *run.scorecard.unscored_packages,
                *reversed(run.scorecard.failed_attempts),
            )
            if score.package_id == package_id
        ),
        None,
    )


def _status(score: PackageScore) -> str:
    if score.run_status.kind == "behavioural":
        return f"stopped: {_cell(score.run_status.class_)}"
    if score.bound_reached:
        return "bound-reached"
    return "completed" if score.run_status.kind == "completed" else UNKNOWN


def _failed_status(score: UnscoredPackage | FailedAttempt) -> str:
    return f"failed: infrastructure, {_cell(score.class_)}"


def _counts(counts: Counter[str]) -> str:
    return (
        "; ".join(f"{name}: {format_count(count)}" for name, count in sorted(counts.items()))
        or "none"
    )


def _money(amount: float) -> str:
    """Keep sub-cent spend visible, including amounts smaller than any fixed decimal place."""
    if amount == 0:
        return "0"
    if abs(amount) < 0.01:
        return f"{amount:.6g}"
    return str(int(amount)) if float(amount).is_integer() else f"{amount:.2f}"


def _cost(cost: Cost) -> str:
    """Render the recorded amount, reasons and basis; pricing never runs in the report."""
    if cost.synthetic:
        return "synthetic, not priced"
    value = f"USD {_money(cost.amount)}" if cost.amount is not None else UNKNOWN
    if cost.amount is None and cost.missing:
        value += f" ({'; '.join(cost.missing)})"
    if cost.basis:
        value += "; " + "; ".join(cost.basis)
    return value


def _failed_attempts(
    runs: Sequence[_Run], *, package_id: str | None = None, prefix: str = ""
) -> list[str]:
    attempts = [
        (run, attempt)
        for run in runs
        for attempt in run.scorecard.failed_attempts
        if package_id is None or attempt.package_id == package_id
    ]
    if not attempts:
        return []
    lines = [
        "<h2>Failed attempts</h2>",
        "<table>",
        _row(
            [
                "run",
                "package",
                "attempt",
                "kind",
                "class",
                "retries",
                "billed usage",
                "cost",
                "transcript",
            ],
            header=True,
        ),
    ]
    for run, attempt in attempts:
        href = prefix + run.failed_transcript(attempt)
        cells = [
            run.name,
            attempt.package_id,
            format_count(attempt.attempt),
            "infrastructure",
            _cell(attempt.class_),
            format_count(attempt.retries),
            _tokens(run.failed_logs[attempt.folder].usage, run.reasoning_label),
            _cost(attempt.cost),
        ]
        lines.append(
            _row([*map(_e, cells), f'<a href="{_e(_href(href))}">transcript</a>'], raw=True)
        )
    return [*lines, "</table>"]


def _tags(package_id: str, score: PackageScore, runs: Sequence[_Run]) -> str:
    """Held-out and tuned-on known defects by producer, from `graded_items`, and the saved
    entry's `represents` when present."""
    defects = [item for item in score.graded_items if item.kind == "known_defect"]
    parts = []
    for tag, label in (("held_out", "held out"), ("tuned_on", "tuned on")):
        counts = []
        for producer in ("model", "code"):
            count = sum(1 for item in defects if item.tag == tag and item.producer == producer)
            counts.append(f"{producer}-produced {format_count(count)}")
        parts.append(f"{label}: {', '.join(counts)}")
    represents = next(
        (
            run.entries[package_id].represents
            for run in runs
            if package_id in run.entries and run.entries[package_id].represents
        ),
        None,
    )
    if represents:
        parts.append(f"represents {', '.join(represents)}")
    return "; ".join(parts)


def _defects(score: PackageScore, *, tag: str | None, producer: str, headline: bool = False) -> str:
    """Detected of keyed for one partition of the known defects; `not assessed` when the key has
    none. The headline adds flagged below expected and cleared (3A)."""
    keyed = [
        item.id
        for item in score.graded_items
        if item.kind == "known_defect"
        and item.producer == producer
        and (tag is None or item.tag == tag)
    ]
    if not keyed:
        return NOT_ASSESSED
    detected = sum(1 for item in keyed if item in score.matched_defect_ids)
    text = f"{format_count(detected)} of {format_count(len(keyed))} detected"
    if headline:
        below = sum(1 for item in keyed if item in score.flagged_below_expected_defect_ids)
        cleared = sum(1 for item in keyed if item in score.cleared_defect_ids)
        text += f"; {format_count(below)} flagged below expected; {format_count(cleared)} cleared"
    return text


def _false_alarms(score: PackageScore) -> str:
    """The deciding count, then the others by origin."""
    deciding = deciding_false_alarm_ids(score)
    tuned_on = set(score.tuned_on_false_alarm_finding_ids)
    others: dict[str, int] = {}
    for finding_id in score.false_alarm_finding_ids:
        if finding_id in deciding:
            continue
        origin = score.finding_origins.get(finding_id, UNKNOWN)
        label = f"{origin}, tuned-on" if finding_id in tuned_on else origin
        others[label] = others.get(label, 0) + 1
    text = f"{format_count(len(deciding))} deciding"
    if others:
        text += "; others: " + ", ".join(
            f"{label} {format_count(count)}" for label, count in sorted(others.items())
        )
    else:
        text += "; no others"
    return text


def _tokens(usage: TokenUsage | None, reasoning: str) -> str:
    if usage is None:
        return UNKNOWN
    return (
        f"input {format_count(usage.input_tokens)}; cached input "
        f"{format_count(usage.cached_input_tokens)}; output {format_count(usage.output_tokens)}; "
        f"{reasoning} {format_count(usage.reasoning_tokens)}; cache-write "
        f"{format_count(usage.cache_write_tokens)}"
    )


# --- a transcript page (`report.md` 5) -------------------------------------------------------


def _transcript_page(run: _Run, score: PackageScore | FailedAttempt, legend: _Legend) -> list[str]:
    """Header, the system prompt as sent and the legend, the log in its own order, then the
    final state; each file of the package folder read once."""
    failed = isinstance(score, FailedAttempt)
    folder = runner.resolve_attempt_folder(run.path, score.folder if failed else score.package_id)
    record = run.provenance
    session, session_note = _read_session(folder)
    prompts, prompts_note = _read_prompts(folder)
    answer_log, log_note = _read_answer_log(folder)
    unreadable: list[int] = []
    if failed:
        log = run.failed_logs[score.folder]
        events, malformed, unreadable = log.events, log.malformed, list(log.unreadable)
        usage, served = log.usage, log.served_models
        status, wall = _failed_status(score), UNKNOWN
    else:
        logged = list(replay_events(run.streams[score.package_id], on_unreadable=unreadable.append))
        events, malformed = _readable_prefix(logged)
        usage, served = score.usage, score.served_models
        status, wall = _status(score), format_count(score.wall_clock_s)
    prefix = "../" * (len(run.name.split("/")) + 1 + int(failed))
    back = prefix + INDEX_FILE

    lines = [*_page(f"{score.package_id} in {run.name}"), f"<h1>{_e(score.package_id)}</h1>"]
    lines.append("<table>")
    for label, value in (
        ("run", run.name),
        ("package", score.package_id),
        ("arm", _recorded(record, "arm")),
        ("repetition", _recorded(record, "rep")),
        ("status", status),
        ("requested model", _recorded(record, "model")),
        ("responding model", ", ".join(served) or UNKNOWN),
        ("usage", _tokens(usage, run.reasoning_label)),
        ("cost", _cost(score.cost)),
        ("wall clock s", wall),
    ):
        lines.append(_row([label, value]))
    if failed:
        lines.append(_row(["retries", format_count(score.retries)]))
    lines += ["</table>", f'<p><a href="{_e(back)}">back to the report</a></p>']

    lines.append("<h2>The system prompt as sent</h2>")
    if prompts is not None:
        lines.append(f"<pre>{_e(prompts.system)}</pre>")
    else:
        lines.append(_note(prompts_note))
    lines += _legend_lines(legend)

    lines.append("<h2>The log</h2>")
    if log_note is not None:
        lines.append(_note(log_note))
    walk = _LogWalk(
        folder=folder,
        session=session,
        session_note=session_note,
        messages=prompts.user_messages if prompts is not None else None,
        message_note=prompts_note,
        points={point.after_turn: point for point in answer_log.points} if answer_log else {},
        reasoning=run.reasoning_label,
        stopped_early=malformed is not None or bool(unreadable),
    )
    lines += walk.render(events)
    if malformed is not None:
        lines.append(
            _note(MALFORMED_FROM.format(run=run.name, package=score.package_id, seq=malformed))
        )
    elif unreadable:
        lines.append(_note(UNREADABLE_FROM.format(line=unreadable[0])))
    elif not events:
        lines.append(_note(NO_EVENTS))

    if failed:
        lines += ["<h2>The final state</h2>", _note("not scored: failed")]
        if session is None:
            lines.append(_note(session_note))
        else:
            lines += [
                "<h3>Findings</h3>",
                "<table>",
                _row(["finding", "check", "status", "title"], header=True),
            ]
            for finding in session.findings:
                lines.append(_row([finding.id, finding.check, finding.status, finding.title]))
            lines.append("</table>")
    else:
        lines += _final_state(score, session, session_note, events)
        lines += _failed_attempts([run], package_id=score.package_id, prefix=prefix)
    lines += ["</body>", "</html>"]
    return lines


def _readable_prefix(events: list[AgentEvent]) -> tuple[list[AgentEvent], int | None]:
    """The events before the first whose body the walk cannot read, with that event's `seq`, or
    every event and `None` (owner decision 83A): a call's step that is not an integer, a round
    whose counts do not read, a coverage row whose item is not an object."""
    for index, event in enumerate(events):
        if not _readable_body(event):
            return events[:index], event.seq
    return events, None


def _readable_body(event: AgentEvent) -> bool:
    body = event.body
    if event.type in ("tool.started", "tool.finished"):
        step = body.get("step_index")
        return isinstance(step, int) and not isinstance(step, bool)
    if event.type == "usage":
        try:
            usage_from_body(body)
        except (KeyError, ValueError):
            return False
    if event.type == "coverage":
        return isinstance(body.get("item", {}), dict)
    return True


def _note(text: str | None) -> str:
    return f'<p class="note">{_e(text)}</p>'


def _read_session(folder: Path) -> tuple[ReviewSession | None, str | None]:
    path = folder / SESSION_FILE_NAME
    if not path.is_file():
        return None, NO_SESSION
    try:
        return load_session(path), None
    except (OSError, ValueError):
        return None, SESSION_UNREADABLE


def _read_prompts(folder: Path) -> tuple[PromptsRecord | None, str]:
    """The record, or why none is shown in its place."""
    try:
        record = read_prompts_record(folder)
    except (OSError, ValueError):
        return None, PROMPTS_UNREADABLE
    return record, NOT_RECORDED


def _read_answer_log(folder: Path) -> tuple[AnswerLog | None, str | None]:
    """The log through the one parser the scorer uses; an absent one is not shown."""
    try:
        return read_answer_log(folder), None
    except (OSError, ValueError):
        return None, ANSWER_LOG_UNREADABLE


def _legend_lines(legend: _Legend) -> list[str]:
    lines = ["<h2>Component names</h2>"]
    if legend.names is None:
        return [*lines, _note(legend.note)]
    lines += ["<table>", _row(["component", "name"], header=True)]
    lines += [_row([component, name]) for component, name in legend.names.items()]
    return [*lines, "</table>"]


@dataclass
class _Call:
    """A tool call between its `tool.started` and `tool.finished`, with the findings and
    withdrawals its bracket holds."""

    step: int
    tool: str
    arguments: Any
    under: list[str] = field(default_factory=list)


class _LogWalk:
    """One pass over a package's events, in their own order, grouped into turns at each
    `turn.ended` (`report.md` 5 item 3)."""

    def __init__(
        self,
        *,
        folder: Path,
        session: ReviewSession | None,
        session_note: str | None,
        messages: list[str] | None,
        message_note: str,
        points: dict[int, AnswerPoint],
        reasoning: str,
        stopped_early: bool = False,
    ) -> None:
        self.folder = folder
        self.session = session
        self.session_note = session_note
        self.messages = messages
        self.message_note = message_note
        self.points = points
        self.reasoning = reasoning
        self.stopped_early = stopped_early
        """The log stopped at a damaged body or an unreadable line, before its end."""
        self.questions = (
            {request.id: request.question or request.what for request in session.evidence_requests}
            if session is not None
            else {}
        )
        self.lines: list[str] = []
        self.calls: dict[int, _Call] = {}
        self.coverage: list[str] = []
        self.rounds = 0
        self.text_done = False

    def render(self, events: list[AgentEvent]) -> list[str]:
        """Each turn ends at its `turn.ended`; the events after the last one are an open turn
        when they hold a round or no turn ended, else what followed the last turn. Turn 0's
        message is always shown, and each recorded message past the last logged turn is listed
        (owner decision 83A)."""
        turns: list[list[AgentEvent]] = [[]]
        for event in events:
            turns[-1].append(event)
            if event.type == "turn.ended":
                turns.append([])
        after = turns.pop()
        if not turns or any(event.type == "usage" for event in after):
            turns.append(after)
            after = []
        for number, turn in enumerate(turns):
            self._turn(number, turn)
        self._unscripted_on_its_own(len(turns) - 1)
        self._sent_past_the_log(len(turns))
        if after:
            self.lines.append("<h3>After the last turn</h3>")
            for event in after:
                self._event(event)
            self._flush_calls()
            self._flush_coverage()
        return self.lines

    def _turn(self, number: int, events: list[AgentEvent]) -> None:
        """The turn's message as sent, then its events in order; an answer turn's engineer's
        turn where its first answer, or failing one its first round, is logged."""
        self.rounds, self.text_done = 0, False
        first_round = next(
            (index for index, event in enumerate(events) if event.type == "usage"), len(events)
        )
        if number == 0 and first_round > 0:
            self.lines.append(f"<h3>{_e(CODE_BEFORE_THE_FIRST_TURN)}</h3>")
            for event in events[:first_round]:
                self._event(event)
            self._flush_calls()
            events, first_round = events[first_round:], 0
        self.lines.append(f"<h3>Turn {_e(format_count(number))}</h3>")
        self.lines.append(f"<pre>{_e(self._message(number))}</pre>")
        point = self.points.get(number - 1) if number > 0 else None
        engineer_shown = number == 0
        for index, event in enumerate(events):
            answering = index < first_round and event.type == "evidence.answered"
            if not engineer_shown and (answering or index >= first_round):
                self.lines.append("<h4>The engineer's turn</h4>")
                for answer in events[index:first_round]:
                    if answer.type == "evidence.answered":
                        self._answered(answer)
                self._unscripted(point)
                engineer_shown = True
            if not answering:
                self._event(event)
        self._flush_calls()
        self._flush_coverage()

    def _sent_past_the_log(self, first: int) -> None:
        """The recorded messages of turns the log does not reach: an attempt cut short, or a
        log that stopped early before them (owner decision 91A)."""
        label = NOT_SHOWN if self.stopped_early else NOT_IN_THE_LOG
        for number in range(first, len(self.messages or [])):
            self.lines.append(f"<h3>Turn {_e(format_count(number))}</h3>")
            self.lines.append(f"<pre>{_e(self._message(number))}</pre>")
            self.lines.append(_note(label))

    def _message(self, number: int) -> str:
        if self.messages is None:
            return self.message_note
        return self.messages[number] if number < len(self.messages) else NOT_RECORDED

    def _unscripted(self, point: AnswerPoint | None) -> None:
        """The questions the driver gave nothing at `point`, with the reason."""
        if point is None or not point.unscripted:
            return
        self.lines.append("<ul>")
        for request in point.unscripted:
            reason = request.reason
            if request.entries:
                reason += f" ({', '.join(request.entries)})"
            question = self.questions.get(request.request_id, "")
            self.lines.append(
                f"<li>{_e(request.request_id)} ({_e(question)}): given nothing, {_e(reason)}</li>"
            )
        self.lines.append("</ul>")

    def _unscripted_on_its_own(self, last: int) -> None:
        """A point no answer turn follows, shown on its own after the last turn."""
        point = self.points.get(last)
        if point is None or not point.unscripted:
            return
        self.lines.append(f"<h4>After turn {_e(format_count(last))}: given nothing</h4>")
        self._unscripted(point)

    def _answered(self, event: AgentEvent) -> None:
        request_id = str(event.body.get("request_id"))
        question = self.questions.get(request_id, "")
        answer = event.body.get("answer")
        self.lines.append(f"<p>{_e(request_id)} ({_e(question)}): answered {_e(answer)}</p>")

    def _event(self, event: AgentEvent) -> None:
        """One event where the log puts it; `text.delta` is never shown."""
        body = event.body
        if event.type == "text.delta":
            return
        if event.type == "usage":
            self._flush_calls()
            self.rounds += 1
            label = f"Round {format_count(self.rounds)}"
            if round_kind(self.text_done) == "presentation":
                label += f": {EXPLANATION_PASS}"
            usage = _tokens(usage_from_body(body), self.reasoning)
            self.lines.append(f"<h4>{_e(label)}</h4><p>{_e(usage)}</p>")
        elif event.type == "tool.started":
            step = body["step_index"]
            self.calls[step] = _Call(step, str(body.get("tool")), body.get("arguments") or {})
        elif event.type == "tool.finished":
            call = self.calls.pop(body["step_index"], None)
            if call is not None:
                self._call(call, body)
        elif event.type in ("finding", "finding.withdrawn"):
            line = _finding_line(event)
            step = bracketing_step(self.calls)
            if step is not None:
                self.calls[step].under.append(line)
            else:
                self.lines.append(f"<p>{line}</p>")
        elif event.type == "text.done":
            self.text_done = True
            self.lines.append(f"<p>The model's text:</p><pre>{_e(body.get('text', ''))}</pre>")
        elif event.type == "evidence.requested":
            question = body.get("question") or body.get("what")
            self.lines.append(f"<p>Question {_e(body.get('id'))}: {_e(question)}</p>")
        elif event.type == "evidence.answered":
            self._answered(event)
        elif event.type == "coverage":
            item = body.get("item") or {}
            self.coverage.append(f"{body.get('bucket')}: {item.get('check')}: {item.get('reason')}")
        elif event.type == "error":
            error = f"{body.get('error_class')}: {body.get('message')}"
            self.lines.append(f"<p>Error {_e(error)}</p>")
        elif event.type == "turn.ended":
            self._flush_calls()
            self._flush_coverage()
            self.lines.append(f"<p>The turn ended: {_e(body.get('reason'))}</p>")
        else:
            self.lines.append(f"<p>{_e(event.type)}: {_e(_compact(body))}</p>")

    def _call(self, call: _Call, finished: dict[str, Any] | None) -> None:
        """Tool, arguments, status and summary; the findings its bracket holds; and its full
        result, read through `read_stored_result` and embedded escaped, never parsed again."""
        if finished is None:
            outcome = "did not finish"
        else:
            outcome = f"{finished.get('status')}: {finished.get('result_summary', '')}"
        self.lines.append(
            f"<p>Step {_e(format_count(call.step))}: {_e(call.tool)} "
            f"<code>{_e(_compact(call.arguments))}</code>: {_e(outcome)}</p>"
        )
        if call.under:
            self.lines += ["<ul>", *(f"<li>{line}</li>" for line in call.under), "</ul>"]
        if finished is None:
            return
        if self.session is None:
            self.lines.append(_note(self.session_note))
            return
        stored = read_stored_result(self.folder, self.session.session_id, call.step)
        if isinstance(stored, Unstored):
            self.lines.append(_note(UNSTORED[stored.reason]))
        else:
            self.lines.append(
                f"<details><summary>full result</summary><pre>{_e(stored.text)}</pre></details>"
            )

    def _flush_calls(self) -> None:
        """A call still open where its turn ends, or the log stops, did not finish."""
        for call in self.calls.values():
            self._call(call, None)
        self.calls = {}

    def _flush_coverage(self) -> None:
        """The turn's coverage rows, one line each, collapsed."""
        if not self.coverage:
            return
        count = format_count(len(self.coverage))
        self.lines.append(f"<details><summary>coverage rows ({_e(count)})</summary>")
        self.lines += [f"<p>{_e(row)}</p>" for row in self.coverage]
        self.lines.append("</details>")
        self.coverage = []


def _finding_line(event: AgentEvent) -> str:
    body = event.body
    if event.type == "finding":
        return (
            f"finding {_e(body.get('id'))} ({_e(body.get('check'))}, "
            f"{_e(body.get('status'))}): {_e(body.get('title'))}"
        )
    return f"withdrawn {_e(body.get('finding_id'))}: {_e(body.get('reason'))}"


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _final_state(
    score: PackageScore,
    session: ReviewSession | None,
    session_note: str | None,
    events: list[AgentEvent],
) -> list[str]:
    """Every finding with the scorecard's grading of it, read from its id lists; each known
    defect's and condition's outcome by entry id; the withdrawn findings with their reason. No
    finding-to-defect link is drawn: the scorecard records none."""
    lines = ["<h2>The final state</h2>", "<h3>Findings</h3>"]
    if session is None:
        lines.append(_note(session_note))
    else:
        deciding = set(deciding_false_alarm_ids(score))
        false_alarms = set(score.false_alarm_finding_ids)
        forbidden = set(score.forbidden_hit_finding_ids or [])
        tuned_on = set(score.tuned_on_false_alarm_finding_ids)
        lines += [
            "<table>",
            _row(["finding", "check", "status", "origin", "grading", "title"], header=True),
        ]
        for finding in session.findings:
            grading = []
            if finding.id in false_alarms:
                grading.append("false alarm, deciding" if finding.id in deciding else "false alarm")
            if finding.id in forbidden:
                grading.append("forbidden hit")
            if finding.id in tuned_on:
                grading.append("tuned-on")
            origin = score.finding_origins.get(finding.id)
            lines.append(
                _row(
                    [
                        finding.id,
                        finding.check,
                        finding.status,
                        _cell(origin),
                        "; ".join(grading) or "none",
                        finding.title,
                    ]
                )
            )
        lines.append("</table>")

    lines += ["<h3>Known defects</h3>", "<table>"]
    lines.append(_row(["entry", "tag", "producer", "expected", "outcome"], header=True))
    for item in score.graded_items:
        if item.kind == "known_defect":
            row = [item.id, item.tag, _cell(item.producer), _cell(item.expected_status)]
            lines.append(_row([*row, _defect_outcome(score, item.id)]))
    lines += ["</table>", "<h3>Correct conditions</h3>"]
    contradicted, confirmed = score.contradicted_condition_ids, score.confirmed_condition_ids
    if contradicted is None or confirmed is None:
        lines.append(_note(NOT_ASSESSED))
    else:
        lines += ["<table>", _row(["entry", "outcome"], header=True)]
        for item in score.graded_items:
            if item.kind == "correct_condition":
                outcome = [
                    label
                    for label, ids in (("contradicted", contradicted), ("confirmed", confirmed))
                    if item.id in ids
                ]
                lines.append(_row([item.id, "; ".join(outcome) or "neither"]))
        lines.append("</table>")

    lines.append("<h3>Withdrawn findings</h3>")
    withdrawn = [event.body for event in events if event.type == "finding.withdrawn"]
    if not withdrawn:
        lines.append(_note("none"))
        return lines
    hits = score.withdrawn_forbidden_hit_finding_ids
    lines += ["<table>", _row(["finding", "reason", "withdrawn forbidden hit"], header=True)]
    for body in withdrawn:
        finding_id = str(body.get("finding_id"))
        hit = UNKNOWN if hits is None else ("yes" if finding_id in hits else "no")
        lines.append(_row([finding_id, str(body.get("reason")), hit]))
    lines.append("</table>")
    return lines


def _defect_outcome(score: PackageScore, entry: str) -> str:
    """A known defect's outcome from the per-entry lists (13A)."""
    outcome = []
    if entry in score.matched_defect_ids:
        outcome.append("flagged" if entry in score.flagged_defect_ids else "credited")
    for label, ids in (
        ("status mismatch", score.status_mismatch_defect_ids),
        ("flagged below expected", score.flagged_below_expected_defect_ids),
        ("cleared", score.cleared_defect_ids),
        ("missed", score.missed_defect_ids),
    ):
        if entry in ids:
            outcome.append(label)
    return "; ".join(outcome) or "none"
