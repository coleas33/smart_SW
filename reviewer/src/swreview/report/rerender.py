"""Re-render one run folder's report from the files the folder itself holds.

Three commands re-render a run they did not run - `swreview timing`, `swreview
disposition` and `swreview exceptions accept-rms` / `accept-standards`. Each of them used
to call `render_report(session)` with nothing but the session, which quietly threw away
two things the folder was holding all along: `package.json`, without which every component
reads as a bare id and Manifest Discrepancies degrades to "the evidence package was not
supplied to the renderer", and a standards folder's verdict header, which `_write_report`
prepends outside the renderer and a plain re-render therefore deletes.

So the re-render is **one** function that reads the folder for everything the renderer
needs, and the three commands call it rather than each rendering a little differently
(research R2.7). It writes `report.md` and `attention.json` from one `Ranking`, so the
"Start here" section and the record beside it are the same order by construction.

This module also names the files a run folder holds, because it is the one module that has
to know all of them at once. `report/dispositions.py` and `checks/rules/run.py` re-export
the names their own callers already import. Two of the four are defined elsewhere and
re-exported here rather than restated: `session.json` beside `load_session`, and
`attention.json` beside the record's reader and writer, which this module calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

from swreview.ir.loader import PACKAGE_FILE_NAME, load_package
from swreview.ir.models import EvidencePackage
from swreview.report.attention import rank
from swreview.report.attention_record import ATTENTION_FILE_NAME, write_attention_record
from swreview.report.markdown import render_report
from swreview.report.session import SESSION_FILE_NAME, ReviewSession, load_session

__all__ = [
    "ATTENTION_FILE_NAME",
    "BENCHMARK_RUN_ROOT",
    "CHECK_FILE_NAME",
    "NO_SESSION",
    "REPORT_FILE_NAME",
    "SESSION_FILE_NAME",
    "UNREADABLE_CHECK_RECORD",
    "rerender_run_folder",
    "run_folder_session",
]

REPORT_FILE_NAME = "report.md"
CHECK_FILE_NAME = "check.json"

NO_SESSION = "{path} is not a file, so {directory} holds no run to re-render"

BENCHMARK_RUN_ROOT = (
    "{directory} holds no {session} of its own, but {count} folder(s) below it do "
    "({packages}), which is a benchmark run root and not a run folder. Record timing "
    "against one package of it with `swreview benchmark time {directory} <package_id>`"
)
"""Why a benchmark run root is named rather than reported as a missing session: the two
layouts differ by one level, and an engineer who reaches for the wrong command should be
told which one is the right one rather than that a file is absent (contract timing.md
section 2)."""

UNREADABLE_CHECK_RECORD = (
    "{path} cannot be read as a check record ({error}), so the verdict header it carries "
    "cannot be rebuilt; re-rendering over it would silently drop that header"
)


def rerender_run_folder(run_dir: Path | str) -> Path:
    """Re-render a run folder's report and record from its own files; return the report path.

    Reads `session.json` (required), `package.json` (when the folder holds one) and
    `check.json` (for a standards folder's verdict header), ranks the session once, and
    writes `report.md` and `attention.json` from that one `Ranking` - the same object, so
    the section the report prints and the record beside it can never disagree (research
    R2.7). Nothing else in the folder is touched, and nothing at all is written when any of
    the three reads refuses.

    Only the report path is returned: every caller re-renders in order to serve or name
    `report.md`, and the record's path is `<run_dir>/attention.json` by construction.

    Raises:
        FileNotFoundError: the folder holds no `session.json`; a benchmark run root, whose
            sessions sit one level down, is named as such and pointed at `benchmark time`
            through a `ValueError` instead.
        ValueError: a benchmark run root, or a `check.json` whose verdict cannot be read.
        pydantic.ValidationError: a `session.json` or `package.json` this build cannot read.
    """
    directory = Path(run_dir)
    session = _session_of(directory)
    package = _package_of(directory)
    header = _header_of(directory, session)
    ranking = rank(session)

    report_file = directory / REPORT_FILE_NAME
    report_file.write_text(
        header + render_report(session, package, ranking=ranking), encoding="utf-8"
    )
    write_attention_record(directory, ranking, session.session_id)
    return report_file


def run_folder_session(run_dir: Path | str) -> Path:
    """The `session.json` `run_dir` holds, or the refusal that says why it holds none.

    Public because `swreview timing` has to resolve and refuse the folder *before* it
    writes anything to it, and the two refusals - "this folder holds no run" and "this is a
    benchmark run root, use `benchmark time`" - are written once, here, rather than again
    in the command (contract timing.md section 2).
    """
    directory = Path(run_dir)
    session_file = directory / SESSION_FILE_NAME
    if not session_file.is_file():
        _refuse_without_a_session(directory, session_file)
    return session_file


def _session_of(directory: Path) -> ReviewSession:
    return load_session(run_folder_session(directory))


def _refuse_without_a_session(directory: Path, session_file: Path) -> NoReturn:
    below = sorted(path.parent.name for path in directory.glob(f"*/{SESSION_FILE_NAME}"))
    if below:
        raise ValueError(
            BENCHMARK_RUN_ROOT.format(
                directory=directory,
                session=SESSION_FILE_NAME,
                count=len(below),
                packages=", ".join(below),
            )
        )
    raise FileNotFoundError(NO_SESSION.format(path=session_file, directory=directory))


def _package_of(directory: Path) -> EvidencePackage | None:
    """The package the folder holds, or `None`.

    A review folder and a pane-written check folder hold one; a check folder written by
    `--out <elsewhere>` does not, and renders the way `swreview report` does today.
    """
    if not (directory / PACKAGE_FILE_NAME).is_file():
        return None
    return load_package(directory).package


def _header_of(directory: Path, session: ReviewSession) -> str:
    """The standards verdict header to re-prepend, or `""` for every other folder.

    The two standards names are imported here rather than at the top of the module because
    `swreview.checks.standards` imports its own check modules on import, and those reach
    `checks/rules/run.py`, which imports this module for the run folder's file names. A
    module-level import would close that cycle; a call-time one - taken only for a folder
    that actually holds a `check.json` - keeps the report layer importable on its own.
    """
    check_file = directory / CHECK_FILE_NAME
    if not check_file.is_file():
        return ""

    from swreview.checks.standards.registry import STANDARDS_FAMILY
    from swreview.checks.standards.verdict import verdict_header

    try:
        record = json.loads(check_file.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(UNREADABLE_CHECK_RECORD.format(path=check_file, error=exc)) from exc
    if not isinstance(record, dict):
        raise ValueError(
            UNREADABLE_CHECK_RECORD.format(
                path=check_file, error=f"it is a {type(record).__name__}, not an object"
            )
        )
    if record.get("family") != STANDARDS_FAMILY.check_file_family:
        return ""
    try:
        return verdict_header(session.design_id, record["verdict"])
    except (KeyError, TypeError) as exc:
        raise ValueError(
            UNREADABLE_CHECK_RECORD.format(path=check_file, error=f"{type(exc).__name__}: {exc}")
        ) from exc
