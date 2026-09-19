"""The one no-language-model evaluation entry point for the standards checks (T052).

`swreview check standards` and `POST /checks/standards` are its two callers (FR-043,
`contracts/cli.md`, `contracts/standards-check.md` section 1), and there is exactly one of
it so that what an engineer reads in the Standards tab and what a release gate reads on the
command line cannot be two different gradings of the same design.

What one call does, in order, and why each step is where it is:

1. **load and validate the profile**, in one place and with no fallback (FR-002). A
   missing, unreadable or schema-invalid profile refuses the run by name, first, **before
   anything is created**: a default value would grade a document against the wrong standard
   and report a clean result, which is the worst failure a release gate has;
2. **load the package and refuse one that does not carry the evidence** (FR-043). The test
   is the **phase rows** and not the profile name: the `cutlist` row, plus the `drawing` row
   when the root document is a drawing. Any package that actually ran them is accepted,
   whatever profile produced it, and the refusal names the profile that produced this one
   and the phases that are missing - because sixteen unresolved checks read as a broken
   model rather than as a missing extract;
3. **decide the graded set once** (FR-003), which is also the last refusal a run can make:
   a root with no recorded kind or no path has no check sequence to run, and refusing it
   here means a refused run leaves no folder behind;
4. **carry accepted exceptions forward** (FR-041): the newest `exceptions.json` under the
   caller's run root whose package carries the same `design_id`, copied byte-identically
   into the run folder *before the checks run*. A missing candidate is reported and is not
   an error; a candidate that cannot be parsed refuses the run, because an unreadable store
   read as "no exceptions" silently re-raises a condition somebody already accepted;
5. **dispatch the one check tool through `ToolRegistry` with a `SessionSink`** (FR-035).
   `checks/standards/report.py` gives every finding `tool_result_ids=[current_step_id]`, and
   that id is the index the *next* recorded step takes - true only inside a recorded call.
   The tool is offered only because this module attached the run to the context, which is
   also what makes it invisible to every other tab;
6. **write the run folder**: `session.json`, `report.md` and `check.json` into `out_dir`,
   the report headed by the verdict and the no-rebuild sentence. The package directory is
   **read and never written** (SC-010): grading a package must not edit it;
7. **record what the session does not** in `check.json` - the documents and their kinds, the
   profile **identity only**, the verdict, the structured subjects, what the carry-forward
   did and which checks this build does not run. That is what makes `read_standards_check`,
   and so `GET /checks/{check_id}`, a read rather than a second evaluation over the file an
   engineer's disposition is recorded in.

No provider is constructed, no key is read and no network call is made on any path
(FR-045): the only thing this module asks `agent/settings.py` for is the default model id
that `new_session` stamps on the session it writes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from swreview.checks.rules.run import (
    CHECK_FILE_NAME,
    SUPPLIED_STORE,
    UNREADABLE_RECORD,
    CarriedForward,
    CheckRunError,
    NotACheckError,
    UnreadableExceptionsError,
    carry_forward,
    check_record,
    close_session,
    coverage_rows,
    recorded_session,
    store_to_grade_against,
    write_check_record,
)
from swreview.checks.standards.profile import (
    ProfileIdentity,
    load_profile,
)
from swreview.checks.standards.registry import CHECK_TOOL, STANDARDS_FAMILY
from swreview.checks.standards.report import check_rows, verdict_from, verdict_json
from swreview.checks.standards.traversal import (
    UngradableRootError,
    graded_documents,
)
from swreview.checks.standards.verdict import (
    NO_REBUILD_SENTENCE,
    VERDICT_HEADER,
    ReleaseVerdict,
    verdict_header,
)
from swreview.exceptions import ExceptionStore
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.attention import rank
from swreview.report.attention_record import write_attention_record
from swreview.report.dispositions import REPORT_FILE_NAME, SESSION_FILE_NAME
from swreview.report.markdown import render_report
from swreview.report.session import ReviewSession, save_session
from swreview.tools.context import build_context
from swreview.tools.registry import SessionSink, ToolRegistry
from swreview.tools.standards_checks import (
    StandardsRun,
    attach_standards_run,
    unavailable_checks,
)

__all__ = [
    "CHECK_FILE_NAME",
    "MISSING_PHASES",
    "NOT_THIS_FAMILY",
    "NO_CHECK_TOOL",
    "NO_REBUILD_SENTENCE",
    "STANDARDS_PHASES",
    "VERDICT_HEADER",
    "CarriedForward",
    "MissingStandardsPhasesError",
    "NotACheckError",
    "StandardsCheckRun",
    "StandardsRunError",
    "UngradableRootError",
    "UnreadableExceptionsError",
    "missing_standards_phases",
    "read_standards_check",
    "run_standards_check",
]

StandardsRunError = CheckRunError
"""A check that cannot run, described so a caller can report it without a traceback.

The family-neutral `CheckRunError` under the name this family's callers catch: a
`ValueError`, so `swreview check standards` turns it into one line on stderr through the
handled-error list it already has, and `error_class` is what `POST /checks/standards` puts
in the error body. `MissingStandardsPhasesError`, `UngradableRootError`,
`UnreadableExceptionsError` and `NotACheckError` are its subclasses, so a caller that
catches this one catches every refusal a run can make. The two **profile** refusals are
not: they are `ProfileUnreadable` and `ProfileInvalid`, which carry their own error classes
and are raised by the one module that owns the schema (FR-002).
"""

STANDARDS_PHASES: tuple[str, ...] = ("cutlist",)
"""The phases every standards check reads, whatever the root document is.

`document`, `manifest`, `mate`, `feature` and `equation` are run by every profile this
build has, including `model_check`, so a package that carries none of them is a package the
loader has already refused; `cutlist` is what the `standards` profile adds, and it is the
row that tells a standards extract from a model-check one (`data-model.md` section 2.5).
"""

DRAWING_PHASE = "drawing"
"""Asked for only when the root document is a drawing: a standards dump of a part or an
assembly records this row `skipped` by design, and requiring it would refuse every model
run (`data-model.md` section 2.5)."""

NEVER_RAN = "skipped"
"""The one status that means a phase did not run. A `failed` phase **ran**: what it lost is
recorded as gaps, and the checks that read them report unresolved, which is the honest
answer. Only a phase nobody ran makes the evidence absent."""

MISSING_PHASES = (
    "{directory} does not carry the evidence the standards checks read: its {phases} phase "
    "row(s) are recorded {status!r} and it was written by the {profile!r} dump profile. "
    "Extract the design again with --profile standards; grading it as it stands would "
    "report unresolved checks that read as a broken model rather than as a missing extract"
)

NO_CHECK_TOOL = (
    "the {tool} tool was not offered for this run, so nothing was dispatched; a standards "
    "run is attached to the context before the tools are built, and without it the check "
    "tool is not registered at all"
)

NOT_THIS_FAMILY = (
    "{directory} holds a {family!r} check and this is the {ours!r} family's reader; one "
    "family never answers for the other's record"
)

class MissingStandardsPhasesError(CheckRunError):
    """The package does not record the phases the standards checks read (FR-043)."""

    error_class = "MissingStandardsPhases"


@dataclass(frozen=True)
class StandardsCheckRun:
    """Everything one standards check produced: what was graded, found and written."""

    package_dir: Path
    documents: list[str]
    """Every document graded, in traversal order."""

    document_kinds: dict[str, str | None]
    """The kind of each graded document; `None` for one the package records none for, which
    is unresolved coverage for every check rather than a document nobody mentions."""

    document_reached_by: dict[str, str]
    """How the traversal reached each graded document: `root`, `component_tree` or
    `drawing_reference` (`contracts/standards-check.md` section 1). Carried here rather
    than left on the traversal, because it is the field that tells a reader a document was
    pulled in by a drawing view rather than by a component tree, and a read of the folder
    answers with it too."""

    profile: ProfileIdentity
    """`{path, sha256}` and never a profile value (FR-001, FR-034)."""

    verdict: ReleaseVerdict
    findings: list[dict[str, Any]]
    subjects: dict[str, list[dict[str, Any]]]
    """The structured subjects of each finding, keyed by finding id and living beside the
    findings rather than on them, so the feature 001 finding contract is unchanged."""

    coverage: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    """All sixteen checks with the buckets each landed in and the worst of them (FR-033)."""

    exceptions_carried_forward: CarriedForward
    unavailable_checks: list[dict[str, str]]
    session: ReviewSession
    session_file: Path
    report_file: Path
    check_file: Path


def run_standards_check(
    package_dir: Path | str,
    profile_path: Path | str,
    out_dir: Path | str,
    *,
    run_root: Path | str | None = None,
    exceptions: ExceptionStore | None = None,
) -> StandardsCheckRun:
    """Grade the package in `package_dir` against the sixteen release checks.

    Args:
        package_dir: The directory holding `package.json`. For a check started from the
            pane this is the check's own run folder. It is read and never written.
        profile_path: The standards profile this design is graded against. There is no
            default and no fallback: a run without a usable profile is refused (FR-002).
        out_dir: The run folder `session.json`, `report.md`, `check.json` and the
            carried-forward `exceptions.json` go into, created when it is not there. The
            pane passes its check run folder, which is also the package directory;
            `swreview check standards --out <dir>` passes a directory beside the package,
            because grading a package must not edit it.
        run_root: The run root whose earlier folders the carry-forward may copy an
            `exceptions.json` from (FR-041). Named rather than inferred from
            `package_dir.parent`, because a package is not always a run folder: `None`
            carries nothing forward and reports that.
        exceptions: The store to grade against, for a caller that owns more than one
            grading of the same design and has to apply one store to all of them unchanged.
            A store given here is used as it is: nothing is carried forward over it.

    Returns:
        Everything the run produced, with `session.json`, `report.md` and `check.json`
        written into `out_dir`.

    Raises:
        ProfileUnreadable, ProfileInvalid: the profile cannot be used (FR-002).
        MissingStandardsPhasesError: the package does not record the phases the checks read.
        UngradableRootError: the root document has no recorded kind or has never been saved.
        UnreadableExceptionsError: the carry-forward candidate cannot be parsed.
        StandardsRunError: the check tool reported an error result.
        FileNotFoundError, pydantic.ValidationError, UnsupportedSchemaVersionError: the
            package itself cannot be read, reported by the loader as they always are.
    """
    profile = load_profile(profile_path)

    directory = Path(package_dir).resolve()
    loaded = load_package(directory)
    package = loaded.package
    _refuse_missing_phases(directory, package)

    context = build_context(loaded)
    documents = graded_documents(package, profile)

    # After every refusal above, so a refused run leaves no folder behind, and before the
    # carry-forward, which copies into it.
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    if exceptions is None:
        carried = carry_forward(
            out, design_id=package.design.design_id, run_root=run_root
        )
        store = store_to_grade_against(loaded, out)
        if store is not None:
            store.refresh(package)
    else:
        store = exceptions
        carried = CarriedForward(
            from_run=None, count=len(store.exceptions), reason=SUPPLIED_STORE.format(directory=out)
        )
    context.exceptions = store
    attach_standards_run(context, StandardsRun(profile=profile, documents=documents))

    started = perf_counter()
    payload = _dispatch(context)
    session = close_session(context, started)
    verdict = verdict_from(payload["verdict"])

    run = StandardsCheckRun(
        package_dir=directory,
        documents=[document.document_id for document in documents],
        document_kinds={
            document.document_id: document.kind for document in documents
        },
        document_reached_by={
            document.document_id: document.reached_by for document in documents
        },
        profile=profile.identity,
        verdict=verdict,
        findings=list(payload["findings"]),
        subjects=dict(payload["subjects"]),
        coverage=coverage_rows(session),
        checks=check_rows(session),
        exceptions_carried_forward=carried,
        unavailable_checks=unavailable_checks(),
        session=session,
        session_file=save_session(session, out / SESSION_FILE_NAME),
        report_file=_write_report(out, session, package, verdict),
        check_file=out / CHECK_FILE_NAME,
    )
    _write_check_record(run)
    return run


# --- 1. the refusals ----------------------------------------------------------------------


def missing_standards_phases(package: EvidencePackage) -> list[str]:
    """The phases the standards checks read whose rows say they never ran, in wanted order.

    The rows and not the profile name, so a `full` extract that ran them is gradable and a
    `standards` extract from a build that did not is not. A phase the package records no row
    for at all is missing too: a row is how a package says a phase ran, and inferring "it
    must have" from an empty array is the assumption this test exists to remove.

    Public because two callers ask the same question and must not answer it twice: this
    family's own entry point **refuses** a package that fails it (`_refuse_missing_phases`),
    and the gate's `prerun.attach_standards` turns the same condition into a not-evaluated
    line rather than losing the review over it (`contracts/gate.md` section 2).
    """
    wanted = [*STANDARDS_PHASES]
    if _root_kind(package) == "drawing":
        wanted.append(DRAWING_PHASE)
    ran = {row.name: row.status for row in package.extractor.phases}
    return [name for name in wanted if ran.get(name, NEVER_RAN) == NEVER_RAN]


def _refuse_missing_phases(directory: Path, package: EvidencePackage) -> None:
    """Refuse a package whose phase rows show the standards phases never ran (FR-043)."""
    missing = missing_standards_phases(package)
    if not missing:
        return
    raise MissingStandardsPhasesError(
        MISSING_PHASES.format(
            directory=directory,
            phases=", ".join(missing),
            status=NEVER_RAN,
            profile=package.extractor.profile,
        )
    )


def _root_kind(package: EvidencePackage) -> str | None:
    """The kind of the root document, whatever it is (`ir-additions.md` section 7)."""
    root = package.design.root_assembly_document_id
    return next(
        (row.kind for row in package.documents if row.document_id == root), None
    )


# --- 2. the dispatch ----------------------------------------------------------------------


def _dispatch(context: Any) -> dict[str, Any]:
    """The family's one check tool, run as the step its findings will cite (FR-035).

    Built through `ToolRegistry` rather than called directly, which is what records the
    step: a finding citing a step that was never recorded is a finding whose evidence
    cannot be looked up, and that is what this indirection buys.
    """
    tools = ToolRegistry().build(context, sink=SessionSink(context))
    tool = next((item for item in tools if item.name == CHECK_TOOL), None)
    if tool is None:  # pragma: no cover - the run attaches itself before building
        raise StandardsRunError(NO_CHECK_TOOL.format(tool=CHECK_TOOL))
    payload = dict(tool.call({}).payload)
    if "error" in payload:
        raise StandardsRunError(str(payload["error"]))
    return payload


# --- 3. the run folder --------------------------------------------------------------------


def _write_report(
    directory: Path, session: ReviewSession, package: EvidencePackage, verdict: ReleaseVerdict
) -> Path:
    """The rendered report, headed by the verdict and the no-rebuild sentence (FR-033).

    Deliberately not a second renderer: the body is feature 001's `render_report`, and what
    this feature adds is the header a release gate reads first. A reader who sees the counts
    without being told that nothing was rebuilt would read the rebuild-error checks as a
    statement about the design now rather than as it stood (difference g).

    The header is `verdict.verdict_header` over the same `verdict_json` block
    `_write_check_record` writes into `check.json`, so `report/rerender.py` rebuilds it byte
    for byte from the folder when an offline command re-renders this report (research R2.7).

    `attention.json` is written here too, from the one `Ranking` the body is rendered with,
    so the "Start here" section under the header and the record beside the session are the
    same order by construction rather than by two calls agreeing.
    """
    ranking = rank(session)
    header = verdict_header(session.design_id, verdict_json(verdict))
    report_file = directory / REPORT_FILE_NAME
    report_file.write_text(
        header + render_report(session, package, ranking=ranking), encoding="utf-8"
    )
    write_attention_record(directory, ranking, session.session_id)
    return report_file


def _write_check_record(run: StandardsCheckRun) -> Path:
    """Write `check.json` for `run`, stamped with the family, and return the file."""
    carried = run.exceptions_carried_forward
    return write_check_record(
        run.check_file,
        STANDARDS_FAMILY,
        {
            "session_id": str(run.session.session_id),
            "documents": run.documents,
            "document_kinds": run.document_kinds,
            "document_reached_by": run.document_reached_by,
            "profile": {"path": run.profile.path, "sha256": run.profile.sha256},
            "verdict": verdict_json(run.verdict),
            "subjects": run.subjects,
            "exceptions_carried_forward": {
                "from_run": carried.from_run,
                "count": carried.count,
                "reason": carried.reason,
            },
            "unavailable_checks": run.unavailable_checks,
        },
    )


def read_standards_check(check_dir: Path | str) -> StandardsCheckRun:
    """The standards check `check_dir` holds, rebuilt from the folder. Nothing is evaluated.

    This is what makes `GET /checks/{check_id}` a read (`contracts/standards-check.md`
    section 1). Re-running the checks to answer it would write a new `session.json` and a
    new `report.md` on every page refresh, over the file an engineer's recorded disposition
    lives in. The findings, the coverage and the sixteen rendered rows come off the session,
    which is the record of what the checks said; everything else comes off `check.json`.

    Raises:
        NotACheckError: the folder holds no check record, holds one that cannot be read,
            holds a session that its record does not name, or holds another family's check.
    """
    directory = Path(check_dir).resolve()
    record = check_record(directory)
    family = str(record.get("family", "rms"))
    if family != STANDARDS_FAMILY.check_file_family:
        raise NotACheckError(
            NOT_THIS_FAMILY.format(
                directory=directory,
                family=family,
                ours=STANDARDS_FAMILY.check_file_family,
            )
        )
    session = recorded_session(directory, record)
    try:
        return StandardsCheckRun(
            package_dir=directory,
            documents=[str(item) for item in record["documents"]],
            document_kinds=dict(record["document_kinds"]),
            document_reached_by=dict(record["document_reached_by"]),
            profile=ProfileIdentity(**record["profile"]),
            verdict=verdict_from(record["verdict"]),
            findings=[finding.model_dump(mode="json") for finding in session.findings],
            subjects=_subjects(record["subjects"]),
            coverage=coverage_rows(session),
            checks=check_rows(session),
            exceptions_carried_forward=CarriedForward(**record["exceptions_carried_forward"]),
            unavailable_checks=[dict(row) for row in record["unavailable_checks"]],
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


def _subjects(body: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        str(finding_id): [dict(entry) for entry in entries]
        for finding_id, entries in body.items()
    }
