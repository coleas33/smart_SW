"""Turn a `SourceRef` into the one `Dimension` it points at.

The check tools take references, never numbers (contracts/agent-tools.md): the model says
*which* dimension on *which* sheet, and this module finds it in the package. That is the
whole guard against a typed-in size reaching an arithmetic check, so the resolution lives
in one place and refuses rather than chooses:

- an annotation that matches nothing raises `LookupError` naming the reference;
- an annotation that matches more than one dimension raises `LookupError` too, because
  picking the first would silently decide which dimension the finding is about.

Matching is on document, sheet and annotation - the locators a drawing dimension carries
(`Dimension.source`). `view`, `page` and `bbox` are not matched on: they describe where
the value sits on the page, not which value it is.

`swreview.checks.golden.find_dimension`, the golden harness's way in, is a one-line
delegation to this function: a fixture and a tool call resolve a reference identically or
the baseline is not testing what the model does.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from swreview.checks.result import cite
from swreview.ir.models import Dimension, EvidencePackage, SourceRef

__all__ = ["RefArg", "resolve_dimension"]

RefArg = Mapping[str, Any] | SourceRef
"""A reference as the model sends it (a JSON object) or as Python holds it."""


def as_source_ref(ref: RefArg) -> SourceRef:
    """`ref` as a validated `SourceRef`. Raises `pydantic.ValidationError` if it is not one."""
    return ref if isinstance(ref, SourceRef) else SourceRef(**dict(ref))


def resolve_dimension(package: EvidencePackage, source_ref: RefArg) -> Dimension:
    """The one dimension on a drawing sheet of `package` that `source_ref` points at.

    Raises `LookupError` when the reference names no dimension or more than one, and
    `pydantic.ValidationError` when it is not a well-formed `SourceRef`.
    """
    source = as_source_ref(source_ref)
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
