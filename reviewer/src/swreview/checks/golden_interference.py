"""Golden-harness adapter for the grouped interference check (T075).

`tests/golden/test_golden.py` calls `module:function(package, **kwargs)`, so it hands over
a loaded `EvidencePackage` and nothing else - no directory, and therefore no way to find
the `exceptions.json` that sits beside `package.json`. `interference_case` accepts either:
a directory (the CLI and the bridge have one, and the file is read from it) or a package
plus the exception records inline, which is what a fixture's `case.json` carries. The
fixture keeps both, and a unit test asserts the two copies agree.

The result is one JSON-ready dict: every grouped condition with its `CheckResult`, the
unresolved coverage for pairs that were never computed, and the exception statuses after
`refresh`, so the baseline pins FR-011, FR-013, FR-018 and FR-019 in one file.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

from swreview.checks.interference import (
    check_interference_group,
    group_interferences,
    run_coverage,
)
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage

__all__ = ["interference_case"]


def interference_case(
    package_or_dir: EvidencePackage | Path | str,
    exceptions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Group, check and cover every interference in a package.

    `package_or_dir` is a loaded package or the directory holding `package.json`; with a
    directory, `exceptions.json` is read from it and the `exceptions` argument is ignored.
    """
    if isinstance(package_or_dir, EvidencePackage):
        package = package_or_dir
        store = ExceptionStore.from_records([dict(record) for record in exceptions or ()])
    else:
        directory = Path(package_or_dir)
        package = load_package(directory).package
        store = ExceptionStore(directory / EXCEPTIONS_FILE_NAME).load()

    store.refresh(package)
    groups = group_interferences(package)

    return {
        "groups": [
            {
                "group_key": group.group_key,
                "configuration": group.configuration,
                "component_ids": group.component_ids,
                "member_interference_ids": [item.id for item in group.interferences],
                "detection_status": group.status,
                "result": to_jsonable_python(check_interference_group(group, package, store)),
            }
            for group in groups
        ],
        "unresolved_coverage": to_jsonable_python(run_coverage(package)),
        "exceptions": [
            {"id": item.id, "check": item.check, "status": item.status}
            for item in store.exceptions
        ],
    }
