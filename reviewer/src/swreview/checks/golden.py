"""Adapters that let the golden harness run a check over a fixture package (T082).

`tests/golden/test_golden.py` calls `module:function(package, **kwargs)` with the kwargs
read from `case.json`, so a check cannot be named there directly: its arguments are
`Dimension` objects, not JSON. These adapters take the JSON form of a `SourceRef`,
resolve it against the drawing sheets in the package - the same rule the `check_fit` and
`check_axial_stack` tools use, so a fixture exercises real references and not
hand-typed numbers - and return the `CheckResult` as JSON-ready data.

A `TypeError` from a check (an angular dimension where a length belongs) is returned as
an `error` entry. A fixture that hands an angle to a length check must record that
refusal, never a number (FR-022).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic_core import to_jsonable_python

from swreview.checks.fit import check_fit
from swreview.checks.result import CheckResult, cite
from swreview.checks.stack import check_axial_stack
from swreview.ir.models import Dimension, EvidencePackage, SourceRef

__all__ = ["find_dimension", "fit_case", "stack_case"]

RefArg = Mapping[str, Any] | SourceRef


def find_dimension(package: EvidencePackage, ref: RefArg) -> Dimension:
    """The one dimension on a drawing sheet that `ref` points at.

    Matching is on document, sheet and annotation: the locators a drawing dimension
    carries. An ambiguous or unknown reference raises rather than picking one.
    """
    source = ref if isinstance(ref, SourceRef) else SourceRef(**ref)
    matches = [
        dimension
        for sheet in package.drawings
        for dimension in sheet.dimensions
        if (
            dimension.source.document_id == source.document_id
            and dimension.source.sheet == source.sheet
            and dimension.source.annotation == source.annotation
        )
    ]
    if not matches:
        raise LookupError(f"no drawing dimension at {cite(source)}")
    if len(matches) > 1:
        raise LookupError(f"{len(matches)} drawing dimensions at {cite(source)}; ambiguous")
    return matches[0]


def _jsonable(result: CheckResult) -> dict[str, Any]:
    return to_jsonable_python(result)


def fit_case(package: EvidencePackage, bore_ref: RefArg, shaft_ref: RefArg) -> dict[str, Any]:
    """Run `check_fit` over two dimensions named by reference in the package."""
    bore = find_dimension(package, bore_ref)
    shaft = find_dimension(package, shaft_ref)
    try:
        return _jsonable(check_fit(bore, shaft))
    except TypeError as error:
        return {"error": f"TypeError: {error}"}


def stack_case(
    package: EvidencePackage,
    dimension_refs: list[RefArg],
    signs: list[int],
    target_gap_ref: RefArg | None = None,
) -> dict[str, Any]:
    """Run `check_axial_stack` over dimensions named by reference in the package."""
    dims = [find_dimension(package, ref) for ref in dimension_refs]
    target = None if target_gap_ref is None else find_dimension(package, target_gap_ref)
    try:
        return _jsonable(check_axial_stack(dims, signs, target))
    except TypeError as error:
        return {"error": f"TypeError: {error}"}
