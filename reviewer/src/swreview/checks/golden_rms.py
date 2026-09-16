"""Golden-harness adapters for the RMS rules (T030; assembly T036, equations T043).

`tests/golden/test_golden.py` calls `module:function(package, **kwargs)`, so it hands over
a loaded `EvidencePackage` and nothing else - no directory, and therefore no way to find
the `exceptions.json` that sits beside `package.json`. `part_case` accepts either, exactly
as `golden_interference.interference_case` does: a directory (the CLI and the bridge have
one, and the file is read from it) or a package plus the exception records inline, which is
what a fixture's `case.json` carries.

Each adapter runs the real path rather than a parallel one: `run_part_checks`,
`run_assembly_checks` or `run_equation_checks` over a `ToolContext` with a session, which
is the same call the matching `check_rms_*` tool and `swreview check rms --scope <scope>`
make. The baseline
therefore pins what a reviewer would actually see - the finding bodies, their component
ids and inputs, the aggregated coverage per rule per bucket, and the exception statuses
after `refresh` - and a rule whose verdict, wording or bucket moves shows up as a diff
instead of as a silently different report.

The three differ in one line - which scope is dispatched - so `_graded` is that one line's
argument and everything else is written once (constitution Principle V).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import CoverageBucket, ReviewSession
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.query import ToolResult
from swreview.tools.rms_checks import (
    run_assembly_checks,
    run_equation_checks,
    run_part_checks,
)

__all__ = ["assembly_case", "equations_case", "part_case"]

BUCKETS: tuple[CoverageBucket, ...] = (
    "checked",
    "skipped",
    "unresolved",
    "failed",
    "out_of_scope",
)


def part_case(
    package_or_dir: EvidencePackage | Path | str,
    exceptions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grade every part document of a package against the part-scope RMS rules.

    `package_or_dir` is a loaded package or the directory holding `package.json`; with a
    directory, `exceptions.json` is read from it and the `exceptions` argument is ignored.
    """
    return _graded(run_part_checks, package_or_dir, exceptions)


def assembly_case(
    package_or_dir: EvidencePackage | Path | str,
    exceptions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grade a package's root assembly document against the assembly-scope RMS rules.

    The same two arguments as `part_case`, although this scope has no document selection:
    only the root assembly's mates are extracted, so `design.root_assembly_document_id` is
    the whole scope and the subassemblies arrive as the `rms.assembly.subassemblies`
    coverage item.
    """
    return _graded(run_assembly_checks, package_or_dir, exceptions)


def equations_case(
    package_or_dir: EvidencePackage | Path | str,
    exceptions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grade every part document of a package against the equation-scope RMS rules.

    The same two arguments as `part_case`, for the same reason: the golden harness hands
    over a package, and the CLI and the bridge have a directory with `exceptions.json`
    beside it.
    """
    return _graded(run_equation_checks, package_or_dir, exceptions)


def _graded(
    run: Callable[[ToolContext], ToolResult],
    package_or_dir: EvidencePackage | Path | str,
    exceptions: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Run one scope's checks over the package and return what the session then holds."""
    if isinstance(package_or_dir, EvidencePackage):
        package = package_or_dir
        store = ExceptionStore.from_records([dict(record) for record in exceptions or ()])
    else:
        directory = Path(package_or_dir)
        package = load_package(directory).package
        store = ExceptionStore(directory / EXCEPTIONS_FILE_NAME).load()

    store.refresh(package)
    context = context_for(package)
    context.exceptions = store
    with use_context(context):
        result = run(context)
    if "error" in result:  # pragma: no cover - every part document is dispatchable
        return {"error": result["error"]}

    session = context.require_session()
    return {
        "documents": result["documents"],
        "findings": to_jsonable_python(session.findings),
        "coverage": _coverage(session),
        "exceptions": [
            {"id": item.id, "check": item.check, "status": item.status}
            for item in store.exceptions
        ],
    }


def _coverage(session: ReviewSession) -> list[dict[str, Any]]:
    """Every coverage item the run wrote, as one flat row, bucket included."""
    return [
        {"bucket": bucket, **to_jsonable_python(item)}
        for bucket in BUCKETS
        for item in getattr(session.coverage, bucket)
    ]
