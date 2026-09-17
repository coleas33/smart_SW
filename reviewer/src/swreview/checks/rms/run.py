"""The one no-language-model evaluation entry point for the RMS rules (T067).

`swreview check rms` and `POST /checks/rms` are its two callers (FR-024, plan key point
9), and there is exactly one of it so that what an engineer reads in the Model check tab
and what a reviewer reads on the command line cannot be two different evaluations of the
same part. A third option - the add-in launching `swreview check rms --json` as a
subprocess - was weighed and rejected in the plan: `uv run` re-resolves the environment
and imports pydantic, typer and PyYAML, which is one to three seconds of cold start on the
one path where the work itself is tens of milliseconds.

What one call does, in order, and why each step is where it is:

1. **load the package**, and refuse a `features` array that is empty, naming the dump
   profile that wrote it (FR-022). Thirty-four unresolved rules read as a broken part;
   "this package carries no feature tree" reads as a missing extract, which is what it is;
2. **resolve the documents** before anything is written, so an id the package does not
   carry costs nothing;
3. **carry accepted exceptions forward** (FR-029): the newest `exceptions.json` under the
   caller's run root whose package carries the same `design_id`, copied byte-identically
   into the run folder *before the rules run*, so an acceptance survives the next check
   without an engineer copying a file. A missing candidate is reported and is not an
   error; a candidate that cannot be parsed refuses the run, because an unreadable store
   read as "no exceptions" silently re-raises a condition somebody already accepted
   (RK-18). The run root is a parameter and has no default: the pane's check folder sits
   in one, and `swreview check rms` names `--out`'s parent, because the package it is
   pointed at can sit anywhere and the folders beside *it* are not this design's earlier
   runs. A candidate is a folder that is its own package, which is what the pane's check
   folders are; a `swreview check rms --out` run folder is not one, so that command
   carries nothing forward from its own earlier runs and an acceptance survives it
   through the store beside the package instead (`_store_to_grade_against`);
4. **dispatch the check tools through `ToolRegistry` with a `SessionSink`** (defect D1).
   `report.py` gives every finding `tool_result_ids=[context.current_step_id]`, and that id
   is the index the *next* recorded step takes - true only inside a recorded call. Calling
   the check functions directly, as the command line used to, wrote findings citing a step
   that was never recorded. Dispatching through the registry also brings the never-raise
   rule and the `failed` coverage item for a tool that fails;
5. **write the run folder**: `session.json` and `report.md` in `out_dir` - the package
   directory itself when no caller named one - which is what makes a check replayable and
   what `swreview exceptions accept` reads afterwards. A caller that names one is saying
   the package is not its run folder: `swreview check rms` grades a directory an engineer
   chose, and grading a package must not edit it;
6. **record what the session does not** in `check.json`: the scope, the documents graded,
   the structured subjects of each finding and what the carry-forward did. That is what
   makes `read_rms_check` - and so `GET /checks/{check_id}` - a read. Answering a read by
   evaluating the folder again would write a new session id and a new `report.md` every
   time a page was refreshed, over the file an engineer's disposition is recorded in.

No provider is constructed, no key is read and no network call is made on any path here
(SC-011): the only thing this module asks `agent/settings.py` for is the default model id
that `new_session` stamps on the session it writes.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Any, get_args

from pydantic_core import to_jsonable_python

from swreview.agent.runner import load_exceptions
from swreview.checks.rms.grade import RmsGrade, grade
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.ir.loader import PACKAGE_FILE_NAME, LoadedPackage, load_package
from swreview.ir.models import EvidencePackage
from swreview.report.dispositions import REPORT_FILE_NAME, SESSION_FILE_NAME
from swreview.report.markdown import render_report
from swreview.report.session import (
    CoverageBucket,
    ReviewSession,
    load_session,
    save_session,
)
from swreview.tools import rms_checks
from swreview.tools.context import ToolContext, build_context, use_context
from swreview.tools.query import ToolResult
from swreview.tools.registry import RecordingSink, SessionSink, ToolRegistry, record_call

__all__ = [
    "CHECK_FILE_NAME",
    "RMS_DOCUMENT_SCOPES",
    "RMS_SCOPE_CHECKS",
    "RMS_SCOPE_NOT_BUILT",
    "RMS_SCOPE_RUNS",
    "RMS_SCOPE_TOOLS",
    "RMS_SCOPES_BUILT",
    "CarriedForward",
    "EmptyFeatureTreeError",
    "NotACheckError",
    "RmsCheckRun",
    "RmsRunError",
    "RmsScope",
    "UnreadableExceptionsError",
    "carry_forward",
    "is_check_folder",
    "read_rms_check",
    "run_rms_check",
]


class RmsScope(StrEnum):
    """Which family of Resilient Modeling rules a check runs (contracts/cli.md)."""

    part = "part"
    assembly = "assembly"
    equations = "equations"
    all = "all"


RMS_SCOPE_NOT_BUILT = (
    "not yet available in this build: the {scope}-scope rules are in the catalogue but "
    "no check runs them yet, so nothing was evaluated for them and nothing about them "
    "is claimed"
)
"""What a scope this build cannot run reports. It is reported rather than skipped: a
command that answered a scope it does not run with silence would read like a clean one."""

RMS_SCOPE_TOOLS: dict[RmsScope, str] = {
    RmsScope.part: "check_rms_part",
    RmsScope.assembly: "check_rms_assembly",
    RmsScope.equations: "check_rms_equations",
}
"""The curated tool each scope is dispatched as (`contracts/tools.md`). The tool is the
unit of dispatch, not the function, because the step recorded for it is what every finding
of that scope cites (D1)."""

RMS_SCOPE_CHECKS: dict[
    RmsScope, Callable[[ToolContext, Sequence[str] | None], ToolResult]
] = {
    RmsScope.part: rms_checks.run_part_checks,
    RmsScope.equations: rms_checks.run_equation_checks,
}
"""The runner behind each *document-scoped* tool, for the one selection no single tool
call expresses: several named documents (see `_dispatch`). The assembly family is
deliberately absent - it takes no document argument, because only the root assembly's
mates are extracted."""

RMS_DOCUMENT_SCOPES: frozenset[RmsScope] = frozenset(RMS_SCOPE_CHECKS)
"""The families that grade a part document, and so read the feature tree: every family but
the assembly one, whose rules read the mates and the component instances instead. Derived
from `RMS_SCOPE_CHECKS` rather than listed again, so "which families are document-scoped"
has one answer. An empty `features[]` is refused for exactly these (FR-022)."""

RMS_SCOPES_BUILT: frozenset[RmsScope] = frozenset(RMS_SCOPE_TOOLS)
"""Every scope this build actually runs. A scope in `RmsScope` and not here is reported
through `RMS_SCOPE_NOT_BUILT`."""

RMS_SCOPE_RUNS: dict[RmsScope, tuple[RmsScope, ...]] = {
    RmsScope.part: (RmsScope.part,),
    RmsScope.assembly: (RmsScope.assembly,),
    RmsScope.equations: (RmsScope.equations,),
    RmsScope.all: (RmsScope.part, RmsScope.assembly, RmsScope.equations),
}

CHECK_FILE_NAME = "check.json"
"""What a check records beside its session, and why the folder needs a second file.

`session.json` holds the findings and the coverage, and so the grade; it does not hold
which scope ran, which documents were selected, the structured subjects that sit beside
each finding, or what the carry-forward did. Those four are written here, so that reading
a check back is a read rather than a second evaluation (`contracts/model-check.md`
section 1)."""

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
"""What a check reports when its store was handed in. Feature 004 grades two dumps of one
copy against **one** store it refreshed once, so this is the honest reading of what its
carry-forward did: it happened, once, in the run that owns both grades."""

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


class RmsRunError(ValueError):
    """A check that cannot run, described so a caller can report it without a traceback.

    A `ValueError`, so `swreview check rms` turns it into one line on stderr through the
    handled-error list it already has; `error_class` is what the backend route puts in the
    error body of `contracts/model-check.md`.
    """

    error_class = "RmsRunError"


class EmptyFeatureTreeError(RmsRunError):
    """The package carries no feature rows, so there is no tree to grade (FR-022)."""

    error_class = "EmptyFeatureTree"


class UnreadableExceptionsError(RmsRunError):
    """The carry-forward candidate exists and cannot be parsed (FR-029)."""

    error_class = "UnreadableExceptions"


class NotACheckError(RmsRunError):
    """The folder holds no check of its own to read back (`contracts/model-check.md`)."""

    error_class = "UnknownCheck"


@dataclass(frozen=True)
class CarriedForward:
    """What the carry-forward did, including when it did nothing.

    Reported rather than silent in every case: "no exception was carried forward" and
    "two were" are different statements about what silenced what, and an engineer looking
    at a rule that did not fire needs to know which one they are reading.
    """

    from_run: str | None
    """The run folder the file was copied from, or `None` when nothing was copied."""

    count: int
    """How many exceptions the copied file holds; zero when nothing was copied."""

    reason: str | None
    """Why nothing was copied; `None` when something was."""


@dataclass(frozen=True)
class RmsCheckRun:
    """Everything one check produced: what was graded, what it found, and what it wrote."""

    package_dir: Path
    scope: RmsScope
    documents: list[str]
    """The part documents graded, in the order they were selected."""

    assembly_document: str | None
    """The root assembly document graded, or `None` - the scope did not include the
    assembly family, or the package has no assembly document."""

    findings: list[dict[str, Any]]
    subjects: dict[str, list[dict[str, Any]]]
    """The structured subjects of each finding, keyed by finding id and living beside the
    findings rather than on them, so the feature 001 finding contract is unchanged
    (FR-026)."""

    coverage: list[dict[str, Any]]
    """Every coverage item the session holds, as one flat row with its bucket."""

    grade: RmsGrade
    exceptions_carried_forward: CarriedForward
    unavailable_scopes: list[dict[str, str]]
    session: ReviewSession
    session_file: Path
    report_file: Path
    check_file: Path
    """`check.json`: what a reader of the folder needs and the session does not hold."""


def run_rms_check(
    package_dir: Path | str,
    *,
    out_dir: Path | str | None = None,
    scope: RmsScope = RmsScope.all,
    document_id: str | Sequence[str] | None = None,
    families: Sequence[RmsScope] | None = None,
    run_root: Path | str | None = None,
    exceptions: ExceptionStore | None = None,
) -> RmsCheckRun:
    """Grade the package in `package_dir` against the Resilient Modeling rules.

    Args:
        package_dir: The directory holding `package.json`. For a check started from the
            pane this is the check's own run folder. It is read and never written.
        out_dir: The run folder `session.json`, `report.md`, `check.json` and the
            carried-forward `exceptions.json` go into, created when it is not there.
            `None`, the default, is `package_dir` itself, which is what `POST /checks/rms`
            relies on: a check run folder *is* its own package directory, and the route
            reads the folder it passed back as the check. `swreview check rms --out <dir>`
            names one, because it is pointed at a package it must not edit.
        scope: Which rule families to run.
        document_id: One part document id, several, or `None` for every part document in
            the package. Several is the command line's repeatable `--document`; the tab
            sends one or none (`contracts/model-check.md`).
        families: The families to actually run, for a caller that offers fewer than
            `scope` names. `POST /checks/rms` runs `all` as the part and equation families
            because the assembly rules are not calibrated and the route refuses them by
            name; running them under an alias would fold the verdict it refuses to give
            into the grade. Defaults to the families `scope` names.
        run_root: The run root whose earlier run folders the carry-forward may copy an
            `exceptions.json` from (FR-029). Named rather than inferred from
            `package_dir.parent`, because a package is not always a run folder: `None`
            carries nothing forward and reports that. The command line names `--out`'s
            parent; a sibling is a candidate only when it is its own package, so what the
            command line finds there is the pane's check folders, or the package itself
            when `--out` was pointed beside it, and never one of its own run folders.
        exceptions: The store to grade against, for a caller that owns more than one
            grade of the same part and has to apply one store to all of them unchanged.
            Feature 004's re-modeler is that caller: it grades a dump of the copy before
            and after its changes, and `fingerprint_kind_for` makes every `rms.*`
            exception a `feature_tree` fingerprint over every feature row in index order,
            so refreshing again for the second grade would re-open every waiver over the
            rename and the reorder the run just made, and move the delta for exactly the
            wrong reason (`specs/004-resilient-remodeler/contracts/run-artifacts.md`).
            A store given here is used as it is: nothing is carried forward over it and it
            is **not** refreshed, because the caller has already refreshed it against the
            dump it chose. `None`, the default, is every other caller - carry forward
            under `run_root`, load what is beside the package, refresh it here.

    Returns:
        Everything the run produced, with `session.json`, `report.md` and `check.json`
        written into `out_dir`.

    Raises:
        EmptyFeatureTreeError: the package carries no feature rows.
        UnreadableExceptionsError: the carry-forward candidate cannot be parsed.
        RmsRunError: an argument names a document the package does not carry as a part, or
            a check tool reported an error result.
        FileNotFoundError, pydantic.ValidationError, UnsupportedSchemaVersionError: the
            package itself cannot be read, reported by the loader as they always are.
    """
    directory = Path(package_dir).resolve()
    loaded = load_package(directory)
    package = loaded.package
    runs = tuple(families) if families is not None else RMS_SCOPE_RUNS[scope]
    _refuse_empty_feature_tree(directory, package, runs)

    context = build_context(loaded)
    documents = _part_documents(context, document_id)

    # After both refusals above, so a run that is refused for its arguments leaves no
    # folder behind, and before the carry-forward, which copies into it.
    out = directory if out_dir is None else Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    if exceptions is None:
        carried = _carry_forward(out, package, run_root)
        store = _store_to_grade_against(loaded, out)
        if store is not None:
            store.refresh(package)
    else:
        store = exceptions
        carried = CarriedForward(
            from_run=None,
            count=len(store.exceptions),
            reason=SUPPLIED_STORE.format(directory=out),
        )
    context.exceptions = store

    started = perf_counter()
    sink = SessionSink(context)
    dispatch = ToolRegistry().dispatch(context, sink=sink)
    findings: list[dict[str, Any]] = []
    subjects: dict[str, list[dict[str, Any]]] = {}
    graded: list[str] = []
    assembly_document: str | None = None

    for family in runs:
        if family not in RMS_SCOPES_BUILT:
            continue
        payload = _dispatch(dispatch, context, sink, family, documents)
        if "error" in payload:
            raise RmsRunError(str(payload["error"]))
        findings.extend(payload["findings"])
        subjects.update(payload["subjects"])
        if family == RmsScope.assembly:
            # Empty when the package has no assembly document at all: the four rules are
            # then unresolved coverage naming the document that is not one.
            assembly_document = next(iter(payload["documents"]), None)
        else:
            graded = documents

    session = _close(context, started)
    run = RmsCheckRun(
        package_dir=directory,
        scope=scope,
        documents=graded,
        assembly_document=assembly_document,
        findings=findings,
        subjects=subjects,
        coverage=coverage_rows(session),
        grade=grade(session),
        exceptions_carried_forward=carried,
        unavailable_scopes=[
            {"scope": family.value, "reason": RMS_SCOPE_NOT_BUILT.format(scope=family.value)}
            for family in runs
            if family not in RMS_SCOPES_BUILT
        ],
        session=session,
        session_file=save_session(session, out / SESSION_FILE_NAME),
        report_file=_write_report(out, session, package),
        check_file=out / CHECK_FILE_NAME,
    )
    _write_check_record(run)
    return run


def coverage_rows(session: ReviewSession) -> list[dict[str, Any]]:
    """Every coverage item of `session` as one flat row, bucket included."""
    return [
        {"bucket": bucket, **to_jsonable_python(item)}
        for bucket in get_args(CoverageBucket)
        for item in getattr(session.coverage, bucket)
    ]


# --- 1. what is graded ------------------------------------------------------------


def _refuse_empty_feature_tree(
    directory: Path, package: EvidencePackage, runs: Sequence[RmsScope]
) -> None:
    """Refuse a package with no feature rows, naming the profile that wrote it (FR-022).

    Asked of every run that grades a part document (`RMS_DOCUMENT_SCOPES`), because both
    families that do read the tree that is not there. The part rules report 34 unresolved
    rules; the equation rules are worse, because they never skip - both `rms.params.*`
    rules come back as an affirmative "the equation manager holds no equations" over a
    document the extract may never have opened (constitution Principle I). The route of
    `contracts/model-check.md` qualifies its `EmptyFeatureTree` row by no scope, and the
    three scopes it offers - `part`, `equations`, `all` - are all document-scoped.

    The assembly family is the one exception, and it is not a scope the route offers: its
    four rules read the mates and the component instances and never `features[]`, so a
    package of assembly evidence with no part trees in it is a legitimate thing to grade
    rather than a failed extract.
    """
    if not any(family in RMS_DOCUMENT_SCOPES for family in runs):
        return
    if package.features:
        return
    raise EmptyFeatureTreeError(
        EMPTY_FEATURE_TREE.format(directory=directory, profile=package.extractor.profile)
    )


def _part_documents(
    context: ToolContext, document_id: str | Sequence[str] | None
) -> list[str]:
    """The part documents to grade, or `RmsRunError` naming what the package does not have.

    `tools/rms_checks.part_documents` decides this, here as everywhere else, so the
    command line, the route and the tool agree on which documents a selection means and on
    the order they come back in.
    """
    if document_id is None:
        selected: Sequence[str] | None = None
    elif isinstance(document_id, str):
        selected = [document_id]
    else:
        selected = list(document_id)
    documents = rms_checks.part_documents(context, selected)
    if isinstance(documents, dict):
        raise RmsRunError(str(documents["error"]))
    return documents


def _dispatch(
    dispatch: Any,
    context: ToolContext,
    sink: RecordingSink,
    family: RmsScope,
    documents: Sequence[str],
) -> dict[str, Any]:
    """Run one rule family as one recorded call, and return its payload.

    One call per family and not one per document: `report.py` writes aggregated coverage
    through `replace_coverage`, so grading two documents as two calls would leave the
    second one's coverage and drop the first one's.

    The curated tool takes a single document id (`contracts/tools.md`), which expresses
    both selections the tab can make - every part document, or one named part - and those
    go through `ToolRegistry` as FR-024 requires. Several named documents is the one
    selection no single tool call expresses; it runs the same runner the tool runs,
    recorded through the same sink with the same never-raise rule, rather than becoming
    several calls that each replace the coverage of the one before.
    """
    name = RMS_SCOPE_TOOLS[family]
    if family == RmsScope.assembly:
        return dict(dispatch.call(name, {}).payload)
    every_part = rms_checks.part_documents(context, None)
    if list(documents) == every_part:
        return dict(dispatch.call(name, {"document_id": None}).payload)
    if len(documents) == 1:
        return dict(dispatch.call(name, {"document_id": documents[0]}).payload)
    return _recorded(context, sink, name, RMS_SCOPE_CHECKS[family], documents)


def _recorded(
    context: ToolContext,
    sink: RecordingSink,
    name: str,
    run: Callable[[ToolContext, Sequence[str] | None], ToolResult],
    documents: Sequence[str],
) -> dict[str, Any]:
    """`run` over several named documents, recorded as the step its findings will cite.

    The same three things `RecordedTool.call` does for the tool: bind the context, record
    the call through the sink after the function returns - which is what makes
    `ToolContext.current_step_id` the step this call is being recorded as - and turn a
    raise into an error result rather than letting it out.
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


def _close(context: ToolContext, started: float) -> ReviewSession:
    """End the session honestly: when it ended, and how long it ran.

    Deliberately *not* `agent/runner.finalize_session`: that closes out a review's
    checklist, and a check answers one checklist item. Recording the other items as
    "the review ended without a finding for it" would be a claim about a review that never
    started.
    """
    session = context.require_session()
    session.ended_at = datetime.now(UTC)
    session.timing = session.timing.replace(
        unattended_runtime_minutes=(perf_counter() - started) / 60.0
    )
    return session


def _write_report(directory: Path, session: ReviewSession, package: EvidencePackage) -> Path:
    """Render `session` into the run folder and return the file."""
    report_file = directory / REPORT_FILE_NAME
    report_file.write_text(render_report(session, package), encoding="utf-8")
    return report_file


# --- 2. the carry-forward (FR-029) ------------------------------------------------


def _store_to_grade_against(loaded: LoadedPackage, out: Path) -> ExceptionStore | None:
    """The `exceptions.json` this run grades against: the run folder's, else the package's.

    The run folder first, because that is where the carry-forward just wrote (FR-029) and
    a copy nothing graded against would silence nothing - the acceptance would quietly
    not survive the next check. The package's own store is the fallback, because a package
    the command line is pointed at is read where it is: its waivers are evidence about it,
    and a run folder somewhere else does not make them disappear.

    The two are the same file whenever `out_dir` was not named, which is every caller but
    `swreview check rms --out <dir>`, so this is one rule and not a branch on the caller.
    """
    carried = out / EXCEPTIONS_FILE_NAME
    if carried.is_file():
        return ExceptionStore(carried).load()
    return load_exceptions(loaded)


def _carry_forward(
    directory: Path, package: EvidencePackage, run_root: Path | str | None
) -> CarriedForward:
    """This check's carry-forward: the design is the package's own (FR-029)."""
    return carry_forward(
        directory, design_id=package.design.design_id, run_root=run_root
    )


def carry_forward(
    directory: Path,
    *,
    design_id: str,
    run_root: Path | str | None,
    design_id_of: Callable[[Path], str | None] | None = None,
) -> CarriedForward:
    """Copy the newest same-design `exceptions.json` under `run_root` into `directory`.

    A candidate is a folder directly under the run root that holds both a package naming
    the same `design_id` and an `exceptions.json`. Newest is by the file's own
    modification time, with the folder name as the tie-break so two files written in the
    same second still order the same way on every run.

    The run root is the caller's and has no default. `POST /checks/rms` knows its own
    (`--run-root`, and the check folder is created under it), while `swreview check rms
    --package <dir>` is pointed at any directory at all - so inferring the root from the
    package's parent is how a store the engineer never asked about is copied into their
    directory, and how an unrelated folder's truncated file refuses a run that has nothing
    to do with it. A caller that names no run root carries nothing forward, and is told so.

    The copy is a byte copy, not a load and a re-save: a store that round-tripped through
    this build would silently rewrite what an engineer accepted under an older one.

    `design_id_of` is how a candidate folder's design is read, and it is a parameter
    because feature 004's candidates are read two ways: a `-check` folder from its
    `package.json`, a `-remodel` folder from its `source-attestation.json`, whose packages
    are dumps of a copy and carry that copy's path-derived id. The default is this
    module's: `package.json`, `design.design_id`.
    """
    read_design_id = _design_id_of if design_id_of is None else design_id_of
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


def _design_id_of(directory: Path) -> str | None:
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


# --- 3. the check record: what makes a read a read (T072) -------------------------


def _write_check_record(run: RmsCheckRun) -> Path:
    """Write `check.json` for `run`, and return the file.

    `session_id` is what ties the two halves of a check together. A folder whose
    `session.json` is no longer the one this record describes - a review claimed the
    folder and rotated the check's session aside, or a later run replaced it - is no
    longer this check, and reading it must say so rather than answer with somebody else's
    session.
    """
    carried = run.exceptions_carried_forward
    body = {
        "session_id": str(run.session.session_id),
        "scope": run.scope.value,
        "documents": run.documents,
        "assembly_document": run.assembly_document,
        "subjects": run.subjects,
        "exceptions_carried_forward": {
            "from_run": carried.from_run,
            "count": carried.count,
            "reason": carried.reason,
        },
        "unavailable_scopes": run.unavailable_scopes,
    }
    run.check_file.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return run.check_file


def read_rms_check(check_dir: Path | str) -> RmsCheckRun:
    """The check `check_dir` holds, rebuilt from the folder. Nothing is evaluated.

    This is what makes `GET /checks/{check_id}` a read (`contracts/model-check.md`
    section 1). Re-running the rules to answer it would write a new `session.json` and a
    new `report.md` on every page refresh: a new session id for the same check, over the
    file `swreview exceptions accept` reads by name and an engineer's recorded disposition
    lives in. The findings, the coverage and the grade come off the session, which is the
    record of what the rules said; everything else comes off `check.json`.

    Raises:
        NotACheckError: the folder holds no check record, holds one that cannot be read,
            or holds a session that its record does not name.
    """
    directory = Path(check_dir).resolve()
    record = _check_record(directory)
    session = _recorded_session(directory, record)
    try:
        return RmsCheckRun(
            package_dir=directory,
            scope=RmsScope(str(record["scope"])),
            documents=[str(item) for item in record["documents"]],
            assembly_document=record["assembly_document"],
            findings=[finding.model_dump(mode="json") for finding in session.findings],
            subjects=record["subjects"],
            coverage=coverage_rows(session),
            grade=grade(session),
            exceptions_carried_forward=CarriedForward(
                **record["exceptions_carried_forward"]
            ),
            unavailable_scopes=record["unavailable_scopes"],
            session=session,
            session_file=directory / SESSION_FILE_NAME,
            report_file=directory / REPORT_FILE_NAME,
            check_file=directory / CHECK_FILE_NAME,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise NotACheckError(
            UNREADABLE_RECORD.format(
                path=directory / CHECK_FILE_NAME, error=f"{type(exc).__name__}: {exc}"
            )
        ) from exc


def is_check_folder(directory: Path | str) -> bool:
    """Whether `directory` holds a check record naming the session that is in it.

    What `POST /sessions` asks before refusing a folder that already holds a session: a
    check's `session.json` is not a review's - a check writes no event stream, which is
    what that rule protects - so a review may claim the folder a check wrote (User Story 6
    scenario 11).
    """
    try:
        read_rms_check(directory)
    except NotACheckError:
        return False
    return True


def _check_record(directory: Path) -> Mapping[str, Any]:
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


def _recorded_session(directory: Path, record: Mapping[str, Any]) -> ReviewSession:
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
