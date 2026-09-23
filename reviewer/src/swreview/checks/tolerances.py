"""Where a tolerance comes from, and the one question every stack-up asks (feature 010).

`contracts/tolerances.md` section 4 and `data-model.md` section 5 are normative. A check
that needs a tolerance asks a `ToleranceLookup` about a *subject* - a hole's size, a pin's
size, a hole's position - and gets back either a `ResolvedTolerance`, naming the source it
came from and carrying the `Dimension` `checks/result.limits_mm` reads, or an
`UnresolvedTolerance` listing every source searched and why none bound. There is no third
answer and no default: a tolerance the evidence does not contain is never inferred
(constitution Principle I, FR-025, SC-007).

This module lands with User Story 3, before any tolerance is read, with the types and
`NoSources`, whose every answer is unresolved. User Story 8 adds the resolver that walks the
five sources in precedence (T083) and replaces `NoSources` as the default lookup; the
stack-up does not change when it does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from swreview.ir.models import Dimension

__all__ = [
    "NO_SOURCE_READ_YET",
    "SOURCE_LABELS",
    "SOURCE_ORDER",
    "NoSources",
    "ResolvedTolerance",
    "SourceKind",
    "SubjectKind",
    "ToleranceLookup",
    "ToleranceSubject",
    "UnresolvedTolerance",
]

SourceKind = Literal["drawing", "annotation", "model_dimension", "hole_wizard", "general"]
SubjectKind = Literal["hole_size", "pin_size", "hole_position"]

SOURCE_ORDER: tuple[SourceKind, ...] = (
    "drawing",
    "annotation",
    "model_dimension",
    "hole_wizard",
    "general",
)
"""The sources in precedence (research R2.18): the first that binds a subject wins."""

SOURCE_LABELS: dict[SourceKind, str] = {
    "drawing": "drawing callout",
    "annotation": "model annotation",
    "model_dimension": "model dimension",
    "hole_wizard": "Hole Wizard class",
    "general": "general tolerance",
}
"""How a finding names each source to an engineer."""

NO_SOURCE_READ_YET = "no tolerance source is read yet"


@dataclass(frozen=True)
class ToleranceSubject:
    """What a contributor to a stack-up is: whose size or position, and how big nominally."""

    kind: SubjectKind
    nominal_mm: float
    document_id: str | None
    face_ids: tuple[str, ...] = ()
    instance_id: str | None = None
    component_id: str | None = None

    @property
    def label(self) -> str:
        """`the size of hol:0018#1`, `the position of hol:0027#2`, `the pin size`."""
        what = {"hole_size": "the size", "pin_size": "the size", "hole_position": "the position"}
        whom = self.instance_id or self.component_id
        if whom is None:
            return "the pin size"
        return f"{what[self.kind]} of {whom}"


@dataclass(frozen=True)
class ResolvedTolerance:
    """A tolerance one source binds to a subject, and where it came from."""

    subject: ToleranceSubject
    source_kind: SourceKind
    cited: str
    """What an engineer opens to check it: the document and entity, or the profile section."""
    dimension: Dimension
    also_found: tuple[SourceKind, ...] = ()
    """Lower-precedence sources that carried a tolerance too."""
    conflict: str | None = None
    """Set when an `also_found` source disagrees; the consuming check makes it a limit."""


@dataclass(frozen=True)
class UnresolvedTolerance:
    """No source binds the subject. Never carries a number."""

    subject: ToleranceSubject
    searched: tuple[tuple[SourceKind, str], ...]
    """One `(source, why it did not bind)` per source, in precedence order."""

    def searched_text(self) -> str:
        return "; ".join(f"{SOURCE_LABELS[source]}: {why}" for source, why in self.searched)


class ToleranceLookup(Protocol):
    """The one question a stack-up asks. `NoSources` now; the resolver from US8."""

    def resolve(self, subject: ToleranceSubject) -> ResolvedTolerance | UnresolvedTolerance:
        """Bind `subject` to a tolerance from the first source that can, or say why not."""
        ...

    def holds_any_source(self) -> bool:
        """Whether any source could bind anything in this package at all. When none can,
        the stack-up is one skipped coverage item for every joint, not a finding per joint
        (`contracts/alignment.md` section 4)."""
        ...


class NoSources:
    """The lookup before any tolerance is read: every subject is unresolved, and says why.

    `resolve` lists all five sources with the same reason, so a stack-up that asks still
    names what it searched (FR-010).
    """

    def resolve(self, subject: ToleranceSubject) -> UnresolvedTolerance:
        return UnresolvedTolerance(
            subject=subject,
            searched=tuple((source, NO_SOURCE_READ_YET) for source in SOURCE_ORDER),
        )

    def holds_any_source(self) -> bool:
        return False
