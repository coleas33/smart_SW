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

**The second resolution (feature 008): an entity id to its persistent reference.** The two
bridge tools that act on an entity take the short id the model was shown (`cmp:0001`, a
face id), never the base64 reference a slimmed view no longer carries, and
`resolve_entity_ref` finds the reference server-side (FR-016, research R2.27). It refuses the
same way: an unknown id, an entity whose reference is null, and one id held by two kinds
with different references are each an `EntityRefRefused` naming the id.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from swreview.checks.result import cite
from swreview.drawings import binding
from swreview.drawings.native import native_matches, shadowed_sheets
from swreview.ir.models import Dimension, EvidencePackage, SourceRef

__all__ = ["EntityRefRefused", "RefArg", "resolve_dimension", "resolve_entity_ref"]

RefArg = Mapping[str, Any] | SourceRef
"""A reference as the model sends it (a JSON object) or as Python holds it."""


def as_source_ref(ref: RefArg) -> SourceRef:
    """`ref` as a validated `SourceRef`. Raises `pydantic.ValidationError` if it is not one."""
    return ref if isinstance(ref, SourceRef) else SourceRef(**dict(ref))


def resolve_dimension(package: EvidencePackage, source_ref: RefArg) -> Dimension:
    """The one dimension on a drawing sheet of `package` that `source_ref` points at.

    Raises `LookupError` when the reference names no dimension or more than one, and
    `pydantic.ValidationError` when it is not a well-formed `SourceRef`.

    Feature 011 matches the natively read sheets too, through the one conversion
    (`drawings/native.native_matches`), and an ingested sheet of the same document and name
    as a native one is not read beside it. **A native match is refused while
    `DRAWING_BINDING_VALIDATED` is false**, with a `LookupError` naming the seat validation, so
    every check that takes a reference returns its error result and computes nothing (FR-024,
    research R2.11); a PDF-ingested match resolves whatever the switch.
    """
    source = as_source_ref(source_ref)
    shadowed = shadowed_sheets(package)
    matches = [
        dimension
        for sheet in package.drawings
        if (sheet.document_id, sheet.sheet_name) not in shadowed
        for dimension in sheet.dimensions
        if (
            dimension.source.document_id == source.document_id
            and dimension.source.sheet == source.sheet
            and dimension.source.annotation == source.annotation
        )
    ]
    native = native_matches(package, source)
    count = len(matches) + len(native)
    if not count:
        raise LookupError(f"no drawing dimension at {cite(source)}")
    if count > 1:
        raise LookupError(f"{count} drawing dimensions at {cite(source)}; ambiguous")
    if matches:
        return matches[0]
    _, converted = native[0]
    if not binding.DRAWING_BINDING_VALIDATED:
        raise LookupError(
            f"{cite(source)} is a native drawing dimension, and {binding.NOT_VALIDATED}"
        )
    if isinstance(converted, str):
        raise LookupError(f"{cite(source)}: {converted}")
    return converted


class EntityRefRefused(LookupError):
    """An entity id that does not resolve to exactly one persistent reference."""


ENTITY_KINDS: tuple[tuple[str, str], ...] = (
    ("components", "component"),
    ("features", "feature"),
    ("mates", "mate"),
    ("holes", "hole"),
    ("threads", "cosmetic thread"),
    ("fasteners", "fastener"),
    ("faces", "face"),
    ("bodies", "body"),
    ("cut_list_items", "cut-list item"),
    ("captures", "capture"),
)
"""The package arrays an entity id is looked up in, with what the refusal calls each kind."""


def _entities(package: EvidencePackage) -> Iterator[tuple[str, str, str | None, str | None]]:
    """Every `(id, kind, persist_ref, scope)` the package holds, drawing records included.

    A drawing record is keyed by its document id and carries no reference of its own, so it
    is listed to be refused by kind rather than reported unknown.
    """
    for array, kind in ENTITY_KINDS:
        for row in getattr(package, array):
            yield row.id, kind, row.persist_ref, getattr(row, "persist_ref_scope", None)
    for record in package.drawing_records:
        yield record.document_id, "drawing record", None, None


def resolve_entity_ref(package: EvidencePackage, entity_id: str) -> tuple[str, str | None]:
    """The persistent reference and scope of the one entity `entity_id` names in `package`.

    Read from the package as it stands, so rows a bridge call appended since the context was
    built are found. The scope is the document whose extension produced the reference, or
    `None` for a capture, which records none.

    Raises:
        EntityRefRefused: no entity has that id (a reference passed as an id is not one);
            the entity carries no reference; or two kinds hold the id with different
            references. Each message names the id.
    """
    matches = [entity for entity in _entities(package) if entity[0] == entity_id]
    if not matches:
        raise EntityRefRefused(
            f"no entity {entity_id!r} in this package; pass an entity id a query tool "
            "returned, such as a component, face or hole id"
        )
    with_refs = [(kind, ref, scope) for _, kind, ref, scope in matches if ref]
    if not with_refs:
        kinds = " and ".join(sorted({kind for _, kind, _, _ in matches}))
        raise EntityRefRefused(
            f"{kinds} {entity_id!r} carries no persistent reference, so SOLIDWORKS cannot "
            "be pointed at it"
        )
    if len({ref for _, ref, _ in with_refs}) > 1:
        kinds = ", ".join(sorted({kind for kind, _, _ in with_refs}))
        raise EntityRefRefused(
            f"entity id {entity_id!r} is ambiguous: {kinds} each hold it with a different "
            "persistent reference"
        )
    _, ref, scope = with_refs[0]
    return ref, scope
