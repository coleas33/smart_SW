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

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Any

from swreview.checks.rms.grade import RmsGrade, grade
from swreview.checks.rms.registry import RMS_FAMILY
from swreview.checks.rules.run import (
    CHECK_FILE_NAME,
    EMPTY_FEATURE_TREE,
    SUPPLIED_STORE,
    UNREADABLE_RECORD,
    CarriedForward,
    CheckRunError,
    EmptyFeatureTreeError,
    NotACheckError,
    UnreadableExceptionsError,
    carry_forward,
    check_record,
    close_session,
    coverage_rows,
    recorded_call,
    recorded_session,
    store_to_grade_against,
    write_check_record,
    write_report,
)
from swreview.exceptions import ExceptionStore
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.dispositions import REPORT_FILE_NAME, SESSION_FILE_NAME
from swreview.report.session import ReviewSession, save_session
from swreview.tools import rms_checks
from swreview.tools.context import ToolContext, build_context
from swreview.tools.query import ToolResult
from swreview.tools.registry import RecordingSink, SessionSink, ToolRegistry

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
    "coverage_rows",
    "is_check_folder",
    "read_rms_check",
    "run_rms_check",
]

RmsRunError = CheckRunError
"""A check that cannot run, described so a caller can report it without a traceback.

The family-neutral `CheckRunError` under the name this family's callers already catch: a
`ValueError`, so `swreview check rms` turns it into one line on stderr through the
handled-error list it already has, and `error_class` is what the backend route puts in the
error body of `contracts/model-check.md`. `EmptyFeatureTreeError`,
`UnreadableExceptionsError` and `NotACheckError` are its subclasses, so a caller that
catches this one catches every refusal a run can make.
"""


class RmsScope(StrEnum):
    """Which scope of Resilient Modeling rules a check runs (contracts/cli.md)."""

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
    RmsScope(scope): tool for scope, tool in RMS_FAMILY.tools.items()
}
"""The curated tool each scope is dispatched as (`contracts/tools.md`). The tool is the
unit of dispatch, not the function, because the step recorded for it is what every finding
of that scope cites (D1). "Scope" throughout this module is what `RmsScope` and
`RULES.scope` have always called it; `family` here means the rms rules as against the
standards checks (`specs/006-standards-check/research.md` R7).

Read off `RMS_FAMILY.tools`, which is where the family's facts live, rather than typed out
a second time: a scope this build dispatches is one fact, and the run folder's record and
the family descriptor must not be able to disagree about it."""

RMS_SCOPE_CHECKS: dict[
    RmsScope, Callable[[ToolContext, Sequence[str] | None], ToolResult]
] = {
    RmsScope.part: rms_checks.run_part_checks,
    RmsScope.equations: rms_checks.run_equation_checks,
}
"""The runner behind each *document-scoped* tool, for the one selection no single tool
call expresses: several named documents (see `_dispatch`). The assembly scope is
deliberately absent - it takes no document argument, because only the root assembly's
mates are extracted."""

RMS_DOCUMENT_SCOPES: frozenset[RmsScope] = frozenset(RMS_SCOPE_CHECKS)
"""The scopes that grade a part document, and so read the feature tree: every scope but
the assembly one, whose rules read the mates and the component instances instead. Derived
from `RMS_SCOPE_CHECKS` rather than listed again, so "which scopes are document-scoped"
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


@dataclass(frozen=True)
class RmsCheckRun:
    """Everything one check produced: what was graded, what it found, and what it wrote."""

    package_dir: Path
    scope: RmsScope
    documents: list[str]
    """The part documents graded, in the order they were selected."""

    assembly_document: str | None
    """The root assembly document graded, or `None` - the run did not include the
    assembly scope, or the package has no assembly document."""

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
    scopes: Sequence[RmsScope] | None = None,
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
        scope: Which rule scopes to run.
        document_id: One part document id, several, or `None` for every part document in
            the package. Several is the command line's repeatable `--document`; the tab
            sends one or none (`contracts/model-check.md`).
        scopes: The rule scopes to actually run, for a caller that offers fewer than
            `scope` names. `POST /checks/rms` runs `all` as the part and equation scopes
            because the assembly rules are not calibrated and the route refuses them by
            name; running them under an alias would fold the verdict it refuses to give
            into the grade. Defaults to the scopes `scope` names.
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
    runs = tuple(scopes) if scopes is not None else RMS_SCOPE_RUNS[scope]
    _refuse_empty_feature_tree(directory, package, runs)

    context = build_context(loaded)
    documents = _part_documents(context, document_id)

    # After both refusals above, so a run that is refused for its arguments leaves no
    # folder behind, and before the carry-forward, which copies into it.
    out = directory if out_dir is None else Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    if exceptions is None:
        carried = _carry_forward(out, package, run_root)
        store = store_to_grade_against(loaded, out)
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

    for run_scope in runs:
        if run_scope not in RMS_SCOPES_BUILT:
            continue
        payload = _dispatch(dispatch, context, sink, run_scope, documents)
        if "error" in payload:
            raise RmsRunError(str(payload["error"]))
        findings.extend(payload["findings"])
        subjects.update(payload["subjects"])
        if run_scope == RmsScope.assembly:
            # Empty when the package has no assembly document at all: the four rules are
            # then unresolved coverage naming the document that is not one.
            assembly_document = next(iter(payload["documents"]), None)
        else:
            graded = documents

    session = close_session(context, started)
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
            {
                "scope": run_scope.value,
                "reason": RMS_SCOPE_NOT_BUILT.format(scope=run_scope.value),
            }
            for run_scope in runs
            if run_scope not in RMS_SCOPES_BUILT
        ],
        session=session,
        session_file=save_session(session, out / SESSION_FILE_NAME),
        report_file=write_report(out, session, package),
        check_file=out / CHECK_FILE_NAME,
    )
    _write_check_record(run)
    return run


# --- 1. what is graded ------------------------------------------------------------


def _refuse_empty_feature_tree(
    directory: Path, package: EvidencePackage, runs: Sequence[RmsScope]
) -> None:
    """Refuse a package with no feature rows, naming the profile that wrote it (FR-022).

    Asked of every run that grades a part document (`RMS_DOCUMENT_SCOPES`), because both
    scopes that do read the tree that is not there. The part rules report 34 unresolved
    rules; the equation rules are worse, because they never skip - both `rms.params.*`
    rules come back as an affirmative "the equation manager holds no equations" over a
    document the extract may never have opened (constitution Principle I). The route of
    `contracts/model-check.md` qualifies its `EmptyFeatureTree` row by no scope, and the
    three scopes it offers - `part`, `equations`, `all` - are all document-scoped.

    The assembly scope is the one exception, and it is not a scope the route offers: its
    four rules read the mates and the component instances and never `features[]`, so a
    package of assembly evidence with no part trees in it is a legitimate thing to grade
    rather than a failed extract.
    """
    if not any(run_scope in RMS_DOCUMENT_SCOPES for run_scope in runs):
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
    scope: RmsScope,
    documents: Sequence[str],
) -> dict[str, Any]:
    """Run one rule scope as one recorded call, and return its payload.

    The parameter is the rule **scope** - what `RmsScope` and `RULES.scope` have always
    called it - and not a "family", which now means the rms rules as against the standards
    checks (`specs/006-standards-check/research.md` R7).

    One call per scope and not one per document: `report.py` writes aggregated coverage
    through `replace_coverage`, so grading two documents as two calls would leave the
    second one's coverage and drop the first one's.

    The curated tool takes a single document id (`contracts/tools.md`), which expresses
    both selections the tab can make - every part document, or one named part - and those
    go through `ToolRegistry` as FR-024 requires. Several named documents is the one
    selection no single tool call expresses; it runs the same runner the tool runs,
    recorded through the same sink with the same never-raise rule, rather than becoming
    several calls that each replace the coverage of the one before.
    """
    name = RMS_SCOPE_TOOLS[scope]
    if scope == RmsScope.assembly:
        return dict(dispatch.call(name, {}).payload)
    every_part = rms_checks.part_documents(context, None)
    if list(documents) == every_part:
        return dict(dispatch.call(name, {"document_id": None}).payload)
    if len(documents) == 1:
        return dict(dispatch.call(name, {"document_id": documents[0]}).payload)
    return recorded_call(context, sink, name, RMS_SCOPE_CHECKS[scope], documents)


# --- 2. the carry-forward (FR-029) ------------------------------------------------


def _carry_forward(
    directory: Path, package: EvidencePackage, run_root: Path | str | None
) -> CarriedForward:
    """This check's carry-forward: the design is the package's own (FR-029)."""
    return carry_forward(
        directory, design_id=package.design.design_id, run_root=run_root
    )


# --- 3. the check record: what makes a read a read (T072) -------------------------


def _write_check_record(run: RmsCheckRun) -> Path:
    """Write `check.json` for `run`, and return the file.

    What is written here is what a reader of the folder needs and `session.json` does not
    hold; the family stamp and the file itself are `checks/rules/run.py`'s, because a
    backend handed a run directory has to know whose check it is holding before it can
    answer a read of it.
    """
    carried = run.exceptions_carried_forward
    return write_check_record(
        run.check_file,
        RMS_FAMILY,
        {
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
        },
    )


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
    record = check_record(directory)
    session = recorded_session(directory, record)
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
