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

`build_report` writes one static page, `index.html`, and one transcript page per scored package
of each run folder, from run folders alone: every number is the scorecard's (`read_scorecard`,
the one reader), counted from its id lists where it is rendered and formatted by the ledger's
rule (`compare.format_count`); the matcher is never run and no key is read. Each stream is found
through `event_stream`, plain or packed, and read in one pass through `replay_events` (plan
decisions RF-29, RF-83); each call's full result through `read_stored_result`, embedded escaped
(RF-30). Every recorded string is escaped; the pages hold one inline style block, no script, no
external resource and no build time. The status and cost columns and the failed attempts' pages
are the robustness slice's (T216, T217).
"""

from __future__ import annotations

import html
import json
import os
import re
import secrets
import shutil
import stat
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

from swreview import atomic
from swreview.agent.events import event_stream, replay_events
from swreview.agent.providers import AgentEvent, ProviderName, TokenUsage, usage_from_body
from swreview.agent.runner import SESSION_FILE_NAME
from swreview.benchmark.answers import AnswerLog, AnswerPoint, read_answer_log
from swreview.benchmark.compare import distinct_run_dirs, format_count
from swreview.benchmark.origins import MODEL_ORIGINS
from swreview.benchmark.recording import bracketing_step, round_kind
from swreview.benchmark.runner import SAVED_SET_FILE, RunProvenance, load_provenance
from swreview.benchmark.scorecard import (
    NOT_ASSESSED,
    SCORECARD_FILE,
    UNKNOWN,
    PackageScore,
    Scorecard,
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
from swreview.report.session import ReviewSession, load_session
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

    @property
    def reasoning_label(self) -> str:
        """Reasoning tokens' name for the run's provider (ab-harness 10.8)."""
        provider = self.provenance.provider if self.provenance is not None else None
        return "thoughts" if provider == ProviderName.GEMINI.value else "reasoning"

    def transcript(self, package_id: str) -> str:
        """The package's transcript page, relative to the output folder, `/`-separated."""
        return f"{TRANSCRIPTS_DIR}/{self.name}/{package_id}.html"


def deciding_false_alarm_ids(score: PackageScore) -> list[str]:
    """The false alarms the verdict counts (17A, D15): model origin, and not tuned-on."""
    tuned_on = set(score.tuned_on_false_alarm_finding_ids)
    return [
        finding_id
        for finding_id in score.false_alarm_finding_ids
        if score.finding_origins.get(finding_id) in MODEL_ORIGINS and finding_id not in tuned_on
    ]


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
    its contents (owner decision 91A). Removing the old report is best effort: one that cannot be
    removed is named in `ReportBuilt.warnings`, the new report being in place; siblings a killed
    build left are removed first and named in `ReportBuilt.removed`. The build needs write
    access to `out`'s parent.
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
        for score in run.scorecard.per_package:
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
        leftover = _place(building, target, in_place=in_place)
    except BaseException:
        _remove(building)
        raise
    return ReportBuilt(
        index=target / INDEX_FILE,
        transcripts=written,
        removed=removed,
        warnings=stuck + (() if leftover is None else (_leftover_warning(leftover),)),
    )


def _legend_of(run: _Run, score: PackageScore, legends: dict[Path, _Legend]) -> _Legend:
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
    if out.is_symlink() or out.is_junction():
        return True
    return target.exists() and Path.cwd().resolve().is_relative_to(target)


def _place(built: Path, target: Path, *, in_place: bool) -> Path | None:
    """Put the finished build at `target`; the folder this left and could not remove, if any.

    Moved when it can be: a previous report, or an empty folder, aside, the build in, the
    previous one removed. Copied in place when `in_place`, when the previous report cannot be
    moved aside, or when the build cannot be moved in, the previous report then moved back first
    (owner decision 91A).
    """
    if in_place:
        _copy_in_place(built, target)
        return _remove(built)
    if not target.exists():
        built.rename(target)
        return None
    previous = _sibling(target, PREVIOUS)
    try:
        target.rename(previous)
    except OSError:
        _copy_in_place(built, target)
        return _remove(built)
    try:
        built.rename(target)
    except OSError:
        previous.rename(target)
        _copy_in_place(built, target)
        return _remove(built)
    return _remove(previous)


def _copy_in_place(built: Path, target: Path) -> None:
    """Replace `target`'s report with the build's, keeping the folder itself; not atomic."""
    transcripts = target / TRANSCRIPTS_DIR
    if transcripts.is_dir():
        shutil.rmtree(transcripts, onexc=_writable)
    if (built / TRANSCRIPTS_DIR).is_dir():
        shutil.copytree(built / TRANSCRIPTS_DIR, transcripts)
    shutil.copyfile(built / INDEX_FILE, target / INDEX_FILE)


def _writable(function: Any, name: str, error: BaseException) -> None:
    """`shutil.rmtree`'s retry for a read-only file or folder: clear the flag, try once more."""
    os.chmod(name, stat.S_IWRITE)
    function(name)


def _remove(folder: Path) -> Path | None:
    """Remove a folder this command wrote, read-only flags cleared; best effort: the folder
    when it could not be removed, else `None`."""
    try:
        shutil.rmtree(folder, onexc=_writable)
    except OSError:
        return folder
    return None


def _remove_orphans(target: Path) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    """The siblings a killed build of `target` left (`.<name>.<random>.building` or
    `.previous`), each removed, best effort: those removed, and a warning for each that was not,
    both to be named (91A)."""
    left = re.compile(
        rf"\.{re.escape(target.name)}\.[0-9a-z_]+(?:{re.escape(BUILDING)}|{re.escape(PREVIOUS)})"
    )
    if not target.parent.is_dir():
        return (), ()
    orphans = sorted(
        child
        for child in target.parent.iterdir()
        if left.fullmatch(child.name) and child.is_dir() and not child.is_symlink()
    )
    stuck = [orphan for orphan in orphans if _remove(orphan) is not None]
    removed = tuple(orphan for orphan in orphans if orphan not in stuck)
    return removed, tuple(
        f"could not remove {orphan}, left by an earlier build; remove it by hand"
        for orphan in stuck
    )


def _leftover_warning(leftover: Path) -> str:
    what = "the previous report" if leftover.name.endswith(PREVIOUS) else "this build's copy"
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
    """`--out` is absent, empty, or a previous report: only an `index.html` carrying the
    generator tag and, optionally, `transcripts/` (`report.md` 6)."""
    if not out.exists():
        return
    refusal = ReportError(f"{out} holds files this command did not write; choose an empty folder")
    if not out.is_dir():
        raise refusal
    held = {child.name for child in out.iterdir()}
    if not held:
        return
    index = out / INDEX_FILE
    if (
        INDEX_FILE not in held
        or not held <= {INDEX_FILE, TRANSCRIPTS_DIR}
        or not index.is_file()
        or (TRANSCRIPTS_DIR in held and not (out / TRANSCRIPTS_DIR).is_dir())
        or GENERATOR_TAG.encode("utf-8") not in index.read_bytes()
    ):
        raise refusal


def _relative_names(paths: Sequence[Path]) -> list[str]:
    """Each run folder relative to the common parent of the folders' parents.

    Refused when there is none (two drives), and when a run folder lies in the home folder while
    the common parent is the home folder or above it: the names would then carry the home
    folder's own folders, `Users/<name>/AppData/...` (owner decision 84A).
    """
    resolved = [path.resolve() for path in paths]
    try:
        common = Path(os.path.commonpath([str(path.parent) for path in resolved]))
    except ValueError:
        raise ReportError(
            "the run folders have no common parent (they lie on different drives); "
            "copy them under one folder first"
        ) from None
    home = Path.home().resolve()
    if home.is_relative_to(common):
        for path, full in zip(paths, resolved, strict=True):
            if full.is_relative_to(home):
                raise ReportError(
                    f"{path} lies in the home folder and the run folders' common parent {common} "
                    "is at or above it, so the report would name the home folder's folders; copy "
                    "the run folders under one study folder first"
                )
    return [path.relative_to(common).as_posix() for path in resolved]


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
            score.package_id: event_stream(path / score.package_id)
            for score in scorecard.per_package
        },
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
    lines += ["</table>", "<h2>Totals</h2>", "<table>"]
    lines.append(_row(["run", "packages scored", "total tokens", "wall clock s"], header=True))
    for run in runs:
        aggregate = run.scorecard.aggregate
        per_package = run.scorecard.per_package
        tokens = format_count(aggregate.total_tokens)
        if aggregate.total_tokens is None:
            tokens += (
                f" ({format_count(aggregate.packages - aggregate.packages_with_usage)} of "
                f"{format_count(aggregate.packages)} packages report no usage)"
            )
        seconds = sum_or_none([score.wall_clock_s for score in per_package])
        wall = format_count(seconds)
        if seconds is None:
            missing = sum(1 for score in per_package if score.wall_clock_s is None)
            wall += (
                f" ({format_count(missing)} of {format_count(len(per_package))} packages "
                "report no wall clock)"
            )
        lines.append(_row([run.name, format_count(len(per_package)), tokens, wall]))
    lines.append("</table>")
    for package_id in _case_order(runs):
        lines += _case_section(package_id, runs)
    lines += ["</body>", "</html>"]
    return lines


def _row(cells: Sequence[str], *, header: bool = False, raw: bool = False) -> str:
    tag = "th" if header else "td"
    return (
        "<tr>" + "".join(f"<{tag}>{cell if raw else _e(cell)}</{tag}>" for cell in cells) + "</tr>"
    )


def _case_order(runs: Sequence[_Run]) -> list[str]:
    """The first run folder's saved-set order, then any package only a later one holds, then any
    scored package no saved set names, in scorecard order; scored packages only."""
    scored = {score.package_id for run in runs for score in run.scorecard.per_package}
    ordered: dict[str, None] = {}
    for run in runs:
        for package_id in run.entries:
            if package_id in scored:
                ordered.setdefault(package_id)
    for run in runs:
        for score in run.scorecard.per_package:
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
            for score in run.scorecard.per_package
            if score.package_id == package_id
        ),
        key=lambda pair: _study_order(pair[0]),
    )
    first = rows[0][1]
    lines = [f"<section><h2>{_e(package_id)}</h2>", f"<p>{_e(_tags(package_id, first, runs))}</p>"]
    lines += ["<table>"]
    lines.append(
        _row(
            [
                "run",
                "held-out model-produced",
                "code-produced",
                "tuned-on model-produced",
                "false alarms",
                "tokens",
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
        link = f'<a href="{_e(_href(run.transcript(package_id)))}">transcript</a>'
        cells = [
            _e(run_cell),
            _e(_defects(score, tag="held_out", producer="model", headline=True)),
            _e(_defects(score, tag=None, producer="code")),
            _e(_defects(score, tag="tuned_on", producer="model")),
            _e(_false_alarms(score)),
            _e(_tokens(score.usage, run.reasoning_label)),
            _e(format_count(score.wall_clock_s)),
            link,
        ]
        lines.append(_row(cells, raw=True))
    lines += ["</table>", "</section>"]
    return lines


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


def _transcript_page(run: _Run, score: PackageScore, legend: _Legend) -> list[str]:
    """Header, the system prompt as sent and the legend, the log in its own order, then the
    final state; each file of the package folder read once."""
    folder = run.path / score.package_id
    record = run.provenance
    session, session_note = _read_session(folder)
    prompts, prompts_note = _read_prompts(folder)
    answer_log, log_note = _read_answer_log(folder)
    unreadable: list[int] = []
    logged = list(replay_events(run.streams[score.package_id], on_unreadable=unreadable.append))
    events, malformed = _readable_prefix(logged)
    back = "../" * (len(run.name.split("/")) + 1) + INDEX_FILE

    lines = [*_page(f"{score.package_id} in {run.name}"), f"<h1>{_e(score.package_id)}</h1>"]
    lines.append("<table>")
    for label, value in (
        ("run", run.name),
        ("package", score.package_id),
        ("arm", _recorded(record, "arm")),
        ("repetition", _recorded(record, "rep")),
        ("requested model", _recorded(record, "model")),
        ("usage", _tokens(score.usage, run.reasoning_label)),
        ("wall clock s", format_count(score.wall_clock_s)),
    ):
        lines.append(_row([label, value]))
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

    lines += _final_state(score, session, session_note, events)
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
