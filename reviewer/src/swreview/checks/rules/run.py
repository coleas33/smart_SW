"""The run-folder machinery every check family shares: carry-forward, dispatch, record.

A family's evaluation entry point loads a package, decides what to grade, dispatches its
own tools and writes a run folder. Which tools it dispatches and what it grades are the
family's; everything around them is the same run folder, written the same way, read back
the same way, and that half lives here:

1. **the refusals**, as one exception family a caller can report without a traceback. They
   are `ValueError`s, so a command turns them into one line on stderr through the
   handled-error list it already has, and `error_class` is what a backend route puts in the
   error body;
2. **the carry-forward** (`carry_forward`): the newest `exceptions.json` under the caller's
   run root whose package carries the same `design_id`, copied byte-identically into the
   run folder *before the rules run*, so an acceptance survives the next check without an
   engineer copying a file. A missing candidate is reported and is not an error; a
   candidate that cannot be parsed refuses the run, because an unreadable store read as "no
   exceptions" silently re-raises a condition somebody already accepted;
3. **the recorded call** (`recorded_call`): running an evaluator as the step its findings
   will cite. A family's report layer gives every finding
   `tool_result_ids=[context.current_step_id]`, and that id is the index the *next*
   recorded step takes - true only inside a recorded call;
4. **closing the run**: when the session ended, how long it ran, and the rendered report;
5. **the check record** (`check.json`): what makes reading a run folder back a read rather
   than a second evaluation. `session.json` holds the findings, the coverage and so the
   grade; it does not hold which family ran, which scope, which documents were selected,
   the structured subjects beside each finding, or what the carry-forward did.

`family` is written into every record, because a backend handed a folder has to know whose
check it is holding before it can answer a read of it.

No provider is constructed, no key is read and no network call is made on any path here.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, get_args

from pydantic_core import to_jsonable_python

from swreview.agent.runner import load_exceptions
from swreview.checks.rules.family import CheckFamily
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.ir.loader import PACKAGE_FILE_NAME, LoadedPackage
from swreview.report.markdown import render_report

# `CHECK_FILE_NAME` - what a check records beside its session, and why the folder needs a
# second file - is re-exported from here: `report/rerender.py` names every file a run folder
# holds, so the one offline re-render can read all of them (research R2.7).
from swreview.report.rerender import (
    CHECK_FILE_NAME,
    REPORT_FILE_NAME,
    SESSION_FILE_NAME,
)
from swreview.report.session import CoverageBucket, ReviewSession, load_session
from swreview.tools.context import ToolContext, use_context
from swreview.tools.query import ToolResult
from swreview.tools.registry import RecordingSink, record_call

__all__ = [
    "ALREADY_PRESENT",
    "CHECK_FILE_NAME",
    "EMPTY_FEATURE_TREE",
    "NOT_A_CHECK",
    "NO_CANDIDATE",
    "NO_RUN_ROOT",
    "SESSION_IS_NOT_THE_RECORDED_ONE",
    "SUPPLIED_STORE",
    "UNREADABLE_CANDIDATE",
    "UNREADABLE_RECORD",
    "CarriedForward",
    "CheckRunError",
    "EmptyFeatureTreeError",
    "NotACheckError",
    "UnreadableExceptionsError",
    "carry_forward",
    "check_record",
    "close_session",
    "coverage_rows",
    "package_design_id",
    "recorded_call",
    "recorded_session",
    "store_to_grade_against",
    "write_check_record",
    "write_report",
]

EMPTY_FEATURE_TREE = (
    "{directory} carries no feature rows: its package was written by the {profile!r} dump "
    "profile and its features array is empty, so there is no feature tree to grade. "
    "Extract the model again before checking it; grading it would report every rule as "
    "unresolved, which reads as a broken part rather than as a missing extract"
)

NO_CANDIDATE = (
    "no earlier run under {run_root} carries an {file} for design {design_id}, so no "
    "accepted exception was carried forward"
)

ALREADY_PRESENT = (
    "{directory} already carries an {file}, which is this run's own evidence; nothing was "
    "carried forward over it"
)

NO_RUN_ROOT = (
    "no run root was named for this run, so no earlier run was looked at and nothing was "
    "carried forward; the directory above a package is a run root only when a caller says "
    "it is"
)

SUPPLIED_STORE = (
    "the caller supplied the exception store this check was graded against, so nothing "
    "was looked for under a run root and nothing was copied into {directory}"
)
"""What a check reports when its store was handed in: a caller that grades two dumps of one
copy against **one** store it refreshed once. The carry-forward happened, once, in the run
that owns both grades."""

NOT_A_CHECK = "{directory} holds no {file}, so no check has run in it"

UNREADABLE_RECORD = (
    "{path} cannot be read as a check record ({error}), so this folder cannot be read "
    "back as the check it holds"
)

SESSION_IS_NOT_THE_RECORDED_ONE = (
    "{directory} holds a {session} that its {file} does not name: the record describes "
    "session {recorded} and the folder holds {found}, so the folder is no longer that "
    "check - a review has claimed it, or a later run replaced the session"
)

UNREADABLE_CANDIDATE = (
    "{path} cannot be read as an exception store ({error}); the run is refused rather "
    "than carried forward as an empty store, because an exception nobody can read is one "
    "an engineer accepted and would silently be raised again"
)


class CheckRunError(ValueError):
    """A check that cannot run, described so a caller can report it without a traceback.

    A `ValueError`, so a command turns it into one line on stderr through the handled-error
    list it already has; `error_class` is what a backend route puts in the error body.
    """

    error_class = "CheckRunError"


class EmptyFeatureTreeError(CheckRunError):
    """The package carries no feature rows, so there is no tree to grade."""

    error_class = "EmptyFeatureTree"


class UnreadableExceptionsError(CheckRunError):
    """The carry-forward candidate exists and cannot be parsed."""

    error_class = "UnreadableExceptions"


class NotACheckError(CheckRunError):
    """The folder holds no check of its own to read back."""

    error_class = "UnknownCheck"


def coverage_rows(session: ReviewSession) -> list[dict[str, Any]]:
    """Every coverage item of `session` as one flat row, bucket included."""
    return [
        {"bucket": bucket, **to_jsonable_python(item)}
        for bucket in get_args(CoverageBucket)
        for item in getattr(session.coverage, bucket)
    ]


# --- 1. the recorded call ---------------------------------------------------------


def recorded_call(
    context: ToolContext,
    sink: RecordingSink,
    name: str,
    run: Callable[[ToolContext, Sequence[str] | None], ToolResult],
    documents: Sequence[str],
) -> dict[str, Any]:
    """`run` over several named documents, recorded as the step its findings will cite.

    The same three things a recorded tool does: bind the context, record the call through
    the sink after the function returns - which is what makes `ToolContext.current_step_id`
    the step this call is being recorded as - and turn a raise into an error result rather
    than letting it out.
    """
    started = perf_counter()
    try:
        with use_context(context):
            payload = dict(to_jsonable_python(run(context, list(documents))))
    except Exception as exc:  # noqa: BLE001 - every failure becomes a result, as in the registry
        payload = {"error": f"{type(exc).__name__}: {exc}"}
    error = str(payload["error"]) if "error" in payload else None
    record_call(
        sink,
        tool=name,
        arguments={"document_ids": list(documents)},
        payload=payload,
        elapsed_s=perf_counter() - started,
        error=error,
    )
    return payload


def close_session(context: ToolContext, started: float) -> ReviewSession:
    """End the session honestly: when it ended, and how long it ran.

    Deliberately *not* `agent/runner.finalize_session`: that closes out a review's
    checklist, and a check answers one checklist item. Recording the other items as "the
    review ended without a finding for it" would be a claim about a review that never
    started.
    """
    session = context.require_session()
    session.ended_at = datetime.now(UTC)
    session.timing = session.timing.replace(
        unattended_runtime_minutes=(perf_counter() - started) / 60.0
    )
    return session


def write_report(directory: Path, session: ReviewSession, package: Any) -> Path:
    """Render `session` into the run folder and return the file."""
    report_file = directory / REPORT_FILE_NAME
    report_file.write_text(render_report(session, package), encoding="utf-8")
    return report_file


# --- 2. the carry-forward ---------------------------------------------------------


@dataclass(frozen=True)
class CarriedForward:
    """What the carry-forward did, including when it did nothing.

    Reported rather than silent in every case: "no exception was carried forward" and "two
    were" are different statements about what silenced what, and an engineer looking at a
    rule that did not fire needs to know which one they are reading.
    """

    from_run: str | None
    """The run folder the file was copied from, or `None` when nothing was copied."""

    count: int
    """How many exceptions the copied file holds; zero when nothing was copied."""

    reason: str | None
    """Why nothing was copied; `None` when something was."""


def store_to_grade_against(loaded: LoadedPackage, out: Path) -> ExceptionStore | None:
    """The `exceptions.json` this run grades against: the run folder's, else the package's.

    The run folder first, because that is where the carry-forward just wrote and a copy
    nothing graded against would silence nothing - the acceptance would quietly not survive
    the next check. The package's own store is the fallback, because a package a command is
    pointed at is read where it is: its waivers are evidence about it, and a run folder
    somewhere else does not make them disappear.

    The two are the same file whenever no separate output directory was named, which is
    every caller but one grading a package it must not edit, so this is one rule and not a
    branch on the caller.
    """
    carried = out / EXCEPTIONS_FILE_NAME
    if carried.is_file():
        return ExceptionStore(carried).load()
    return load_exceptions(loaded)


def carry_forward(
    directory: Path,
    *,
    design_id: str,
    run_root: Path | str | None,
    design_id_of: Callable[[Path], str | None] | None = None,
) -> CarriedForward:
    """Copy the newest same-design `exceptions.json` under `run_root` into `directory`.

    A candidate is a folder directly under the run root that holds both a package naming
    the same `design_id` and an `exceptions.json`. Newest is by the file's own modification
    time, with the folder name as the tie-break so two files written in the same second
    still order the same way on every run.

    The run root is the caller's and has no default. A pane knows its own (the check folder
    is created under it), while a command pointed at any directory at all does not - so
    inferring the root from the package's parent is how a store the engineer never asked
    about is copied into their directory, and how an unrelated folder's truncated file
    refuses a run that has nothing to do with it. A caller that names no run root carries
    nothing forward, and is told so.

    The copy is a byte copy, not a load and a re-save: a store that round-tripped through
    this build would silently rewrite what an engineer accepted under an older one.

    `design_id_of` is how a candidate folder's design is read, and it is a parameter
    because a caller may keep its own kind of run folder beside the check folders - one
    whose design id lives in a different file. The default is this module's:
    `package.json`, `design.design_id`.
    """
    read_design_id = package_design_id if design_id_of is None else design_id_of
    target = directory / EXCEPTIONS_FILE_NAME
    if target.exists():
        return CarriedForward(
            from_run=None,
            count=0,
            reason=ALREADY_PRESENT.format(directory=directory, file=EXCEPTIONS_FILE_NAME),
        )

    if run_root is None:
        return CarriedForward(from_run=None, count=0, reason=NO_RUN_ROOT)

    root = Path(run_root).resolve()
    candidates = [
        candidate / EXCEPTIONS_FILE_NAME
        for candidate in sorted(root.iterdir() if root.is_dir() else [])
        if candidate.is_dir()
        and candidate.resolve() != directory
        and (candidate / EXCEPTIONS_FILE_NAME).is_file()
        and read_design_id(candidate) == design_id
    ]
    if not candidates:
        return CarriedForward(
            from_run=None,
            count=0,
            reason=NO_CANDIDATE.format(
                run_root=root,
                file=EXCEPTIONS_FILE_NAME,
                design_id=design_id,
            ),
        )

    newest = max(candidates, key=lambda path: (path.stat().st_mtime, path.parent.name))
    try:
        store = ExceptionStore(newest).load()
    except (OSError, ValueError) as exc:
        raise UnreadableExceptionsError(
            UNREADABLE_CANDIDATE.format(path=newest, error=exc)
        ) from exc
    shutil.copyfile(newest, target)
    return CarriedForward(from_run=newest.parent.name, count=len(store.exceptions), reason=None)


def package_design_id(directory: Path) -> str | None:
    """The `design.design_id` of the package in `directory`, or `None`.

    Read as JSON rather than as an `EvidencePackage`: this asks one question of every
    sibling run folder, and validating each of their packages to answer it would make the
    cost of a check grow with the number of runs the engineer has kept. A folder whose
    package cannot be read this way is not a candidate - it is not refused either, because
    it is not this run's evidence and may be a folder no check ever wrote.
    """
    try:
        body = json.loads((directory / PACKAGE_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    design = body.get("design")
    if not isinstance(design, dict):
        return None
    found = design.get("design_id")
    return found if isinstance(found, str) else None


# --- 3. the check record: what makes a read a read --------------------------------


def write_check_record(
    check_file: Path, family: CheckFamily, body: Mapping[str, Any]
) -> Path:
    """Write `check.json` for one run, stamped with the family, and return the file.

    The family is written first because it is the question a reader of a folder asks first:
    a backend handed a run directory answers a read of it by the family the record names,
    without opening the session or guessing from the folder's own name.

    `session_id` is what ties the two halves of a check together. A folder whose
    `session.json` is no longer the one this record describes - a review claimed the folder
    and rotated the check's session aside, or a later run replaced it - is no longer this
    check, and reading it must say so rather than answer with somebody else's session.
    """
    record = {"family": family.check_file_family, **dict(body)}
    check_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return check_file


def check_record(directory: Path) -> Mapping[str, Any]:
    """`check.json` as a mapping, or `NotACheckError` naming what is wrong with it."""
    file = directory / CHECK_FILE_NAME
    try:
        body = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise NotACheckError(
            NOT_A_CHECK.format(directory=directory, file=CHECK_FILE_NAME)
        ) from exc
    except ValueError as exc:
        raise NotACheckError(UNREADABLE_RECORD.format(path=file, error=exc)) from exc
    if not isinstance(body, dict):
        raise NotACheckError(
            UNREADABLE_RECORD.format(path=file, error="it is not a JSON object")
        )
    return body


def recorded_session(directory: Path, record: Mapping[str, Any]) -> ReviewSession:
    """The session `record` describes, or `NotACheckError` naming what the folder holds."""
    file = directory / SESSION_FILE_NAME
    try:
        session = load_session(file)
    except OSError as exc:
        raise NotACheckError(
            NOT_A_CHECK.format(directory=directory, file=SESSION_FILE_NAME)
        ) from exc
    except ValueError as exc:  # a ValidationError is one
        raise NotACheckError(UNREADABLE_RECORD.format(path=file, error=exc)) from exc
    if str(session.session_id) != str(record.get("session_id")):
        raise NotACheckError(
            SESSION_IS_NOT_THE_RECORDED_ONE.format(
                directory=directory,
                session=SESSION_FILE_NAME,
                file=CHECK_FILE_NAME,
                recorded=record.get("session_id"),
                found=session.session_id,
            )
        )
    return session
