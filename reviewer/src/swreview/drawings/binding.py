"""Which drawing record ties to which tolerance subject, and why none does (feature 011).

`contracts/drawing-source.md` section 3 and research R2.8 are normative. A drawing dimension or
annotation is evidence about one of feature 010's `ToleranceSubject`s - a hole's size or
position, a pin's size - only when it sits in a view usable for the subject's component
(`drawings/evidence.py`, section 1) **and** it ties to the subject by one of two exact routes:

- **attached face**: one of its `attached_faces`, scoped to the subject's document, carries the
  persistent reference of one of the subject's faces (an edge's two faces count, `via_edge`);
- **model dimension**: its name, before a document suffix however the drawing spells it, is the
  name of the one model dimension feature 010's source 3 binds to the subject
  (`checks/tolerances.unique_model_dimension`, one rule for both).

A size subject binds a diameter, a radius or a hole callout **of the subject's size** - a
counterbore's diameter sits on a face of the same hole instance and is not the bore's size - and
a position subject a geometric tolerance with a position or coaxiality frame. A dimension whose
displayed value is overridden, or whose override flag is unread, binds nothing: the number the
sheet shows is not the model's (the defect `standards.drawing.dimensions_not_overridden`
reports). Nothing looser binds (FR-020); no value is inferred (Principle I).

**It ships disabled.** `DRAWING_BINDING_VALIDATED` is false until the seat task T066 records
probes D6 and D8 passing on a drawing whose callouts are known: while it is false nothing binds,
`tools/refs.resolve_dimension` refuses a native dimension, and both say `NOT_VALIDATED` (FR-024,
constitution Principle III). Every test of the binding sets it; the shipped code does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from swreview import units
from swreview.checks.result import round_length
from swreview.checks.tolerances import (
    LENGTH_EQUAL_MM,
    ToleranceSubject,
    is_position_frame,
    unique_model_dimension,
)
from swreview.drawings.evidence import DrawingIndex, ViewEvidence, id_order
from swreview.ir.models import (
    AttachedFace,
    DisplayDimensionRecord,
    DrawingAnnotation,
    EvidencePackage,
    ModelDimension,
    Quantity,
)

__all__ = [
    "DRAWING_BINDING_VALIDATED",
    "NOT_VALIDATED",
    "BindingSearch",
    "DrawingBinding",
    "bindings_for",
    "search_bindings",
]

DRAWING_BINDING_VALIDATED: bool = False
"""T066 sets True, one edit in a commit of its own on the development machine, citing probes D4,
D5, D6 and D8; the same commit edits `test_drawing_binding.test_the_switch_ships_off`, the one
test that reads this value (T096)."""

NOT_VALIDATED = (
    "drawing callouts are read but not yet validated on a seat against a drawing whose "
    "callouts are known (feature 011 research R2.8)"
)
"""What the drawing source and `resolve_dimension` say while the switch is off."""

SIZE_DIMENSION_TYPES: frozenset[int] = frozenset({5, 6, 14, 15})
"""`swDimensionType_e` that size a hole or pin: radial 5, diameter 6, radial linear 14 and
diametric linear 15. A linear dimension never sizes one."""

RADIAL_DIMENSION_TYPES: frozenset[int] = frozenset({5, 14})
"""The two whose value is a radius, doubled to compare with a diameter."""

GTOL_ANNOTATION_TYPE = 5
"""`swAnnotationType_e.swGTol`."""

Route = Literal["attached_face", "model_dimension"]


@dataclass(frozen=True, eq=False)
class DrawingBinding:
    """One piece of drawing evidence tied to one subject, and how."""

    subject: ToleranceSubject
    record: DisplayDimensionRecord | DrawingAnnotation
    view: ViewEvidence
    route: Route
    via_edge: bool
    """Tied through an edge's adjacent face only, never through the face itself."""

    @property
    def record_id(self) -> str:
        return self.record.id


@dataclass(frozen=True)
class BindingSearch:
    """What the drawing says about one subject: what binds, what was left out and why."""

    subject: ToleranceSubject
    bindings: tuple[DrawingBinding, ...]
    """Every record that binds, in the index's order: drawing, sheet, view, record id."""
    excluded: tuple[str, ...]
    """Why each record that ties to the subject was not used: its view is unusable for the
    subject's component (section 1's words), or its displayed value is overridden."""
    why: str | None
    """Why nothing binds, when nothing does: no drawing of the document, the switch, no usable
    view, the records left out, or nothing that ties - the first that applies."""


def _whom(subject: ToleranceSubject) -> str:
    return subject.instance_id or subject.component_id or "the subject"


def _document_names(package: EvidencePackage) -> frozenset[str]:
    """Every package document's file name and stem, casefolded: the suffixes a name may carry."""
    names: set[str] = set()
    for document in package.documents:
        names.add(document.file_name.casefold())
        names.add(document.file_name.rsplit(".", 1)[0].casefold())
    return frozenset(names)


def _without_document(name: str, documents: frozenset[str]) -> str:
    """`name` before its `@document` suffix, casefolded; unchanged when the last part is not a
    package document's name (a feature's, as in `D1@Sketch1`)."""
    head, separator, last = name.rpartition("@")
    if separator and last.casefold() in documents:
        return head.casefold()
    return name.casefold()


def _attached(
    faces: list[AttachedFace], document_id: str, refs: frozenset[str]
) -> bool | None:
    """`via_edge` when an attachment scoped to `document_id` is one of `refs`, else `None`."""
    matches = [face for face in faces if face.scope == document_id and face.persist_ref in refs]
    if not matches:
        return None
    return all(face.via == "edge" for face in matches)


def _size_mm(record: DisplayDimensionRecord) -> float | None:
    """The diameter a dimension states, in mm: its value, doubled for a radius."""
    if not isinstance(record.value, Quantity):
        return None
    size = units.as_mm(record.value)
    return 2.0 * size if record.dimension_type_raw in RADIAL_DIMENSION_TYPES else size


@dataclass(frozen=True)
class _Terms:
    """What a record must match to tie to one subject."""

    subject: ToleranceSubject
    document_id: str
    refs: frozenset[str]
    documents: frozenset[str]
    model_name: str | None
    """The unique model dimension's name before its document suffix, casefolded."""

    def size_tie(self, record: DisplayDimensionRecord) -> tuple[Route, bool] | None:
        if record.dimension_type_raw not in SIZE_DIMENSION_TYPES and not record.is_hole_callout:
            return None
        size = _size_mm(record)
        if size is None or abs(size - self.subject.nominal_mm) > LENGTH_EQUAL_MM:
            return None
        via_edge = _attached(record.attached_faces, self.document_id, self.refs)
        if via_edge is not None:
            return "attached_face", via_edge
        if (
            self.model_name is not None
            and record.name is not None
            and _without_document(record.name, self.documents) == self.model_name
        ):
            return "model_dimension", False
        return None

    def position_tie(self, annotation: DrawingAnnotation) -> tuple[Route, bool] | None:
        if annotation.type_raw != GTOL_ANNOTATION_TYPE:
            return None
        if not any(is_position_frame(frame) for frame in annotation.gtol_frames):
            return None
        via_edge = _attached(annotation.attached_faces, self.document_id, self.refs)
        return None if via_edge is None else ("attached_face", via_edge)


def _override_why(record: DisplayDimensionRecord) -> str | None:
    if record.is_overridden is None:
        return f"whether dimension {record.id} is overridden on the drawing was not read"
    if record.is_overridden:
        return f"dimension {record.id} is overridden on the drawing"
    return None


def search_bindings(
    index: DrawingIndex, package: EvidencePackage, subject: ToleranceSubject
) -> BindingSearch:
    """Every drawing record that binds `subject`, and why each record that ties does not."""

    def nothing(why: str) -> BindingSearch:
        return BindingSearch(subject=subject, bindings=(), excluded=(), why=why)

    document_id = subject.document_id
    if document_id is None:
        return nothing("the document the subject belongs to is not known")
    views = index.views_of(document_id)
    if not views:
        return nothing(f"no drawing of {document_id} was read")
    if not DRAWING_BINDING_VALIDATED:
        return nothing(NOT_VALIDATED)
    unusable = {id(view): index.why_not_for(view, subject.component_id) for view in views}
    if all(why is not None for why in unusable.values()):
        return nothing("; ".join(dict.fromkeys(why for why in unusable.values() if why)))

    documents = _document_names(package)
    model = unique_model_dimension(package, subject)
    wanted = frozenset(subject.face_ids)
    terms = _Terms(
        subject=subject,
        document_id=document_id,
        refs=frozenset(face.persist_ref for face in package.faces if face.id in wanted),
        documents=documents,
        model_name=None if isinstance(model, str) else _without_document(model.name, documents),
    )
    bindings: list[DrawingBinding] = []
    excluded: list[str] = []
    for view in views:
        records: list[tuple[DisplayDimensionRecord | DrawingAnnotation, tuple[Route, bool]]] = []
        if subject.kind == "hole_position":
            for annotation in sorted(view.view.annotations, key=lambda item: id_order(item.id)):
                tie = terms.position_tie(annotation)
                if tie is not None:
                    records.append((annotation, tie))
        else:
            for dimension in sorted(
                view.view.display_dimensions, key=lambda item: id_order(item.id)
            ):
                tie = terms.size_tie(dimension)
                if tie is not None:
                    records.append((dimension, tie))
        for record, (route, via_edge) in records:
            why = unusable[id(view)]
            if why is None and isinstance(record, DisplayDimensionRecord):
                why = _override_why(record)
            if why is not None:
                excluded.append(why)
                continue
            bindings.append(
                DrawingBinding(
                    subject=subject, record=record, view=view, route=route, via_edge=via_edge
                )
            )

    reasons = tuple(dict.fromkeys(excluded))
    why = None
    if not bindings:
        why = "; ".join(reasons) if reasons else _nothing_ties(subject, document_id, model)
    return BindingSearch(subject=subject, bindings=tuple(bindings), excluded=reasons, why=why)


def _nothing_ties(
    subject: ToleranceSubject, document_id: str, model: ModelDimension | str
) -> str:
    whom = _whom(subject)
    if subject.kind == "hole_position":
        return (
            "no geometric tolerance with a position or coaxiality frame on a usable view of "
            f"{document_id} is attached to a face of {whom}"
        )
    nominal = round_length(subject.nominal_mm)
    sentence = (
        f"no diameter, radius or hole callout of {nominal!r} mm on a usable view of "
        f"{document_id} is attached to a face of {whom}"
    )
    if isinstance(model, str):
        return f"{sentence}, and none can name its model dimension: {model}"
    return f"{sentence} or names its model dimension {model.name} ({model.id})"


def bindings_for(
    index: DrawingIndex, package: EvidencePackage, subject: ToleranceSubject
) -> tuple[DrawingBinding, ...]:
    """Every record that binds `subject`, in the fixed order; none while the switch is off."""
    return search_bindings(index, package, subject).bindings
